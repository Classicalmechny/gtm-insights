"""
Decision-maker finder.

Input: list of company dicts from job_scraper (each has employer_name,
       employer_website, optionally employer_linkedin)
Output: list of decision-maker dicts:
       { first_name, last_name, title, linkedin_url, company_name,
         company_domain, company_linkedin_url, employer_website,
         job_title (the role they're hiring for),
         job_description_snippet, job_role_query, ... }

Strategy (matches the user's pipeline screenshot):
  Provider 1 (primary): BlitzAPI Waterfall ICP search by company LinkedIn URL.
                        Returns the SINGLE BEST DM matching the cascade.
  Provider 2 (fallback): BlitzAPI Employee Finder by company LinkedIn URL +
                         job_level filter (broader, returns N).

For companies without a known LinkedIn URL → BlitzAPI domain-to-linkedin
first; skip if not found.

Per-company cap: 1 DM by default (founder/CEO). Configurable.
"""
from __future__ import annotations

import time

from _common import (
    env, log_event, make_session, normalize_domain, normalize_linkedin,
    run_dir, write_csv,
)

BLITZ_BASE = "https://api.blitz-api.ai"
EP_DOMAIN_TO_LI = "/v2/enrichment/domain-to-linkedin"
EP_WATERFALL = "/v2/search/waterfall-icp-keyword"
EP_EMPLOYEE_FINDER = "/v2/search/employee-finder"

# ICP cascade for staff augmentation pitch — try founder/CEO first
# (decides alone), then exec engineering, then directors.
WATERFALL_CASCADE = [
    {
        "include_title": ["Founder", "Co-Founder", "CEO", "Chief Executive Officer",
                          "President & Founder"],
        "exclude_title": ["assistant", "intern", "former", "ex-", "advisor"],
        "location": ["NORTH_AMERICA"],
        "include_headline_search": False,
    },
    {
        "include_title": ["CTO", "Chief Technology Officer",
                          "VP Engineering", "VP of Engineering",
                          "Head of Engineering"],
        "exclude_title": ["assistant", "intern", "former", "ex-"],
        "location": ["NORTH_AMERICA"],
        "include_headline_search": False,
    },
    {
        "include_title": ["Head of AI", "Head of Machine Learning", "Head of Data",
                          "VP AI", "VP Machine Learning", "VP Data",
                          "Director of Engineering", "Director of AI",
                          "Director of Machine Learning"],
        "exclude_title": ["assistant", "intern", "former", "ex-"],
        "location": ["NORTH_AMERICA"],
        "include_headline_search": False,
    },
]

EMPLOYEE_FINDER_JOB_LEVELS = ["C-Team", "VP", "Director"]


def _auth_headers() -> dict:
    return {"x-api-key": env("BLITZAPI_KEY"), "Content-Type": "application/json"}


def domain_to_company_linkedin(session, domain: str) -> str:
    """Resolve a company domain to its LinkedIn URL. Empty string on miss."""
    if not domain:
        return ""
    try:
        r = session.post(BLITZ_BASE + EP_DOMAIN_TO_LI,
                         json={"domain": domain},
                         headers=_auth_headers(), timeout=30)
        if r.status_code >= 400:
            return ""
        body = r.json()
        if body.get("found"):
            return normalize_linkedin(body.get("company_linkedin_url") or "")
        return ""
    except Exception:
        return ""


def waterfall_icp(session, company_li: str, max_results: int = 1) -> list[dict]:
    """Waterfall ICP search — returns up to max_results ranked DMs."""
    if not company_li:
        return []
    try:
        r = session.post(BLITZ_BASE + EP_WATERFALL,
                         json={"company_linkedin_url": company_li,
                               "cascade": WATERFALL_CASCADE,
                               "max_results": max_results},
                         headers=_auth_headers(), timeout=60)
        if r.status_code >= 400:
            return []
        body = r.json()
        return body.get("results", []) or []
    except Exception:
        return []


