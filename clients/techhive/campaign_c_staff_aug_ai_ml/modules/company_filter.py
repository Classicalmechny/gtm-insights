"""
ICP firmographic filter.

Campaign C (per strategy doc): headcount 2-50, US/Canada (already enforced
by the job scraper), services-only product, founder/CEO decision speed.

For each scraped company:
  1. Resolve domain → company_linkedin_url (BlitzAPI domain-to-linkedin)
  2. Enrich via BlitzAPI /v2/enrichment/company (returns size, industry, hq)
  3. Drop if:
       - size not in {"1-10", "11-50"}                ← hard rule from doc
       - hq.country_code not in {"US", "CA"}          ← reject ROW HQ companies
       - industry matches a hard-exclude bucket       ← regulated/in-house eng
       - employees_on_linkedin > 50                   ← extra guard

Output: qualified_companies.csv with the enriched firmographics merged onto
the original JSearch row (employer_name, job_title_hiring, etc.).
"""
from __future__ import annotations

import time
from pathlib import Path

from _common import (
    env, log_event, make_session, normalize_domain, normalize_linkedin,
    run_dir, write_csv,
)

BLITZ_BASE = "https://api.blitz-api.ai"
EP_DOMAIN_TO_LI = "/v2/enrichment/domain-to-linkedin"
EP_COMPANY_ENRICH = "/v2/enrichment/company"

# Per Campaign C strategy doc: headcount 2-50
ALLOWED_SIZE_BUCKETS = {"1-10", "11-50"}

# Per Campaign C strategy doc: US, Canada (UK + AU also valid in broader brief
# but the user explicitly scoped to US + Canada for this run).
ALLOWED_HQ_COUNTRIES = {"US", "CA"}

# Hard-exclude industries — these companies have in-house engineering teams,
# slow procurement, or regulatory blockers that prevent staff aug.
EXCLUDE_INDUSTRY_KEYWORDS = {
    # Big in-house engineering / FAANG-equivalent
    "banking", "financial services", "insurance",
    "investment management", "investment banking",
    "credit cards", "wealth management",
    # Slow procurement
    "government", "public administration", "defense", "military",
    "higher education", "primary/secondary education",
    # Heavily regulated / in-house
    "hospitals & health care", "pharmaceutical", "biotechnology",
    "utilities", "oil & gas", "mining",
    "telecommunications", "airlines",
}


def _auth_headers() -> dict:
    return {"x-api-key": env("BLITZAPI_KEY"), "Content-Type": "application/json"}


def domain_to_company_linkedin(session, domain: str) -> str:
    if not domain:
        return ""
    try:
        r = session.post(BLITZ_BASE + EP_DOMAIN_TO_LI,
                         json={"domain": domain},
                         headers=_auth_headers(), timeout=30)
        if r.status_code >= 400:
            return ""
        body = r.json()
        return normalize_linkedin(body.get("company_linkedin_url") or "") if body.get("found") else ""
    except Exception:
        return ""


def enrich_company(session, company_li: str) -> dict:
    """Return BlitzAPI company-enrichment payload (dict under `company` key)."""
    if not company_li:
        return {}
    try:
        r = session.post(BLITZ_BASE + EP_COMPANY_ENRICH,
                         json={"company_linkedin_url": company_li},
                         headers=_auth_headers(), timeout=30)
        if r.status_code >= 400:
            return {}
        body = r.json()
        if not body.get("found"):
            return {}
        return body.get("company", body)  # API returns either shape
    except Exception:
        return {}


def _is_excluded_industry(industry: str) -> bool:
    i = (industry or "").lower()
    return any(kw in i for kw in EXCLUDE_INDUSTRY_KEYWORDS)


