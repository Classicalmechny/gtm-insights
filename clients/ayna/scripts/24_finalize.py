#!/usr/bin/env python3
"""
Final integration:
  1. Merge multi-Instantly leads (raw/instantly_multi.csv) into people_all_v8.csv
  2. Run BlitzAPI find-work-email + Instantly Supersearch waterfall on all remaining missing-email leads
  3. Write final people_all_final.csv + verified.csv
"""
import csv, json, time, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID

IN_PEOPLE = RD / "people_all_v8.csv"
IN_MULTI = RD / "raw" / "instantly_multi.csv"
OUT = RD / "people_all_final.csv"
FINAL = RD / "verified.csv"

BLITZ_H = {"x-api-key": "blitz_mkbWaJvTNLHs525Aegh4W9gt", "Content-Type": "application/json"}
INST_H = {"Authorization": "Bearer NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==",
          "Content-Type": "application/json"}
BASE = "https://api.instantly.ai"

def blitz_email(li):
    if not li: return ""
    try:
        r = requests.post("https://api.blitz-api.ai/v2/enrichment/email",
            json={"person_linkedin_url": li}, headers=BLITZ_H, timeout=30)
        if r.status_code == 200:
            return (r.json().get("email") or "").lower()
    except Exception: pass
    return ""

