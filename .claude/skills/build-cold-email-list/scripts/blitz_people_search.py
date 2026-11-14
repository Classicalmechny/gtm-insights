#!/usr/bin/env python3
"""
BlitzAPI People Search.

Reads icp.json from the run directory, calls BlitzAPI people search,
paginates, writes raw/blitz_people.csv. Idempotent — resumes from the
last completed page on re-run.

Usage:
  python blitz_people_search.py --run-id 2026-05-14_1330_xxx [--limit 1000]

Docs: https://docs.blitz-api.ai/api-reference/people-search/find-people
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from _common import (
    arg, append_csv, get_key, load_checkpoint, load_json, log_event,
    make_session, normalize_country, normalize_domain, normalize_linkedin,
    normalize_name, run_dir, save_checkpoint,
)

BLITZ_BASE = "https://api.blitz-api.ai"
ENDPOINT = "/people/search"

FIELDS = [
    "source", "external_id", "first_name", "last_name", "full_name",
    "title", "linkedin_url",
    "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city", "raw_json",
]


def build_payload(icp: dict, page: int, page_size: int) -> dict:
    persona = icp.get("persona", {})
    firmo = icp.get("firmographics", {})
    geo = icp.get("geographics", {})
    return {
        "title_keywords": persona.get("titles", []),
        "title_keywords_exclude": persona.get("title_exclusions", []),
        "seniority": persona.get("seniority", []),
        "departments": persona.get("departments", []),
        "industries": firmo.get("industries", []),
        "industries_exclude": firmo.get("industries_exclude", []),
        "employee_count_min": firmo.get("employee_count_min"),
        "employee_count_max": firmo.get("employee_count_max"),
        "countries": geo.get("countries", []),
        "page": page,
        "limit": page_size,
    }


def normalize_person(p: dict) -> dict:
    return {
        "source": "blitz_people",
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
        "company_domain": normalize_domain(p.get("company_domain") or p.get("company_website") or ""),
        "company_linkedin_url": normalize_linkedin(p.get("company_linkedin_url") or ""),
        "company_industry": (p.get("company_industry") or p.get("industry") or "").strip(),
        "company_employee_count": p.get("company_employee_count") or p.get("employee_count") or "",
        "country": normalize_country(p.get("country") or ""),
        "state": (p.get("state") or p.get("region") or "").strip(),
        "city": (p.get("city") or "").strip(),
        "raw_json": json.dumps(p, ensure_ascii=False),
    }


def main() -> None:
    run_id = arg("run-id", required=True)
    page_size = int(arg("page-size", "100"))
    overall_limit = int(arg("limit", "2000"))

    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")
    out_path = rd / "raw" / "blitz_people.csv"

    ckpt = load_checkpoint(run_id, "blitz_people", default={"page": 1, "total": 0})
    page = ckpt["page"]
    total = ckpt["total"]

    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('BLITZAPI_KEY')}",
        "Content-Type": "application/json",
    }

    log_event(run_id, "blitz_people.start", page=page, target=overall_limit)

    while total < overall_limit:
        payload = build_payload(icp, page, min(page_size, overall_limit - total))
        r = session.post(BLITZ_BASE + ENDPOINT, json=payload, headers=headers, timeout=60)
        if r.status_code == 429:
            time.sleep(5)
            continue
        if r.status_code >= 400:
            log_event(run_id, "blitz_people.error",
                      status=r.status_code, body=r.text[:500])
            r.raise_for_status()

        body = r.json()
        rows = body.get("people") or body.get("results") or body.get("data") or []
        if not rows:
            break

        normalised = [normalize_person(p) for p in rows]
        wrote = append_csv(out_path, normalised, FIELDS)
        total += wrote
        page += 1
        save_checkpoint(run_id, "blitz_people", {"page": page, "total": total})
        log_event(run_id, "blitz_people.page",
                  page=page - 1, wrote=wrote, total=total)

        # End if API signals no more pages.
        if body.get("has_more") is False or len(rows) < page_size:
            break

        time.sleep(0.25)

    log_event(run_id, "blitz_people.done", total=total)
    print(f"BlitzAPI people search → {total} rows → {out_path}")


if __name__ == "__main__":
    main()
