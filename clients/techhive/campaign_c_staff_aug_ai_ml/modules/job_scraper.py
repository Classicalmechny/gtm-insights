"""
JSearch (RapidAPI) job-board scraper.

Pulls jobs for AI/ML roles in US + Canada posted in the last 7 days,
dedupes by (employer_name, employer_website), returns a list of company
hiring signals.

Each hiring signal row:
    {
      "employer_name": "...",
      "employer_website": "...",        # cleaned domain
      "employer_linkedin": "...",       # if available
      "job_title": "...",               # most recent posting title
      "job_id": "...",
      "job_apply_link": "...",
      "job_posted_at": "...",
      "job_city": "...",
      "job_state": "...",
      "job_country": "...",
      "job_description_snippet": "...", # first ~400 chars
      "job_role_query": "...",          # which role-query found this
      "job_count_for_company": N,       # how many of the 8 roles this company is hiring
    }
"""
from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from _common import (
    env, log_event, make_session, normalize_domain, run_dir, write_csv, write_json,
)

JSEARCH_HOST = "jsearch.p.rapidapi.com"
JSEARCH_URL = f"https://{JSEARCH_HOST}/search"

ROLES = [
    "Machine Learning Engineer",
    "ML Engineer",
    "Deep Learning Engineer",
    "NLP Engineer",
    "Computer Vision Engineer",
    "AI Research Engineer",
    "Applied AI Engineer",
    "AI Engineer",
]

COUNTRIES = ["US", "CA"]

# Filter out non-target employers (FAANG, dev-agency competitors, recruiters)
EXCLUDE_EMPLOYER_KEYWORDS = {
    # FAANG + mega-corps (in-house eng teams, won't buy staff aug)
    "google", "alphabet", "meta", "facebook", "instagram", "whatsapp",
    "amazon", "aws", "apple", "microsoft", "azure", "openai",
    "anthropic", "nvidia", "intel", "ibm", "oracle", "salesforce",
    "tesla", "spacex", "netflix", "uber", "lyft", "airbnb",
    "stripe", "shopify", "snowflake", "databricks", "palantir",
    "twitter", "x corp", "linkedin", "tiktok", "bytedance",
    "deepmind", "github", "gitlab",
    # Recruiter / staffing agency reposts
    "robert half", "kforce", "tek systems", "teksystems",
    "insight global", "randstad", "hays", "experis", "adecco",
    "michael page", "deloitte", "accenture", "cognizant", "infosys",
    "tata consultancy", "tcs", "wipro", "capgemini", "mindtree",
    # Job-board reposters
    "jobot", "lensa", "jobleads", "ladders", "ziprecruiter",
    "talent.com", "diversity recruiter", "joblist",
}


def _is_excluded(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in EXCLUDE_EMPLOYER_KEYWORDS)


