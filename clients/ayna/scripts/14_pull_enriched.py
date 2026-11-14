#!/usr/bin/env python3
"""Poll Instantly enrichment job, then pull enriched leads + update people_all.csv."""
import csv, json, os, time
from pathlib import Path
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
LIST_ID = "c66d7bc3-1008-49db-b399-8954e6204685"
H = {"Authorization": "Bearer NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==",
     "Content-Type": "application/json"}

IN = RD / "people_all.csv"
OUT = RD / "people_all_enriched.csv"
FINAL = RD / "verified.csv"

POLL_INTERVAL = 60
MAX_WAIT = 60 * 60  # 1 hour

def poll():
    """Wait until enrichment is done (best effort)."""
    t0 = time.time()
    last_count = -1
    stable_count = 0
    while time.time() - t0 < MAX_WAIT:
        # Get a quick page of leads, see how many have emails now
        r = requests.post("https://api.instantly.ai/api/v2/leads/list",
            json={"list_id": LIST_ID, "limit": 100}, headers=H, timeout=60)
        if r.status_code != 200:
            time.sleep(POLL_INTERVAL); continue
        items = r.json().get("items", [])
        with_email = sum(1 for it in items if it.get("email") and not str(it.get("email","")).startswith("placeholder_"))
        elapsed = int(time.time() - t0)
        print(f"  [{elapsed}s] sample with_email={with_email}/{len(items)} from page 1")
        # Heuristic: stop if leads stop changing for 2 polls
        if with_email == last_count and with_email > 0:
            stable_count += 1
            if stable_count >= 3:
                print("  Stable — stopping polling")
                return
        else:
            stable_count = 0
            last_count = with_email
        time.sleep(POLL_INTERVAL)

def pull_all():
    """Paginate and return mapping of (li_url or first|last|domain) -> (email, verification)."""
    mapping = {}
    cursor = None
    page = 0
    while True:
        body = {"list_id": LIST_ID, "limit": 100}
        if cursor: body["starting_after"] = cursor
        r = requests.post("https://api.instantly.ai/api/v2/leads/list",
                          json=body, headers=H, timeout=60)
        if r.status_code != 200:
            print(f"  err {r.status_code}: {r.text[:200]}"); break
        items = r.json().get("items", [])
        if not items: break
        for it in items:
            email = str(it.get("email") or "").strip().lower()
            if not email or email.startswith("placeholder_"): continue
            verif = str(it.get("verification_status") or it.get("email_verification_status") or "").lower()
            # Some Instantly statuses use integer codes
            payload = it.get("payload") or {}
            if not verif and isinstance(payload, dict):
                verif = str(payload.get("verification_status") or "").lower()
            li = str(it.get("linkedin_url") or "").strip()
            fn = str(it.get("first_name") or "").strip().lower()
            ln = str(it.get("last_name") or "").strip().lower()
            dom = str(it.get("website") or it.get("company_domain") or "").strip().lower()
            if dom.startswith("http"): dom = dom.split("//",1)[1]
            if dom.startswith("www."): dom = dom[4:]
            if li: mapping[li] = (email, verif)
            mapping[f"{fn}|{ln}|{dom}"] = (email, verif)
        cursor = r.json().get("next_starting_after")
        page += 1
        print(f"  page={page} total_keys={len(mapping)}")
        if not cursor: break
    return mapping

def main():
    print("Polling for enrichment to complete…")
    poll()
    print("\nPulling enriched leads…")
    mapping = pull_all()
    print(f"Found {len(mapping)} key→email mappings")

    people = list(csv.DictReader(IN.open(encoding="utf-8")))
    n_added = 0
    for p in people:
        if p["email"]: continue
        li = (p.get("linkedin_url") or "").strip()
        fn = (p.get("first_name") or "").strip().lower()
        ln = (p.get("last_name") or "").strip().lower()
        dom = (p.get("company_domain") or "").strip().lower()
        match = mapping.get(li) or mapping.get(f"{fn}|{ln}|{dom}")
        if match:
            email, verif = match
            p["email"] = email
            p["email_verification_status"] = verif or "unknown"
            p["email_source"] = "instantly_supersearch_enrich"
            n_added += 1
    print(f"\nNew emails matched into people_all: {n_added}")

    fields = list(people[0].keys())
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in people: w.writerow(p)
    print(f"→ {OUT}")

    have = [p for p in people if p["email"]]
    # Filter to verified-ish: accept valid, accept_all, or apollo_pre_verified, or unknown (since Instantly verify is async)
    accepted = ("valid","accept_all","accept-all","accept all","")
    keep = [p for p in have if p["email_verification_status"] in accepted or p["email_source"] in ("apollo_pre_verified","instantly_supersearch_verified","instantly_supersearch_enrich")]
    with FINAL.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in keep: w.writerow(p)
    print(f"Final verified (have email + acceptable status): {len(keep)} → {FINAL}")
    print(f"  (total with any email: {len(have)})")

if __name__ == "__main__":
    main()
