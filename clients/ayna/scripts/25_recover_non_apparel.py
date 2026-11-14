#!/usr/bin/env python3
"""
Fix: recover the 7,892 'non-apparel' dropped brands that ARE actually apparel.

Root cause: my apparel-keyword filter required ≥4 collection titles to match
{"shirt", "dress", "pants", ...} — but many real DTC fashion brands name their
collections like "Spring '26", "$10 and Under", "Bestsellers", "Capsule".
Storeleads ALREADY tagged these brands as `/Apparel` — trust that.

Recovery rule:
  - Storeleads category contains /Apparel  (true for all Storeleads rows here)
  - AND at least 1 niche keyword hit in collections OR domain/merchant_name
  - AND NOT dominated by hard-non-apparel terms (jewelry, furniture, food,
    electronics, board sports gear, supplements, etc.) — use stricter
    non-apparel signal
"""
import csv, json, re, sys
from pathlib import Path
from collections import Counter

ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = ROOT / "clients/ayna/output" / RUN_ID
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
import importlib.util
spec = importlib.util.spec_from_file_location("stage2", str(ROOT / "clients/ayna/scripts/03_collections_enrich.py"))
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)
NICHE_PATTERNS = stage2.NICHE_PATTERNS
NICHE_PRIORITY = stage2.NICHE_PRIORITY

DROPPED = RD / "raw" / "storeleads_dropped.csv"
VERIFIED = RD / "raw" / "storeleads_verified.csv"
RECOVERED = RD / "raw" / "storeleads_recovered.csv"
OUT = RD / "raw" / "storeleads_non_apparel_recovered.csv"
OUT_DOMAINS = RD / "domains_for_clay/batch_v3_all_niche.csv"

# Strict non-apparel terms — if these dominate, brand is genuinely not fashion
STRICT_NON_APPAREL = {
    "necklace","necklaces","ring","rings","earring","earrings","amber","gemstone",
    "diamond","pearl","pearls","fine jewelry","engagement ring",
    "furniture","sofa","chair","table","crib","stroller","car seat","high chair",
    "candle","candles","mug","mugs","supplement","vitamin","food","snack",
    "skateboard","surfboard","wetsuit","helmet","helmets","fishing gear",
    "guitar","piano","camera","laptop","phone case","drone",
    "subscription box","gift card","ebook","course",
}
# Stronger non-apparel domain stems
STRICT_NON_APPAREL_DOMAIN = re.compile(
    r"(jewelry|jewellery|amber|gem|gold|silver|furniture|home-decor|"
    r"vitamins|supplements|food|snack|gourmet|guitar|skateboard|firearms|"
    r"camera|electronics|cigar|liquor|wine|beer|coffee|tea-shop|nutrition)",
    re.IGNORECASE,
)


def primary(niches):
    for k in NICHE_PRIORITY:
        if k in niches: return k
    return niches[0] if niches else ""


def main():
    dropped = list(csv.DictReader(DROPPED.open(encoding="utf-8")))
    verified = list(csv.DictReader(VERIFIED.open(encoding="utf-8")))
    recovered = list(csv.DictReader(RECOVERED.open(encoding="utf-8")))
    existing_domains = {r["company_domain"] for r in verified} | {r["company_domain"] for r in recovered}

    non_apparel = [r for r in dropped
                   if r.get("verification_source") == "collections.json"
                   and r.get("is_apparel") == "no"]
    print(f"Non-apparel drops to evaluate: {len(non_apparel):,}")

    fields = list(verified[0].keys()) + ["recovery_reason"]
    new_rows = []
    for r in non_apparel:
        domain = r["company_domain"]
        if not domain or domain in existing_domains: continue

        # Storeleads source = Shopify apparel only — trust the category tag (all should be apparel)
        # Now check if it has any niche signal
        merchant = (r.get("company_name") or "").lower()
        sample_titles = (r.get("sample_collection_titles") or "").lower()
        try:
            intensities = json.loads(r.get("niche_intensity_json","{}"))
        except Exception:
            intensities = {}

        # niche hits from collections OR name/domain
        name_blob = f"{merchant} {domain}"
        positive_niches = [k for k, c in intensities.items() if c >= 1]
        name_niches = [k for k, pat in NICHE_PATTERNS.items()
                       if re.search(pat, name_blob, re.IGNORECASE)]
        all_niches = list(set(positive_niches + name_niches))
        if not all_niches:
            continue

        # Strict non-apparel check on title text + domain stem
        if STRICT_NON_APPAREL_DOMAIN.search(domain):
            continue
        non_apparel_word_count = sum(1 for kw in STRICT_NON_APPAREL if kw in sample_titles)
        n_apparel_signal = int(r.get("n_apparel","0") or 0)
        n_total = int(r.get("n_collections","0") or 0) or 1
        # Hard exclude: if >40% of collections explicitly are strict-non-apparel terms
        if non_apparel_word_count >= 5 and (non_apparel_word_count / max(n_total, 1)) > 0.4:
            continue

        new = dict(r)
        new["primary_niche_verified"] = primary(all_niches)
        new["niches_detected"] = "|".join(all_niches)
        new["recovery_reason"] = "non_apparel_rescued"
        new_rows.append(new)

    print(f"Recovered (non-apparel fix): {len(new_rows):,}")
    nd = Counter(r["primary_niche_verified"] for r in new_rows)
    print(f"\nNiche distribution:")
    for k,v in nd.most_common():
        print(f"  {k:20s} {v}")

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader()
        for r in new_rows: w.writerow(r)
    print(f"\n→ {OUT}")

    # Combine with all existing niche-verified brands → new master domain list
    all_brands = {r["company_domain"]: r for r in verified}
    for r in recovered: all_brands.setdefault(r["company_domain"], r)
    for r in new_rows: all_brands.setdefault(r["company_domain"], r)
    print(f"\nTotal niche-verified brands (master TAM): {len(all_brands):,}")

    # Write expanded master domain list
    with OUT_DOMAINS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["domain","url"])
        for d in sorted(all_brands.keys()):
            w.writerow([d, f"https://{d}"])
    print(f"→ {OUT_DOMAINS}")

if __name__ == "__main__":
    main()
