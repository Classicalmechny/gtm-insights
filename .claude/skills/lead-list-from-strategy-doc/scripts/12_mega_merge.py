#!/usr/bin/env python3
"""
Mega-merge: combine all people sources into one deduped pool.

Sources:
  output/<run>/people_with_blitz_emails.csv (412 BlitzAPI DMs + 6 Instantly = 418, 115 with emails)
  output/<run>/raw/apollo.csv               (1879 Apollo leads, 489 with emails)

Output:
  output/<run>/people_all.csv               (mega-merged, deduped)
  output/<run>/domains_for_clay/batch_*.csv (10K domains per batch)
"""
import csv
from pathlib import Path
from collections import defaultdict

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
PRIOR_PEOPLE = RD / "people_with_blitz_emails.csv"
APOLLO = RD / "raw" / "apollo.csv"
STORELEADS = RD / "raw" / "storeleads_verified.csv"
OUT = RD / "people_all.csv"
CLAY_DIR = RD / "domains_for_clay"
CLAY_DIR.mkdir(parents=True, exist_ok=True)

def load_csv(p):
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8")))

def norm_domain(s):
    if not s: return ""
    s = str(s).strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def main():
    prior = load_csv(PRIOR_PEOPLE)
    apollo = load_csv(APOLLO)
    storeleads = load_csv(STORELEADS)
    print(f"Loaded: prior={len(prior)}, apollo={len(apollo)}, storeleads_brands={len(storeleads)}")

    sl_idx = {r["company_domain"]: r for r in storeleads}

    # Canonical fields - union of both schemas
    fields = [
        "source","first_name","last_name","full_name","title","linkedin_url",
        "email","email_verification_status","email_source",
        "company_name","company_domain","company_linkedin_url","company_website",
        "primary_niche","all_niches","is_multi_brand_retailer",
        "monthly_revenue_usd","plan","products_created_30","products_created_90",
        "high_cadence","most_recent_product_title","most_recent_product_image_url",
        "most_recent_product_url","instagram_url","tiktok_url",
        "city","state","country",
        "annual_revenue_usd","employee_count","industry","keywords","technologies",
    ]

    def to_canonical(r):
        out = {k: r.get(k, "") for k in fields}
        # ensure domain normalized
        out["company_domain"] = norm_domain(r.get("company_domain","") or r.get("website",""))
        return out

    # Dedupe by:  email > linkedin > (first|last|domain)
    seen = {}
    def key(r):
        if r.get("email"): return ("email", r["email"].lower())
        if r.get("linkedin_url"): return ("li", r["linkedin_url"].lower().rstrip("/"))
        return ("name", (r.get("first_name","")+"|"+r.get("last_name","")+"|"+r.get("company_domain","")).lower())

    # Helper to enrich a row with Storeleads brand context where missing
    def enrich_from_storeleads(r):
        d = r["company_domain"]
        if d in sl_idx:
            sl = sl_idx[d]
            for src_field, sl_field in [
                ("primary_niche","primary_niche_verified"),
                ("all_niches","niches_detected"),
                ("is_multi_brand_retailer","is_multi_brand_retailer"),
                ("monthly_revenue_usd","estimated_monthly_sales_usd"),
                ("plan","plan"),
                ("products_created_30","products_created_30"),
                ("products_created_90","products_created_90"),
                ("high_cadence","high_cadence"),
                ("most_recent_product_title","most_recent_product_title"),
                ("most_recent_product_image_url","most_recent_product_image_url"),
                ("most_recent_product_url","most_recent_product_url"),
                ("instagram_url","instagram_url"),
                ("tiktok_url","tiktok_url"),
            ]:
                if not r.get(src_field) and sl.get(sl_field):
                    r[src_field] = sl[sl_field]
            if not r.get("company_name") and sl.get("company_name"):
                r["company_name"] = sl["company_name"]
            if not r.get("company_linkedin_url") and sl.get("company_linkedin_url"):
                r["company_linkedin_url"] = sl["company_linkedin_url"]
        return r

    def add(rows):
        for r in rows:
            r = to_canonical(r)
            if not r["company_domain"]: continue
            if not r["first_name"] and not r["last_name"]: continue
            r = enrich_from_storeleads(r)
            k = key(r)
            if k in seen:
                # Prefer the one with more email signal
                existing = seen[k]
                if r["email"] and not existing["email"]:
                    seen[k] = r
                elif not r["email"] and existing["email"]:
                    pass
                else:
                    # keep existing
                    pass
            else:
                seen[k] = r

    add(apollo)
    add(prior)
    merged = list(seen.values())
    print(f"\nMega-merged unique people: {len(merged)}")
    print(f"  with email: {sum(1 for r in merged if r['email'])}")
    print(f"  without email: {sum(1 for r in merged if not r['email'])}")

    # Write people_all.csv
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in merged: w.writerow(r)
    print(f"→ {OUT}")

    # Export unique domains in 10K batches for Clay
    all_domains = set()
    # From storeleads_verified (brands)
    for r in storeleads:
        if r["company_domain"]: all_domains.add(r["company_domain"])
    # From merged people
    for r in merged:
        if r["company_domain"]: all_domains.add(r["company_domain"])
    all_domains = sorted(all_domains)
    print(f"\nUnique domains across all sources: {len(all_domains):,}")

    BATCH = 10_000
    n_batches = (len(all_domains) + BATCH - 1) // BATCH
    for i in range(n_batches):
        batch = all_domains[i*BATCH:(i+1)*BATCH]
        path = CLAY_DIR / f"batch_{i+1:02d}_of_{n_batches:02d}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["domain", "url"])
            for d in batch:
                w.writerow([d, f"https://{d}"])
        print(f"  batch {i+1}: {len(batch)} domains → {path}")

    # Niche distribution in merged
    from collections import Counter
    nd = Counter(r["primary_niche"] for r in merged)
    print(f"\nNiche distribution in mega-merged:")
    for k,v in nd.most_common():
        print(f"  {k:20s} {v}")

if __name__ == "__main__":
    main()
