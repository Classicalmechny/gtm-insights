#!/usr/bin/env python3
"""Paginate through all Instantly leads in the AYNA list and write to raw/instantly.csv."""
import csv, json, os, time
from pathlib import Path
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
OUT = RD / "raw" / "instantly.csv"

H = {"Authorization": "Bearer NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==",
     "Content-Type": "application/json"}

state = json.load(open(RD / "checkpoints" / "instantly.json"))
list_id = state["list_id"]
print(f"Pulling from list_id={list_id}")

FIELDS = [
    "source","external_id","first_name","last_name","full_name",
    "title","linkedin_url","email","email_verification_status",
    "company_name","company_domain","company_linkedin_url",
    "company_industry","company_employee_count","country","state","city",
    "enriched_at","raw_json",
]

def normalize_domain(s):
    if not s: return ""
    s = s.strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def normalize(l):
    return {
        "source": "instantly_supersearch",
        "external_id": l.get("id") or "",
        "first_name": (l.get("first_name") or "").strip(),
        "last_name": (l.get("last_name") or "").strip(),
        "full_name": (l.get("full_name") or
            f'{l.get("first_name","")} {l.get("last_name","")}').strip(),
        "title": (l.get("title") or l.get("job_title") or "").strip(),
        "linkedin_url": (l.get("linkedin_url") or "").strip(),
        "email": (l.get("email") or l.get("work_email") or "").strip().lower(),
        "email_verification_status": str(
            l.get("verification_status") or l.get("email_verification_status") or ""
        ).lower(),
        "company_name": (l.get("company_name") or l.get("organization_name") or "").strip(),
        "company_domain": normalize_domain(
            l.get("company_domain") or l.get("organization_website") or ""),
        "company_linkedin_url": (l.get("company_linkedin_url") or
            l.get("organization_linkedin_url") or "").strip(),
        "company_industry": (l.get("company_industry") or l.get("industry") or "").strip(),
        "company_employee_count": (l.get("company_employee_count") or l.get("employee_count") or ""),
        "country": (l.get("country") or "").strip(),
        "state": (l.get("state") or "").strip(),
        "city": (l.get("city") or "").strip(),
        "enriched_at": l.get("timestamp_updated") or "",
        "raw_json": json.dumps(l, ensure_ascii=False),
    }

f = OUT.open("w", newline="", encoding="utf-8")
w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
w.writeheader()

cursor = None
total = 0
page = 0
while True:
    body = {"list_id": list_id, "limit": 100}
    if cursor: body["starting_after"] = cursor
    r = requests.post("https://api.instantly.ai/api/v2/leads/list",
                      json=body, headers=H, timeout=60)
    if r.status_code >= 400:
        print(f"  ERROR {r.status_code}: {r.text[:300]}"); break
    body_j = r.json()
    leads = body_j.get("items") or []
    if not leads:
        print(f"  end at page {page}, total={total}"); break
    for l in leads:
        w.writerow(normalize(l))
    total += len(leads)
    f.flush()
    cursor = body_j.get("next_starting_after")
    page += 1
    print(f"  page={page} wrote={len(leads)} total={total}")
    if not cursor: break

f.close()
print(f"\nDone: {total} leads → {OUT}")
