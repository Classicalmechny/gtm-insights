#!/usr/bin/env python3
"""BlitzAPI company search -> 300 NY local businesses. One-off for this run."""
import csv, json, os, sys, time
import requests

def _key():
    if os.environ.get("BLITZAPI_KEY"):
        return os.environ["BLITZAPI_KEY"]
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.lower().startswith("blitzapi key"):
                return line.split(":", 1)[1].strip()
    raise SystemExit("BLITZAPI_KEY not found")

KEY = _key()
URL = "https://api.blitz-api.ai/v2/search/companies"
OUT = os.path.join(os.path.dirname(__file__), "blitz_ny_local_300.csv")
TARGET = 300

INDUSTRIES = [
    "Restaurants", "Food and Beverage Services", "Caterers",
    "Retail", "Retail Apparel and Fashion", "Retail Groceries",
    "Wellness and Fitness Services", "Hospitality",
    "Cosmetics", "Personal Care Services",
    "Vehicle Repair and Maintenance",
    "Dentists", "Physicians", "Medical Practice",
    "Law Practice", "Legal Services",
    "Real Estate", "Facilities Services",
]

FIELDS = ["company_name", "domain", "website", "industry", "employee_range",
          "employees_on_linkedin", "city", "state", "country", "linkedin_url",
          "founded_year", "source"]

def row(c):
    hq = c.get("hq") or {}
    return {
        "company_name": c.get("name", ""),
        "domain": c.get("domain", ""),
        "website": c.get("website", ""),
        "industry": c.get("industry", ""),
        "employee_range": c.get("size", ""),
        "employees_on_linkedin": c.get("employees_on_linkedin", ""),
        "city": hq.get("city", ""),
        "state": hq.get("state", ""),
        "country": hq.get("country_name") or hq.get("country_code", ""),
        "linkedin_url": c.get("linkedin_url", ""),
        "founded_year": c.get("founded_year", ""),
        "source": "blitz_companies",
    }

def main():
    cursor, total, seen = None, 0, set()
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        while total < TARGET:
            payload = {
                "company": {
                    "industry": {"include": INDUSTRIES},
                    "hq": {"state": {"include": ["New York"]}, "country_code": ["US"]},
                    "employee_range": ["1-10", "11-50"],
                },
                "max_results": min(50, TARGET - total),
                "cursor": cursor,
            }
            r = requests.post(URL, json=payload,
                              headers={"x-api-key": KEY, "Content-Type": "application/json"},
                              timeout=60)
            if r.status_code >= 400:
                print(f"HTTP {r.status_code}: {r.text[:1000]}", file=sys.stderr)
                sys.exit(1)
            body = r.json()
            results = body.get("results") or []
            if not results:
                break
            for c in results:
                key = c.get("linkedin_url") or c.get("domain") or c.get("name")
                if key in seen:
                    continue
                seen.add(key)
                w.writerow(row(c))
                total += 1
                if total >= TARGET:
                    break
            print(f"page done, total={total}, total_results={body.get('total_results')}")
            cursor = body.get("cursor")
            if not cursor:
                break
            time.sleep(0.3)
    print(f"DONE {total} rows -> {OUT}")

if __name__ == "__main__":
    main()
