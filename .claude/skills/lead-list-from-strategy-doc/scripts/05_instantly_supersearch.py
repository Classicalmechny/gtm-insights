#!/usr/bin/env python3
"""
Stage 3b — Instantly Supersearch (Shopify-tech-filtered).

Confirmed via testing (2026-05-21):
- `technologies: ["Shopify"]` IS a valid (undocumented) search_filter that filters
  results to Shopify-running companies. Verified 95% of returned domains expose
  /collections.json (Shopify endpoint) on a 20-lead test.
- `subIndustry: {"include": ["Apparel & Fashion"]}` narrows to fashion brands.
- `locations` requires Google Place ID; US is `ChIJCzYy5IS16lQRQrfeQ5K5Oxw`.
- Auth is `Authorization: Bearer <key>` (not Basic).

Writes output/<run>/raw/instantly.csv
"""
import csv, json, os, time
from pathlib import Path
import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
OUT = RD / "raw" / "instantly.csv"
CKPT = RD / "checkpoints" / "instantly.json"
CKPT.parent.mkdir(parents=True, exist_ok=True)

INSTANTLY_KEY = os.environ.get("INSTANTLY_KEY",
    "REDACTED_INSTANTLY_KEY")
BASE = "https://api.instantly.ai"

MAX_LEADS = int(os.environ.get("INSTANTLY_MAX", "2000"))
POLL_INTERVAL = 30

icp = json.loads((RD / "icp.json").read_text())
firmo = icp["firmographics"]
persona = icp["persona"]

H = {"Authorization": f"Bearer {INSTANTLY_KEY}", "Content-Type": "application/json"}

# Google Place ID for "United States"
US_PLACE_ID = "ChIJCzYy5IS16lQRQrfeQ5K5Oxw"

SEARCH_FILTERS = {
    "industry": {"include": ["Retail"]},
    "subIndustry": {"include": ["Apparel & Fashion"]},
    "title": {"include": persona["titles"], "exclude": []},
    "employeeCount": ["0 - 25", "25 - 100"],
    "technologies": firmo["tech_stack_includes"],   # ← undocumented but works
    "locations": [{"label": "United States", "place_id": US_PLACE_ID}],
}

FIELDS = [
    "source","external_id","first_name","last_name","full_name",
    "title","linkedin_url","email","email_verification_status",
    "company_name","company_domain","company_linkedin_url",
    "company_industry","company_employee_count","country","state","city",
    "enriched_at","raw_json",
]

def normalize_domain(s):
    if not s: return ""
    s = s.strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")

def normalize(l):
    return {
        "source": "instantly_supersearch",
        "external_id": l.get("id") or "",
        "first_name": (l.get("first_name") or "").strip(),
        "last_name": (l.get("last_name") or "").strip(),
        "full_name": (l.get("full_name") or
            f'{l.get("first_name","")} {l.get("last_name","")}').strip(),
        "title": (l.get("title") or l.get("job_title") or "").strip(),
        "linkedin_url": (l.get("linkedin_url") or "").strip(),
        "email": (l.get("email") or l.get("work_email") or "").strip().lower(),
        "email_verification_status": (
            l.get("email_verification_status") or l.get("verification_status") or ""
        ).lower(),
        "company_name": (l.get("company_name") or l.get("organization_name") or "").strip(),
        "company_domain": normalize_domain(
            l.get("company_domain") or l.get("organization_website") or ""),
        "company_linkedin_url": (l.get("company_linkedin_url") or
            l.get("organization_linkedin_url") or "").strip(),
        "company_industry": (l.get("company_industry") or l.get("industry") or "").strip(),
        "company_employee_count": (l.get("company_employee_count") or l.get("employee_count") or ""),
        "country": (l.get("country") or "").strip(),
        "state": (l.get("state") or "").strip(),
        "city": (l.get("city") or "").strip(),
        "enriched_at": l.get("timestamp_updated") or l.get("enriched_at") or "",
        "raw_json": json.dumps(l, ensure_ascii=False),
    }

def main():
    state = json.loads(CKPT.read_text()) if CKPT.exists() else {
        "list_id": None, "cursor": None, "total": 0, "enrichment_submitted": False
    }

    # 1. Submit enrichment job (auto-creates list)
    if not state.get("enrichment_submitted"):
        payload = {
            "search_filters": SEARCH_FILTERS,
            "limit": MAX_LEADS,
            "search_name": f"AYNA_{RUN_ID}",
            "list_name": f"AYNA_{RUN_ID}",
            "work_email_enrichment": True,
            "fully_enriched_profile": True,
        }
        r = requests.post(f"{BASE}/api/v2/supersearch-enrichment/enrich-leads-from-supersearch",
                          json=payload, headers=H, timeout=60)
        if r.status_code >= 400:
            print(f"submit ERROR {r.status_code}: {r.text[:500]}"); return
        body = r.json()
        state["list_id"] = body["resource_id"]
        state["enrichment_submitted"] = True
        CKPT.write_text(json.dumps(state))
        print(f"Submitted: resource_id={state['list_id']}  job_id={body['id']}")

    list_id = state["list_id"]

    # 2. Poll until completed (cap at 90 minutes)
    print("Polling enrichment status…")
    t0 = time.time()
    last_status = None
    while True:
        if time.time() - t0 > 90 * 60:
            print("Poll timeout — moving on to list leads anyway")
            break
        try:
            r = requests.get(f"{BASE}/api/v2/supersearch-enrichment/get-enrichment-for-resource",
                params={"resource_id": list_id, "resource_type": "lead-list"},
                headers=H, timeout=30)
            if r.status_code == 400:
                # The polling endpoint has UUID validation quirks; try alternative
                break
            body = r.json()
            status = (body.get("status") or body.get("state") or "").lower()
            progress = body.get("progress")
            if status != last_status:
                print(f"  [{int(time.time()-t0)}s] status={status} progress={progress}")
                last_status = status
            if status in ("completed","complete","done","finished"): break
            if status in ("failed","cancelled","error"):
                print(f"FAILED: {json.dumps(body)[:300]}"); return
        except Exception as e:
            print(f"  poll exception: {e}")
        time.sleep(POLL_INTERVAL)

    # 3. Paginate via POST /leads/list (NOT GET)
    exists = OUT.exists()
    f = OUT.open("a" if exists else "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    if not exists: w.writeheader()

    cursor = state.get("cursor")
    total = state.get("total", 0)
    page = 0
    while True:
        body = {"list_id": list_id, "limit": 100}
        if cursor: body["starting_after"] = cursor
        r = requests.post(f"{BASE}/api/v2/leads/list", json=body, headers=H, timeout=60)
        if r.status_code >= 400:
            print(f"list_leads ERROR {r.status_code}: {r.text[:300]}"); break
        body_j = r.json()
        leads = body_j.get("items") or body_j.get("leads") or body_j.get("data") or []
        if not leads:
            print(f"  no more leads at page {page}"); break
        for l in leads:
            w.writerow(normalize(l))
        total += len(leads)
        f.flush()
        cursor = body_j.get("next_starting_after") or body_j.get("next_cursor")
        state["cursor"] = cursor; state["total"] = total
        CKPT.write_text(json.dumps(state))
        page += 1
        print(f"  page={page} wrote={len(leads)} total={total}")
        if not cursor or len(leads) < 100: break

    f.close()
    print(f"\nDone: {total} leads → {OUT}")

if __name__ == "__main__":
    main()
