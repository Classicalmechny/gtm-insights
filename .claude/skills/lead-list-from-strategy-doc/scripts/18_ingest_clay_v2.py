#!/usr/bin/env python3
"""
Ingest second Clay export (Brand and Creative Leaders, E-commerce, DTC).
Filter to senior titles via TITLES_RX (exclude junior via TITLES_RX_EXCLUDE).
Backfill niches from storeleads + apollo.
Merge into people_all_v4.csv (output from script 17) → people_all_v5.csv.
"""
import csv, re, sys
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
from _titles import TITLES_RX, TITLES_RX_EXCLUDE

CLAY = RD / "domains_for_clay" / "Brand-and-Creative-Leaders,-E-commerce,-DTC-Default-view-export-1779347321185.csv"
STORELEADS = RD / "raw" / "storeleads_verified.csv"
APOLLO = RD / "raw" / "apollo.csv"
PRIOR = RD / "people_all_v4.csv"
OUT = RD / "people_all_v5.csv"
OUT_CLAY = RD / "raw" / "clay_v2.csv"

# Niche logic
import importlib.util
spec = importlib.util.spec_from_file_location("stage2", str(ROOT / "clients/ayna/scripts/03_collections_enrich.py"))
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)
NICHE_PATTERNS = stage2.NICHE_PATTERNS
NICHE_PRIORITY = stage2.NICHE_PRIORITY

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

def parse_location(s):
    parts = [p.strip() for p in (s or "").split(",")]
    if len(parts) >= 3: return (parts[0], parts[1], parts[2])
    if len(parts) == 2: return ("", parts[0], parts[1])
    return ("", "", parts[0] if parts else "")

def main():
    storeleads = list(csv.DictReader(STORELEADS.open(encoding="utf-8")))
    sl_idx = {r["company_domain"]: r for r in storeleads}

    # Apollo domain → niche
    apollo = list(csv.DictReader(APOLLO.open(encoding="utf-8")))
    apollo_domain_niche = {}
    for r in apollo:
        d = r["company_domain"]
        if d and r["primary_niche"] and d not in apollo_domain_niche:
            apollo_domain_niche[d] = (r["primary_niche"], r["all_niches"])

    # Existing pool
    existing = list(csv.DictReader(PRIOR.open(encoding="utf-8")))
    fields = list(existing[0].keys())
    existing_keys = set()
    for p in existing:
        if p.get("email"): existing_keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): existing_keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            existing_keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))
    print(f"Starting pool (v4): {len(existing)} people, {sum(1 for p in existing if p.get('email'))} with email")

    # Parse new Clay
    new_rows = []
    n_total = n_no_domain = n_no_title = n_excluded = n_dup = 0
    n_in_us = 0
    title_counts = Counter()
    with CLAY.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            n_total += 1
            domain = norm_domain(r.get("Company Domain", ""))
            if not domain or domain == "linkedin.com":
                n_no_domain += 1; continue
            title = (r.get("Job Title") or "").strip()
            if not TITLES_RX.search(title):
                n_no_title += 1; continue
            if TITLES_RX_EXCLUDE.search(title):
                n_excluded += 1; continue
            # Strong US filter — Clay may include non-US people
            loc = (r.get("Location") or "").strip()
            if "United States" not in loc and "USA" not in loc and "US" not in loc.upper().split(","):
                n_no_domain += 1; continue
            n_in_us += 1
            title_counts[title] += 1

            li = (r.get("LinkedIn Profile") or "").strip()
            fn = (r.get("First Name") or "").strip()
            ln = (r.get("Last Name") or "").strip()
            key_li = ("li", li.lower().rstrip("/")) if li else None
            key_nd = ("nd", f"{fn}|{ln}|{domain}".lower())
            if (key_li and key_li in existing_keys) or key_nd in existing_keys:
                n_dup += 1; continue

            brand = sl_idx.get(domain, {})
            niches = []
            if brand.get("niches_detected"):
                niches = brand["niches_detected"].split("|")
            elif domain in apollo_domain_niche:
                niches = apollo_domain_niche[domain][1].split("|")

            city, state, country = parse_location(loc)
            new = {
                "source": "clay_v2",
                "first_name": fn, "last_name": ln,
                "full_name": (r.get("Full Name") or f"{fn} {ln}").strip(),
                "title": title, "linkedin_url": li,
                "email": "", "email_verification_status": "", "email_source": "",
                "company_name": brand.get("company_name", "") or domain.split(".")[0].title(),
                "company_domain": domain,
                "company_linkedin_url": brand.get("company_linkedin_url", ""),
                "company_website": f"https://{domain}",
                "primary_niche": primary(niches), "all_niches": "|".join(niches),
                "is_multi_brand_retailer": brand.get("is_multi_brand_retailer", "no"),
                "monthly_revenue_usd": brand.get("estimated_monthly_sales_usd", ""),
                "plan": brand.get("plan", ""),
                "products_created_30": brand.get("products_created_30", "0"),
                "products_created_90": brand.get("products_created_90", "0"),
                "high_cadence": brand.get("high_cadence", "no"),
                "most_recent_product_title": brand.get("most_recent_product_title", ""),
                "most_recent_product_image_url": brand.get("most_recent_product_image_url", ""),
                "most_recent_product_url": brand.get("most_recent_product_url", ""),
                "instagram_url": brand.get("instagram_url", ""),
                "tiktok_url": brand.get("tiktok_url", ""),
                "city": city, "state": state, "country": country or "United States",
                "annual_revenue_usd": "", "employee_count": "",
                "industry": "DTC Fashion", "keywords": "", "technologies": "",
            }
            new_rows.append(new)
            existing_keys.add(key_nd)
            if key_li: existing_keys.add(key_li)

    print(f"\nClay v2 parse: total={n_total}")
    print(f"  no_domain or non-US: {n_no_domain}")
    print(f"  no_title_match: {n_no_title}")
    print(f"  excluded (junior/etc): {n_excluded}")
    print(f"  duplicate of existing: {n_dup}")
    print(f"  in-US senior: {n_in_us}")
    print(f"  NEW from Clay v2: {len(new_rows)}")
    print(f"\nNew leads by title:")
    for t, c in title_counts.most_common(15):
        print(f"  {c:3d}  {t}")

    # Save normalized
    OUT_CLAY.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CLAY.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for r in new_rows: w.writerow(r)
    print(f"\n→ {OUT_CLAY}")

    # Merge
    all_people = existing + new_rows
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in all_people: w.writerow(p)
    print(f"Merged pool (v5): {len(all_people)} ({sum(1 for p in all_people if p.get('email'))} w/ email, {sum(1 for p in all_people if not p.get('email'))} need enrich)")

if __name__ == "__main__":
    main()
