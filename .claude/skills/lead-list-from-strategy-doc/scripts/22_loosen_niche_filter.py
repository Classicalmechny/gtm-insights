#!/usr/bin/env python3
"""
Efficiency Gain C: loosen Stage 2 niche filter and recover dropped brands.

Reads raw/storeleads_dropped.csv (21,563 brands), identifies those that:
  - had /collections.json data
  - are apparel-focused
  - had at least 1 niche keyword hit in collections OR in merchant_name/domain
    (vs previous threshold of 3 hits AND 10%+)
Adds them to a new raw/storeleads_recovered.csv.

This recovers ~5,000 weak-signal brands. They'll need Apollo/Clay/Blitz queries
against their domains to find people.
"""
import csv, json, re
from pathlib import Path
from collections import Counter

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
DROPPED = RD / "raw" / "storeleads_dropped.csv"
VERIFIED = RD / "raw" / "storeleads_verified.csv"
OUT_RECOVERED = RD / "raw" / "storeleads_recovered.csv"
OUT_ALL_DOMAINS = RD / "domains_for_clay" / "batch_v2_all_niche.csv"

# Same niche patterns as Stage 2
import importlib.util, sys
spec = importlib.util.spec_from_file_location("stage2", "scripts/03_collections_enrich.py")
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)
NICHE_PATTERNS = stage2.NICHE_PATTERNS
NICHE_PRIORITY = stage2.NICHE_PRIORITY

def primary(niches):
    for k in NICHE_PRIORITY:
        if k in niches: return k
    return niches[0] if niches else ""

def main():
    dropped = list(csv.DictReader(DROPPED.open(encoding="utf-8")))
    verified = list(csv.DictReader(VERIFIED.open(encoding="utf-8")))
    verified_domains = {r["company_domain"] for r in verified}
    print(f"Dropped: {len(dropped):,}")

    recovered = []
    for r in dropped:
        # Re-evaluate with looser threshold
        if r.get("verification_source") != "collections.json": continue
        if r.get("is_apparel") != "yes": continue
        try:
            intensities = json.loads(r.get("niche_intensity_json", "{}"))
        except Exception:
            continue
        if not intensities: continue

        # Loosen: ≥1 niche hit (was ≥3); OR name/domain match
        positive_niches = [k for k, c in intensities.items() if c >= 1]
        merchant = (r.get("company_name") or "").lower()
        domain = (r.get("company_domain") or "").lower()
        name_blob = f"{merchant} {domain}"
        name_match_niches = [k for k, pat in NICHE_PATTERNS.items()
                              if re.search(pat, name_blob, re.IGNORECASE)]
        all_niches = list(set(positive_niches + name_match_niches))
        if not all_niches: continue

        # Additional safety: drop if explicitly multi-brand retailer with no niche in name
        # (kept-per-user but let's flag)
        # Stay liberal — let downstream segmentation decide.

        new = dict(r)
        new["primary_niche_verified"] = primary(all_niches)
        new["niches_detected"] = "|".join(all_niches)
        new["recovery_reason"] = "loosened_filter"
        recovered.append(new)

    print(f"Recovered (looser filter): {len(recovered):,}")
    if not recovered: return

    # Niche distribution
    nd = Counter(r["primary_niche_verified"] for r in recovered)
    print(f"\nRecovered niche distribution:")
    for k,v in nd.most_common():
        print(f"  {k:20s} {v}")

    # Write recovered file with same schema as verified
    fields = list(verified[0].keys()) + ["recovery_reason"]
    with OUT_RECOVERED.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for r in recovered: w.writerow(r)
    print(f"\n→ {OUT_RECOVERED}")

    # Build domain export with verified + recovered (deduped)
    all_domains = sorted(verified_domains | {r["company_domain"] for r in recovered if r["company_domain"]})
    print(f"\nCombined unique domains (verified+recovered): {len(all_domains):,}")
    with OUT_ALL_DOMAINS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["domain","url"])
        for d in all_domains: w.writerow([d, f"https://{d}"])
    print(f"→ {OUT_ALL_DOMAINS}")

if __name__ == "__main__":
    main()
