#!/usr/bin/env python3
"""
Stage 3c — Ingest Apollo CSVs (revenue + headcount), normalize, niche-tag,
and merge with existing pipeline outputs.

Inputs:
  brain/assets/ayna_apollo_revenue.csv  (3,393 leads)
  brain/assets/ayna_apollo_headcount.csv (8,783 leads)

Outputs:
  output/<run>/raw/apollo.csv  — normalized + niche-tagged
"""
import csv, json, re
from pathlib import Path
import sys

RUN_ID = "2026-05-21_ayna_niche_fashion"
ROOT = Path("/Users/anirudhgupta1177/Antigravity/Personal Assistant")
RD = ROOT / "clients/ayna/output" / RUN_ID
OUT = RD / "raw" / "apollo.csv"
APOLLO_FILES = [
    ROOT / "brain/assets/ayna_apollo_revenue.csv",
    ROOT / "brain/assets/ayna_apollo_headcount.csv",
]

# Reuse Stage 2 niche detection for collection-style text matching
# Apply against company "Keywords" field which Apollo populates with category words
sys.path.insert(0, str(ROOT / "clients/ayna/scripts"))
import importlib.util
spec = importlib.util.spec_from_file_location("stage2", str(ROOT / "clients/ayna/scripts/03_collections_enrich.py"))
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)

NICHE_PATTERNS = stage2.NICHE_PATTERNS
NICHE_PRIORITY = stage2.NICHE_PRIORITY

def normalize_domain(s):
    if not s: return ""
    s = str(s).strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def tag_niches_from_text(text):
    text = (text or "").lower()
    hits = []
    for k, p in NICHE_PATTERNS.items():
        if re.search(p, text, re.IGNORECASE):
            hits.append(k)
    return hits

def primary(niches):
    for k in NICHE_PRIORITY:
        if k in niches: return k
    return niches[0] if niches else ""

FIELDS = [
    "source","first_name","last_name","full_name","title","linkedin_url",
    "email","email_verification_status",
    "company_name","company_domain","company_linkedin_url","company_website",
    "primary_niche","all_niches","is_multi_brand_retailer",
    "monthly_revenue_usd","plan","products_created_30","products_created_90",
    "high_cadence","most_recent_product_title","most_recent_product_image_url",
    "most_recent_product_url","instagram_url","tiktok_url",
    "city","state","country","email_source",
    "annual_revenue_usd","employee_count","industry","keywords","technologies",
]

# Acceptable titles per ICP (loose match — substring)
ACCEPTABLE_TITLES_RX = re.compile(
    r"(founder|cofounder|co.?founder|chief executive|\bceo\b|owner|president|managing director|principal)",
    re.IGNORECASE,
)

def normalize_lead(row, source_label):
    title = str(row.get("Title") or "").strip()
    if not ACCEPTABLE_TITLES_RX.search(title):
        return None
    domain = normalize_domain(row.get("Website") or row.get("Company Linkedin Url") or "")
    if not domain:
        return None
    keywords = str(row.get("Keywords") or "")
    industry = str(row.get("Industry") or "")
    company_name = str(row.get("Company Name") or "").strip()
    niche_text = " | ".join([keywords, industry, company_name, domain])
    niches = tag_niches_from_text(niche_text)
    if not niches:
        return None  # drop non-niche leads — same filter we apply elsewhere
    annual_rev = row.get("Annual Revenue")
    try:
        annual_rev_v = float(annual_rev) if annual_rev else 0
    except Exception:
        annual_rev_v = 0
    email = str(row.get("Email") or "").strip().lower()
    email_status = str(row.get("Email Status") or "").strip().lower()
    if email_status not in ("valid","accept_all","accept-all","accept all"):
        if email_status not in ("valid","",None,"nan"):
            # invalid / bounced — drop email but keep lead for re-enrichment
            email = ""
            email_status = ""

    return {
        "source": source_label,
        "first_name": str(row.get("First Name","") or "").strip(),
        "last_name": str(row.get("Last Name","") or "").strip(),
        "full_name": f'{row.get("First Name","")} {row.get("Last Name","")}'.strip(),
        "title": title,
        "linkedin_url": str(row.get("Person Linkedin Url","") or row.get("Contact LinkedIn Profile","") or ""),
        "email": email,
        "email_verification_status": email_status if email else "",
        "company_name": company_name,
        "company_domain": domain,
        "company_linkedin_url": str(row.get("Company Linkedin Url","") or row.get("Company LinkedIn Profile","") or ""),
        "company_website": str(row.get("Website","") or ""),
        "primary_niche": primary(niches),
        "all_niches": "|".join(niches),
        "is_multi_brand_retailer": "no",
        "monthly_revenue_usd": "",
        "plan": "",
        "products_created_30": "0",
        "products_created_90": "0",
        "high_cadence": "no",
        "most_recent_product_title": "",
        "most_recent_product_image_url": "",
        "most_recent_product_url": "",
        "instagram_url": "",
        "tiktok_url": "",
        "city": str(row.get("City","") or "").strip(),
        "state": str(row.get("State","") or "").strip(),
        "country": str(row.get("Country","") or "United States").strip(),
        "email_source": "apollo_pre_verified" if email else "",
        "annual_revenue_usd": annual_rev_v if annual_rev_v else "",
        "employee_count": row.get("# Employees","") or "",
        "industry": industry,
        "keywords": keywords,
        "technologies": str(row.get("Technologies","") or "")[:500],
    }

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fout = OUT.open("w", newline="", encoding="utf-8")
    w = csv.DictWriter(fout, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    n_total = 0
    n_kept = 0
    n_by_source = {}
    seen = set()  # dedupe by (email or linkedin or first+last+domain)
    for src in APOLLO_FILES:
        label = "apollo_" + src.stem.replace("ayna_apollo_","")
        with src.open(encoding="utf-8", errors="replace") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                n_total += 1
                norm = normalize_lead(row, label)
                if not norm: continue
                key = norm["email"] or norm["linkedin_url"] or f'{norm["first_name"]}|{norm["last_name"]}|{norm["company_domain"]}'.lower()
                if key in seen: continue
                seen.add(key)
                w.writerow(norm)
                n_kept += 1
                n_by_source[label] = n_by_source.get(label, 0) + 1
    fout.close()
    print(f"Apollo ingest: scanned {n_total:,} rows, kept {n_kept:,} niche-tagged leads")
    for k,v in n_by_source.items():
        print(f"  {k}: {v}")
    print(f"→ {OUT}")

if __name__ == "__main__":
    main()
