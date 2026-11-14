#!/usr/bin/env python3
"""
Round-3 unified waterfall: BlitzAPI find-work-email → Instantly Supersearch enrichment.
Input: people_all_v5.csv (3,006 people, 1,544 need emails)
Output: people_all_v6.csv + verified.csv

Step A: BlitzAPI /v2/enrichment/email (fast, per-LinkedIn)
Step B: Instantly Supersearch enrichment on remaining via bulk-add + work_email_enrichment + email_verification
"""
import csv, json, time, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
IN = RD / "people_all_v5.csv"
OUT = RD / "people_all_v6.csv"
FINAL = RD / "verified.csv"
CKPT = RD / "checkpoints" / "waterfall_r3.json"
CKPT.parent.mkdir(parents=True, exist_ok=True)

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
    people = list(csv.DictReader(IN.open(encoding="utf-8")))
    state = json.loads(CKPT.read_text()) if CKPT.exists() else {
        "blitz_done": False, "list_id": None, "added": 0,
        "enrich_submitted": False, "verify_submitted": False,
    }

    need = [p for p in people if not p["email"] and p.get("linkedin_url")]
    print(f"Pool: {len(people)} ({sum(1 for p in people if p.get('email'))} w/ email)")
    print(f"  → Step A (BlitzAPI by LinkedIn): {len(need)} candidates")

    # Step A: BlitzAPI by LinkedIn (cheap, fast)
    if not state["blitz_done"]:
        n_found = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(blitz_email, p["linkedin_url"]): p for p in need}
            for i, fut in enumerate(as_completed(futures), 1):
                p = futures[fut]
                email = fut.result()
                if email:
                    p["email"] = email
                    p["email_source"] = "blitz_find_work_email"
                    p["email_verification_status"] = "unverified_blitz"
                    n_found += 1
                if i % 200 == 0:
                    print(f"  [{i}/{len(need)}] blitz found: {n_found}")
        print(f"  BlitzAPI total found: {n_found}")
        state["blitz_done"] = True
        CKPT.write_text(json.dumps(state))
        # Save intermediate
        fields = list(people[0].keys())
        with OUT.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
            for p in people: w.writerow(p)

    # Step B: Instantly Supersearch enrichment for remaining
    remaining = [p for p in people if not p["email"] and (p.get("linkedin_url") or (p.get("first_name") and p.get("last_name") and p.get("company_domain")))]
    print(f"\n  → Step B (Instantly Supersearch): {len(remaining)} remaining")

    if remaining:
        if not state["list_id"]:
            r = requests.post(f"{BASE}/api/v2/lead-lists",
                json={"name": f"AYNA_R3_{RUN_ID}"[:64]}, headers=INST_H, timeout=30)
            if r.status_code >= 400:
                print(f"List error: {r.text[:300]}"); return
            state["list_id"] = r.json()["id"]
            CKPT.write_text(json.dumps(state))
        list_id = state["list_id"]
        print(f"  List: {list_id}")

        # Bulk add
        if state["added"] < len(remaining):
            BATCH = 100
            i = state["added"]
            while i < len(remaining):
                batch = remaining[i:i+BATCH]
                payload = {
                    "list_id": list_id, "skip_if_in_workspace": False,
                    "leads": [{
                        "list_id": list_id,
                        "email": p.get("email") or f"placeholder_{i+j}@{p.get('company_domain') or 'unknown.com'}",
                        "first_name": p.get("first_name", ""),
                        "last_name": p.get("last_name", ""),
                        "company_name": p.get("company_name", ""),
                        "website": p.get("company_domain", ""),
                        "linkedin_url": p.get("linkedin_url", ""),
                    } for j, p in enumerate(batch)]
                }
                r = requests.post(f"{BASE}/api/v2/leads/add", json=payload, headers=INST_H, timeout=120)
                if r.status_code in (200, 201):
                    state["added"] += len(batch)
                    CKPT.write_text(json.dumps(state))
                    print(f"    added {state['added']}/{len(remaining)}")
                else:
                    print(f"    err {r.status_code}: {r.text[:200]}")
                i += BATCH
                time.sleep(0.2)

        # Enrichment jobs
        if not state["enrich_submitted"]:
            r = requests.post(f"{BASE}/api/v2/supersearch-enrichment",
                json={"resource_id": list_id, "resource_type": "lead-list", "type": "work_email_enrichment", "limit": 3000},
                headers=INST_H, timeout=30)
            print(f"  enrichment: {r.status_code}")
            if r.status_code in (200, 201):
                state["enrich_submitted"] = True; CKPT.write_text(json.dumps(state))
        if not state["verify_submitted"]:
            r = requests.post(f"{BASE}/api/v2/supersearch-enrichment",
                json={"resource_id": list_id, "resource_type": "lead-list", "type": "email_verification", "limit": 3000},
                headers=INST_H, timeout=30)
            print(f"  verification: {r.status_code}")
            if r.status_code in (200, 201):
                state["verify_submitted"] = True; CKPT.write_text(json.dumps(state))

        # Poll
        print("  Polling…")
        t0 = time.time()
        last = -1; stable = 0
        while time.time() - t0 < 60 * 60:
            r = requests.post(f"{BASE}/api/v2/leads/list",
                json={"list_id": list_id, "limit": 100}, headers=INST_H, timeout=60)
            if r.status_code != 200:
                time.sleep(60); continue
            items = r.json().get("items", [])
            cnt = sum(1 for it in items if it.get("email") and not str(it.get("email","")).startswith("placeholder_"))
            elapsed = int(time.time() - t0)
            print(f"  [{elapsed}s] sample={cnt}/{len(items)}")
            if cnt == last:
                stable += 1
                if stable >= 3: break
            else:
                stable = 0; last = cnt
            time.sleep(60)

        # Pull
        print("\n  Pulling…")
        mapping = {}; cursor = None; page = 0
        while True:
            body = {"list_id": list_id, "limit": 100}
            if cursor: body["starting_after"] = cursor
            r = requests.post(f"{BASE}/api/v2/leads/list", json=body, headers=INST_H, timeout=60)
            if r.status_code != 200: break
            items = r.json().get("items", [])
            if not items: break
            for it in items:
                email = str(it.get("email") or "").strip().lower()
                if not email or email.startswith("placeholder_"): continue
                verif = str(it.get("verification_status") or "").lower()
                li = str(it.get("linkedin_url") or "").strip().lower().rstrip("/")
                fn = str(it.get("first_name") or "").strip().lower()
                ln = str(it.get("last_name") or "").strip().lower()
                dom = str(it.get("website") or it.get("company_domain") or "").strip().lower()
                if dom.startswith("http"): dom = dom.split("//",1)[1]
                if dom.startswith("www."): dom = dom[4:]
                if li: mapping[li] = (email, verif)
                mapping[f"{fn}|{ln}|{dom}"] = (email, verif)
            cursor = r.json().get("next_starting_after")
            page += 1
            print(f"  page={page} keys={len(mapping)}")
            if not cursor: break

        n_new = 0
        for p in people:
            if p["email"]: continue
            li = (p.get("linkedin_url") or "").strip().lower().rstrip("/")
            fn = (p.get("first_name") or "").strip().lower()
            ln = (p.get("last_name") or "").strip().lower()
            dom = (p.get("company_domain") or "").strip().lower()
            match = mapping.get(li) or mapping.get(f"{fn}|{ln}|{dom}")
            if match:
                email, verif = match
                p["email"] = email
                p["email_verification_status"] = verif or "unknown"
                p["email_source"] = "instantly_supersearch_enrich_r3"
                n_new += 1
        print(f"\n  Instantly waterfall new: {n_new}")

    # Save
    fields = list(people[0].keys())
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in people: w.writerow(p)
    print(f"→ {OUT}")

    have = [p for p in people if p["email"]]
    with FINAL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in have: w.writerow(p)
    print(f"Final verified: {len(have)} → {FINAL}")

if __name__ == "__main__":
    main()
