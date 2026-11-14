#!/usr/bin/env python3
"""
Two efficiency gains:
  A) Extract public emails from Storeleads' `emails_from_storeleads` field
  B) Re-ingest ALL Apollo senior leads (no niche pre-filter); they're already
     pre-filtered to US/Shopify/apparel/5-50emp — trust those filters and run
     /collections.json niche verification ONLY on new domains.
"""
import csv, json, re, sys, time
from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
from _titles import TITLES_RX, TITLES_RX_EXCLUDE
import importlib.util
spec = importlib.util.spec_from_file_location("stage2", str(ROOT / "clients/ayna/scripts/03_collections_enrich.py"))
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)

STORELEADS = RD / "raw" / "storeleads_verified.csv"
APOLLO_FILES = [
    ROOT / "brain/assets/ayna_apollo_revenue.csv",
    ROOT / "brain/assets/ayna_apollo_headcount.csv",
]
# Use whichever is latest people file
PRIOR_CANDIDATES = [RD / "people_all_v6.csv", RD / "people_all_v5.csv", RD / "people_all_v4.csv"]
PRIOR = next(p for p in PRIOR_CANDIDATES if p.exists())
OUT = RD / "people_all_v7.csv"

def norm_d(s):
    s = str(s or "").strip().lower()
    if "://" in s: s = s.split("://",1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/",1)[0].split("?",1)[0]

def split_emails(s):
    if not s: return []
    return [e.strip().lower() for e in re.split(r"[:,;|\s]+", str(s)) if "@" in e]

def main():
    storeleads = list(csv.DictReader(STORELEADS.open(encoding="utf-8")))
    sl_idx = {r["company_domain"]: r for r in storeleads}
    sl_email_map = {r["company_domain"]: split_emails(r.get("emails_from_storeleads","")) for r in storeleads}

    existing = list(csv.DictReader(PRIOR.open(encoding="utf-8")))
    fields = list(existing[0].keys())
    existing_keys = set()
    for p in existing:
        if p.get("email"): existing_keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): existing_keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            existing_keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))
    print(f"Starting pool: {len(existing)} people ({sum(1 for p in existing if p['email'])} w/ email) from {PRIOR.name}")

    # ============ GAIN A: Storeleads public emails ============
    # For each person at a storeleads-verified brand who has no email, attach
    # the storeleads public email as a generic fallback (info@, founder@, etc.).
    print("\n--- GAIN A: Storeleads public emails ---")
    a_added = 0
    for p in existing:
        if p["email"]: continue
        d = p["company_domain"]
        emails = sl_email_map.get(d, [])
        # Prefer a "founder@" / "ceo@" / "owner@" type if available, else first
        founder_email = next((e for e in emails if any(k in e for k in ["founder","ceo","owner","hello"])), None)
        chosen = founder_email or (emails[0] if emails else None)
        if chosen:
            p["email"] = chosen
            p["email_source"] = "storeleads_public_email"
            p["email_verification_status"] = "public_storeleads"
            a_added += 1
    print(f"  Filled {a_added} public emails from Storeleads")

    # ============ GAIN B: Re-ingest ALL Apollo senior leads ============
    print("\n--- GAIN B: Re-ingest ALL Apollo senior leads ---")
    apollo_candidates = []
    for src in APOLLO_FILES:
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                t = str(r.get("Title") or "").strip()
                if not TITLES_RX.search(t): continue
                if TITLES_RX_EXCLUDE.search(t): continue
                d = norm_d(r.get("Website",""))
                if not d: continue
                country = str(r.get("Country") or "").strip()
                if country and "united states" not in country.lower(): continue
                li = str(r.get("Person Linkedin Url","") or "").strip()
                fn = str(r.get("First Name","") or "").strip()
                ln = str(r.get("Last Name","") or "").strip()
                key_li = ("li", li.lower().rstrip("/")) if li else None
                key_nd = ("nd", f"{fn}|{ln}|{d}".lower())
                if (key_li and key_li in existing_keys) or key_nd in existing_keys: continue

                email = str(r.get("Email") or "").strip().lower()
                estat = str(r.get("Email Status","") or "").strip().lower()
                if estat not in ("valid","accept_all","accept-all","accept all"):
                    if email and estat not in ("",None,"nan"):
                        email = ""; estat = ""

                apollo_candidates.append({
                    "first_name": fn, "last_name": ln, "title": t, "linkedin_url": li,
                    "email": email, "email_status": estat,
                    "company_name": str(r.get("Company Name") or "").strip(),
                    "company_domain": d,
                    "company_linkedin_url": str(r.get("Company Linkedin Url","") or ""),
                    "company_website": str(r.get("Website","") or ""),
                    "keywords": str(r.get("Keywords") or "")[:300],
                    "industry": str(r.get("Industry") or "").strip(),
                    "annual_revenue": r.get("Annual Revenue") or "",
                    "employee_count": r.get("# Employees") or "",
                    "city": str(r.get("City","") or "").strip(),
                    "state": str(r.get("State","") or "").strip(),
                    "country": "United States",
                    "technologies": str(r.get("Technologies","") or "")[:300],
                })
                existing_keys.add(key_nd)
                if key_li: existing_keys.add(key_li)
    print(f"  Apollo new senior leads (not yet in pool): {len(apollo_candidates)}")

    # Among those, the domains already in storeleads_verified can be auto-niched
    apollo_known = []
    apollo_unknown_domains = set()
    for r in apollo_candidates:
        if r["company_domain"] in sl_idx:
            apollo_known.append(r)
        else:
            apollo_unknown_domains.add(r["company_domain"])
    print(f"  At storeleads-verified domains: {len(apollo_known)}")
    print(f"  At unknown domains needing verification: {len(apollo_unknown_domains)}")

    # /collections.json verify unknown domains in parallel
    domain_to_classification = {}
    if apollo_unknown_domains:
        print(f"  Verifying {len(apollo_unknown_domains)} unknown domains via /collections.json…")
        def verify(d):
            cols = stage2.fetch_collections(d)
            cls = stage2.classify(cols, fallback_text="", merchant_name="", domain=d)
            return d, cls
        with ThreadPoolExecutor(max_workers=15) as ex:
            futures = [ex.submit(verify, d) for d in apollo_unknown_domains]
            n_done = 0
            for fut in as_completed(futures):
                d, cls = fut.result()
                domain_to_classification[d] = cls
                n_done += 1
                if n_done % 200 == 0:
                    print(f"    {n_done}/{len(apollo_unknown_domains)} verified")
        kept = sum(1 for d,c in domain_to_classification.items()
                   if c.get("source_of_truth") == "collections.json"
                   and c.get("niches") and c.get("is_apparel"))
        print(f"  /collections.json passed: {kept}/{len(apollo_unknown_domains)}")

    # Build final new rows
    new_rows = []
    for r in apollo_known:
        sl = sl_idx[r["company_domain"]]
        new = _to_row(r, sl, None)
        new_rows.append(new)
    for r in apollo_candidates:
        if r["company_domain"] not in apollo_unknown_domains: continue
        cls = domain_to_classification.get(r["company_domain"])
        if not cls or cls.get("source_of_truth") != "collections.json": continue
        if not cls.get("niches") or not cls.get("is_apparel"): continue
        new = _to_row(r, None, cls)
        new_rows.append(new)
    print(f"\n  Apollo recoverable senior leads (after verify): {len(new_rows)}")

    all_people = existing + new_rows
    print(f"\nFinal v7 pool: {len(all_people)} ({sum(1 for p in all_people if p['email'])} w/ email)")
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in all_people: w.writerow(p)
    print(f"→ {OUT}")


