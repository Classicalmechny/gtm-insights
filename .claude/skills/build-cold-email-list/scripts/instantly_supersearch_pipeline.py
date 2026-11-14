#!/usr/bin/env python3
"""
Instantly Supersearch — Sourcing + Email Enrichment Pipeline.

Process:
  1. Create a new Instantly lead-list.
  2. Submit a supersearch enrichment job (sourcing + work email + verify).
  3. Poll until completed.
  4. Paginate /leads/list and write raw/instantly.csv.

Idempotent — persists `list_id` so re-runs continue from the same list.

Usage:
  python instantly_supersearch_pipeline.py --run-id 2026-05-14_1330_xxx
        [--max-leads 2000] [--poll-interval 30]

Docs:
  - create list:    https://developer.instantly.ai/api-reference/leadlist/create-lead-list
  - enrich:         https://developer.instantly.ai/api-reference/supersearchenrichment/enrich-leads-from-supersearch
  - poll:           https://developer.instantly.ai/api-reference/supersearchenrichment/get-enrichment-for-resource
  - list leads:     https://developer.instantly.ai/api-reference/lead/list-leads
"""
from __future__ import annotations

import json
import time

from _common import (
    arg, append_csv, get_key, load_checkpoint, load_json, log_event,
    make_session, normalize_country, normalize_domain, normalize_email,
    normalize_linkedin, normalize_name, run_dir, save_checkpoint, slugify,
)

INSTANTLY_BASE = "https://api.instantly.ai"
CREATE_LIST_EP = "/api/v2/lead-lists"
ENRICH_EP = "/api/v2/supersearch-enrichment/enrich-leads-from-supersearch"
POLL_EP = "/api/v2/supersearch-enrichment/get-enrichment-for-resource"
LIST_LEADS_EP = "/api/v2/leads/list"

EMPLOYEE_BUCKETS = [
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 500, "201-500"),
    (501, 1000, "501-1000"),
    (1001, 5000, "1001-5000"),
    (5001, 10000, "5001-10000"),
    (10001, 10**9, "10001+"),
]

FIELDS = [
    "source", "external_id",
    "first_name", "last_name", "full_name",
    "title", "linkedin_url",
    "email", "email_verification_status",
    "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city",
    "enriched_at", "raw_json",
]


def employee_buckets_overlapping(min_v, max_v):
    if min_v is None and max_v is None:
        return []
    mn = min_v if min_v is not None else 1
    mx = max_v if max_v is not None else 10**9
    out = []
    for lo, hi, label in EMPLOYEE_BUCKETS:
        if hi < mn or lo > mx:
            continue
        out.append(label)
    return out


def auth_headers() -> dict:
    return {
        "Authorization": f"Basic {get_key('INSTANTLY_KEY')}",
        "Content-Type": "application/json",
    }


def create_list(session, run_id) -> str:
    name = f"TAM_{run_id}_supersearch"[:64]
    r = session.post(INSTANTLY_BASE + CREATE_LIST_EP,
                     json={"name": name},
                     headers=auth_headers(), timeout=30)
    if r.status_code >= 400:
        log_event(run_id, "instantly.create_list.error",
                  status=r.status_code, body=r.text[:500])
        r.raise_for_status()
    list_id = r.json().get("id") or r.json().get("list_id") or ""
    if not list_id:
        raise RuntimeError(f"No list id in response: {r.text}")
    log_event(run_id, "instantly.create_list.ok", list_id=list_id, name=name)
    return list_id


def submit_enrichment(session, run_id, list_id, icp, max_leads) -> None:
    persona = icp.get("persona", {})
    firmo = icp.get("firmographics", {})
    geo = icp.get("geographics", {})
    payload = {
        "resource_id": list_id,
        "resource_type": "lead-list",
        "enrichment_options": {
            "enrich_work_email": True,
            "verify_work_email": True,
            "include_phone": False,
            "all_signals_enabled": True,
        },
        "search_filters": {
            "person_titles": persona.get("titles", []),
            "person_title_excludes": persona.get("title_exclusions", []),
            "person_seniorities": persona.get("seniority", []),
            "person_departments": persona.get("departments", []),
            "person_locations": geo.get("countries", []),
            "organization_industries": firmo.get("industries", []),
            "organization_employee_counts": employee_buckets_overlapping(
                firmo.get("employee_count_min"),
                firmo.get("employee_count_max"),
            ),
            "organization_locations": geo.get("countries", []),
        },
        "skip_workspace_existing_leads": False,
        "max_leads": max_leads,
    }
    r = session.post(INSTANTLY_BASE + ENRICH_EP, json=payload,
                     headers=auth_headers(), timeout=60)
    if r.status_code >= 400:
        log_event(run_id, "instantly.enrich.error",
                  status=r.status_code, body=r.text[:500])
        r.raise_for_status()
    log_event(run_id, "instantly.enrich.submitted",
              list_id=list_id, max_leads=max_leads, payload=payload)