def main():
    people = list(csv.DictReader(IN_PEOPLE.open(encoding="utf-8")))
    fields = list(people[0].keys())
    keys = set()
    for p in people:
        if p.get("email"): keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))
    print(f"Starting pool: {len(people)} ({sum(1 for p in people if p['email'])} with email)")

    # ============== STEP 1: Merge multi-Instantly leads ==============
    n_merged = 0
    if IN_MULTI.exists():
        multi = list(csv.DictReader(IN_MULTI.open(encoding="utf-8")))
        print(f"\nMulti-Instantly leads: {len(multi)}")
        for m in multi:
            email = (m.get("email") or "").strip().lower()
            li = (m.get("linkedin_url") or "").strip().lower().rstrip("/")
            fn = (m.get("first_name") or "").strip()
            ln = (m.get("last_name") or "").strip()
            d = (m.get("company_domain") or "").strip().lower()
            if email and ("email", email) in keys: continue
            if li and ("li", li) in keys: continue
            if fn and ln and d and ("nd", f"{fn}|{ln}|{d}".lower()) in keys: continue
            # Add as new
            new = {f: "" for f in fields}
            new.update({
                "source": "instantly_multi", "first_name": fn, "last_name": ln,
                "full_name": m.get("full_name",""),
                "title": m.get("title",""), "linkedin_url": li,
                "email": email,
                "email_verification_status": m.get("email_verification_status",""),
                "email_source": "instantly_multi_query" if email else "",
                "company_name": m.get("company_name",""),
                "company_domain": d,
                "company_linkedin_url": m.get("company_linkedin_url",""),
                "company_website": m.get("company_website",""),
                "primary_niche": "",
                "all_niches": "",
                "is_multi_brand_retailer": "no",
                "country": "United States",
                "industry": "DTC Fashion",
            })
            people.append(new)
            if email: keys.add(("email", email))
            if li: keys.add(("li", li))
            if fn and ln and d: keys.add(("nd", f"{fn}|{ln}|{d}".lower()))
            n_merged += 1
        print(f"  Merged unique: {n_merged}")
    print(f"After multi-Instantly merge: {len(people)} ({sum(1 for p in people if p['email'])} with email)")

    # ============== STEP 2: BlitzAPI find-work-email on missing ==============
    need = [p for p in people if not p["email"] and p.get("linkedin_url")]
    print(f"\nStep A — BlitzAPI on {len(need)} missing-email leads…")
    n_blitz = 0
    if need:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(blitz_email, p["linkedin_url"]): p for p in need}
            for i, fut in enumerate(as_completed(futures), 1):
                p = futures[fut]
                em = fut.result()
                if em:
                    p["email"] = em
                    p["email_source"] = "blitz_find_work_email"
                    p["email_verification_status"] = "unverified_blitz"
                    n_blitz += 1
                if i % 200 == 0:
                    print(f"  [{i}/{len(need)}] blitz found: {n_blitz}")
        print(f"  BlitzAPI total: {n_blitz}")

    # ============== STEP 3: Instantly Supersearch waterfall on remaining ==============
    remaining = [p for p in people if not p["email"] and (p.get("linkedin_url") or (p.get("first_name") and p.get("last_name") and p.get("company_domain")))]
    print(f"\nStep B — Instantly Supersearch on {len(remaining)} remaining…")
    if remaining:
        r = requests.post(f"{BASE}/api/v2/lead-lists",
            json={"name": f"AYNA_FINAL_{RUN_ID}"[:64]}, headers=INST_H, timeout=30)
        list_id = r.json()["id"] if r.status_code == 200 else None
        if list_id:
            print(f"  list: {list_id}")
            # Bulk add
            for i in range(0, len(remaining), 100):
                batch = remaining[i:i+100]
                payload = {
                    "list_id": list_id, "skip_if_in_workspace": False,
                    "leads": [{
                        "list_id": list_id,
                        "email": f"placeholder_{i+j}@{p.get('company_domain') or 'unknown.com'}",
                        "first_name": p.get("first_name",""),
                        "last_name": p.get("last_name",""),
                        "company_name": p.get("company_name",""),
                        "website": p.get("company_domain",""),
                        "linkedin_url": p.get("linkedin_url",""),
                    } for j, p in enumerate(batch)]
                }
                requests.post(f"{BASE}/api/v2/leads/add", json=payload, headers=INST_H, timeout=120)
                if i % 500 == 0: print(f"    added {min(i+100, len(remaining))}/{len(remaining)}")
            # Submit jobs
            for t in ("work_email_enrichment", "email_verification"):
                requests.post(f"{BASE}/api/v2/supersearch-enrichment",
                    json={"resource_id": list_id, "resource_type": "lead-list", "type": t, "limit": 3000},
                    headers=INST_H, timeout=30)
            print("  Submitted enrichment + verification jobs. Waiting 12 min…")
            time.sleep(12 * 60)
            # Pull
            print("  Pulling…")
            mapping = {}; cursor = None
            while True:
                body = {"list_id": list_id, "limit": 100}
                if cursor: body["starting_after"] = cursor
                rr = requests.post(f"{BASE}/api/v2/leads/list", json=body, headers=INST_H, timeout=60)
                if rr.status_code != 200: break
                items = rr.json().get("items", [])
                if not items: break
                for it in items:
                    em = str(it.get("email") or "").strip().lower()
                    if not em or em.startswith("placeholder_"): continue
                    verif = str(it.get("verification_status") or "").lower()
                    li = str(it.get("linkedin_url") or "").strip().lower().rstrip("/")
                    fn = str(it.get("first_name") or "").strip().lower()
                    ln = str(it.get("last_name") or "").strip().lower()
                    dom = str(it.get("website") or "").strip().lower()
                    if dom.startswith("http"): dom = dom.split("//",1)[1]
                    if dom.startswith("www."): dom = dom[4:]
                    if li: mapping[li] = (em, verif)
                    mapping[f"{fn}|{ln}|{dom}"] = (em, verif)
                cursor = rr.json().get("next_starting_after")
                if not cursor: break
            n_inst = 0
            for p in people:
                if p["email"]: continue
                li = (p.get("linkedin_url") or "").strip().lower().rstrip("/")
                fn = (p.get("first_name") or "").strip().lower()
                ln = (p.get("last_name") or "").strip().lower()
                dom = (p.get("company_domain") or "").strip().lower()
                match = mapping.get(li) or mapping.get(f"{fn}|{ln}|{dom}")
                if match:
                    em, verif = match
                    p["email"] = em
                    p["email_verification_status"] = verif or "unknown"
                    p["email_source"] = "instantly_supersearch_enrich_final"
                    n_inst += 1
            print(f"  Instantly Supersearch added: {n_inst}")

    # ============== STEP 4: Save final ==============
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in people: w.writerow(p)
    print(f"\n→ {OUT}")
    have = [p for p in people if p["email"]]
    with FINAL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in have: w.writerow(p)
    print(f"FINAL VERIFIED: {len(have)} → {FINAL}")

if __name__ == "__main__":
    main()
