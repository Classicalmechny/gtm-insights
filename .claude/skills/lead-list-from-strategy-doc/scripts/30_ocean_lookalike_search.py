#!/usr/bin/env python3
"""
Ocean.io v3 company search + lookalike (unlocked 2026-05-25 on new token).

Two modes:
  --mode lookalike --seeds cursor.com,lovable.dev,bolt.new
  --mode filter   (uses all CompaniesFiltersV3 args)

Common filters (all optional):
  --countries us,gb,ca,au           ISO 3166-1 alpha-2 codes (primaryLocations)
  --headcount-min 1 --headcount-max 25
  --revenues 1-10M,10-50M
  --industries Beauty,Lingerie      (mode=anyOf)
  --tech-apps Shopify,Klaviyo
  --keywords vibe-coding,no-code    (anyOf)
  --min-relevance A                 (for lookalike; A=highest)
  --size 100                        (per page)
  --max-total 5000                  (stop after this many)

Output: CSV with one row per company. Columns include domain, name, industries,
revenue, technologies, employee count, primary country.
"""
import csv, json, os, sys, time
from pathlib import Path
import requests

KEY = os.environ.get("OCEAN_KEY", "REDACTED_OCEAN_KEY")
URL = "https://api.ocean.io/v3/search/companies"  # NOT /preview — that's 403

FIELDS = [
    "domain","name","primary_country","countries","company_size",
    "revenue","year_founded","employee_count_linkedin","employee_count_ocean",
    "industries","industry_categories","linkedin_industry","technologies",
    "keywords","description","logo","linkedin_url","relevance_score",
]

def arg(name, default=None):
    a = sys.argv[1:]
    for i, x in enumerate(a):
        if x == f"--{name}" and i+1 < len(a): return a[i+1]
        if x.startswith(f"--{name}="): return x.split("=",1)[1]
    return default

def csv_arg(name):
    v = arg(name)
    if not v: return None
    return [s.strip() for s in v.split(",") if s.strip()]

def build_filters():
    f = {}
    if arg("mode","filter") == "lookalike":
        seeds = csv_arg("seeds")
        if not seeds: raise SystemExit("--seeds required in lookalike mode")
        f["lookalikeDomains"] = seeds
        if arg("min-relevance"): f["minRelevance"] = arg("min-relevance")
    countries = csv_arg("countries")
    if countries:
        f["primaryLocations"] = {"includeCountries": countries, "includeRegions": []}
    if arg("headcount-min") or arg("headcount-max"):
        fto = {}
        if arg("headcount-min"): fto["from"] = int(arg("headcount-min"))
        if arg("headcount-max"): fto["to"]   = int(arg("headcount-max"))
        f["employeeCountLinkedin"] = fto
    if arg("year-founded-min") or arg("year-founded-max"):
        fto = {}
        if arg("year-founded-min"): fto["from"] = int(arg("year-founded-min"))
        if arg("year-founded-max"): fto["to"]   = int(arg("year-founded-max"))
        f["yearFounded"] = fto
    revs = csv_arg("revenues")
    if revs: f["revenues"] = revs
    sizes = csv_arg("company-sizes")
    if sizes: f["companySizes"] = sizes
    inds = csv_arg("industries")
    if inds: f["industries"] = {"industries": inds, "mode": "anyOf"}
    apps = csv_arg("tech-apps")
    if apps: f["technologies"] = {"apps": {"anyOf": apps}}
    kws = csv_arg("keywords")
    if kws: f["keywords"] = {"anyOf": kws}
    incl = csv_arg("include-domains")
    if incl: f["includeDomains"] = incl
    excl = csv_arg("exclude-domains")
    if excl: f["excludeDomains"] = excl
    return f

def flatten(c):
    """Flatten a single company dict for CSV row."""
    comp = c.get("company", c)
    return {
        "domain": comp.get("domain",""),
        "name": comp.get("name","") or comp.get("domain",""),
        "primary_country": comp.get("primaryCountry",""),
        "countries": "|".join(comp.get("countries",[]) or []),
        "company_size": comp.get("companySize",""),
        "revenue": comp.get("revenue",""),
        "year_founded": comp.get("yearFounded",""),
        "employee_count_linkedin": comp.get("employeeCountLinkedin",""),
        "employee_count_ocean": comp.get("employeeCountOcean",""),
        "industries": "|".join(comp.get("industries",[]) or []),
        "industry_categories": "|".join(comp.get("industryCategories",[]) or []),
        "linkedin_industry": comp.get("linkedinIndustry",""),
        "technologies": "|".join(comp.get("technologies",[]) or [])[:500],
        "keywords": "|".join(comp.get("keywords",[]) or [])[:500],
        "description": (comp.get("description","") or "")[:1000],
        "logo": comp.get("logo",""),
        "linkedin_url": comp.get("linkedinUrl",""),
        "relevance_score": c.get("relevanceScore",""),
    }

def main():
    out = arg("out","ocean_companies.csv")
    size = int(arg("size","100"))
    max_total = int(arg("max-total","5000"))
    filters = build_filters()
    if not filters:
        raise SystemExit("No filters supplied. See script docstring.")

    f_out = open(out, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()

    search_after = None
    total_pulled = 0
    page = 0
    while total_pulled < max_total:
        body = {"size": min(size, max_total - total_pulled), "companiesFilters": filters}
        if search_after: body["searchAfter"] = search_after
        r = requests.post(f"{URL}?apiToken={KEY}", json=body, timeout=60)
        if r.status_code != 200:
            print(f"  ERROR {r.status_code}: {r.text[:300]}", file=sys.stderr); break
        j = r.json()
        rows = j.get("companies") or []
        if not rows:
            print(f"  no more results at page {page}"); break
        for c in rows:
            writer.writerow(flatten(c))
        total_pulled += len(rows)
        page += 1
        search_after = j.get("searchAfter")
        print(f"  page={page} pulled={len(rows)} total={total_pulled} of {j.get('total','?')} (credits used {j.get('creditsUsed','?')})", file=sys.stderr)
        if not search_after: break
        time.sleep(0.3)

    f_out.close()
    print(f"\n→ {out} ({total_pulled} companies)", file=sys.stderr)

if __name__ == "__main__":
    main()