def filter_companies(run_id: str, companies: list[dict],
                     sleep_between: float = 0.15) -> list[dict]:
    """
    Returns a new list of company dicts with the ICP-fit ones only.
    Each output row is augmented with:
      company_linkedin_url, company_size_bucket, company_industry,
      company_employees_on_linkedin, company_hq_country, company_hq_city,
      company_founded_year, company_specialties
    """
    session = make_session()
    out_dir = run_dir(run_id) / "stage1b_qualified"
    out_dir.mkdir(exist_ok=True)

    qualified: list[dict] = []
    dropped: list[dict] = []
    stats = {"input": len(companies), "no_li": 0, "no_enrich": 0,
             "size_excluded": 0, "industry_excluded": 0, "hq_excluded": 0,
             "qualified": 0}

    for c in companies:
        domain = normalize_domain(c.get("employer_website") or "")
        company_li = normalize_linkedin(c.get("employer_linkedin") or "")

        if not company_li and domain:
            company_li = domain_to_company_linkedin(session, domain)
            time.sleep(sleep_between)

        if not company_li:
            stats["no_li"] += 1
            log_event(run_id, "filter.no_li", company=c.get("employer_name"))
            continue

        enriched = enrich_company(session, company_li)
        time.sleep(sleep_between)
        if not enriched:
            stats["no_enrich"] += 1
            log_event(run_id, "filter.no_enrich",
                      company=c.get("employer_name"), li=company_li)
            continue

        size = (enriched.get("size") or "").strip()
        industry = (enriched.get("industry") or "").strip()
        emp_li = enriched.get("employees_on_linkedin") or 0
        hq = enriched.get("hq", {}) or {}
        hq_country = (hq.get("country_code") or "").upper()

        reason = None
        if size not in ALLOWED_SIZE_BUCKETS:
            reason = f"size={size}"
            stats["size_excluded"] += 1
        elif _is_excluded_industry(industry):
            reason = f"industry={industry}"
            stats["industry_excluded"] += 1
        elif hq_country and hq_country not in ALLOWED_HQ_COUNTRIES:
            reason = f"hq={hq_country}"
            stats["hq_excluded"] += 1
        elif emp_li and emp_li > 60:
            # Belt-and-suspenders: size bucket can be stale, LinkedIn count usually fresher
            reason = f"employees_on_linkedin={emp_li}"
            stats["size_excluded"] += 1

        merged = {
            **c,
            "company_linkedin_url": company_li,
            "company_size_bucket": size,
            "company_industry": industry,
            "company_employees_on_linkedin": emp_li,
            "company_hq_country": hq_country,
            "company_hq_city": hq.get("city", ""),
            "company_founded_year": enriched.get("founded_year"),
            "company_specialties": ", ".join(enriched.get("specialties") or [])[:300],
            "company_about": (enriched.get("about") or "")[:500],
        }

        if reason:
            log_event(run_id, "filter.dropped",
                      company=c.get("employer_name"), reason=reason,
                      size=size, industry=industry, hq=hq_country, emp=emp_li)
            dropped.append({**merged, "drop_reason": reason})
            continue

        qualified.append(merged)
        stats["qualified"] += 1

    log_event(run_id, "filter.done", **stats)

    if qualified:
        write_csv(out_dir / "qualified_companies.csv",
                  qualified, list(qualified[0].keys()))
    if dropped:
        write_csv(out_dir / "dropped_companies.csv",
                  dropped, list(dropped[0].keys()))
    return qualified


if __name__ == "__main__":
    import sys, csv
    run_id = sys.argv[1] if len(sys.argv) > 1 else "smoketest"
    src = run_dir(run_id) / "stage1_jobs" / "companies_hiring.csv"
    companies = []
    with src.open() as f:
        for row in csv.DictReader(f):
            if row.get("employer_website"):
                companies.append(row)
    print(f"Filtering {len(companies)} companies...")
    qualified = filter_companies(run_id, companies)
    print(f"\n{len(qualified)} qualified (ICP-fit) companies:")
    for c in qualified:
        print(f"  - {c['employer_name']:<35} | size={c['company_size_bucket']:<7} | "
              f"hq={c['company_hq_country']} | {c['company_industry'][:30]}")