def poll_until_done(session, run_id, list_id, interval) -> None:
    while True:
        r = session.get(
            INSTANTLY_BASE + POLL_EP,
            params={"resource_id": list_id, "resource_type": "lead-list"},
            headers=auth_headers(),
            timeout=30,
        )
        if r.status_code >= 400:
            log_event(run_id, "instantly.poll.error",
                      status=r.status_code, body=r.text[:300])
            r.raise_for_status()
        body = r.json()
        status = (body.get("status") or body.get("state") or "").lower()
        log_event(run_id, "instantly.poll", list_id=list_id, status=status,
                  progress=body.get("progress"))
        if status in ("completed", "complete", "done", "finished"):
            return
        if status in ("failed", "cancelled", "error"):
            raise RuntimeError(f"Instantly enrichment failed: {body}")
        time.sleep(interval)


def list_leads_paginated(session, run_id, list_id, out_path):
    ckpt = load_checkpoint(run_id, f"instantly_paginate_{slugify(list_id)}",
                           default={"cursor": None, "total": 0})
    cursor = ckpt["cursor"]
    total = ckpt["total"]
    while True:
        params = {"list_id": list_id, "limit": 100}
        if cursor:
            params["starting_after"] = cursor
        r = session.get(INSTANTLY_BASE + LIST_LEADS_EP, params=params,
                        headers=auth_headers(), timeout=60)
        if r.status_code >= 400:
            log_event(run_id, "instantly.list_leads.error",
                      status=r.status_code, body=r.text[:300])
            r.raise_for_status()
        body = r.json()
        leads = body.get("items") or body.get("leads") or body.get("data") or []
        if not leads:
            break
        normalized = [normalize_lead(l) for l in leads]
        wrote = append_csv(out_path, normalized, FIELDS)
        total += wrote
        cursor = body.get("next_starting_after") or body.get("next_cursor")
        save_checkpoint(run_id,
                        f"instantly_paginate_{slugify(list_id)}",
                        {"cursor": cursor, "total": total})
        log_event(run_id, "instantly.page", wrote=wrote, total=total, cursor=cursor)
        if not cursor or len(leads) < 100:
            break
    return total


def normalize_lead(l: dict) -> dict:
    return {
        "source": "instantly_supersearch",
        "external_id": l.get("id") or l.get("_id") or "",
        "first_name": normalize_name(l.get("first_name") or ""),
        "last_name": normalize_name(l.get("last_name") or ""),
        "full_name": normalize_name(
            l.get("full_name") or
            f'{l.get("first_name","")} {l.get("last_name","")}'
        ),
        "title": (l.get("title") or l.get("job_title") or "").strip(),
        "linkedin_url": normalize_linkedin(l.get("linkedin_url") or ""),
        "email": normalize_email(l.get("email") or l.get("work_email") or ""),
        "email_verification_status": (
            l.get("email_verification_status") or l.get("verification_status") or ""
        ).lower(),
        "company_name": (l.get("company_name") or l.get("organization_name") or "").strip(),
        "company_domain": normalize_domain(
            l.get("company_domain") or l.get("organization_website") or ""
        ),
        "company_linkedin_url": normalize_linkedin(
            l.get("company_linkedin_url") or l.get("organization_linkedin_url") or ""
        ),
        "company_industry": (l.get("company_industry") or l.get("industry") or "").strip(),
        "company_employee_count": (
            l.get("company_employee_count") or l.get("employee_count") or ""
        ),
        "country": normalize_country(l.get("country") or ""),
        "state": (l.get("state") or "").strip(),
        "city": (l.get("city") or "").strip(),
        "enriched_at": l.get("enriched_at") or l.get("updated_at") or "",
        "raw_json": json.dumps(l, ensure_ascii=False),
    }


def main() -> None:
    run_id = arg("run-id", required=True)
    max_leads = int(arg("max-leads", "2000"))
    interval = float(arg("poll-interval", "30"))

    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")
    out_path = rd / "raw" / "instantly.csv"

    state = load_checkpoint(run_id, "instantly_pipeline", default={})
    session = make_session()

    if "list_id" not in state:
        list_id = create_list(session, run_id)
        state["list_id"] = list_id
        save_checkpoint(run_id, "instantly_pipeline", state)
    else:
        list_id = state["list_id"]

    if not state.get("submitted"):
        submit_enrichment(session, run_id, list_id, icp, max_leads)
        state["submitted"] = True
        save_checkpoint(run_id, "instantly_pipeline", state)

    if not state.get("completed"):
        poll_until_done(session, run_id, list_id, interval)
        state["completed"] = True
        save_checkpoint(run_id, "instantly_pipeline", state)

    total = list_leads_paginated(session, run_id, list_id, out_path)
    log_event(run_id, "instantly.done", list_id=list_id, total=total)
    print(f"Instantly supersearch → {total} leads → {out_path}")


if __name__ == "__main__":
    main()
