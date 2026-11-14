#!/usr/bin/env python3
"""
Stage 1 sample-pull: stratify 20 leads across niche categories for validation.

Output:
  output/<run_id>/sample_20.csv         — the 20 leads + ICP-validation columns
  output/<run_id>/sample_20_pretty.md   — markdown table the user can review
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from collections import defaultdict

RUN_ID = "2026-05-21_ayna_niche_fashion"
SRC    = Path("output") / RUN_ID / "raw" / "storeleads.csv"
OUT    = Path("output") / RUN_ID / "sample_20.csv"
OUT_MD = Path("output") / RUN_ID / "sample_20_pretty.md"
N      = 20
SEED   = 21

random.seed(SEED)

def main():
    rows = []
    with SRC.open(encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            rows.append(row)
    print(f"Loaded {len(rows):,} niche-tagged brands.")

    # Group by primary category
    buckets = defaultdict(list)
    for r in rows:
        buckets[r["primary_category"] or "uncategorized"].append(r)

    # Target distribution: proportional but cap each niche so we get diversity.
    # Sample at least 1 from each non-empty niche, then proportional fill.
    sample = []
    niches = sorted(buckets.keys())
    print(f"Niches present: {dict((k, len(v)) for k, v in buckets.items())}")

    # 1 mandatory from each niche
    for k in niches:
        pool = buckets[k]
        if pool:
            sample.append(random.choice(pool))

    # Proportional fill for the remainder
    remaining = N - len(sample)
    if remaining > 0:
        weighted = []
        for k in niches:
            weighted.extend(buckets[k] * 1)  # weight by count
        # Avoid duplicates already in sample
        chosen_domains = {s["company_domain"] for s in sample}
        pool = [r for r in weighted if r["company_domain"] not in chosen_domains]
        random.shuffle(pool)
        sample.extend(pool[:remaining])

    # Deduplicate by domain (keep first)
    seen = set()
    dedup = []
    for s in sample:
        d = s["company_domain"]
        if d in seen: continue
        seen.add(d)
        dedup.append(s)
    sample = dedup[:N]

    # Sort by niche for readability
    sample.sort(key=lambda r: (r["primary_category"], r["company_name"]))

    fields = list(sample[0].keys()) + [
        "v1_us_dtc",          # to fill
        "v2_revenue_band",    # to fill
        "v3_niche_correct",   # to fill
        "v4_on_model_pdp",    # to fill
        "validation_pass",    # to fill
        "notes",              # to fill
    ]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sample:
            row = dict(r)
            row.update({k: "" for k in fields if k not in row})
            w.writerow(row)
    print(f"Wrote {len(sample)} samples -> {OUT}")

    # Pretty markdown table
    lines = [
        "# Ayna ICP Validation — 20 Sample Leads",
        "",
        "Each row needs:",
        "- v1 US-based DTC fashion ✓",
        "- v2 Monthly revenue $50K-$1.5M (≈$0.6M-$18M annual) ✓",
        "- v3 Niche category correct ✓",
        "- v4 On-model imagery on PDPs ✓",
        "",
        "| # | Niche | Brand | Domain | Monthly $ | Plan | Drop30 | PDP image URL |",
        "|---|-------|-------|--------|-----------|------|--------|---------------|",
    ]
    for i, r in enumerate(sample, 1):
        mr = r.get("estimated_monthly_sales_usd", "") or ""
        try:
            mr_fmt = f"${int(float(mr)):,}" if mr else ""
        except Exception:
            mr_fmt = mr
        lines.append(
            f"| {i} | {r['primary_category']} | {r['company_name']} | "
            f"{r['company_domain']} | {mr_fmt} | {r['plan']} | "
            f"{r['products_created_30']} | {r['most_recent_product_image_url'][:80]} |"
        )
    OUT_MD.write_text("\n".join(lines))
    print(f"Wrote pretty table -> {OUT_MD}")

if __name__ == "__main__":
    main()