def _to_row(r, sl_brand=None, cls=None):
    # Build canonical row from apollo candidate + either storeleads brand or /collections.json classification
    if sl_brand:
        niches = sl_brand.get("niches_detected","").split("|") if sl_brand.get("niches_detected") else []
        primary_niche = sl_brand.get("primary_niche_verified","")
        brand_meta = sl_brand
    else:
        niches = cls.get("niches", []) if cls else []
        # primary
        from importlib import import_module
        primary_niche = (stage2.primary_pick(niches, cls.get("niche_hit_counts", {})) if cls else "")
        brand_meta = {}
    return {
        "source": "apollo_recovered",
        "first_name": r["first_name"], "last_name": r["last_name"],
        "full_name": f"{r['first_name']} {r['last_name']}".strip(),
        "title": r["title"], "linkedin_url": r["linkedin_url"],
        "email": r["email"], "email_verification_status": r["email_status"] if r["email"] else "",
        "email_source": "apollo_pre_verified" if r["email"] else "",
        "company_name": r["company_name"] or (brand_meta.get("company_name","") if brand_meta else ""),
        "company_domain": r["company_domain"],
        "company_linkedin_url": r["company_linkedin_url"] or brand_meta.get("company_linkedin_url",""),
        "company_website": r["company_website"],
        "primary_niche": primary_niche, "all_niches": "|".join(niches),
        "is_multi_brand_retailer": brand_meta.get("is_multi_brand_retailer","no"),
        "monthly_revenue_usd": brand_meta.get("estimated_monthly_sales_usd",""),
        "plan": brand_meta.get("plan",""),
        "products_created_30": brand_meta.get("products_created_30","0"),
        "products_created_90": brand_meta.get("products_created_90","0"),
        "high_cadence": brand_meta.get("high_cadence","no"),
        "most_recent_product_title": brand_meta.get("most_recent_product_title",""),
        "most_recent_product_image_url": brand_meta.get("most_recent_product_image_url",""),
        "most_recent_product_url": brand_meta.get("most_recent_product_url",""),
        "instagram_url": brand_meta.get("instagram_url",""),
        "tiktok_url": brand_meta.get("tiktok_url",""),
        "city": r["city"], "state": r["state"], "country": r["country"],
        "annual_revenue_usd": r["annual_revenue"], "employee_count": r["employee_count"],
        "industry": r["industry"], "keywords": r["keywords"], "technologies": r["technologies"],
    }


if __name__ == "__main__":
    main()
