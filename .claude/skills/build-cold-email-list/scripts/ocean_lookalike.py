#!/usr/bin/env python3
"""
Ocean.io Lookalike Companies.

Reads icp.json seed_domains + firmographics + geographics, paginates the
Ocean.io companies/search v3 endpoint, writes raw/ocean.csv.

Skips entirely if no seed_domains are present in the ICP.

Usage:
  python ocean_lookalike.py --run-id 2026-05-14_1330_xxx [--limit 500]

Docs: https://app.ocean.io/docs/searchCompaniesV3
"""
from __future__ import annotations

import json
import time

from _common import (
    arg, append_csv, get_key, load_checkpoint, load_json, log_event,
    make_session, normalize_country, normalize_domain, normalize_linkedin,
    run_dir, save_checkpoint,
)

OCEAN_BASES = ["https://api.ocean.io/v3", "https://app.ocean.io/api/v3"]
ENDPOINT = "/companies/search"

FIELDS = [
    "source", "external_id",
    "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city", "founded_year", "lookalike_score",
    "raw_json",
]


def build_payload(icp: dict, offset: int, limit: int) -> dict:
    seeds = icp.get("seed_domains") or []
    firmo = icp.get("firmographics", {})
    geo = icp.get("geographics", {})
    return {
        "lookalike": {"domains": seeds},
        "filters": {
            "industries": firmo.get("industries", []),
            "employeeCount": {
                "min": firmo.get("employee_count_min"),
                "max": firmo.get("employee_count_max"),
            },
            "countries": geo.get("countries", []),
            "foundedYear": {
                "min": firmo.get("founded_year_min"),
                "max": firmo.get("founded_year_max"),
            },
        },
        "limit": limit,
        "offset": offset,
    }


def normalize_company(c: dict) -> dict:
    return {
        "source": "ocean",
        "external_id": c.get("id") or c.get("oceanId") or "",
        "company_name": (c.get("name") or "").strip(),
        "company_domain": normalize_domain(c.get("domain") or c.get("website") or ""),
        "company_linkedin_url": normalize_linkedin(c.get("linkedinUrl") or ""),
        "company_industry": (c.get("industry") or "").strip(),
        "company_employee_count": c.get("employeeCount") or c.get("employee_count") or "",
        "country": normalize_country(c.get("country") or ""),
        "state": (c.get("state") or "").strip(),
        "city": (c.get("city") or c.get("hqCity") or "").strip(),
        "founded_year": c.get("foundedYear") or c.get("founded_year") or "",
        "lookalike_score": c.get("lookalikeScore") or c.get("score") or "",
        "raw_json": json.dumps(c, ensure_ascii=False),
    }


def main() -> None:
    run_id = arg("run-id", required=True)
    overall_limit = int(arg("limit", "500"))
    page_size = int(arg("page-size", "100"))

    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")
    seeds = icp.get("seed_domains") or []
    if not seeds:
        log_event(run_id, "ocean.skip", reason="no_seeds")
        print("No seed_domains in ICP — skipping Ocean.io.")
        return

    out_path = rd / "raw" / "ocean.csv"
    ckpt = load_checkpoint(run_id, "ocean", default={"offset": 0, "total": 0})
    offset = ckpt["offset"]
    total = ckpt["total"]

    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('OCEAN_KEY')}",
        "Content-Type": "application/json",
    }

    log_event(run_id, "ocean.start", offset=offset, target=overall_limit, seeds=seeds)

    # Resolve which base URL works (api.ocean.io preferred; app.ocean.io fallback).
    base_url = ckpt.get("base_url")
    if not base_url:
        for candidate in OCEAN_BASES:
            probe = session.post(candidate + ENDPOINT,
                                 json=build_payload(icp, 0, 1),
                                 headers=headers, timeout=30)
            if probe.status_code < 500 and probe.status_code != 404:
                base_url = candidate
                break
        if not base_url:
            log_event(run_id, "ocean.base_resolve.failed", tried=OCEAN_BASES)
            raise RuntimeError("Could not reach Ocean.io API at any known base URL.")
        log_event(run_id, "ocean.base_resolved", base=base_url)
        ckpt["base_url"] = base_url
        save_checkpoint(run_id, "ocean", ckpt)

    while total < overall_limit:
        payload = build_payload(icp, offset, min(page_size, overall_limit - total))
        r = session.post(base_url + ENDPOINT, json=payload, headers=headers, timeout=60)
        if r.status_code == 429:
            time.sleep(5)
            continue
        if r.status_code == 401:
            # Some installs of Ocean use Api-Key header — try once.
            headers2 = {"Api-Key": get_key("OCEAN_KEY"),
                        "Content-Type": "application/json"}
            r = session.post(base_url + ENDPOINT, json=payload,
                             headers=headers2, timeout=60)
        if r.status_code >= 400:
            log_event(run_id, "ocean.error",
                      status=r.status_code, body=r.text[:500])
            r.raise_for_status()

        body = r.json()
        rows = body.get("companies") or body.get("data") or body.get("results") or []
        if not rows:
            break
        normalised = [normalize_company(c) for c in rows]
        wrote = append_csv(out_path, normalised, FIELDS)
        total += wrote
        offset += len(rows)
        save_checkpoint(run_id, "ocean", {"offset": offset, "total": total})
        log_event(run_id, "ocean.page", offset=offset, wrote=wrote, total=total)

        if len(rows) < page_size or body.get("hasMore") is False:
            break
        time.sleep(0.5)

    log_event(run_id, "ocean.done", total=total)
    print(f"Ocean.io lookalikes → {total} companies → {out_path}")


if __name__ == "__main__":
    main()
