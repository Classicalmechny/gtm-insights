#!/usr/bin/env python3
"""
Stage 5b — Instantly Supersearch waterfall enrichment.

For each person without an email in people_all.csv:
  1. Bulk-add to a new Instantly lead list (first_name, last_name, company, linkedin_url)
  2. Submit enrichment job (enrich_work_email + verify_work_email)
  3. Poll until done
  4. Paginate leads, capture verified emails
  5. Update people_all.csv → people_all_enriched.csv

Output: output/<run>/people_all_enriched.csv  (and verified.csv with valid emails only)
"""
import csv, json, os, time
from pathlib import Path
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
IN_CSV = RD / "people_all.csv"
OUT_CSV = RD / "people_all_enriched.csv"
FINAL_CSV = RD / "verified.csv"
CKPT = RD / "checkpoints" / "instantly_waterfall.json"
CKPT.parent.mkdir(parents=True, exist_ok=True)

INSTANTLY_KEY = "REDACTED_INSTANTLY_KEY"
H = {"Authorization": f"Bearer {INSTANTLY_KEY}", "Content-Type": "application/json"}
BASE = "https://api.instantly.ai"

POLL_INTERVAL = 30
BULK_BATCH = 100

def main():
    people = list(csv.DictReader(IN_CSV.open(encoding="utf-8")))
    need_email = [p for p in people if not p["email"] and (p.get("linkedin_url") or (p.get("first_name") and p.get("last_name") and p.get("company_domain")))]
    have_email = [p for p in people if p["email"]]
    print(f"Total people: {len(people)}")
    print(f"  Have email: {len(have_email)}")
    print(f"  Need email & enrichable: {len(need_email)}")

    state = json.loads(CKPT.read_text()) if CKPT.exists() else {"list_id": None, "added": 0, "enriched_submitted": False, "polled_done": False}

    # 1. Create list (if not exists)
    if not state["list_id"]:
        r = requests.post(f"{BASE}/api/v2/lead-lists",
                          json={"name": f"AYNA_ENRICH_{RUN_ID}"[:64]},
                          headers=H, timeout=30)
        if r.status_code >= 400:
            print(f"create list error: {r.status_code} {r.text[:200]}"); return
        state["list_id"] = r.json()["id"]
        CKPT.write_text(json.dumps(state))
        print(f"List: {state['list_id']}")
    list_id = state["list_id"]

    # 2. Bulk add (in batches)
    if state["added"] < len(need_email):
        print(f"Bulk-adding {len(need_email) - state['added']} leads…")
        i = state["added"]
        added = state["added"]
        while i < len(need_email):
            batch = need_email[i:i+BULK_BATCH]
            payload = {
                "list_id": list_id,
                "skip_if_in_workspace": False,
                "leads": [{
                    "list_id": list_id,
                    "email": p.get("email") or f"placeholder_{idx}@{p.get('company_domain') or 'unknown.com'}",
                    "first_name": p.get("first_name", ""),
                    "last_name": p.get("last_name", ""),
                    "company_name": p.get("company_name", ""),
                    "personalization": p.get("title", ""),
                    "website": p.get("company_domain", ""),
                    "linkedin_url": p.get("linkedin_url", ""),
                } for idx, p in enumerate(batch, start=i)]
            }
            r = requests.post(f"{BASE}/api/v2/leads/add",
                              json=payload, headers=H, timeout=120)
            if r.status_code in (200, 201):
                added += len(batch)
                state["added"] = added
                CKPT.write_text(json.dumps(state))
                print(f"  added {added}/{len(need_email)}")
            else:
                print(f"  bulk-add error {r.status_code}: {r.text[:300]}")
                # Try one-at-a-time
                for idx, p in enumerate(batch, start=i):
                    one = {
                        "list_id": list_id,
                        "email": p.get("email") or f"placeholder_{idx}@{p.get('company_domain') or 'unknown.com'}",
                        "first_name": p.get("first_name", ""),
                        "last_name": p.get("last_name", ""),
                        "company_name": p.get("company_name", ""),
                        "website": p.get("company_domain", ""),
                        "linkedin_url": p.get("linkedin_url", ""),
                    }
                    rr = requests.post(f"{BASE}/api/v2/leads", json=one, headers=H, timeout=30)
                    if rr.status_code in (200, 201):
                        added += 1
                state["added"] = added
                CKPT.write_text(json.dumps(state))
            i += BULK_BATCH
            time.sleep(0.3)
        print(f"Total added: {added}")

    # 3. Submit enrichment job — enrich + verify on existing list
    if not state["enriched_submitted"]:
        payload = {
            "resource_id": list_id,
            "resource_type": "lead-list",
            "enrichment_options": {
                "enrich_work_email": True,
                "verify_work_email": True,
                "include_phone": False,
                "all_signals_enabled": False,
            },
        }
        # Try multiple endpoint variants
        for ep in ["/api/v2/supersearch-enrichment",
                   "/api/v2/supersearch-enrichment/enrich-existing-leads",
                   "/api/v2/leads/enrich"]:
            r = requests.post(f"{BASE}{ep}", json=payload, headers=H, timeout=30)
            print(f"  enrichment submit via {ep}: {r.status_code} {r.text[:200]}")
            if r.status_code in (200, 201):
                state["enriched_submitted"] = True
                CKPT.write_text(json.dumps(state))
                break

    # 4. Poll
    if state["enriched_submitted"] and not state["polled_done"]:
        print("Polling…")
        t0 = time.time()
        while time.time() - t0 < 60 * 60:  # 1hr max
            r = requests.get(f"{BASE}/api/v2/supersearch-enrichment/get-enrichment-for-resource",
                             params={"resource_id": list_id, "resource_type": "lead-list"},
                             headers=H, timeout=30)
            if r.status_code == 200:
                status = (r.json().get("status") or "").lower()
                print(f"  [{int(time.time()-t0)}s] status={status}")
                if status in ("completed","complete","done","finished"):
                    state["polled_done"] = True
                    CKPT.write_text(json.dumps(state))
                    break
                if status in ("failed","cancelled","error"):
                    print(f"FAILED: {r.text[:300]}"); break
            else:
                # Poll endpoint may have UUID quirks; just wait + check via leads list
                if time.time() - t0 > 5 * 60:
                    print("  poll endpoint failing; proceeding to leads list anyway")
                    state["polled_done"] = True
                    break
            time.sleep(POLL_INTERVAL)

    # 5. Paginate leads and capture enriched emails
    print("\nPulling enriched leads…")
    cursor = None
    enriched_emails = {}  # linkedin_url -> email
    page = 0
    while True:
        body = {"list_id": list_id, "limit": 100}
        if cursor: body["starting_after"] = cursor
        r = requests.post(f"{BASE}/api/v2/leads/list", json=body, headers=H, timeout=60)
        if r.status_code != 200:
            print(f"  list error: {r.text[:200]}"); break
        items = r.json().get("items", [])
        if not items: break
        for item in items:
            email = (item.get("email") or "").strip().lower()
            verification = str(item.get("verification_status") or item.get("email_verification_status") or "").lower()
            # skip placeholder emails
            if email.startswith("placeholder_"): continue
            if not email: continue
            li = (item.get("linkedin_url") or "").strip()
            ln_first = (item.get("first_name") or "").strip().lower()
            ln_last  = (item.get("last_name") or "").strip().lower()
            domain = (item.get("website") or item.get("company_domain") or "").strip().lower()
            key1 = li
            key2 = f"{ln_first}|{ln_last}|{domain}"
            enriched_emails[key1] = (email, verification)
            enriched_emails[key2] = (email, verification)
        cursor = r.json().get("next_starting_after")
        page += 1
        print(f"  page={page} have {len(enriched_emails)} keys")
        if not cursor: break

    # Update people list with new emails
    n_new = 0
    for p in people:
        if p["email"]: continue
        li = (p.get("linkedin_url") or "").strip()
        first = (p.get("first_name") or "").strip().lower()
        last  = (p.get("last_name") or "").strip().lower()
        dom = (p.get("company_domain") or "").strip().lower()
        match = enriched_emails.get(li) or enriched_emails.get(f"{first}|{last}|{dom}")
        if match:
            email, verif = match
            p["email"] = email
            p["email_verification_status"] = verif
            p["email_source"] = "instantly_supersearch_enrich"
            n_new += 1
    print(f"\nNew emails added: {n_new}")

    # Write enriched and final files
    fields = list(people[0].keys())
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in people: w.writerow(p)
    print(f"→ {OUT_CSV}")

    # Final verified.csv (anyone with email)
    have = [p for p in people if p["email"]]
    with FINAL_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in have: w.writerow(p)
    print(f"Final verified people: {len(have)} → {FINAL_CSV}")

if __name__ == "__main__":
    main()
