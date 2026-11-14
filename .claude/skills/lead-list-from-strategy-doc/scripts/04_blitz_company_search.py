#!/usr/bin/env python3
"""
BlitzAPI Company Search filtered for Shopify tech-stack + niche fashion industries.
Writes output/<run>/raw/blitz_companies.csv

This complements Storeleads by catching Shopify-platform fashion brands that
Storeleads may have missed (newer stores, less-tracked brands, etc.)
"""
import csv, json, os, time
import requests
from pathlib import Path

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
OUT = RD / "raw" / "blitz_companies.csv"

BLITZ_KEY = os.environ.get("BLITZAPI_KEY", "REDACTED_BLITZAPI_KEY")
BLITZ = "https://api.blitz-api.ai"

PAGE_SIZE = 100
OVERALL_LIMIT = int(os.environ.get("BLITZ_LIMIT", "3000"))

icp = json.loads((RD / "icp.json").read_text())
firmo = icp["firmographics"]
geo = icp["geographics"]

headers = {
    "Authorization": f"Bearer {BLITZ_KEY}",
    "x-api-key": BLITZ_KEY,
    "Content-Type": "application/json",
}

FIELDS = [
    "source","external_id",
    "company_name","company_domain","company_linkedin_url",
    "company_industry","company_employee_count",
    "country","state","city","founded_year","raw_json",
]

def normalize_domain(s):
    if not s: return ""
    s = s.strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    s = s.split("/", 1)[0].split("?", 1)[0].rstrip(".")
    return s

def normalize(c):
    return {
        "source": "blitz_companies",
        "external_id": c.get("id") or c.get("_id") or "",
        "company_name": (c.get("name") or c.get("company_name") or "").strip(),
        "company_domain": normalize_domain(c.get("domain") or c.get("website") or ""),
        "company_linkedin_url": c.get("linkedin_url") or "",
        "company_industry": (c.get("industry") or "").strip(),
        "company_employee_count": c.get("employee_count") or "",
        "country": c.get("country") or "",
        "state": c.get("state") or c.get("region") or "",
        "city": c.get("city") or "",
        "founded_year": c.get("founded_year") or "",
        "raw_json": json.dumps(c, ensure_ascii=False),
    }

# Open output (overwrite or append)
exists = OUT.exists()
f = OUT.open("a" if exists else "w", newline="", encoding="utf-8")
w = csv.DictWriter(f, fieldnames=FIELDS)
if not exists: w.writeheader()

total = 0
page = 1
print(f"Running BlitzAPI company search: industries={firmo['industries']} tech_stack={firmo['tech_stack_includes']}")
while total < OVERALL_LIMIT:
    payload = {
        "industries": firmo["industries"],
        "industries_exclude": firmo.get("industries_exclude", []),
        "employee_count_min": firmo.get("employee_count_min"),
        "employee_count_max": firmo.get("employee_count_max"),
        "tech_stack_includes": firmo["tech_stack_includes"],
        "tech_stack_excludes": firmo.get("tech_stack_excludes", []),
        "countries": geo["countries"],
        "page": page,
        "limit": min(PAGE_SIZE, OVERALL_LIMIT - total),
    }
    r = requests.post(BLITZ + "/company/search", json=payload, headers=headers, timeout=60)
    if r.status_code == 429:
        print(f"  429 rate limit at page {page}, sleeping 5s")
        time.sleep(5); continue
    if r.status_code >= 400:
        print(f"  ERROR page {page}: HTTP {r.status_code} body={r.text[:300]}")
        break
    body = r.json()
    rows = body.get("companies") or body.get("results") or body.get("data") or []
    if not rows:
        print(f"  No more results at page {page}")
        break
    normalized = [normalize(c) for c in rows]
    for n in normalized:
        w.writerow(n)
    f.flush()
    total += len(rows)
    print(f"  page={page} wrote={len(rows)} total={total}")
    page += 1
    if body.get("has_more") is False or len(rows) < PAGE_SIZE:
        break
    time.sleep(0.3)

f.close()
print(f"\nDone: {total} companies → {OUT}")
