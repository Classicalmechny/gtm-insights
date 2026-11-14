#!/usr/bin/env python3
"""Round-2 Instantly waterfall: bulk-add 1,212 missing-email leads, enrich + verify."""
import csv, json, time
from pathlib import Path
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
IN = RD / "people_all_v2.csv"
OUT = RD / "people_all_v3.csv"
FINAL = RD / "verified.csv"
CKPT = RD / "checkpoints" / "waterfall_r2.json"
CKPT.parent.mkdir(parents=True, exist_ok=True)

H = {"Authorization": "Bearer REDACTED_INSTANTLY_KEY",
     "Content-Type": "application/json"}
BASE = "https://api.instantly.ai"

def main():
    people = list(csv.DictReader(IN.open(encoding="utf-8")))
    need = [p for p in people if not p["email"] and (p.get("linkedin_url") or (p.get("first_name") and p.get("last_name") and p.get("company_domain")))]
    print(f"Total people: {len(people)}, need email: {len(need)}")

    state = json.loads(CKPT.read_text()) if CKPT.exists() else {"list_id": None, "added": 0, "enrich_submitted": False, "verify_submitted": False}

    # Create list
    if not state["list_id"]:
        r = requests.post(f"{BASE}/api/v2/lead-lists",
            json={"name": f"AYNA_R2_{RUN_ID}"[:64]}, headers=H, timeout=30)
        if r.status_code >= 400:
            print(f"List error: {r.text[:300]}"); return
        state["list_id"] = r.json()["id"]
        CKPT.write_text(json.dumps(state))
        print(f"List: {state['list_id']}")
    list_id = state["list_id"]

    # Bulk add via /api/v2/leads/add
    if state["added"] < len(need):
        print(f"Bulk-adding {len(need)-state['added']} leads…")
        BATCH = 100; i = state["added"]
        while i < len(need):
            batch = need[i:i+BATCH]
            leads_payload = [{
                "list_id": list_id,
                "email": p.get("email") or f"placeholder_{i+j}@{p.get('company_domain') or 'unknown.com'}",
                "first_name": p.get("first_name",""),
                "last_name": p.get("last_name",""),
                "company_name": p.get("company_name",""),
                "website": p.get("company_domain",""),
                "linkedin_url": p.get("linkedin_url",""),
            } for j,p in enumerate(batch)]
            r = requests.post(f"{BASE}/api/v2/leads/add",
                json={"leads": leads_payload, "list_id": list_id, "skip_if_in_workspace": False},
                headers=H, timeout=90)
            if r.status_code in (200,201):
                state["added"] += len(batch)
                CKPT.write_text(json.dumps(state))
                print(f"  added {state['added']}/{len(need)}")
            else:
                print(f"  err {r.status_code}: {r.text[:200]}")
            i += BATCH
            time.sleep(0.2)

    # Submit enrichment + verification
    if not state["enrich_submitted"]:
        r = requests.post(f"{BASE}/api/v2/supersearch-enrichment",
            json={"resource_id": list_id, "resource_type": "lead-list", "type": "work_email_enrichment", "limit": 2000},
            headers=H, timeout=30)
        print(f"work_email_enrichment: {r.status_code} {r.text[:200]}")
        if r.status_code in (200,201):
            state["enrich_submitted"] = True; CKPT.write_text(json.dumps(state))

    if not state["verify_submitted"]:
        r = requests.post(f"{BASE}/api/v2/supersearch-enrichment",
            json={"resource_id": list_id, "resource_type": "lead-list", "type": "email_verification", "limit": 2000},
            headers=H, timeout=30)
        print(f"email_verification: {r.status_code} {r.text[:200]}")
        if r.status_code in (200,201):
            state["verify_submitted"] = True; CKPT.write_text(json.dumps(state))

    # Poll: wait for enrichment to stabilize
    print("Polling for stable email count…")
    t0 = time.time()
    last_count = -1
    stable = 0
    while time.time() - t0 < 60 * 60:
        r = requests.post(f"{BASE}/api/v2/leads/list",
            json={"list_id": list_id, "limit": 100}, headers=H, timeout=60)
        if r.status_code != 200:
            time.sleep(60); continue
        items = r.json().get("items", [])
        with_email = sum(1 for it in items if it.get("email") and not str(it.get("email","")).startswith("placeholder_"))
        elapsed = int(time.time()-t0)
        print(f"  [{elapsed}s] sample with_email={with_email}/{len(items)}")
        if with_email == last_count:
            stable += 1
            if stable >= 3: break
        else:
            stable = 0
            last_count = with_email
        time.sleep(60)

    # Pull all
    print("\nPulling enriched leads…")
    mapping = {}
    cursor = None; page = 0
    while True:
        body = {"list_id": list_id, "limit": 100}
        if cursor: body["starting_after"] = cursor
        r = requests.post(f"{BASE}/api/v2/leads/list", json=body, headers=H, timeout=60)
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

    print(f"\nFound {len(mapping)} key→email mappings")

    # Apply
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
            p["email_source"] = "instantly_supersearch_enrich_r2"
            n_new += 1
    print(f"New emails matched: {n_new}")

    fields = list(people[0].keys())
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in people: w.writerow(p)
    print(f"→ {OUT}")

    have = [p for p in people if p["email"]]
    with FINAL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in have: w.writerow(p)
    print(f"Final verified people: {len(have)} → {FINAL}")

if __name__ == "__main__":
    main()