def _request_page(session, role: str, country: str, page: int) -> dict:
    params = {
        "query": f"{role} in {country}",
        "page": str(page),
        "num_pages": "1",
        "country": country.lower(),
        "date_posted": "week",
        "employment_types": "FULLTIME",
    }
    headers = {
        "x-rapidapi-host": JSEARCH_HOST,
        "x-rapidapi-key": env("RAPIDAPI_KEY"),
    }
    r = session.get(JSEARCH_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def scrape(run_id: str, roles: list[str] = ROLES, countries: list[str] = COUNTRIES,
           pages_per_role: int = 3, sleep_between: float = 0.5,
           max_jobs_per_company: int = 1) -> list[dict]:
    """
    Run all role × country combinations.

    pages_per_role: how many pages to pull per (role, country). 1 page = 10 jobs.
        Default 3 pages × 8 roles × 2 countries = 48 requests, ~480 jobs.

    max_jobs_per_company: when collapsing per-company, keep only N most-recent.
    """
    session = make_session()
    out_dir = run_dir(run_id) / "stage1_jobs"
    out_dir.mkdir(exist_ok=True)

    all_jobs: list[dict] = []
    for role in roles:
        for country in countries:
            for page in range(1, pages_per_role + 1):
                try:
                    body = _request_page(session, role, country, page)
                except Exception as e:
                    log_event(run_id, "job_scrape.error",
                              role=role, country=country, page=page, error=str(e))
                    continue
                items = body.get("data") or []
                if not items:
                    log_event(run_id, "job_scrape.empty",
                              role=role, country=country, page=page)
                    break
                for j in items:
                    j["_role_query"] = role
                    all_jobs.append(j)
                log_event(run_id, "job_scrape.page",
                          role=role, country=country, page=page, count=len(items))
                time.sleep(sleep_between)

    # Persist raw for debugging
    write_json(out_dir / "raw_jobs.json", all_jobs)

    # Dedupe → per-company signal
    per_company: dict[str, dict] = {}
    role_count: dict[str, set] = defaultdict(set)

    for j in all_jobs:
        name = (j.get("employer_name") or "").strip()
        if not name or _is_excluded(name):
            continue
        domain = normalize_domain(j.get("employer_website") or "")
        # Key by domain when we have it, else by lowercased name
        key = domain or name.lower()
        role_count[key].add(j.get("_role_query"))

        if key not in per_company:
            per_company[key] = {
                "employer_name": name,
                "employer_website": domain,
                "employer_linkedin": (j.get("employer_linkedin") or "").strip(),
                "employer_logo": (j.get("employer_logo") or "").strip(),
                "employer_company_type": (j.get("employer_company_type") or "").strip(),
                "job_title": (j.get("job_title") or "").strip(),
                "job_id": (j.get("job_id") or "").strip(),
                "job_apply_link": (j.get("job_apply_link") or "").strip(),
                "job_posted_at": (j.get("job_posted_at_datetime_utc") or "").strip(),
                "job_city": (j.get("job_city") or "").strip(),
                "job_state": (j.get("job_state") or "").strip(),
                "job_country": (j.get("job_country") or "").strip(),
                "job_description_snippet": (j.get("job_description") or "")[:400],
                "job_role_query": j.get("_role_query"),
                "job_min_salary": j.get("job_min_salary"),
                "job_max_salary": j.get("job_max_salary"),
            }
        else:
            # Keep most-recent job
            prev = per_company[key].get("job_posted_at", "")
            curr = j.get("job_posted_at_datetime_utc", "")
            if curr and curr > prev:
                per_company[key].update({
                    "job_title": (j.get("job_title") or "").strip(),
                    "job_id": (j.get("job_id") or "").strip(),
                    "job_apply_link": (j.get("job_apply_link") or "").strip(),
                    "job_posted_at": curr,
                    "job_city": (j.get("job_city") or "").strip(),
                    "job_state": (j.get("job_state") or "").strip(),
                    "job_country": (j.get("job_country") or "").strip(),
                    "job_description_snippet": (j.get("job_description") or "")[:400],
                    "job_role_query": j.get("_role_query"),
                })

    # Inject role counts
    rows = []
    for key, row in per_company.items():
        row["job_count_for_company"] = len(role_count[key])
        row["all_roles_seen"] = "|".join(sorted(role_count[key]))
        rows.append(row)

    # Sort: companies hiring multiple AI roles first (stronger signal)
    rows.sort(key=lambda r: (-r["job_count_for_company"], r["employer_name"]))

    # Write CSV
    out_csv = out_dir / "companies_hiring.csv"
    fieldnames = [
        "employer_name", "employer_website", "employer_linkedin",
        "employer_logo", "employer_company_type",
        "job_title", "job_id", "job_apply_link", "job_posted_at",
        "job_city", "job_state", "job_country",
        "job_description_snippet", "job_role_query",
        "job_min_salary", "job_max_salary",
        "job_count_for_company", "all_roles_seen",
    ]
    write_csv(out_csv, rows, fieldnames)
    log_event(run_id, "job_scrape.done",
              raw_jobs=len(all_jobs), unique_companies=len(rows), output=str(out_csv))
    return rows


if __name__ == "__main__":
    import sys
    rid = sys.argv[1] if len(sys.argv) > 1 else "smoketest"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    # Smoke-test: one role, US-only, 1 page
    if rid == "smoketest":
        rows = scrape(rid, roles=["Machine Learning Engineer"], countries=["US"],
                      pages_per_role=pages)
    else:
        rows = scrape(rid, pages_per_role=pages)
    print(f"\n{len(rows)} unique companies found.")
    for r in rows[:10]:
        print(f"  - {r['employer_name']:<40} | {r['employer_website']:<30} | {r['job_title']}")
