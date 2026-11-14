#!/usr/bin/env python3
"""
Final round:
  1. BlitzAPI employee finder on 1,984 non-apparel-recovered brands (still pending)
  2. BlitzAPI find-work-email on all missing-email people in v9
  3. Instantly Supersearch waterfall on remaining
  4. Write people_all_final2.csv + verified.csv
"""
import csv, json, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
from _titles import TITLES, TITLES_RX, TITLES_RX_EXCLUDE

NON_APPAREL_RECOVERED = RD / "raw" / "storeleads_non_apparel_recovered.csv"
PRIOR_PEOPLE = RD / "people_all_v9.csv"
OUT = RD / "people_all_final2.csv"
FINAL = RD / "verified.csv"

BLITZ_H = {"x-api-key": "REDACTED_BLITZAPI_KEY", "Content-Type": "application/json"}
INST_H = {"Authorization": "Bearer REDACTED_INSTANTLY_KEY",
          "Content-Type": "application/json"}
BASE = "https://api.instantly.ai"

def main():
    brands = list(csv.DictReader(NON_APPAREL_RECOVERED.open(encoding="utf-8")))
    people = list(csv.DictReader(PRIOR_PEOPLE.open(encoding="utf-8")))
    fields = list(people[0].keys())
    print(f"Non-apparel brands to query: {len(brands)}  ({sum(1 for b in brands if b.get('company_linkedin_url'))} w/ LinkedIn)")
    print(f"Prior pool: {len(people)} ({sum(1 for p in people if p.get('email'))} w/ email)")

    existing_keys = set()
    for p in people:
        if p.get("email"): existing_keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): existing_keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            existing_keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))

    # ===== STEP 1: BlitzAPI employee finder on non-apparel recovered brands =====
    print("\nStep 1 — BlitzAPI employee finder on non-apparel recovered brands…")
    new_people = []
    lock = __import__("threading").Lock()
    n_new = 0

    def query_dms(brand):
        ln = brand.get("company_linkedin_url","").strip()
        if not ln: return brand["company_domain"], brand, []
        try:
            r = requests.post("https://api.blitz-api.ai/v2/search/people",
                json={"company": {"linkedin_url": [ln]},
                      "people": {"job_title": {"include": TITLES, "exclude": []}},
                      "max_results": 10},
                headers=BLITZ_H, timeout=30)
            if r.status_code == 200:
                return brand["company_domain"], brand, r.json().get("results", [])
        except Exception: pass
        return brand["company_domain"], brand, []

    def build_row(p, brand):
        title = p.get("headline") or ""
        exps = p.get("experiences") or []
        cur = exps[0] if exps else {}
        cur_title = cur.get("job_title") or title
        row = {f: "" for f in fields}
        row.update({
            "source": "blitz_dm_non_apparel_rescue",
            "first_name": (p.get("first_name") or "").strip(),
            "last_name": (p.get("last_name") or "").strip(),
            "full_name": (p.get("full_name") or "").strip(),
            "title": cur_title.strip(), "linkedin_url": (p.get("linkedin_url") or "").strip(),
            "company_name": brand.get("company_name",""),
            "company_domain": brand.get("company_domain",""),
            "company_linkedin_url": brand.get("company_linkedin_url",""),
            "company_website": "",
            "primary_niche": brand.get("primary_niche_verified",""),
            "all_niches": brand.get("niches_detected",""),
            "country": "US", "industry": "DTC Fashion",
            "monthly_revenue_usd": brand.get("estimated_monthly_sales_usd",""),
            "plan": brand.get("plan",""),
            "products_created_30": brand.get("products_created_30","0"),
            "products_created_90": brand.get("products_created_90","0"),
            "high_cadence": brand.get("high_cadence","no"),
            "instagram_url": brand.get("instagram_url",""),
            "tiktok_url": brand.get("tiktok_url",""),
        })
        return row

    domains_done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(query_dms, b): b for b in brands if b.get("company_linkedin_url")}
        for fut in as_completed(futures):
            domain, brand, results = fut.result()
            domains_done += 1
            for p in results:
                title = p.get("headline") or ""
                exps = p.get("experiences") or []
                cur = exps[0] if exps else {}
                cur_title = cur.get("job_title") or title
                if not TITLES_RX.search(cur_title): continue
                if TITLES_RX_EXCLUDE.search(cur_title): continue
                lin = (p.get("linkedin_url") or "").strip()
                fn = (p.get("first_name") or "").strip()
                ln = (p.get("last_name") or "").strip()
                key_li = ("li", lin.lower().rstrip("/")) if lin else None
                key_nd = ("nd", f"{fn}|{ln}|{domain}".lower())
                with lock:
                    if (key_li and key_li in existing_keys) or key_nd in existing_keys: continue
                    existing_keys.add(key_nd)
                    if key_li: existing_keys.add(key_li)
                    row = build_row(p, brand)
                    new_people.append(row); n_new += 1
            if domains_done % 200 == 0:
                print(f"  {domains_done} processed, {n_new} new DMs")
    print(f"  Non-apparel-recovered BlitzAPI: {n_new} new DMs")
    people.extend(new_people)

    # Save intermediate
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in people: w.writerow(p)

    # ===== STEP 2: BlitzAPI find-work-email on missing =====
    need = [p for p in people if not p["email"] and p.get("linkedin_url")]
    print(f"\nStep 2 — BlitzAPI find-work-email on {len(need)} missing…")
    def find_email(li):
        if not li: return ""
        try:
            r = requests.post("https://api.blitz-api.ai/v2/enrichment/email",
                json={"person_linkedin_url": li}, headers=BLITZ_H, timeout=30)
            if r.status_code == 200:
                return (r.json().get("email") or "").lower()
        except Exception: pass
        return ""

    n_blitz = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(find_email, p["linkedin_url"]): p for p in need}
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
    print(f"  BlitzAPI emails: {n_blitz}")

    # ===== STEP 3: Instantly Supersearch waterfall on remaining =====
    remaining = [p for p in people if not p["email"] and (p.get("linkedin_url") or (p.get("first_name") and p.get("last_name") and p.get("company_domain")))]
    print(f"\nStep 3 — Instantly Supersearch on {len(remaining)} remaining…")
    if remaining:
        r = requests.post(f"{BASE}/api/v2/lead-lists",
            json={"name": f"AYNA_FINAL2_{RUN_ID}"[:64]}, headers=INST_H, timeout=30)
        list_id = r.json()["id"] if r.status_code == 200 else None
        if list_id:
            print(f"  list: {list_id}")
            BATCH = 100
            for i in range(0, len(remaining), BATCH):
                batch = remaining[i:i+BATCH]
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
                if i % 500 == 0: print(f"    added {min(i+BATCH, len(remaining))}/{len(remaining)}")
            for t in ("work_email_enrichment","email_verification"):
                requests.post(f"{BASE}/api/v2/supersearch-enrichment",
                    json={"resource_id": list_id, "resource_type": "lead-list", "type": t, "limit": 5000},
                    headers=INST_H, timeout=30)
            print("  jobs submitted. waiting 15 min…")
            time.sleep(15 * 60)
            print("  pulling…")
            mapping = {}; cursor = None; page = 0
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
                page += 1
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
                    p["email_source"] = "instantly_supersearch_final2"
                    n_inst += 1
            print(f"  Instantly added: {n_inst}")

    # Save final
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
