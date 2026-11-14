#!/usr/bin/env python3
"""
Round 3: expand title list (+ Head of Brand/Creative/E-commerce/DTC etc.)
  1. Re-filter Apollo CSVs with expanded title regex
  2. Re-filter Clay export with expanded title regex
  3. Re-run BlitzAPI employee finder on 1,287 storeleads_verified brands with new titles
  4. Merge all new people into people_all_v3.csv → people_all_v4.csv
  5. (waterfall enrichment is run by next script)
"""
import csv, json, re, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from collections import Counter, defaultdict

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
from _titles import TITLES, TITLES_RX

STORELEADS = RD / "raw" / "storeleads_verified.csv"
APOLLO_FILES = [
    ROOT / "brain/assets/ayna_apollo_revenue.csv",
    ROOT / "brain/assets/ayna_apollo_headcount.csv",
]
CLAY = RD / "domains_for_clay" / "CEO-Founder-Co-founder-Default-view-export-1779344820794.csv"
EXISTING_PEOPLE = RD / "people_all_v3.csv"
OUT_PEOPLE = RD / "people_all_v4.csv"
OUT_R3_DM = RD / "raw" / "decision_makers_r3.csv"

# Reuse Stage 2 niche logic
import importlib.util
spec = importlib.util.spec_from_file_location("stage2", str(ROOT / "clients/ayna/scripts/03_collections_enrich.py"))
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)
NICHE_PATTERNS = stage2.NICHE_PATTERNS
NICHE_PRIORITY = stage2.NICHE_PRIORITY

BLITZ_KEY = "REDACTED_BLITZAPI_KEY"
BLITZ_H = {"x-api-key": BLITZ_KEY, "Content-Type": "application/json"}

def norm_domain(s):
    if not s: return ""
    s = str(s).strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def tag_niches(text):
    text = (text or "").lower()
    return [k for k, p in NICHE_PATTERNS.items() if re.search(p, text, re.IGNORECASE)]

def primary(niches):
    for k in NICHE_PRIORITY:
        if k in niches: return k
    return niches[0] if niches else ""

FIELDS = [
    "source","first_name","last_name","full_name","title","linkedin_url",
    "email","email_verification_status","email_source",
    "company_name","company_domain","company_linkedin_url","company_website",
    "primary_niche","all_niches","is_multi_brand_retailer",
    "monthly_revenue_usd","plan","products_created_30","products_created_90",
    "high_cadence","most_recent_product_title","most_recent_product_image_url",
    "most_recent_product_url","instagram_url","tiktok_url",
    "city","state","country","annual_revenue_usd","employee_count","industry","keywords","technologies",
]


def parse_location(s):
    parts = [p.strip() for p in (s or "").split(",")]
    if len(parts) >= 3: return (parts[0], parts[1], parts[2])
    if len(parts) == 2: return ("", parts[0], parts[1])
    return ("", "", parts[0] if parts else "")


def build_existing_keys(people):
    keys = set()
    for p in people:
        if p.get("email"): keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))
    return keys


