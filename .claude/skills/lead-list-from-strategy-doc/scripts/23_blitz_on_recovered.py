#!/usr/bin/env python3
"""Run BlitzAPI employee finder on recovered brands' LinkedIn URLs (expanded titles).
Also extract Storeleads public emails for these brands.
"""
import csv, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import re

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
from _titles import TITLES, TITLES_RX, TITLES_RX_EXCLUDE

RECOVERED = RD / "raw" / "storeleads_recovered.csv"
PEOPLE_IN = RD / "people_all_v7.csv"
OUT_DM = RD / "raw" / "decision_makers_r4.csv"
OUT_PEOPLE = RD / "people_all_v8.csv"

BLITZ_H = {"x-api-key": "REDACTED_BLITZAPI_KEY", "Content-Type": "application/json"}

FIELDS = ["source","first_name","last_name","full_name","title","linkedin_url",
    "email","email_verification_status","email_source",
    "company_name","company_domain","company_linkedin_url","company_website",
    "primary_niche","all_niches","is_multi_brand_retailer",
    "monthly_revenue_usd","plan","products_created_30","products_created_90",
    "high_cadence","most_recent_product_title","most_recent_product_image_url",
    "most_recent_product_url","instagram_url","tiktok_url",
    "city","state","country","annual_revenue_usd","employee_count","industry","keywords","technologies"]

def split_emails(s):
    if not s: return []
    return [e.strip().lower() for e in re.split(r"[:,;|\s]+", str(s)) if "@" in e]

def query_dms(brand):
    ln = brand.get("company_linkedin_url","").strip()
    if not ln: return brand["company_domain"], []
    try:
        r = requests.post("https://api.blitz-api.ai/v2/search/people",
            json={"company": {"linkedin_url": [ln]},
                  "people": {"job_title": {"include": TITLES, "exclude": []}},
                  "max_results": 10},
            headers=BLITZ_H, timeout=30)
        if r.status_code == 200:
            return brand["company_domain"], r.json().get("results", [])
    except Exception: pass
    return brand["company_domain"], []

def main():
    recovered = list(csv.DictReader(RECOVERED.open(encoding="utf-8")))
    print(f"Recovered brands: {len(recovered)}")
    print(f"  with LinkedIn URL: {sum(1 for r in recovered if r.get('company_linkedin_url'))}")

    # Existing people
    existing = list(csv.DictReader(PEOPLE_IN.open(encoding="utf-8")))
    existing_keys = set()
    for p in existing:
        if p.get("linkedin_url"): existing_keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            existing_keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))
    print(f"Existing pool: {len(existing)}")

    # BlitzAPI on recovered (parallel)
    f_dm = OUT_DM.open("w", newline="", encoding="utf-8")
    dm_writer = csv.DictWriter(f_dm, fieldnames=FIELDS, extrasaction="ignore"); dm_writer.writeheader()
    lock = __import__("threading").Lock()
    n_new = 0
    n_brands_with_dm = 0
    new_people = []

    def make_row(p, brand, niches_str):
        title = (p.get("headline") or "")
        exps = p.get("experiences") or []
        cur = exps[0] if exps else {}
        cur_title = cur.get("job_title") or title
        return {
            "source": "blitz_dm_r4",
            "first_name": (p.get("first_name") or "").strip(),
            "last_name": (p.get("last_name") or "").strip(),
            "full_name": (p.get("full_name") or "").strip(),
            "title": cur_title.strip(), "linkedin_url": (p.get("linkedin_url") or "").strip(),
            "email": "", "email_verification_status": "", "email_source": "",
            "company_name": brand.get("company_name",""),
            "company_domain": brand.get("company_domain",""),
            "company_linkedin_url": brand.get("company_linkedin_url",""),
            "company_website": brand.get("company_website",""),
            "primary_niche": brand.get("primary_niche_verified",""),
            "all_niches": brand.get("niches_detected",""),
            "is_multi_brand_retailer": brand.get("is_multi_brand_retailer","no"),
            "monthly_revenue_usd": brand.get("estimated_monthly_sales_usd",""),
            "plan": brand.get("plan",""),
            "products_created_30": brand.get("products_created_30","0"),
            "products_created_90": brand.get("products_created_90","0"),
            "high_cadence": brand.get("high_cadence","no"),
            "most_recent_product_title": brand.get("most_recent_product_title",""),
            "most_recent_product_image_url": brand.get("most_recent_product_image_url",""),
            "most_recent_product_url": brand.get("most_recent_product_url",""),
            "instagram_url": brand.get("instagram_url",""),
            "tiktok_url": brand.get("tiktok_url",""),
            "city": "", "state": "", "country": "US",
            "annual_revenue_usd": "", "employee_count": "",
            "industry": "DTC Fashion", "keywords": "", "technologies": "",
        }

    domains_done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(query_dms, b): b for b in recovered if b.get("company_linkedin_url")}
        for fut in as_completed(futures):
            brand = futures[fut]
            domain, people = fut.result()
            domains_done += 1
            local_new = 0
            for p in people:
                title = (p.get("headline") or "")
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
                # Fill public storeleads email if present
                public_emails = split_emails(brand.get("emails_from_storeleads",""))
                public_email = ""
                if public_emails:
                    public_email = next((e for e in public_emails if any(k in e for k in ["founder","ceo","owner","hello"])), public_emails[0])
                row = make_row(p, brand, brand.get("niches_detected",""))
                if public_email:
                    row["email"] = public_email
                    row["email_source"] = "storeleads_public_email"
                    row["email_verification_status"] = "public_storeleads"
                with lock:
                    dm_writer.writerow(row)
                    new_people.append(row)
                    n_new += 1
                    local_new += 1
            if local_new > 0:
                n_brands_with_dm += 1
            if domains_done % 200 == 0:
                print(f"  {domains_done} brands processed, {n_new} new DMs")
    f_dm.close()
    print(f"\nBlitzAPI on recovered: {n_new} new DMs from {n_brands_with_dm} brands")

    # Merge into people pool
    all_people = existing + new_people
    fields = list(existing[0].keys())
    with OUT_PEOPLE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in all_people: w.writerow(p)
    print(f"Final v8 pool: {len(all_people)} ({sum(1 for p in all_people if p['email'])} w/ email) → {OUT_PEOPLE}")

if __name__ == "__main__":
    main()
