#!/usr/bin/env python3
"""
Ocean.io brand enrichment.
Takes a list of domains (typically from storeleads_verified or storeleads_recovered),
calls v2/lookup/companies in batches, and writes Ocean.io industries + tech + size + revenue.

Used to:
  1. Reclassify niche tags when regex was uncertain
  2. Fill /collections.json fallback when blocked
  3. Add metadata (revenue, size, year founded) to brands missing it

Usage:
  python 29_ocean_enrich.py --input <path> --domain-col company_domain --output <path>
  (defaults: input=output/<run_id>/raw/storeleads_verified.csv, output=output/<run_id>/raw/ocean_enriched.csv)
"""
import csv, json, os, sys, time
from pathlib import Path
import requests

OCEAN_KEY = os.environ.get("OCEAN_KEY", "REDACTED_OCEAN_KEY")
BATCH = 100  # lookup batch size

# Map Ocean.io industry strings → our niche taxonomy
INDUSTRY_TO_NICHE = {
    # Innerwear / Lingerie
    "lingerie": "innerwear", "intimates": "innerwear", "shapewear": "innerwear",
    "sleepwear": "innerwear",
    # Plus size
    "plus size": "plus_size", "plus-size": "plus_size", "curvy": "plus_size",
    # Inclusive
    "size inclusive": "inclusive", "body positive": "inclusive",
    "gender neutral": "inclusive",
    # Maternity
    "maternity": "maternity", "pregnancy": "maternity", "nursing": "maternity",
    # Modest
    "modest fashion": "modest", "modest": "modest", "hijab": "modest", "abaya": "modest",
    "islamic clothing": "modest", "muslim fashion": "modest",
    # Adaptive
    "adaptive": "adaptive", "disability": "adaptive", "accessible fashion": "adaptive",
    # Athleisure
    "athleisure": "athleisure", "activewear": "athleisure", "sportswear": "athleisure",
    "yoga": "athleisure",
    # Kidswear
    "childrenswear": "kidswear", "children's": "kidswear", "kids": "kidswear",
    "baby clothing": "kidswear", "babywear": "kidswear", "toddler": "kidswear",
}

# Strong non-fashion signals → drop brand from TAM
NON_FASHION_INDUSTRIES = {
    "cosmetics", "beauty", "skincare", "fragrance",
    "food", "beverage", "snacks",
    "supplements", "wellness", "fitness equipment",
    "jewelry", "fine jewelry",
    "furniture", "home decor",
    "electronics", "consumer electronics", "gadgets",
    "automotive", "outdoor gear", "sporting goods",
}


def lookup_batch(domains):
    """Call Ocean.io v2/lookup/companies. Returns list of company dicts."""
    url = f"https://api.ocean.io/v2/lookup/companies?apiToken={OCEAN_KEY}"
    try:
        r = requests.post(url, json={"domains": list(domains)}, timeout=60)
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post(url, json={"domains": list(domains)}, timeout=60)
        if r.status_code == 200:
            return r.json().get("companies", [])
    except Exception as e:
        print(f"  err: {e}")
    return []


def derive_niches(industries):
    """Map Ocean.io industries array to our niche taxonomy."""
    if not industries: return []
    s = " | ".join(str(i).lower() for i in industries)
    niches = []
    for kw, niche in INDUSTRY_TO_NICHE.items():
        if kw in s and niche not in niches:
            niches.append(niche)
    return niches


def is_non_fashion(industries):
    """Return True if Ocean.io tags suggest the brand is NOT fashion."""
    if not industries: return False
    s = " | ".join(str(i).lower() for i in industries)
    # If "fashion" / "apparel" / "clothing" appears, treat as fashion
    if any(t in s for t in ["fashion","apparel","clothing","retail"]):
        return False
    # If a strong non-fashion industry dominates
    return any(t in s for t in NON_FASHION_INDUSTRIES)


def parse_args():
    args = sys.argv[1:]
    cfg = {"input": None, "output": None, "domain_col": "company_domain"}
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--input","-i"): cfg["input"] = args[i+1]; i += 2
        elif a in ("--output","-o"): cfg["output"] = args[i+1]; i += 2
        elif a in ("--domain-col",): cfg["domain_col"] = args[i+1]; i += 2
        else: i += 1
    return cfg


def main():
    cfg = parse_args()
    if not cfg["input"]:
        print("Usage: python 29_ocean_enrich.py --input <csv> [--output <csv>] [--domain-col company_domain]")
        return
    inp = Path(cfg["input"])
    out = Path(cfg["output"]) if cfg["output"] else inp.with_name(inp.stem + "_ocean.csv")

    rows = list(csv.DictReader(inp.open(encoding="utf-8")))
    domains = sorted({r[cfg["domain_col"]].lower().strip() for r in rows if r.get(cfg["domain_col"])})
    print(f"Loaded {len(rows)} rows, {len(domains)} unique domains")

    # Batch lookup
    domain_to_data = {}
    for i in range(0, len(domains), BATCH):
        chunk = domains[i:i+BATCH]
        companies = lookup_batch(chunk)
        for c in companies:
            d = c.get("domain","").lower().strip()
            if d: domain_to_data[d] = c
        print(f"  batch {i//BATCH + 1}: requested {len(chunk)}, got {len([c for c in companies if c.get('domain','').lower() in chunk])}")
        time.sleep(0.5)

    # Augment rows
    fields = list(rows[0].keys()) + [
        "ocean_industries", "ocean_industry_categories",
        "ocean_company_size", "ocean_revenue", "ocean_year_founded",
        "ocean_technologies", "ocean_primary_country",
        "ocean_derived_niches", "ocean_is_non_fashion",
    ]
    n_enriched = 0
    n_niche_added = 0
    n_non_fashion = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            d = r.get(cfg["domain_col"],"").lower().strip()
            c = domain_to_data.get(d)
            if c:
                n_enriched += 1
                industries = c.get("industries", []) or []
                derived = derive_niches(industries)
                non_fashion = is_non_fashion(industries)
                if derived: n_niche_added += 1
                if non_fashion: n_non_fashion += 1
                r["ocean_industries"] = "|".join(industries)
                r["ocean_industry_categories"] = "|".join(c.get("industryCategories", []) or [])
                r["ocean_company_size"] = c.get("companySize","")
                r["ocean_revenue"] = c.get("revenue","")
                r["ocean_year_founded"] = c.get("yearFounded","")
                r["ocean_technologies"] = "|".join(c.get("technologies", []) or [])
                r["ocean_primary_country"] = c.get("primaryCountry","")
                r["ocean_derived_niches"] = "|".join(derived)
                r["ocean_is_non_fashion"] = "yes" if non_fashion else "no"
            w.writerow(r)
    print(f"\nOcean.io enriched: {n_enriched}/{len(rows)} ({100*n_enriched/max(len(rows),1):.0f}%)")
    print(f"  with derived niche tags: {n_niche_added}")
    print(f"  flagged as non-fashion: {n_non_fashion}")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
