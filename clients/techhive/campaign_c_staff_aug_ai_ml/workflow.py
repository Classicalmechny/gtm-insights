"""
TechHive — Campaign C — Staff Augmentation (AI/ML) — Weekly Orchestrator

Designed to be triggered every Monday by either:
  - the local cron / launchd / systemd-timer (run `python3 workflow.py`)
  - the n8n workflow (which mirrors these stages with HTTP-Request nodes)

Pipeline (per the user's screenshot):
  1. JSearch → companies hiring AI/ML roles (US + Canada, last 7 days)
  2. BlitzAPI domain→LinkedIn → Waterfall ICP → 1 decision maker per company
  3. BlitzAPI email enrichment + MX-check verification floor
  4. Deepinfra (+ Firecrawl when needed) → personalization variables
  5. Instantly upload (dedupes against existing campaign leads)

Outputs go to ./output/<run_id>/ with one folder per stage + a final summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Path import shim so `from <module>` works whether run from this dir or n8n
sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))

from _common import env, log_event, run_dir, today_run_id, write_json
from job_scraper import scrape, ROLES, COUNTRIES
from company_filter import filter_companies
from dm_finder import find_decision_makers
from email_enricher import enrich
from personalizer import personalize
from instantly_uploader import upload


def run(run_id: str | None = None,
        roles: list[str] = ROLES,
        countries: list[str] = COUNTRIES,
        pages_per_role: int = 3,
        per_company_dms: int = 1,
        company_cap: int | None = None,
        skip_personalize: bool = False,
        dry_run_upload: bool = False) -> dict:
    """End-to-end execution. Returns summary dict for downstream reporting."""
    run_id = run_id or today_run_id()
    rd = run_dir(run_id)
    write_json(rd / "config.json", {
        "roles": roles, "countries": countries,
        "pages_per_role": pages_per_role,
        "per_company_dms": per_company_dms,
        "company_cap": company_cap,
        "campaign_id": env("INSTANTLY_CAMPAIGN_ID"),
    })

    started = time.time()
    log_event(run_id, "workflow.start",
              roles=roles, countries=countries,
              pages_per_role=pages_per_role)

    # 1. JOB SCRAPING
    companies = scrape(run_id, roles=roles, countries=countries,
                       pages_per_role=pages_per_role)
    companies = [c for c in companies if c.get("employer_website")]
    if company_cap:
        companies = companies[:company_cap]

    # 1b. ICP FIRMOGRAPHIC FILTER (headcount 2-50, US/CA HQ, allowed industries)
    qualified = filter_companies(run_id, companies)

    # 2. DECISION MAKER FINDING — only on qualified companies
    dms = find_decision_makers(run_id, qualified, per_company=per_company_dms)
    dms = [d for d in dms if d]

    # 3. EMAIL ENRICHMENT + VERIFICATION
    leads = enrich(run_id, dms)

    # 4. AI PERSONALIZATION (skip in tight smoke tests)
    if skip_personalize:
        from personalizer import normalize_role
        for l in leads:
            l["role_being_hired"] = normalize_role(l.get("job_title_hiring", ""))
            l["tech_skills"] = "Python, ML stack"
            l["fallback_role"] = "AI Engineer"
            l.setdefault("company_description", "")
            l.setdefault("usecase", "")
    else:
        leads = personalize(run_id, leads)

    # 5. UPLOAD TO INSTANTLY (or dry-run)
    if dry_run_upload:
        upload_stats = {"input": len(leads), "uploaded": 0, "dry_run": True}
    else:
        upload_stats = upload(run_id, leads)

    elapsed_s = round(time.time() - started, 1)
    summary = {
        "run_id": run_id,
        "elapsed_s": elapsed_s,
        "companies_scraped": len(companies),
        "companies_qualified": len(qualified),
        "decision_makers": len(dms),
        "leads_with_email": len(leads),
        "upload": upload_stats,
    }
    log_event(run_id, "workflow.done",
              elapsed_s=elapsed_s,
              companies_scraped=len(companies),
              companies_qualified=len(qualified),
              decision_makers=len(dms),
              leads_with_email=len(leads),
              upload=upload_stats)
    write_json(rd / "summary.json", summary)
    return summary


def cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--pages-per-role", type=int, default=3)
    ap.add_argument("--per-company-dms", type=int, default=1)
    ap.add_argument("--cap", type=int, default=None,
                    help="Cap companies (smoke test)")
    ap.add_argument("--smoke", action="store_true",
                    help="1 role, US-only, 1 page, cap 5, skip personalize")
    ap.add_argument("--dry-upload", action="store_true",
                    help="Don't actually push to Instantly")
    args = ap.parse_args()

    if args.smoke:
        summary = run(run_id=args.run_id or "smoke_e2e",
                      roles=["Machine Learning Engineer"],
                      countries=["US"], pages_per_role=1,
                      company_cap=5, skip_personalize=True,
                      dry_run_upload=args.dry_upload)
    else:
        summary = run(run_id=args.run_id,
                      pages_per_role=args.pages_per_role,
                      per_company_dms=args.per_company_dms,
                      company_cap=args.cap,
                      dry_run_upload=args.dry_upload)
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    cli()