def main():
    storeleads = list(csv.DictReader(STORELEADS.open(encoding="utf-8")))
    sl_idx = {r["company_domain"]: r for r in storeleads}
    existing = list(csv.DictReader(EXISTING_PEOPLE.open(encoding="utf-8")))
    existing_keys = build_existing_keys(existing)
    print(f"Starting pool: {len(existing)} people, {sum(1 for p in existing if p['email'])} with email")

    # Apollo domain → niche map for backfill
    apollo_domain_niche = {}
    for src in APOLLO_FILES:
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                d = norm_domain(r.get("Website") or "")
                if not d: continue
                if d not in apollo_domain_niche:
                    n = tag_niches(" | ".join([str(r.get("Keywords","")), str(r.get("Industry","")),
                                                str(r.get("Company Name","")), d]))
                    if n: apollo_domain_niche[d] = (primary(n), "|".join(n))

    new_people = []

    # ============== STEP 1: Re-filter Apollo with expanded titles ==============
    print("\n--- Apollo re-filter (expanded titles) ---")
    apollo_added = 0
    for src in APOLLO_FILES:
        label = "apollo_" + src.stem.replace("ayna_apollo_","")
        with src.open(encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                title = str(r.get("Title") or "").strip()
                if not TITLES_RX.search(title): continue
                domain = norm_domain(r.get("Website") or "")
                if not domain: continue
                keywords = str(r.get("Keywords") or "")
                industry = str(r.get("Industry") or "")
                company_name = str(r.get("Company Name") or "").strip()
                niche_text = " | ".join([keywords, industry, company_name, domain])
                niches = tag_niches(niche_text)
                if not niches:
                    # try domain-based backfill from apollo map
                    if domain in apollo_domain_niche:
                        pn, an = apollo_domain_niche[domain]
                        niches = an.split("|")
                if not niches: continue
                fn = str(r.get("First Name","") or "").strip()
                ln = str(r.get("Last Name","") or "").strip()
                li = str(r.get("Person Linkedin Url","") or "").strip()
                email = str(r.get("Email") or "").strip().lower()
                estat = str(r.get("Email Status","") or "").strip().lower()
                if estat not in ("valid","accept_all","accept-all","accept all"):
                    if email and estat not in ("",None,"nan"):
                        email = ""; estat = ""

                key_li = ("li", li.lower().rstrip("/")) if li else None
                key_nd = ("nd", f"{fn}|{ln}|{domain}".lower())
                if (key_li and key_li in existing_keys) or key_nd in existing_keys: continue
                brand = sl_idx.get(domain, {})
                new = {
                    "source": label, "first_name": fn, "last_name": ln,
                    "full_name": f"{fn} {ln}".strip(),
                    "title": title, "linkedin_url": li,
                    "email": email, "email_verification_status": estat if email else "",
                    "email_source": "apollo_pre_verified" if email else "",
                    "company_name": company_name,
                    "company_domain": domain,
                    "company_linkedin_url": str(r.get("Company Linkedin Url","") or ""),
                    "company_website": str(r.get("Website","") or ""),
                    "primary_niche": primary(niches),
                    "all_niches": "|".join(niches),
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
                    "city": str(r.get("City","") or "").strip(),
                    "state": str(r.get("State","") or "").strip(),
                    "country": str(r.get("Country","") or "United States").strip(),
                    "annual_revenue_usd": r.get("Annual Revenue","") or "",
                    "employee_count": r.get("# Employees","") or "",
                    "industry": industry,
                    "keywords": keywords[:300],
                    "technologies": str(r.get("Technologies","") or "")[:300],
                }
                new_people.append(new)
                apollo_added += 1
                existing_keys.add(key_nd)
                if key_li: existing_keys.add(key_li)
    print(f"  Apollo new (expanded titles): {apollo_added}")

    # ============== STEP 2: Re-filter Clay with expanded titles ==============
    print("\n--- Clay re-filter (expanded titles) ---")
    clay_added = 0
    with CLAY.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            domain = norm_domain(r.get("Company Domain",""))
            if not domain or domain == "linkedin.com": continue
            title = str(r.get("Job Title","") or "").strip()
            if not TITLES_RX.search(title): continue
            li = (r.get("LinkedIn Profile") or "").strip()
            fn = (r.get("First Name") or "").strip()
            ln = (r.get("Last Name") or "").strip()
            key_li = ("li", li.lower().rstrip("/")) if li else None
            key_nd = ("nd", f"{fn}|{ln}|{domain}".lower())
            if (key_li and key_li in existing_keys) or key_nd in existing_keys: continue
            brand = sl_idx.get(domain, {})
            niches = []
            if brand.get("niches_detected"):
                niches = brand["niches_detected"].split("|")
            elif domain in apollo_domain_niche:
                niches = apollo_domain_niche[domain][1].split("|")
            city, state, country = parse_location(r.get("Location",""))
            new = {
                "source": "clay", "first_name": fn, "last_name": ln,
                "full_name": (r.get("Full Name") or f"{fn} {ln}").strip(),
                "title": title, "linkedin_url": li,
                "email": "", "email_verification_status": "", "email_source": "",
                "company_name": brand.get("company_name","") or domain.split(".")[0].title(),
                "company_domain": domain,
                "company_linkedin_url": brand.get("company_linkedin_url",""),
                "company_website": f"https://{domain}",
                "primary_niche": primary(niches), "all_niches": "|".join(niches),
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
                "city": city, "state": state, "country": country or "United States",
                "annual_revenue_usd": "", "employee_count": "", "industry": "DTC Fashion",
                "keywords": "", "technologies": "",
            }
            new_people.append(new)
            clay_added += 1
            existing_keys.add(key_nd)
            if key_li: existing_keys.add(key_li)
    print(f"  Clay new (expanded titles): {clay_added}")

    # ============== STEP 3: BlitzAPI employee finder w/ expanded titles ==============
    print("\n--- BlitzAPI employee finder (expanded titles) on 1,287 brands ---")
    out_dm = OUT_R3_DM.open("w", newline="", encoding="utf-8")
    dm_writer = csv.DictWriter(out_dm, fieldnames=FIELDS, extrasaction="ignore")
    dm_writer.writeheader()
    blitz_added = 0
    lock = __import__("threading").Lock()

    def query_dms(brand):
        ln = brand.get("company_linkedin_url","").strip()
        if not ln: return brand["company_domain"], []
        payload = {
            "company": {"linkedin_url": [ln]},
            "people": {"job_title": {"include": TITLES, "exclude": []}},
            "max_results": 10,
        }
        try:
            r = requests.post("https://api.blitz-api.ai/v2/search/people",
                              json=payload, headers=BLITZ_H, timeout=30)
            if r.status_code == 200:
                return brand["company_domain"], r.json().get("results", [])
        except Exception: pass
        return brand["company_domain"], []

    domains_done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(query_dms, b): b for b in storeleads}
        for fut in as_completed(futures):
            brand = futures[fut]
            domain, people = fut.result()
            domains_done += 1
            if domains_done % 100 == 0:
                print(f"  {domains_done}/{len(storeleads)} brands, {blitz_added} new DMs")
            for p in people:
                title = (p.get("headline") or "").strip()
                exps = p.get("experiences") or []
                cur = exps[0] if exps else {}
                cur_title = (cur.get("job_title") or title)
                if not TITLES_RX.search(cur_title or ""): continue
                fn = (p.get("first_name") or "").strip()
                ln = (p.get("last_name") or "").strip()
                lin = (p.get("linkedin_url") or "").strip()
                key_li = ("li", lin.lower().rstrip("/")) if lin else None
                key_nd = ("nd", f"{fn}|{ln}|{domain}".lower())
                with lock:
                    if (key_li and key_li in existing_keys) or key_nd in existing_keys: continue
                    existing_keys.add(key_nd)
                    if key_li: existing_keys.add(key_li)
                loc = p.get("location") or {}
                new = {
                    "source": "blitz_dm_r3", "first_name": fn, "last_name": ln,
                    "full_name": f"{fn} {ln}".strip(),
                    "title": cur_title, "linkedin_url": lin,
                    "email": "", "email_verification_status": "", "email_source": "",
                    "company_name": brand.get("company_name",""),
                    "company_domain": domain,
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
                    "city": loc.get("city",""), "state": loc.get("state_code",""),
                    "country": loc.get("country_code","US"),
                    "annual_revenue_usd": "", "employee_count": "",
                    "industry": "DTC Fashion", "keywords": "", "technologies": "",
                }
                with lock:
                    new_people.append(new)
                    dm_writer.writerow(new)
                    blitz_added += 1
    out_dm.close()
    print(f"  BlitzAPI new DMs: {blitz_added}")

    # ============== STEP 4: Merge & write people_all_v4 ==============
    all_people = existing + new_people
    print(f"\nTotal pool: {len(all_people)} (was {len(existing)})")
    print(f"  with email: {sum(1 for p in all_people if p.get('email'))}")
    print(f"  needs enrich: {sum(1 for p in all_people if not p.get('email'))}")
    fields = list(existing[0].keys())
    with OUT_PEOPLE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in all_people: w.writerow(p)
    print(f"→ {OUT_PEOPLE}")

if __name__ == "__main__":
    main()