def employee_finder(session, company_li: str, max_results: int = 5) -> list[dict]:
    """Fallback: employee finder (less ranked, more results)."""
    if not company_li:
        return []
    try:
        r = session.post(BLITZ_BASE + EP_EMPLOYEE_FINDER,
                         json={"company_linkedin_url": company_li,
                               "job_level": EMPLOYEE_FINDER_JOB_LEVELS,
                               "max_results": max_results,
                               "page": 1},
                         headers=_auth_headers(), timeout=60)
        if r.status_code >= 400:
            return []
        body = r.json()
        return body.get("results", []) or []
    except Exception:
        return []


def _person_from_waterfall_result(res: dict) -> dict:
    p = res.get("person", {}) or {}
    exp = (p.get("experiences") or [{}])[0]
    return {
        "first_name": (p.get("first_name") or "").strip(),
        "last_name": (p.get("last_name") or "").strip(),
        "headline": (p.get("headline") or "").strip(),
        "title": (exp.get("job_title") or p.get("headline") or "").strip(),
        "linkedin_url": normalize_linkedin(p.get("linkedin_url") or ""),
        "person_country": (p.get("location", {}) or {}).get("country_code", ""),
        "person_city": (p.get("location", {}) or {}).get("city", ""),
        "company_name_from_li": (exp.get("company_name") or "").strip(),
        "company_domain_from_li": normalize_domain(exp.get("company_domain") or ""),
        "company_linkedin_url_from_li": normalize_linkedin(exp.get("company_linkedin_url") or ""),
        "blitz_icp_rank": res.get("ranking"),
        "blitz_icp_layer": res.get("icp"),
    }


def _person_from_employee_finder_result(res: dict) -> dict:
    exp = (res.get("experiences") or [{}])[0]
    return {
        "first_name": (res.get("first_name") or "").strip(),
        "last_name": (res.get("last_name") or "").strip(),
        "headline": (res.get("headline") or "").strip(),
        "title": (exp.get("job_title") or res.get("headline") or "").strip(),
        "linkedin_url": normalize_linkedin(res.get("linkedin_url") or ""),
        "person_country": (res.get("location", {}) or {}).get("country_code", ""),
        "person_city": (res.get("location", {}) or {}).get("city", ""),
        "company_name_from_li": (exp.get("company_name") or "").strip(),
        "company_domain_from_li": normalize_domain(exp.get("company_domain") or ""),
        "company_linkedin_url_from_li": normalize_linkedin(exp.get("company_linkedin_url") or ""),
        "blitz_icp_rank": None,
        "blitz_icp_layer": None,
    }


def find_decision_makers(run_id: str, companies: list[dict],
                         per_company: int = 1,
                         sleep_between: float = 0.2) -> list[dict]:
    """Main entry. Returns one row per (company, DM)."""
    session = make_session()
    out_dir = run_dir(run_id) / "stage2_dms"
    out_dir.mkdir(exist_ok=True)

    dm_rows: list[dict] = []
    stats = {"companies": len(companies), "with_li": 0, "with_dm": 0,
             "waterfall_hits": 0, "fallback_hits": 0}

    for c in companies:
        domain = normalize_domain(c.get("employer_website") or "")
        # Prefer the LinkedIn URL added by company_filter; fall back to JSearch's
        # employer_linkedin; fall back to domain→LI lookup (extra Blitz call).
        company_li = (
            normalize_linkedin(c.get("company_linkedin_url") or "")
            or normalize_linkedin(c.get("employer_linkedin") or "")
        )

        if not company_li and domain:
            company_li = domain_to_company_linkedin(session, domain)
            time.sleep(sleep_between)

        if not company_li:
            log_event(run_id, "dm.no_company_li", company=c.get("employer_name"),
                      domain=domain)
            continue
        stats["with_li"] += 1

        # Try waterfall (primary)
        results = waterfall_icp(session, company_li, max_results=per_company)
        if results:
            stats["waterfall_hits"] += 1
            for res in results[:per_company]:
                person = _person_from_waterfall_result(res)
                dm_rows.append(_merge_company_and_person(c, person, company_li, "waterfall"))
                stats["with_dm"] += 1
        else:
            # Fallback to employee finder
            time.sleep(sleep_between)
            results = employee_finder(session, company_li, max_results=per_company)
            if results:
                stats["fallback_hits"] += 1
                for res in results[:per_company]:
                    person = _person_from_employee_finder_result(res)
                    dm_rows.append(_merge_company_and_person(c, person, company_li, "employee_finder"))
                    stats["with_dm"] += 1
            else:
                log_event(run_id, "dm.no_dm_found", company=c.get("employer_name"),
                          company_li=company_li)
        time.sleep(sleep_between)

    # Drop any merge-rejected (None) rows before writing/returning.
    dm_rows = [d for d in dm_rows if d]
    log_event(run_id, "dm.done", **stats)

    out_csv = out_dir / "decision_makers.csv"
    if dm_rows:
        fieldnames = list(dm_rows[0].keys())
        write_csv(out_csv, dm_rows, fieldnames)

    return dm_rows


