#!/usr/bin/env python3
"""
Strict Clay ingestion v3: filter ALL Clay exports against the 8,289 niche TAM.

Loads the canonical niche-TAM domain set (from batch_v3_all_niche.csv).
For each Clay export file, keeps ONLY leads where:
  - Company Domain is in the niche TAM
  - Location contains 'United States' (or US/USA)
  - Title matches TITLES_RX and is NOT TITLES_RX_EXCLUDE

Also audits and removes any prior Clay entries in the pool that have
domains NOT in the TAM (non-ICP leaks like HP, LinkedIn, Google, Chick-fil-A).

Outputs:
  raw/clay_strict.csv          — all 3 Clay exports, strictly filtered
  people_all_v9.csv            — pool with non-ICP Clay entries scrubbed + strict adds
"""
import csv, re, sys
from pathlib import Path
from collections import Counter

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
from _titles import TITLES_RX, TITLES_RX_EXCLUDE

CLAY_FILES = [
    RD / "domains_for_clay" / "CEO-Founder-Co-founder-Default-view-export-1779344820794.csv",
    RD / "domains_for_clay" / "Brand-and-Creative-Leaders,-E-commerce,-DTC-Default-view-export-1779347321185.csv",
    RD / "domains_for_clay" / "Leadership,-Branding,-E-commerce,-DTC-Default-view-export-1779351443266.csv",
]
TAM = RD / "domains_for_clay" / "batch_v3_enriched.csv"
PRIOR_PEOPLE = RD / "people_all_final.csv"
OUT_CLAY = RD / "raw" / "clay_strict.csv"
OUT = RD / "people_all_v9.csv"

def norm_domain(s):
    if not s: return ""
    s = str(s).strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def parse_location(s):
    parts = [p.strip() for p in (s or "").split(",")]
    if len(parts) >= 3: return (parts[0], parts[1], parts[2])
    if len(parts) == 2: return ("", parts[0], parts[1])
    return ("", "", parts[0] if parts else "")

def is_us(loc):
    s = (loc or "").upper()
    return "UNITED STATES" in s or "USA" in s or " US" in f" {s}"

