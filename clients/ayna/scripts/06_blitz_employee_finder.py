#!/usr/bin/env python3
"""
Stage 4 — BlitzAPI Employee Finder.

For each domain in storeleads_verified.csv, queries BlitzAPI to find
decision-makers matching the ICP persona (Founder / CEO / Co-Founder / Owner).
No per-company cap (per Ayna ICP).

Writes output/<run>/raw/decision_makers.csv. Idempotent via checkpoint.

Per BlitzAPI docs:
  Endpoint: POST /v2/search/people  (or /people/employee-finder per old docs)
  Auth: x-api-key header
"""
import csv, json, os, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
SRC = RD / "raw" / "storeleads_verified.csv"
OUT = RD / "raw" / "decision_makers.csv"
CKPT = RD / "checkpoints" / "blitz_dm.json"
CKPT.parent.mkdir(parents=True, exist_ok=True)

BLITZ_KEY = os.environ.get("BLITZAPI_KEY", "blitz_mkbWaJvTNLHs525Aegh4W9gt")
BASE = "https://api.blitz-api.ai"

icp = json.loads((RD / "icp.json").read_text())
persona = icp["persona"]
TITLES = persona["titles"]

H = {
    "x-api-key": BLITZ_KEY,
    "Authorization": f"Bearer {BLITZ_KEY}",
    "Content-Type": "application/json",
}

FIELDS = [
    "source","external_id","sourced_from_domain",
    "first_name","last_name","full_name","title","linkedin_url",
    "company_name","company_domain","company_linkedin_url",
    "company_industry","country","state","city","raw_json",
]

def normalize_domain(s):
    if not s: return ""
    s = s.strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def normalize_person(p, src_domain):
    return {
        "source": "blitz_employee_finder",
        "external_id": p.get("id") or p.get("_id") or "",
        "sourced_from_domain": src_domain,
        "first_name": (p.get("first_name") or "").strip(),
        "last_name": (p.get("last_name") or "").strip(),
        "full_name": (p.get("full_name") or
            f'{p.get("first_name","")} {p.get("last_name","")}').strip(),
        "title": (p.get("title") or "").strip(),
        "linkedin_url": (p.get("linkedin_url") or "").strip(),
        "company_name": (p.get("company_name") or "").strip(),
        "company_domain": normalize_domain(p.get("company_domain") or p.get("company_website") or src_domain),
        "company_linkedin_url": (p.get("company_linkedin_url") or "").strip(),
        "company_industry": (p.get("company_industry") or p.get("industry") or "").strip(),
        "country": (p.get("country") or "").strip(),
        "state": (p.get("state") or p.get("region") or "").strip(),
        "city": (p.get("city") or "").strip(),
        "raw_json": json.dumps(p, ensure_ascii=False),
    }

def query_dms(domain, linkedin_url=""):
    """Query BlitzAPI v2 for decision makers at a company. Needs LinkedIn URL."""
    if not linkedin_url:
        return []
    payload = {
        "company": {
            "linkedin_url": [linkedin_url],
        },
        "people": {
            "job_title": {"include": TITLES, "exclude": []},
        },
        "max_results": 10,
    }
    try:
        r = requests.post(BASE + "/v2/search/people", json=payload, headers=H, timeout=30)
        if r.status_code == 429:
            time.sleep(3)
            return []
        if r.status_code >= 400:
            return []
        body = r.json()
        results = body.get("results") or body.get("people") or body.get("data") or []
        # Re-normalize to expected shape; BlitzAPI uses different field names
        return [_flatten(p) for p in results]
    except Exception:
        return []


def _flatten(p):
    """Flatten BlitzAPI person to the keys our normalize_person expects."""
    loc = p.get("location") or {}
    exps = p.get("experiences") or []
    cur = exps[0] if exps else {}
    return {
        "id": p.get("id") or p.get("linkedin_url",""),
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name", ""),
        "full_name": p.get("full_name", ""),
        "title": cur.get("job_title") or p.get("headline", ""),
        "linkedin_url": p.get("linkedin_url", ""),
        "company_name": cur.get("company_name", ""),
        "company_domain": cur.get("company_domain", "") or cur.get("company_website", ""),
        "company_linkedin_url": cur.get("company_linkedin_url", ""),
        "industry": cur.get("company_industry", ""),
        "country": loc.get("country_code", ""),
        "state": loc.get("state_code", ""),
        "city": loc.get("city", ""),
    }

def load_checkpoint():
    if CKPT.exists():
        try: return json.loads(CKPT.read_text())
        except Exception: return {"done_domains": []}
    return {"done_domains": []}

def save_checkpoint(state):
    CKPT.write_text(json.dumps(state))

def main():
    if not SRC.exists():
        print(f"Source file not found: {SRC}"); return
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    print(f"Loaded {len(rows):,} verified brands")

    state = load_checkpoint()
    done = set(state["done_domains"])
    queue = [r for r in rows if r["company_domain"] not in done]
    print(f"Queue: {len(queue):,} (skipping {len(done):,})")

    exists = OUT.exists()
    f = OUT.open("a" if exists else "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if not exists: w.writeheader()
    lock = __import__("threading").Lock()

    total_people = 0
    processed = 0
    t0 = time.time()

    def worker(row):
        d = row["company_domain"]
        ln = row.get("company_linkedin_url", "")
        people = query_dms(d, ln)
        return d, [normalize_person(p, d) for p in people]

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(worker, r) for r in queue]
        for fut in as_completed(futures):
            d, people = fut.result()
            with lock:
                for p in people:
                    w.writerow(p)
                if people: f.flush()
                done.add(d)
                total_people += len(people)
                processed += 1
                if processed % 50 == 0:
                    save_checkpoint({"done_domains": sorted(done)})
                    rate = processed / max(time.time()-t0, 1)
                    eta = (len(queue)-processed)/rate if rate>0 else 0
                    print(f"[{processed:>5}/{len(queue)}] DMs={total_people} @ {rate:.1f}/s, eta {eta/60:.1f}m")

    save_checkpoint({"done_domains": sorted(done)})
    f.close()
    print(f"\nDone: {total_people} DMs from {processed} companies -> {OUT}")

if __name__ == "__main__":
    main()