def _merge_company_and_person(company: dict, person: dict, company_li: str,
                              dm_source: str) -> dict:
    """Combine company hiring-signal + DM person into a single output row."""
    out = {
        # Person identity
        "first_name": person["first_name"],
        "last_name": person["last_name"],
        "title": person["title"],
        "headline": person.get("headline", ""),
        "linkedin_url": person["linkedin_url"],
        "person_country": person.get("person_country", ""),
        "person_city": person.get("person_city", ""),

        # Company (from JSearch primary, fallback to BlitzAPI)
        "company_name": company.get("employer_name", "") or person["company_name_from_li"],
        "company_domain": company.get("employer_website", "") or person["company_domain_from_li"],
        "company_linkedin_url": company_li,
        "company_logo": company.get("employer_logo", ""),

        # ICP firmographics (from company_filter — required for audit/trust)
        "company_size_bucket": company.get("company_size_bucket", ""),
        "company_industry": company.get("company_industry", ""),
        "company_employees_on_linkedin": company.get("company_employees_on_linkedin", ""),
        "company_hq_country": company.get("company_hq_country", ""),
        "company_hq_city": company.get("company_hq_city", ""),
        "company_founded_year": company.get("company_founded_year", ""),

        # Hiring signal
        "job_title_hiring": company.get("job_title", ""),
        "job_id": company.get("job_id", ""),
        "job_apply_link": company.get("job_apply_link", ""),
        "job_posted_at": company.get("job_posted_at", ""),
        "job_city": company.get("job_city", ""),
        "job_state": company.get("job_state", ""),
        "job_country": company.get("job_country", ""),
        "job_description_snippet": company.get("job_description_snippet", ""),
        "job_role_query": company.get("job_role_query", ""),
        "job_count_for_company": company.get("job_count_for_company", 1),
        "all_roles_seen": company.get("all_roles_seen", ""),

        # Provenance
        "dm_source": dm_source,
        "blitz_icp_rank": person.get("blitz_icp_rank"),
        "blitz_icp_layer": person.get("blitz_icp_layer"),
    }
    # Drop empty rows where we couldn't even get a name
    if not out["first_name"] or not out["last_name"]:
        return None  # type: ignore
    return out


if __name__ == "__main__":
    # Smoke test: read companies CSV from job_scraper run, run DM finder
    import sys, csv
    run_id = sys.argv[1] if len(sys.argv) > 1 else "smoketest"
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    companies_csv = run_dir(run_id) / "stage1_jobs" / "companies_hiring.csv"
    companies = []
    with companies_csv.open() as f:
        for row in csv.DictReader(f):
            # Skip rows without a website (can't lookup LI)
            if not row.get("employer_website"):
                continue
            companies.append(row)
            if len(companies) >= cap:
                break

    print(f"Processing {len(companies)} companies (cap={cap})...")
    dms = find_decision_makers(run_id, companies, per_company=1)
    dms = [d for d in dms if d]
    print(f"\n{len(dms)} decision makers found.")
    for d in dms:
        print(f"  - {d['first_name']} {d['last_name']:<18} | {d['title']:<35} | "
              f"{d['company_name']:<30} | {d['linkedin_url']}")
