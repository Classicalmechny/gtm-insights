#!/usr/bin/env python3
"""
Final deliverables:
  1. FULL TAM DATABASE  →  output/<run>/AYNA_FULL_TAM.csv
       Every person across all sources (with + without email) + brand context.
  2. CAMPAIGN LISTS      →  output/<run>/campaigns_final/
       campaign_1_free_sample.csv
       campaign_2_cost_per_sku.csv
       campaign_3_representation.csv
       campaign_4_drop_velocity.csv
     Each row = an outbound-ready lead with only the variables needed for that campaign.
"""
import csv, json
from pathlib import Path
from collections import Counter

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
SRC = RD / "people_all_final2.csv"
TAM_OUT = RD / "AYNA_FULL_TAM.csv"
CDIR = RD / "campaigns_final"
CDIR.mkdir(parents=True, exist_ok=True)

# Niche slug → human-readable {{category}} label
CATEGORY_LABEL = {
    "kidswear":   "kidswear",
    "innerwear":  "intimates and lingerie",
    "plus_size":  "plus size",
    "inclusive":  "inclusive sizing",
    "maternity":  "maternity",
    "modest":     "modest fashion",
    "adaptive":   "adaptive fashion",
    "athleisure": "athleisure",
}
# Niches that get Campaign 3 (Representation Promise)
REPRESENTATION_NICHES = {"plus_size","inclusive","maternity","adaptive","modest","kidswear","innerwear"}

def is_high_cadence(row):
    try:
        return int(row.get("products_created_30") or 0) >= 10 or int(row.get("products_created_90") or 0) >= 30
    except Exception:
        return False

def main():
    people = list(csv.DictReader(SRC.open(encoding="utf-8")))
    print(f"Loaded pool: {len(people)} people ({sum(1 for p in people if p.get('email'))} w/ email)")

    # =========== 1. Full TAM Database ===========
    # Add computed fields
    for p in people:
        niche = p.get("primary_niche", "")
        p["category_label"] = CATEGORY_LABEL.get(niche, niche.replace("_", " ") if niche else "")
        p["storefront_url"] = f"https://{p['company_domain']}" if p.get("company_domain") else ""
        p["drop_cadence"] = "high" if is_high_cadence(p) else "standard"
        p["has_email"] = "yes" if p.get("email") else "no"
        p["email_deliverable"] = "yes" if p.get("email") and p.get("email_source") in (
            "apollo_pre_verified",
            "instantly_supersearch_verified",
            "instantly_supersearch_enrich",
            "instantly_supersearch_enrich_r2",
            "instantly_supersearch_enrich_r3",
            "instantly_supersearch_enrich_final",
            "instantly_supersearch_final2",
            "instantly_multi_query",
        ) else ("partial" if p.get("email") else "no")
        # Tag campaigns
        camps = []
        if niche:
            camps.append("1_free_sample")
            camps.append("2_cost_per_sku")
            if niche in REPRESENTATION_NICHES: camps.append("3_representation")
        if is_high_cadence(p): camps.append("4_drop_velocity")
        p["campaigns"] = "|".join(camps)

    tam_fields = [
        "first_name", "last_name", "full_name", "title", "email", "email_deliverable",
        "linkedin_url", "company_name", "company_domain", "storefront_url",
        "primary_niche", "category_label", "all_niches",
        "is_multi_brand_retailer", "drop_cadence", "high_cadence",
        "monthly_revenue_usd", "annual_revenue_usd", "employee_count", "plan",
        "products_created_30", "products_created_90",
        "most_recent_product_title", "most_recent_product_image_url", "most_recent_product_url",
        "instagram_url", "tiktok_url",
        "company_linkedin_url", "city", "state", "country",
        "industry", "keywords", "technologies",
        "source", "email_source", "email_verification_status",
        "campaigns", "has_email",
    ]
    with TAM_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=tam_fields, extrasaction="ignore"); w.writeheader()
        for p in people: w.writerow(p)
    print(f"\n=== 1. FULL TAM DATABASE ===")
    print(f"→ {TAM_OUT}")
    print(f"   {len(people)} rows ({sum(1 for p in people if p.get('email'))} with email)")

    # =========== 2. Campaign Lists ===========
    # Only include people WITH email (outbound-ready)
    outbound = [p for p in people if p.get("email") and p.get("primary_niche")]
    print(f"\n=== 2. CAMPAIGN LISTS ===")
    print(f"Outbound-ready: {len(outbound)} (email + niche tagged)")

    # Shared columns across campaigns
    CORE = ["first_name", "last_name", "email", "title", "linkedin_url",
            "company_name", "company_domain", "storefront_url",
            "primary_niche", "category_label", "city", "state", "country",
            "source", "email_source", "email_verification_status"]

    # Campaign 1 — Free Sample (signature). Variables: first_name, company_name, storefront_url, category_label, most_recent_product_*
    C1_FIELDS = CORE + ["most_recent_product_title", "most_recent_product_image_url", "most_recent_product_url"]
    c1 = [p for p in outbound if "1_free_sample" in p["campaigns"]]
    _write(CDIR / "campaign_1_free_sample.csv", c1, C1_FIELDS)
    print(f"  campaign_1_free_sample.csv          {len(c1):5d} leads")

    # Campaign 2 — Cost-Per-SKU Math. Variables: first_name, company_name, category_label, products_created_*
    C2_FIELDS = CORE + ["products_created_30", "products_created_90"]
    c2 = [p for p in outbound if "2_cost_per_sku" in p["campaigns"]]
    _write(CDIR / "campaign_2_cost_per_sku.csv", c2, C2_FIELDS)
    print(f"  campaign_2_cost_per_sku.csv         {len(c2):5d} leads")

    # Campaign 3 — Representation Promise. Variables: first_name, company_name, storefront_url, category_label, niche-specific framing
    C3_FIELDS = CORE + ["all_niches", "most_recent_product_image_url"]
    c3 = [p for p in outbound if "3_representation" in p["campaigns"]]
    _write(CDIR / "campaign_3_representation.csv", c3, C3_FIELDS)
    print(f"  campaign_3_representation.csv       {len(c3):5d} leads")

    # Campaign 4 — Drop Velocity. Variables: first_name, company_name, drop_cadence, products_created_*
    C4_FIELDS = CORE + ["drop_cadence", "products_created_30", "products_created_90", "high_cadence"]
    c4 = [p for p in outbound if "4_drop_velocity" in p["campaigns"]]
    _write(CDIR / "campaign_4_drop_velocity.csv", c4, C4_FIELDS)
    print(f"  campaign_4_drop_velocity.csv        {len(c4):5d} leads")

    # =========== Summary ===========
    print(f"\n=== Summary ===")
    print(f"Full TAM: {len(people)} people  ({sum(1 for p in people if p.get('email'))} with email)")
    print(f"\nNiche dist (with email):")
    for k,v in Counter(p["primary_niche"] for p in outbound).most_common():
        print(f"  {k or '(none)':25s} {v}")
    print(f"\nEmail source breakdown:")
    for k,v in Counter(p["email_source"] for p in outbound).most_common():
        print(f"  {k:45s} {v}")

def _write(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow(r)

if __name__ == "__main__":
    main()