def main():
    tam = list(csv.DictReader(TAM.open(encoding="utf-8")))
    tam_idx = {r["domain"]: r for r in tam}
    print(f"Niche TAM: {len(tam_idx):,} domains")

    existing = list(csv.DictReader(PRIOR_PEOPLE.open(encoding="utf-8")))
    print(f"Prior pool: {len(existing)}")

    # ---- AUDIT: scrub prior Clay-source leaks at non-TAM domains ----
    scrubbed = 0
    audited = []
    for p in existing:
        # Only scrub Clay-source rows; others (storeleads/blitz/apollo/instantly) are independently filtered
        src = (p.get("source") or "").lower()
        if "clay" in src:
            d = norm_domain(p.get("company_domain",""))
            if d not in tam_idx:
                scrubbed += 1
                continue
        audited.append(p)
    print(f"Scrubbed non-ICP Clay leaks from prior pool: {scrubbed}")
    existing = audited

    existing_keys = set()
    for p in existing:
        if p.get("email"): existing_keys.add(("email", p["email"].lower()))
        if p.get("linkedin_url"): existing_keys.add(("li", p["linkedin_url"].strip().lower().rstrip("/")))
        if p.get("first_name") and p.get("last_name") and p.get("company_domain"):
            existing_keys.add(("nd", f'{p["first_name"]}|{p["last_name"]}|{p["company_domain"]}'.lower()))

    # ---- INGEST: re-process all 3 Clay files strictly ----
    fields = list(existing[0].keys())
    clay_writer_file = OUT_CLAY.open("w", newline="", encoding="utf-8")
    cw = csv.DictWriter(clay_writer_file, fieldnames=fields, extrasaction="ignore"); cw.writeheader()

    summary = []
    new_people = []
    for clay_path in CLAY_FILES:
        if not clay_path.exists():
            print(f"  SKIP missing: {clay_path.name}")
            continue
        n_total = 0; n_no_dom = 0; n_dom_not_in_tam = 0; n_no_title = 0
        n_excluded = 0; n_non_us = 0; n_dup = 0; n_new = 0
        with clay_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                n_total += 1
                d = norm_domain(r.get("Company Domain",""))
                if not d or d == "linkedin.com":
                    n_no_dom += 1; continue
                if d not in tam_idx:
                    n_dom_not_in_tam += 1; continue
                t = (r.get("Job Title") or "").strip()
                if not TITLES_RX.search(t): n_no_title += 1; continue
                if TITLES_RX_EXCLUDE.search(t): n_excluded += 1; continue
                if not is_us(r.get("Location","")): n_non_us += 1; continue

                li = (r.get("LinkedIn Profile") or "").strip()
                fn = (r.get("First Name") or "").strip()
                ln = (r.get("Last Name") or "").strip()
                key_li = ("li", li.lower().rstrip("/")) if li else None
                key_nd = ("nd", f"{fn}|{ln}|{d}".lower())
                if (key_li and key_li in existing_keys) or key_nd in existing_keys:
                    n_dup += 1; continue

                brand = tam_idx[d]
                city, state, country = parse_location(r.get("Location",""))
                row = {f: "" for f in fields}
                row.update({
                    "source": f"clay_strict_{clay_path.stem[:30]}",
                    "first_name": fn, "last_name": ln,
                    "full_name": (r.get("Full Name") or f"{fn} {ln}").strip(),
                    "title": t, "linkedin_url": li,
                    "email": "", "email_verification_status": "", "email_source": "",
                    "company_name": brand.get("company_name", d.split(".")[0].title()),
                    "company_domain": d,
                    "company_linkedin_url": brand.get("company_linkedin_url",""),
                    "company_website": brand.get("url", f"https://{d}"),
                    "primary_niche": brand.get("primary_niche",""),
                    "all_niches": brand.get("all_niches",""),
                    "is_multi_brand_retailer": "no",
                    "monthly_revenue_usd": brand.get("monthly_revenue_usd",""),
                    "plan": brand.get("plan",""),
                    "products_created_30": brand.get("products_created_30","0"),
                    "products_created_90": brand.get("products_created_90","0"),
                    "high_cadence": brand.get("high_cadence","no"),
                    "instagram_url": brand.get("instagram_url",""),
                    "tiktok_url": brand.get("tiktok_url",""),
                    "city": city, "state": state, "country": country or "United States",
                    "industry": "DTC Fashion",
                })
                new_people.append(row); cw.writerow(row)
                existing_keys.add(key_nd)
                if key_li: existing_keys.add(key_li)
                n_new += 1
        summary.append({"file": clay_path.name, "total": n_total, "dom_not_in_tam": n_dom_not_in_tam,
                        "no_dom": n_no_dom, "no_title": n_no_title, "excluded": n_excluded,
                        "non_us": n_non_us, "dup": n_dup, "new": n_new})
    clay_writer_file.close()

    print("\n=== Per-file breakdown ===")
    for s in summary:
        print(f"\n  {s['file']}")
        for k, v in s.items():
            if k != "file": print(f"    {k:20s} {v}")

    total_new = sum(s["new"] for s in summary)
    print(f"\nNew strict-Clay leads: {total_new}")

    # Niche dist of new
    nd = Counter(p["primary_niche"] for p in new_people)
    print(f"\nNiche distribution of new Clay leads:")
    for k, v in nd.most_common():
        print(f"  {k or '(none)':20s} {v}")

    # Merge
    all_people = existing + new_people
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for p in all_people: w.writerow(p)
    print(f"\nFinal v9 pool: {len(all_people)} ({sum(1 for p in all_people if p['email'])} w/ email)")
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()
