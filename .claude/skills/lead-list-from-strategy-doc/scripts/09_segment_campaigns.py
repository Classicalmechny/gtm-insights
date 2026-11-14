#!/usr/bin/env python3
"""
Stage 6 — Segment verified.csv into 4 campaign CSVs + add personalization fields.

Reads:
  output/<run>/verified.csv

Writes:
  output/<run>/campaigns/1_free_sample.csv      (all niche)
  output/<run>/campaigns/2_cost_per_sku.csv     (all niche)
  output/<run>/campaigns/3_representation.csv   (subset)
  output/<run>/campaigns/4_drop_velocity.csv    (subset)
  output/<run>/campaigns/all_segmented.csv      (single combined file with campaign tags)
"""
import csv, json
from pathlib import Path

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
VERIFIED = RD / "verified.csv"  # Note: now contains all email-having merged people (1301)
CDIR = RD / "campaigns"
CDIR.mkdir(parents=True, exist_ok=True)

# Map niche slug → human-readable {{category}} value used in email copy
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

REPRESENTATION_NICHES = {"plus_size","inclusive","maternity","adaptive","modest","kidswear","innerwear"}

def is_high_cadence(row):
    try:
        return int(row.get("products_created_30") or 0) >= 10 or int(row.get("products_created_90") or 0) >= 30
    except Exception:
        return False

def main():
    rows = list(csv.DictReader(VERIFIED.open(encoding="utf-8")))
    print(f"Loaded {len(rows)} verified people")

    # Add personalization fields to each row
    for r in rows:
        niche = r["primary_niche"]
        r["category_label"] = CATEGORY_LABEL.get(niche, niche.replace("_", " "))
        r["storefront_url"] = "https://" + r["company_domain"] if r["company_domain"] else ""
        r["drop_cadence"] = "high" if is_high_cadence(r) else "standard"
        r["campaigns"] = []
        # Tag campaigns
        if niche:
            r["campaigns"].append("1_free_sample")
            r["campaigns"].append("2_cost_per_sku")
        if niche in REPRESENTATION_NICHES:
            r["campaigns"].append("3_representation")
        if is_high_cadence(r):
            r["campaigns"].append("4_drop_velocity")

    fields = list(rows[0].keys()) if rows else []
    fields = [f for f in fields if f != "campaigns"] + ["campaigns_csv"]

    # Write per-campaign CSV
    def filter_by(name):
        return [r for r in rows if name in r["campaigns"]]

    counts = {}
    for name in ["1_free_sample","2_cost_per_sku","3_representation","4_drop_velocity"]:
        subset = filter_by(name)
        counts[name] = len(subset)
        p = CDIR / f"{name}.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in subset:
                out = dict(r); out["campaigns_csv"] = "|".join(r["campaigns"])
                w.writerow(out)
        print(f"  {name:20s} → {len(subset):5d} leads → {p}")

    # Combined file
    p = CDIR / "all_segmented.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = dict(r); out["campaigns_csv"] = "|".join(r["campaigns"])
            w.writerow(out)
    print(f"\nCombined → {p}")

    print("\n=== Summary ===")
    for n, c in counts.items():
        print(f"  {n}: {c}")

if __name__ == "__main__":
    main()
