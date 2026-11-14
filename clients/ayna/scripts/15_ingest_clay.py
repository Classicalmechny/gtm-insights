#!/usr/bin/env python3
"""
Ingest Clay export, merge into people_all_enriched, enrich missing emails via Instantly.
"""
import csv, json, re, time
from pathlib import Path
from collections import Counter
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
CLAY = RD / "domains_for_clay" / "CEO-Founder-Co-founder-Default-view-export-1779344820794.csv"
PEOPLE = RD / "people_all_enriched.csv"
STORELEADS = RD / "raw" / "storeleads_verified.csv"
OUT_PEOPLE = RD / "people_all_v2.csv"
OUT_CLAY_NORM = RD / "raw" / "clay.csv"

H = {"Authorization": "Bearer NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==",
     "Content-Type": "application/json"}

ACCEPTABLE_TITLES_RX = re.compile(
    r"(founder|cofounder|co.?founder|chief executive|\bceo\b|owner|president|principal|managing director)",
    re.IGNORECASE,
)

def normalize_domain(s):
    if not s: return ""
    s = str(s).strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def parse_location(s):
    if not s: return ("","","")
    parts = [p.strip() for p in str(s).split(",")]
    if len(parts) >= 3:
        return (parts[0], parts[1], parts[2])
    if len(parts) == 2:
        return ("", parts[0], parts[1])
    return ("", "", parts[0])

def main():
    storeleads = list(csv.DictReader(STORELEADS.open(encoding="utf-8")))
    sl_idx = {r["company_domain"]: r for r in storeleads}

    # Existing people
    people = list(csv.DictReader(PEOPLE.open(encoding="utf-8")))
    fields = list(people[0].keys())
    existing_keys = set()
    for p in people:
        if p.get("email"): existing_keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): existing_keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            existing_keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))
    print(f"Existing people: {len(people)} ({sum(1 for p in people if p.get('email'))} with email)")

    # Parse Clay
    clay_rows = []
    n_clay = 0
    n_dropped = 0
    n_dup = 0
    n_no_title = 0
    n_no_domain = 0
    with CLAY.open(encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            n_clay += 1
            domain = normalize_domain(r.get("Company Domain", ""))
            if not domain or domain == "linkedin.com":
                n_no_domain += 1; continue
            title = (r.get("Job Title") or "").strip()
            if not ACCEPTABLE_TITLES_RX.search(title):
                n_no_title += 1; continue

            li = (r.get("LinkedIn Profile") or "").strip()
            fn = (r.get("First Name") or "").strip()
            ln = (r.get("Last Name") or "").strip()

            # Dedupe vs existing
            key_li = ("li", li.lower().rstrip("/")) if li else None
            key_nd = ("nd", f"{fn}|{ln}|{domain}".lower())
            if (key_li and key_li in existing_keys) or key_nd in existing_keys:
                n_dup += 1; continue

            # Get brand context from storeleads
            brand = sl_idx.get(domain, {})
            city, state, country = parse_location(r.get("Location", ""))

            new = {
                "source": "clay",
                "first_name": fn,
                "last_name": ln,
                "full_name": (r.get("Full Name") or f"{fn} {ln}").strip(),
                "title": title,
                "linkedin_url": li,
                "email": "",
                "email_verification_status": "",
                "email_source": "",
                "company_name": brand.get("company_name", "") or domain.split(".")[0].title(),
                "company_domain": domain,
                "company_linkedin_url": brand.get("company_linkedin_url", ""),
                "company_website": brand.get("company_website", "") or f"https://{domain}",
                "primary_niche": brand.get("primary_niche_verified", ""),
                "all_niches": brand.get("niches_detected", ""),
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
                "annual_revenue_usd": "",
                "employee_count": "",
                "industry": "DTC Fashion",
                "keywords": "",
                "technologies": "",
            }
            clay_rows.append(new)
            n_dropped += 1
            existing_keys.add(key_nd)
            if key_li: existing_keys.add(key_li)

    print(f"\nClay parse: total={n_clay}")
    print(f"  no_domain (incl. linkedin.com): {n_no_domain}")
    print(f"  no_title_match: {n_no_title}")
    print(f"  duplicate of existing: {n_dup}")
    print(f"  NEW from Clay: {len(clay_rows)}")
    # Niche distribution
    nd = Counter(r["primary_niche"] for r in clay_rows)
    print(f"\nNiche distribution (Clay new):")
    for k,v in nd.most_common(): print(f"  {k or '(none)':20s} {v}")

    # Save normalized Clay
    OUT_CLAY_NORM.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CLAY_NORM.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in clay_rows: w.writerow(r)
    print(f"\nWrote Clay normalized → {OUT_CLAY_NORM}")

    # Merge into people pool
    all_people = people + clay_rows
    with OUT_PEOPLE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in all_people: w.writerow(p)
    print(f"Wrote merged pool ({len(all_people)} people) → {OUT_PEOPLE}")
    print(f"  with email: {sum(1 for p in all_people if p.get('email'))}")
    print(f"  needs email enrich: {sum(1 for p in all_people if not p.get('email'))}")

if __name__ == "__main__":
    main()
