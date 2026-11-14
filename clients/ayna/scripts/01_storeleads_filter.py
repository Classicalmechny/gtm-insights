#!/usr/bin/env python3
"""
Stage 1 — Storeleads filter + niche tagging.

Reads the provided Storeleads Shopify-apparel CSV, applies the 4 compulsory
ICP filters (US + Active + Shopify + revenue band), tags niche categories
via regex over (merchant_name + collections + most_recent_product_title +
domain), and writes one row per brand to:

  output/<run_id>/raw/storeleads.csv

A row is included if BOTH:
  - it passes the US + Active + Shopify + revenue-band filter (TAM gate)
  - it has at least one niche-category match  (niche gate)

In-band brands that pass the TAM gate but FAIL the niche gate are written
to output/<run_id>/raw/storeleads_unmatched.csv so Stage 2 can attempt
storefront / API category recovery on them.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pandas as pd

INPUT  = "storeleads_apparel.csv"   # relative to client root
RUN_ID = "2026-05-21_ayna_niche_fashion"
OUT_DIR = Path("output") / RUN_ID / "raw"

# Revenue band in monthly USD ($50k-$1.5M monthly ≈ $0.6M-$18M annual)
REV_MIN_MONTHLY = 50_000.0
REV_MAX_MONTHLY = 1_500_000.0

# Niche taxonomy.  Keys become the {{category}} variable.
NICHE_PATTERNS = {
    "kidswear":      r"(kids|kids[\s-]?wear|baby|babies|toddler|infant|child(?:ren)?|boys|girls|youth|tween|newborn|onesie|romper|nursery|kidz|childrenswear)",
    "innerwear":     r"(lingerie|underwear|innerwear|bras\b|bra\b|bralette|panty|panties|undie|knicker|brassiere|shapewear|sleepwear|loungewear|pajama|nightgown|nightie|nightwear|intimate|intimates|robe|chemise)",
    "plus_size":     r"(plus[\s-]?size|curve|curvy|fuller[\s-]?figure|extended[\s-]?sizing|14\+|16\+)",
    "inclusive":     r"(inclusive|size[\s-]?inclusive|all[\s-]?sizes|every[\s-]?body|body[\s-]?positive|body[\s-]?neutral|gender[\s-]?neutral|non[\s-]?binary|unisex sizing)",
    "maternity":     r"(maternity|pregnan(?:t|cy)|nursing|breastfeed|breastfeeding|bump|expecting|postpartum|babywearing|bumpwear)",
    "modest":        r"(modest|hijab|abaya|kaftan|jilbab|burqa|tznius|tznua|tzniut|niqab|islamic|muslim|orthodox|jewish|christian fashion|halal[\s-]?fashion|sharia)",
    "adaptive":      r"(adaptive|disabili|wheelchair|sensory|magnetic[\s-]?closure|seated[\s-]?wear|easy[\s-]?dress|seniors|elderly[\s-]?clothing|caregiver)",
    "athleisure":    r"(athleisure|activewear|yoga[\s-]?wear|workout|gym[\s-]?wear|fitness[\s-]?wear|performance[\s-]?wear|leggings|sports?[\s-]?bra|run(?:ning)?[\s-]?wear|active[\s-]?lifestyle)",
}

# Order matters — first match wins for primary niche
NICHE_PRIORITY = [
    "modest", "adaptive", "maternity", "plus_size", "inclusive",
    "kidswear", "innerwear", "athleisure",
]

MONEY_RX = re.compile(r"[\d,\.]+")

def parse_money(s) -> float | None:
    if pd.isna(s):
        return None
    m = MONEY_RX.search(str(s).replace("USD ", "").replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:
        return None


def tag_niches(text: str) -> list[str]:
    """Return list of niche keys whose pattern hits text. Empty if none."""
    text = (text or "").lower()
    hits = []
    for key, pat in NICHE_PATTERNS.items():
        if re.search(pat, text, re.IGNORECASE):
            hits.append(key)
    return hits


def primary_niche(hits: list[str]) -> str:
    for k in NICHE_PRIORITY:
        if k in hits:
            return k
    return hits[0] if hits else ""


def is_us(loc: str) -> bool:
    if not loc:
        return False
    s = str(loc)
    return ", USA" in s or s.endswith(" US") or s.endswith(", US")


def is_shopify(plan_val, technologies_val) -> bool:
    """Storeleads provides apparel Shopify stores only; this is a safety check."""
    # All rows in this dataset are Shopify; if `plan` is set, it confirms.
    # `Shopify Plus`, `Shopify`, NaN (regular Shopify) all qualify.
    if pd.notna(plan_val):
        p = str(plan_val).lower()
        if "shopify" in p:
            return True
    tech = str(technologies_val or "").lower()
    return "shopify" in tech or True   # dataset is shopify-only


OUTPUT_COLUMNS = [
    "source", "external_id",
    "company_name", "company_domain", "company_website",
    "company_linkedin_url",
    "company_industry", "country", "state", "city",
    "estimated_monthly_sales_usd", "estimated_monthly_visits",
    "plan", "products_sold",
    "products_created_30", "products_created_90",
    "product_images_created_30", "product_images_created_90",
    "primary_category", "all_categories",
    "high_cadence",
    "emails_from_storeleads",
    "most_recent_product_title", "most_recent_product_image_url",
    "most_recent_product_url",
    "instagram_url", "tiktok_url",
    "tiktok_followers", "pinterest_followers", "twitter_followers",
    "categories_raw", "collections_raw",
    "installed_apps_names", "technologies",
]


def row_to_lead(row, hits: list[str]):
    domain = str(row.get("domain") or "").strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    pc30 = row.get("products_created_30") or 0
    pc90 = row.get("products_created_90") or 0
    try:
        pc30 = int(pc30) if pd.notna(pc30) else 0
    except Exception:
        pc30 = 0
    try:
        pc90 = int(pc90) if pd.notna(pc90) else 0
    except Exception:
        pc90 = 0
    high_cadence = (pc30 >= 10) or (pc90 >= 30)
    return {
        "source": "storeleads",
        "external_id": domain,
        "company_name": (row.get("merchant_name") or "").strip(),
        "company_domain": domain,
        "company_website": row.get("domain_url") or "",
        "company_linkedin_url": row.get("linkedin_url") or "",
        "company_industry": "DTC Fashion",
        "country": "United States",
        "state": "",
        "city": row.get("city") or "",
        "estimated_monthly_sales_usd": row.get("_mrev") or "",
        "estimated_monthly_visits": row.get("estimated_monthly_visits") or "",
        "plan": row.get("plan") or "Shopify",
        "products_sold": row.get("products_sold") or "",
        "products_created_30": pc30,
        "products_created_90": pc90,
        "product_images_created_30": row.get("product_images_created_30") or 0,
        "product_images_created_90": row.get("product_images_created_90") or 0,
        "primary_category": primary_niche(hits),
        "all_categories": "|".join(hits),
        "high_cadence": "yes" if high_cadence else "no",
        "emails_from_storeleads": row.get("emails") or "",
        "most_recent_product_title": row.get("most_recent_product_title") or "",
        "most_recent_product_image_url": row.get("most_recent_product_image_url") or "",
        "most_recent_product_url": row.get("most_recent_product_url") or "",
        "instagram_url": row.get("instagram_url") or "",
        "tiktok_url": row.get("tiktok_url") or "",
        "tiktok_followers": row.get("tiktok_followers") or "",
        "pinterest_followers": row.get("pinterest_followers") or "",
        "twitter_followers": row.get("twitter_followers") or "",
        "categories_raw": row.get("categories") or "",
        "collections_raw": row.get("collections") or "",
        "installed_apps_names": row.get("installed_apps_names") or "",
        "technologies": row.get("technologies") or "",
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matched_path  = OUT_DIR / "storeleads.csv"
    unmatched_path = OUT_DIR / "storeleads_unmatched.csv"

    if matched_path.exists():
        matched_path.unlink()
    if unmatched_path.exists():
        unmatched_path.unlink()

    use_cols = [
        "domain", "merchant_name", "company_location", "status", "plan",
        "estimated_monthly_sales", "estimated_monthly_visits",
        "collections", "most_recent_product_title", "most_recent_product_image_url",
        "most_recent_product_url", "categories", "products_sold",
        "products_created_30", "products_created_90",
        "product_images_created_30", "product_images_created_90",
        "emails", "linkedin_url", "city", "domain_url",
        "instagram_url", "tiktok_url",
        "tiktok_followers", "pinterest_followers", "twitter_followers",
        "installed_apps_names", "technologies",
    ]

    total_rows = 0
    tam_pass   = 0
    niche_pass = 0
    matched_writer = None
    unmatched_writer = None
    fmatched = open(matched_path, "w", newline="", encoding="utf-8")
    funmatched = open(unmatched_path, "w", newline="", encoding="utf-8")
    matched_writer = csv.DictWriter(fmatched, fieldnames=OUTPUT_COLUMNS)
    matched_writer.writeheader()
    unmatched_writer = csv.DictWriter(funmatched, fieldnames=OUTPUT_COLUMNS)
    unmatched_writer.writeheader()

    chunks = pd.read_csv(INPUT, chunksize=50_000, low_memory=False, usecols=use_cols)
    for chunk in chunks:
        total_rows += len(chunk)
        # 1. TAM filter
        us_mask = chunk["company_location"].astype(str).map(is_us)
        active_mask = chunk["status"].astype(str).eq("Active")
        chunk = chunk[us_mask & active_mask].copy()
        if chunk.empty:
            continue

        chunk["_mrev"] = chunk["estimated_monthly_sales"].apply(parse_money)
        in_band = chunk["_mrev"].between(REV_MIN_MONTHLY, REV_MAX_MONTHLY, inclusive="both")
        chunk = chunk[in_band].copy()
        if chunk.empty:
            continue
        tam_pass += len(chunk)

        # 2. Niche tagging
        for _, row in chunk.iterrows():
            signal_text = " | ".join([
                str(row.get("merchant_name") or ""),
                str(row.get("collections") or ""),
                str(row.get("most_recent_product_title") or ""),
                str(row.get("domain") or ""),
                str(row.get("categories") or ""),
            ])
            hits = tag_niches(signal_text)
            lead = row_to_lead(row, hits)
            if hits:
                matched_writer.writerow(lead)
                niche_pass += 1
            else:
                unmatched_writer.writerow(lead)

    fmatched.close()
    funmatched.close()

    print(f"Total Storeleads rows scanned:    {total_rows:,}")
    print(f"Passed TAM gate (US+Active+band): {tam_pass:,}")
    print(f"Passed niche keyword gate:        {niche_pass:,}")
    print(f"In-band but no niche hit:         {tam_pass - niche_pass:,}")
    print(f"\nMatched   -> {matched_path}")
    print(f"Unmatched -> {unmatched_path}")


if __name__ == "__main__":
    main()
