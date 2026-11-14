#!/usr/bin/env python3
"""
BlitzAPI Employee Finder — Decision Maker Enrichment.

Reads all raw/*.csv that are company-only sources, dedupes domains,
and queries BlitzAPI for matching decision makers per the ICP persona.

Writes raw/decision_makers.csv. Idempotent — keeps a checkpoint of
completed domains so re-runs only process the remainder.

Usage:
  python blitz_employee_finder.py --run-id 2026-05-14_1330_xxx
        [--per-company 3]
        [--sources ocean,blitz_companies,existing_db_crunchbase]
"""
from __future__ import annotations

import json
import time

from _common import (
    arg, append_csv, get_key, load_checkpoint, load_json, log_event,
    make_session, normalize_country, normalize_domain, normalize_linkedin,
    normalize_name, read_csv, run_dir, save_checkpoint,
)

BLITZ_BASE = "https://api.blitz-api.ai"
ENDPOINT = "/people/employee-finder"

# Sources that return companies (no people) and therefore need DM finding.
COMPANY_SOURCES_DEFAULT = [
    "ocean",
    "blitz_companies",
    "existing_db_crunchbase",
    "existing_db_gmaps",
    # any "<directory_slug>" sources from raw/ — auto-detected below as well.
]

FIELDS = [
    "source", "external_id",
    "first_name", "last_name", "full_name",
    "title", "linkedin_url",
    "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city",
    "sourced_from_domain", "raw_json",
]


def collect_company_rows(rd, explicit_sources):
    """Scan raw/ for company-only source CSVs and yield (source_name, row)."""
    raw_dir = rd / "raw"
    files = sorted(raw_dir.glob("*.csv"))
    explicit = set(explicit_sources or [])
    auto = set(COMPANY_SOURCES_DEFAULT)
    for f in files:
        # Heuristic: if filename suggests a directory or company source, include.
        slug = f.stem
        if explicit and slug not in explicit:
            continue
        if not explicit and slug not in auto and not slug.startswith("directory_"):
            # Skip people sources (instantly_supersearch, blitz_people).
            if slug in ("instantly_supersearch", "blitz_people", "decision_makers"):
                continue
            # Conservative default: skip unknown.
            if slug not in auto:
                continue
        for row in read_csv(f):
            yield slug, row


def normalize_person(p: dict, source_slug: str, queried_domain: str) -> dict:
    return {
        "source": f"{source_slug}_dm",
        "external_id": p.get("id") or p.get("_id") or "",
        "first_name": normalize_name(p.get("first_name") or ""),
        "last_name": normalize_name(p.get("last_name") or ""),
        "full_name": normalize_name(
            p.get("full_name") or
            f'{p.get("first_name","")} {p.get("last_name","")}'
        ),
        "title": (p.get("title") or "").strip(),
        "linkedin_url": normalize_linkedin(p.get("linkedin_url") or ""),
        "company_name": (p.get("company_name") or "").strip(),
        "company_domain": normalize_domain(
            p.get("company_domain") or p.get("company_website") or queried_domain
        ),
        "company_linkedin_url": normalize_linkedin(p.get("company_linkedin_url") or ""),
        "company_industry": (p.get("company_industry") or p.get("industry") or "").strip(),
        "company_employee_count": p.get("company_employee_count") or p.get("employee_count") or "",
        "country": normalize_country(p.get("country") or ""),
        "state": (p.get("state") or p.get("region") or "").strip(),
        "city": (p.get("city") or "").strip(),
        "sourced_from_domain": queried_domain,
        "raw_json": json.dumps(p, ensure_ascii=False),
    }


def main() -> None:
    run_id = arg("run-id", required=True)
    per_company = int(arg("per-company", "3"))
    explicit_sources = (arg("sources", "") or "").split(",") if arg("sources") else []
    explicit_sources = [s.strip() for s in explicit_sources if s.strip()]

    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")
    persona = icp.get("persona", {})

    # 1. Build the unique-domain queue with provenance.
    domain_to_source = {}
    domain_to_linkedin = {}
    for source_slug, row in collect_company_rows(rd, explicit_sources):
        d = normalize_domain(row.get("company_domain") or row.get("website") or "")
        if not d:
            continue
        domain_to_source.setdefault(d, source_slug)
        if row.get("company_linkedin_url"):
            domain_to_linkedin.setdefault(d, normalize_linkedin(row["company_linkedin_url"]))

    ckpt = load_checkpoint(run_id, "blitz_dm", default={"done_domains": []})
    done = set(ckpt["done_domains"])
    queue = [d for d in domain_to_source if d not in done]
    log_event(run_id, "blitz_dm.start", total_domains=len(domain_to_source),
              remaining=len(queue))

    if not queue:
        print("No new domains to process.")
        return

    out_path = rd / "raw" / "decision_makers.csv"
    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('BLITZAPI_KEY')}",
        "Content-Type": "application/json",
    }
    total_people = 0

    for d in queue:
        body_payload = {
            "company_domain": d,
            "title_keywords": persona.get("titles", []),
            "title_keywords_exclude": persona.get("title_exclusions", []),
            "seniority": persona.get("seniority", []),
            "departments": persona.get("departments", []),
            "limit": per_company,
        }
        if d in domain_to_linkedin:
            body_payload["company_linkedin_url"] = domain_to_linkedin[d]

        try:
            r = session.post(BLITZ_BASE + ENDPOINT, json=body_payload,
                             headers=headers, timeout=60)
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code >= 400:
                log_event(run_id, "blitz_dm.error", domain=d,
                          status=r.status_code, body=r.text[:300])
                done.add(d)
                save_checkpoint(run_id, "blitz_dm", {"done_domains": sorted(done)})
                continue
            body = r.json()
            people = body.get("employees") or body.get("people") or body.get("results") or []
            normalized = [normalize_person(p, domain_to_source[d], d) for p in people]
            wrote = append_csv(out_path, normalized, FIELDS) if normalized else 0
            total_people += wrote
            done.add(d)
            save_checkpoint(run_id, "blitz_dm", {"done_domains": sorted(done)})
            if wrote == 0:
                log_event(run_id, "blitz_dm.no_dm", domain=d)
        except Exception as e:
            log_event(run_id, "blitz_dm.exception", domain=d, error=str(e))
        time.sleep(0.2)

    log_event(run_id, "blitz_dm.done",
              total_domains=len(domain_to_source), people_found=total_people)
    print(f"BlitzAPI employee finder → {total_people} decision makers → {out_path}")


if __name__ == "__main__":
    main()
