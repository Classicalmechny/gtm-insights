#!/usr/bin/env python3
"""
Existing GitHub Database Filter.

Pulls the pre-scraped dataset (Crunchbase / Google Maps US) from:
  https://github.com/growthenginenowoslawski/coldoutboundskills

Cached locally at ~/.cache/cold-outbound-db/. Refreshes weekly.

Applies ICP firmographics + geographics filters, writes:
  - raw/existing_db_crunchbase.csv
  - raw/existing_db_gmaps.csv

Usage:
  python existing_db_filter.py --run-id 2026-05-14_1330_xxx
        [--subsets crunchbase,gmaps]
        [--max 2000]
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

from _common import (
    arg, append_csv, load_json, log_event, normalize_country,
    normalize_domain, run_dir,
)

REPO_URL = "https://github.com/growthenginenowoslawski/coldoutboundskills.git"
CACHE_DIR = Path.home() / ".cache" / "cold-outbound-db"
DATA_SUBPATH = "Common Outbound Lists"   # folder inside the repo
REFRESH_DAYS = 7

# Adapt these names to actual file names in the repo. The script
# auto-detects any CSV whose path contains one of these tokens.
SUBSET_TOKENS = {
    "crunchbase": ["crunchbase", "saas", "startup"],
    "gmaps": ["google", "maps", "gmaps", "local"],
}

OUT_FIELDS = [
    "source", "external_id",
    "company_name", "company_domain", "company_industry",
    "company_employee_count",
    "country", "state", "city",
    "phone", "website",
    "funding_total", "last_funding_at",
    "rating", "review_count",
    "first_name", "last_name", "full_name",
    "raw_json",
]


def ensure_cache():
    refreshed_marker = CACHE_DIR / ".last_refreshed"
    needs_refresh = True
    if CACHE_DIR.exists() and refreshed_marker.exists():
        try:
            ts = _dt.datetime.fromisoformat(refreshed_marker.read_text().strip())
            age_days = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - ts).days
            needs_refresh = age_days >= REFRESH_DAYS
        except Exception:
            needs_refresh = True

    if not CACHE_DIR.exists():
        CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["git", "clone", "--depth", "1", REPO_URL,
                            str(CACHE_DIR)], check=True, timeout=300)
        except Exception as e:
            print(f"git clone failed: {e}; will attempt to keep going if cache exists.", file=sys.stderr)
            return
    elif needs_refresh:
        try:
            subprocess.run(["git", "-C", str(CACHE_DIR), "pull", "--ff-only"],
                           check=True, timeout=300)
        except Exception as e:
            print(f"git pull failed: {e}; using existing cache.", file=sys.stderr)
    refreshed_marker.write_text(_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat())


def find_subset_files(subset: str) -> list[Path]:
    tokens = SUBSET_TOKENS[subset]
    matches = []
    for p in CACHE_DIR.rglob("*.csv"):
        plower = str(p).lower()
        if any(t in plower for t in tokens):
            matches.append(p)
    return matches


def passes_filter(row: dict, icp: dict, _subset: str) -> bool:
    firmo = icp.get("firmographics", {})
    geo = icp.get("geographics", {})

    # Country filter
    countries = [c.lower() for c in (geo.get("countries") or [])]
    if countries:
        ctry = normalize_country(row.get("country") or row.get("Country") or "").lower()
        if ctry and not any(c in ctry or ctry in c for c in countries):
            return False

    # Employee count filter — handle both scalar ("23") and bucket ("11-50") values.
    emp = (row.get("employee_count") or row.get("Employee Count") or
           row.get("employees") or "")
    if emp:
        try:
            s = str(emp).replace(",", "").strip()
            parts = s.split("-")
            emp_lo = int(parts[0])
            emp_hi = int(parts[1]) if len(parts) > 1 else emp_lo
            mn = firmo.get("employee_count_min")
            mx = firmo.get("employee_count_max")
            # Bucket overlap check: keep the row if its range intersects [mn, mx].
            if mn is not None and emp_hi < mn:
                return False
            if mx is not None and emp_lo > mx:
                return False
        except Exception:
            pass

    # Industry filter (substring match — loose)
    industries = [i.lower() for i in (firmo.get("industries") or [])]
    if industries:
        ind = (row.get("industry") or row.get("Industry") or
               row.get("category") or row.get("Category") or "").lower()
        if ind and not any(i in ind or ind in i for i in industries):
            return False

    # Industry exclusion
    excludes = [i.lower() for i in (firmo.get("industries_exclude") or [])]
    if excludes:
        ind = (row.get("industry") or row.get("Industry") or
               row.get("category") or row.get("Category") or "").lower()
        if any(i in ind for i in excludes):
            return False

    return True


def normalize_row(row: dict, subset: str) -> dict:
    return {
        "source": f"existing_db_{subset}",
        "external_id": (
            row.get("uuid") or row.get("id") or row.get("place_id") or
            row.get("crunchbase_uuid") or ""
        ),
        "company_name": (row.get("name") or row.get("company_name") or
                         row.get("Name") or "").strip(),
        "company_domain": normalize_domain(
            row.get("website") or row.get("Website") or
            row.get("domain") or ""
        ),
        "company_industry": (row.get("industry") or row.get("Industry") or
                              row.get("category") or row.get("Category") or "").strip(),
        "company_employee_count": (
            row.get("employee_count") or row.get("Employee Count") or
            row.get("employees") or ""
        ),
        "country": normalize_country(row.get("country") or row.get("Country") or ""),
        "state": (row.get("state") or row.get("State") or "").strip(),
        "city": (row.get("city") or row.get("City") or "").strip(),
        "phone": (row.get("phone") or row.get("Phone") or "").strip(),
        "website": (row.get("website") or row.get("Website") or "").strip(),
        "funding_total": (row.get("total_funding_usd") or row.get("funding_total") or ""),
        "last_funding_at": (row.get("last_funding_at") or row.get("last_funding") or ""),
        "rating": (row.get("rating") or row.get("Rating") or ""),
        "review_count": (row.get("review_count") or row.get("Reviews") or ""),
        "first_name": (row.get("first_name") or row.get("owner_first_name") or "").strip(),
        "last_name": (row.get("last_name") or row.get("owner_last_name") or "").strip(),
        "full_name": (row.get("full_name") or row.get("owner_name") or "").strip(),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def run_subset(run_id: str, subset: str, icp: dict, max_rows: int) -> int:
    files = find_subset_files(subset)
    if not files:
        log_event(run_id, "existing_db.skip", subset=subset, reason="no_files")
        return 0
    rd = run_dir(run_id)
    out_path = rd / "raw" / f"existing_db_{subset}.csv"
    total = 0
    for fp in files:
        with fp.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            batch = []
            for row in reader:
                if not passes_filter(row, icp, subset):
                    continue
                batch.append(normalize_row(row, subset))
                if len(batch) >= 500:
                    append_csv(out_path, batch, OUT_FIELDS)
                    total += len(batch)
                    batch = []
                    if total >= max_rows:
                        break
            if batch:
                append_csv(out_path, batch, OUT_FIELDS)
                total += len(batch)
        if total >= max_rows:
            break
    log_event(run_id, "existing_db.done", subset=subset, rows=total)
    return total


def main() -> None:
    run_id = arg("run-id", required=True)
    subsets = (arg("subsets", "crunchbase,gmaps") or "").split(",")
    subsets = [s.strip() for s in subsets if s.strip() in SUBSET_TOKENS]
    max_rows = int(arg("max", "2000"))

    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")

    ensure_cache()
    if not CACHE_DIR.exists():
        print("Existing DB cache unavailable — skipping.")
        return

    grand = 0
    for s in subsets:
        n = run_subset(run_id, s, icp, max_rows)
        print(f"existing_db_{s} → {n} rows")
        grand += n
    print(f"Existing DB total → {grand} rows")


if __name__ == "__main__":
    main()
