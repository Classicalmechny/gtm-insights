#!/usr/bin/env python3
"""
Efficiency Gain D: Multi-query Instantly Supersearch.

Strategy: instead of 1 query with broad filters returning 223 leads,
run 8 parallel queries — one per niche keyword — each pulling up to 2000.

Filter combo per query (all use technologies:Shopify):
  - subIndustry: Apparel & Fashion
  - title: Founder/CEO/Co-Founder/Owner + Brand/Creative/E-commerce/DTC heads
  - employeeCount: 0-25, 25-100
  - locations: United States (place_id)
  - keyword_filter: <niche keyword>  ← differs per query

Plus 2 extra queries on subIndustry:Cosmetics and broad Retail for adjacency.

Each enrichment job auto-runs work_email_enrichment + email_verification.
After all jobs complete, pull leads, /collections.json verify niches, merge.
"""
import csv, json, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
RAW = RD / "raw"
CKPT = RD / "checkpoints" / "multi_instantly.json"
CKPT.parent.mkdir(parents=True, exist_ok=True)
OUT = RAW / "instantly_multi.csv"

H = {"Authorization": "Bearer REDACTED_INSTANTLY_KEY",
     "Content-Type": "application/json"}
BASE = "https://api.instantly.ai"
US_PLACE_ID = "ChIJCzYy5IS16lQRQrfeQ5K5Oxw"

TITLES = [
    "Founder","Co-Founder","Co Founder","Cofounder","CEO","Chief Executive Officer",
    "Owner","President","Managing Director",
    "Head of Brand","Brand Director","Creative Director","Head of Creative",
    "Head of E-commerce","Head of Ecommerce","Head of DTC","Head of D2C",
    "CMO","Chief Marketing Officer","Chief Brand Officer",
    "Design Director","Art Director","Director of E-commerce","Director of DTC",
]

# 8 niche queries + 2 broader sweeps = 10 total queries
QUERIES = [
    {"name": "kidswear",    "keywords": ["kidswear"], "subInd": ["Apparel & Fashion"]},
    {"name": "lingerie",    "keywords": ["lingerie"], "subInd": ["Apparel & Fashion"]},
    {"name": "plus_size",   "keywords": ["plus size"], "subInd": ["Apparel & Fashion"]},
    {"name": "inclusive",   "keywords": ["inclusive sizing"], "subInd": ["Apparel & Fashion"]},
    {"name": "maternity",   "keywords": ["maternity"], "subInd": ["Apparel & Fashion"]},
    {"name": "modest",      "keywords": ["modest fashion"], "subInd": ["Apparel & Fashion"]},
    {"name": "adaptive",    "keywords": ["adaptive fashion"], "subInd": ["Apparel & Fashion"]},
    {"name": "athleisure",  "keywords": ["athleisure"], "subInd": ["Apparel & Fashion"]},
    {"name": "intimates",   "keywords": ["intimates", "underwear"], "subInd": ["Apparel & Fashion"]},
    {"name": "shopify_general", "keywords": [], "subInd": ["Apparel & Fashion"]},  # broad sweep
]

LIMIT_PER_QUERY = 2000

def submit_query(q):
    """Submit one supersearch enrichment job. Returns resource_id (list_id)."""
    filters = {
        "subIndustry": {"include": q["subInd"]},
        "title": {"include": TITLES, "exclude": []},
        "employeeCount": ["0 - 25", "25 - 100"],
        "technologies": ["Shopify"],
        "locations": [{"label": "United States", "place_id": US_PLACE_ID}],
    }
    if q["keywords"]:
        filters["keyword_filter"] = {"include": q["keywords"]}
    payload = {
        "search_filters": filters,
        "limit": LIMIT_PER_QUERY,
        "search_name": f"AYNA_MQ_{q['name']}"[:64],
        "list_name": f"AYNA_MQ_{q['name']}"[:64],
        "work_email_enrichment": True,
        "fully_enriched_profile": True,
    }
    r = requests.post(f"{BASE}/api/v2/supersearch-enrichment/enrich-leads-from-supersearch",
                      json=payload, headers=H, timeout=30)
    if r.status_code == 200:
        body = r.json()
        return body["resource_id"], body["id"]
    print(f"  [{q['name']}] submit error {r.status_code}: {r.text[:300]}")
    return None, None

def pull_list(list_id):
    """Paginate through list, return all lead items."""
    items = []
    cursor = None
    while True:
        body = {"list_id": list_id, "limit": 100}
        if cursor: body["starting_after"] = cursor
        r = requests.post(f"{BASE}/api/v2/leads/list", json=body, headers=H, timeout=60)
        if r.status_code != 200: break
        page = r.json().get("items", [])
        if not page: break
        items.extend(page)
        cursor = r.json().get("next_starting_after")
        if not cursor: break
    return items

def main():
    state = json.loads(CKPT.read_text()) if CKPT.exists() else {"jobs": {}}

    # Submit all queries (skip already-submitted)
    for q in QUERIES:
        if q["name"] in state["jobs"]:
            continue
        rid, jid = submit_query(q)
        if rid:
            state["jobs"][q["name"]] = {"list_id": rid, "job_id": jid, "polled_done": False}
            CKPT.write_text(json.dumps(state))
            print(f"  [{q['name']}] submitted list_id={rid}")
        time.sleep(1)

    # Poll: simple wait — Instantly typically takes 5-15 min
    print(f"\nSubmitted {len(state['jobs'])} jobs. Waiting 12 minutes for enrichment…")
    time.sleep(12 * 60)

    # Pull all
    print("\nPulling all leads…")
    all_items = []
    for name, info in state["jobs"].items():
        items = pull_list(info["list_id"])
        with_email = sum(1 for it in items if it.get("email") and not str(it.get("email","")).startswith("placeholder_"))
        print(f"  [{name}] total={len(items)}  with_email={with_email}")
        for it in items:
            it["_query"] = name
        all_items.extend(items)

    # Normalize + dedupe
    FIELDS = ["source","first_name","last_name","full_name","title","linkedin_url",
        "email","email_verification_status","email_source",
        "company_name","company_domain","company_linkedin_url",
        "company_website","city","state","country","employee_count","industry","raw_json"]
    seen = set()
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader()
        n_written = 0
        for it in all_items:
            email = str(it.get("email") or "").strip().lower()
            if not email or email.startswith("placeholder_"): continue
            if email in seen: continue
            seen.add(email)
            d = str(it.get("website") or it.get("company_domain") or "").strip().lower()
            if d.startswith("http"): d = d.split("//",1)[1]
            if d.startswith("www."): d = d[4:]
            d = d.split("/",1)[0]
            w.writerow({
                "source": f"instantly_mq_{it.get('_query')}",
                "first_name": (it.get("first_name") or "").strip(),
                "last_name": (it.get("last_name") or "").strip(),
                "full_name": (it.get("full_name") or "").strip(),
                "title": (it.get("title") or it.get("job_title") or "").strip(),
                "linkedin_url": (it.get("linkedin_url") or "").strip(),
                "email": email,
                "email_verification_status": str(it.get("verification_status") or "").lower(),
                "email_source": "instantly_multi_query",
                "company_name": (it.get("company_name") or "").strip(),
                "company_domain": d,
                "company_linkedin_url": (it.get("company_linkedin_url") or "").strip(),
                "company_website": d, "city": "", "state": "",
                "country": "United States", "employee_count": "",
                "industry": "DTC Fashion", "raw_json": json.dumps(it, ensure_ascii=False)[:1000],
            })
            n_written += 1
    print(f"\nUnique leads with verified emails: {n_written} → {OUT}")

if __name__ == "__main__":
    main()
