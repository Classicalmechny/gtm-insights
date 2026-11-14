#!/usr/bin/env python3
"""
Stage 5b — Email enrichment with corrected BlitzAPI v2 endpoint.

Uses POST /v2/enrichment/email with body {person_linkedin_url: ...}.
Reads people_merged.csv, finds work emails for rows missing email,
then verifies via Instantly bulk lead-list email verification.

Output: verified.csv (final email-verified people)
"""
import csv, json, time, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
SRC = RD / "people_merged.csv"
WITH_BLITZ = RD / "people_with_blitz_emails.csv"
FINAL = RD / "verified.csv"

BLITZ_H = {"x-api-key": "REDACTED_BLITZAPI_KEY",
           "Content-Type": "application/json"}
INST_H = {"Authorization": "Bearer REDACTED_INSTANTLY_KEY",
          "Content-Type": "application/json"}

def find_email(linkedin_url):
    try:
        r = requests.post("https://api.blitz-api.ai/v2/enrichment/email",
            json={"person_linkedin_url": linkedin_url}, headers=BLITZ_H, timeout=30)
        if r.status_code == 200:
            body = r.json()
            return (body.get("email") or "").lower()
        return ""
    except Exception:
        return ""

def main():
    people = list(csv.DictReader(SRC.open(encoding="utf-8")))
    print(f"Loaded {len(people)} merged people")

    need_email = [p for p in people if not p["email"] and p["linkedin_url"]]
    have_email = [p for p in people if p["email"]]
    print(f"Have email: {len(have_email)}  Need email: {len(need_email)}")

    n_found = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(find_email, p["linkedin_url"]): p for p in need_email}
        for i, fut in enumerate(as_completed(futures), 1):
            p = futures[fut]
            email = fut.result()
            if email:
                p["email"] = email
                p["email_source"] = "blitz_find_work_email"
                n_found += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(need_email)}] found {n_found} so far")
    print(f"BlitzAPI emails found: {n_found}/{len(need_email)}")

    # Save intermediate
    fields = list(people[0].keys())
    with WITH_BLITZ.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in people:
            w.writerow(p)
    print(f"Intermediate → {WITH_BLITZ}")

    # Verify Blitz-found emails via Instantly bulk-add to a verification list
    to_verify = [p for p in people if p["email_source"] == "blitz_find_work_email"]
    print(f"\nBulk-creating list for {len(to_verify)} emails to verify…")
    r = requests.post("https://api.instantly.ai/api/v2/lead-lists",
        json={"name": f"AYNA_VERIFY_{RUN_ID}"}, headers=INST_H, timeout=30)
    if r.status_code != 200:
        print(f"List creation failed: {r.text[:300]}"); return
    list_id = r.json()["id"]
    print(f"Verify list: {list_id}")

    # Bulk add leads
    print(f"Bulk-adding {len(to_verify)} leads to verify list…")
    BATCH = 50
    added = 0
    for i in range(0, len(to_verify), BATCH):
        batch = to_verify[i:i+BATCH]
        leads = []
        for p in batch:
            leads.append({
                "email": p["email"],
                "first_name": p["first_name"],
                "last_name": p["last_name"],
                "company_name": p["company_name"],
                "list_id": list_id,
            })
        r = requests.post("https://api.instantly.ai/api/v2/leads",
            json={"leads": leads, "list_id": list_id},
            headers=INST_H, timeout=60)
        if r.status_code not in (200, 201):
            # Try one-at-a-time
            for lead in leads:
                rr = requests.post("https://api.instantly.ai/api/v2/leads",
                    json=lead, headers=INST_H, timeout=30)
                if rr.status_code in (200, 201): added += 1
        else:
            added += len(leads)
        if i % 200 == 0:
            print(f"  added {added}/{len(to_verify)}")
    print(f"Total added: {added}")

    # Submit verification job (enrich verify_work_email on existing list)
    print("Submitting Instantly verification job…")
    verify_payload = {
        "resource_id": list_id,
        "resource_type": "lead-list",
        "enrichment_options": {
            "enrich_work_email": False,
            "verify_work_email": True,
            "all_signals_enabled": False,
        },
    }
    r = requests.post("https://api.instantly.ai/api/v2/supersearch-enrichment/supersearch-enrichment",
        json=verify_payload, headers=INST_H, timeout=30)
    print(f"  submit: {r.status_code} {r.text[:300]}")
    # Try alternative endpoint
    if r.status_code != 200:
        r2 = requests.post(f"https://api.instantly.ai/api/v2/email-verification",
            json={"emails": [p["email"] for p in to_verify[:100]]}, headers=INST_H, timeout=60)
        print(f"  alt: {r2.status_code} {r2.text[:300]}")

    # Wait a bit then fetch verification status per email by reading list
    print("Waiting 60s for verification to start, then polling list…")
    time.sleep(60)

    # Pull lead statuses
    by_email = {p["email"]: p for p in people}
    cursor = None
    verified_count = 0
    while True:
        body = {"list_id": list_id, "limit": 100}
        if cursor: body["starting_after"] = cursor
        r = requests.post("https://api.instantly.ai/api/v2/leads/list",
            json=body, headers=INST_H, timeout=60)
        if r.status_code != 200: break
        items = r.json().get("items", [])
        if not items: break
        for item in items:
            email = (item.get("email") or "").lower()
            status = str(item.get("verification_status") or "").lower()
            if email in by_email:
                by_email[email]["email_verification_status"] = status
                if status in ("valid","accept_all"):
                    verified_count += 1
        cursor = r.json().get("next_starting_after")
        if not cursor: break
    print(f"Verified via Instantly: {verified_count}/{len(to_verify)}")

    # Final: keep emails that are valid OR accept_all OR from Instantly Supersearch (already verified)
    final = [p for p in people if p["email"] and (
        p["email_verification_status"] in ("valid","accept_all") or
        p["email_source"] == "instantly_supersearch_verified"
    )]
    print(f"\nFinal verified people: {len(final)}")

    with FINAL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in final:
            w.writerow(p)
    print(f"Wrote → {FINAL}")

if __name__ == "__main__":
    main()
