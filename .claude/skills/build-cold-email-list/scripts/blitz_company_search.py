#!/usr/bin/env python3
"""
BlitzAPI Company Search.

Reads icp.json firmographics + geographics, paginates BlitzAPI company
search, writes raw/blitz_companies.csv. Idempotent.

Usage:
  python blitz_company_search.py --run-id 2026-05-14_1330_xxx [--limit 2000]

Docs: https://docs.blitz-api.ai/api-reference/company-search/company-search
"""
from __future__ import annotations

import json
import time

from _common import (
    arg, append_csv, get_key, load_checkpoint, load_json, log_event,
    make_session, normalize_country, normalize_domain, normalize_linkedin,
    run_dir, save_checkpoint,
)

BLITZ_BASE = "https://api.blitz-api.ai"
ENDPOINT = "/company/search"

FIELDS = [
    "source", "external_id",
    "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city", "founded_year", "raw_json",
]


def build_payload(icp: dict, page: int, page_size: int) -> dict:
    firmo = icp.get("firmographics", {})
    geo = icp.get("geographics", {})
    return {
        "industries": firmo.get("industries", []),
        "industries_exclude": firmo.get("industries_exclude", []),
        "employee_count_min": firmo.get("employee_count_min"),
        "employee_count_max": firmo.get("employee_count_max"),
        "founded_year_min": firmo.get("founded_year_min"),
        "founded_year_max": firmo.get("founded_year_max"),
        "tech_stack_includes": firmo.get("tech_stack_includes", []),
        "tech_stack_excludes": firmo.get("tech_stack_excludes", []),
        "countries": geo.get("countries", []),
        "page": page,
        "limit": page_size,
    }


def normalize_company(c: dict) -> dict:
    return {
        "source": "blitz_companies",
        "external_id": c.get("id") or c.get("_id") or "",
        "company_name": (c.get("name") or c.get("company_name") or "").strip(),
        "company_domain": normalize_domain(
            c.get("domain") or c.get("website") or c.get("company_domain") or ""
        ),
        "company_linkedin_url": normalize_linkedin(c.get("linkedin_url") or ""),
        "company_industry": (c.get("industry") or "").strip(),
        "company_employee_count": c.get("employee_count") or "",
        "country": normalize_country(c.get("country") or ""),
        "state": (c.get("state") or c.get("region") or "").strip(),
        "city": (c.get("city") or "").strip(),
        "founded_year": c.get("founded_year") or "",
        "raw_json": json.dumps(c, ensure_ascii=False),
    }


def main() -> None:
    run_id = arg("run-id", required=True)
    page_size = int(arg("page-size", "100"))
    overall_limit = int(arg("limit", "2000"))

    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")
    out_path = rd / "raw" / "blitz_companies.csv"

    ckpt = load_checkpoint(run_id, "blitz_companies", default={"page": 1, "total": 0})
    page = ckpt["page"]
    total = ckpt["total"]

    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('BLITZAPI_KEY')}",
        "Content-Type": "application/json",
    }

    log_event(run_id, "blitz_companies.start", page=page, target=overall_limit)

    while total < overall_limit:
        payload = build_payload(icp, page, min(page_size, overall_limit - total))
        r = session.post(BLITZ_BASE + ENDPOINT, json=payload, headers=headers, timeout=60)
        if r.status_code == 429:
            time.sleep(5)
            continue
        if r.status_code >= 400:
            log_event(run_id, "blitz_companies.error",
                      status=r.status_code, body=r.text[:500])
            r.raise_for_status()

        body = r.json()
        rows = body.get("companies") or body.get("results") or body.get("data") or []
        if not rows:
            break

        normalised = [normalize_company(c) for c in rows]
        wrote = append_csv(out_path, normalised, FIELDS)
        total += wrote
        page += 1
        save_checkpoint(run_id, "blitz_companies", {"page": page, "total": total})
        log_event(run_id, "blitz_companies.page",
                  page=page - 1, wrote=wrote, total=total)

        if body.get("has_more") is False or len(rows) < page_size:
            break
        time.sleep(0.25)

    log_event(run_id, "blitz_companies.done", total=total)
    print(f"BlitzAPI company search → {total} rows → {out_path}")


if __name__ == "__main__":
    main()
