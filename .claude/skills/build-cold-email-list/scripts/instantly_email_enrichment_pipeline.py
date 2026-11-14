#!/usr/bin/env python3
"""
Instantly Email Enrichment Pipeline.

Two modes:

  mode=enrich  (Pass 1)
    Take leads from an input CSV (e.g. merged.csv), create a new
    Instantly lead-list, bulk-add the leads, run BOTH work-email enrichment
    AND verification, poll, paginate. Output: verified.csv-style rows.

  mode=verify  (Pass 3)
    Take leads that already have a candidate_email (e.g. from BlitzAPI),
    create a new lead-list, bulk-add, run VERIFICATION-ONLY (no
    enrich_work_email), poll, paginate. Output: verified Pass-2 finds.

Idempotent — persists list_id and progress per mode.

Usage:
  python instantly_email_enrichment_pipeline.py
        --run-id 2026-05-14_1330_xxx
        --mode enrich|verify
        --input output/<run>/merged.csv
        --output output/<run>/verified.csv
        [--poll-interval 30]

Docs:
  - create list:   https://developer.instantly.ai/api-reference/leadlist/create-lead-list
  - bulk add:      https://developer.instantly.ai/api-reference/lead/add-leads-in-bulk-to-a-campaign-or-list
  - create job:    https://developer.instantly.ai/api-reference/supersearchenrichment/create-an-enrichment
  - poll:          https://developer.instantly.ai/api-reference/supersearchenrichment/get-enrichment-for-resource
  - list leads:    https://developer.instantly.ai/api-reference/lead/list-leads
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from _common import (
    arg, get_key, load_checkpoint, log_event, make_session,
    normalize_domain, normalize_email, normalize_linkedin, run_dir,
    save_checkpoint, slugify,
)

INSTANTLY_BASE = "https://api.instantly.ai"
CREATE_LIST_EP = "/api/v2/lead-lists"
BULK_ADD_EP = "/api/v2/leads/add-leads-to-campaign-or-list"
CREATE_ENRICHMENT_EP = "/api/v2/supersearch-enrichment"
POLL_EP = "/api/v2/supersearch-enrichment/get-enrichment-for-resource"
LIST_LEADS_EP = "/api/v2/leads/list"

BATCH_SIZE = 500


def auth_headers() -> dict:
    return {
        "Authorization": f"Basic {get_key('INSTANTLY_KEY')}",
        "Content-Type": "application/json",
    }


def create_list(session, run_id, label) -> str:
    name = f"TAM_{run_id}_{label}"[:64]
    r = session.post(INSTANTLY_BASE + CREATE_LIST_EP,
                     json={"name": name},
                     headers=auth_headers(), timeout=30)
    if r.status_code >= 400:
        log_event(run_id, f"instantly_{label}.create_list.error",
                  status=r.status_code, body=r.text[:500])
        r.raise_for_status()
    list_id = r.json().get("id") or r.json().get("list_id") or ""
    if not list_id:
        raise RuntimeError(f"No list id: {r.text}")
    log_event(run_id, f"instantly_{label}.create_list.ok",
              list_id=list_id, name=name)
    return list_id


def bulk_add(session, run_id, list_id, label, leads):
    """Bulk add leads in batches of BATCH_SIZE."""
    n = 0
    for i in range(0, len(leads), BATCH_SIZE):
        chunk = leads[i:i + BATCH_SIZE]
        payload = {
            "list_id": list_id,
            "leads": chunk,
            "skip_workspace_existing_leads": False,
        }
        r = session.post(INSTANTLY_BASE + BULK_ADD_EP, json=payload,
                         headers=auth_headers(), timeout=120)
        if r.status_code >= 400:
            log_event(run_id, f"instantly_{label}.bulk_add.error",
                      status=r.status_code, body=r.text[:300],
                      batch_start=i)
            r.raise_for_status()
        n += len(chunk)
        log_event(run_id, f"instantly_{label}.bulk_add.batch",
                  batch_start=i, batch_size=len(chunk), cumulative=n)
        time.sleep(0.5)
    return n


def create_enrichment_job(session, run_id, list_id, label, mode):
    enrich_work_email = (mode == "enrich")
    payload = {
        "resource_id": list_id,
        "resource_type": "lead-list",
        "enrichment_options": {
            "enrich_work_email": enrich_work_email,
            "verify_work_email": True,
        },
    }
    r = session.post(INSTANTLY_BASE + CREATE_ENRICHMENT_EP, json=payload,
                     headers=auth_headers(), timeout=60)
    if r.status_code >= 400:
        log_event(run_id, f"instantly_{label}.enrich_job.error",
                  status=r.status_code, body=r.text[:300])
        r.raise_for_status()
    log_event(run_id, f"instantly_{label}.enrich_job.ok", body=r.json())


def poll_until_done(session, run_id, list_id, label, interval):
    while True:
        r = session.get(INSTANTLY_BASE + POLL_EP,
                        params={"resource_id": list_id,
                                "resource_type": "lead-list"},
                        headers=auth_headers(), timeout=30)
        if r.status_code >= 400:
            log_event(run_id, f"instantly_{label}.poll.error",
                      status=r.status_code, body=r.text[:300])
            r.raise_for_status()
        body = r.json()
        status = (body.get("status") or body.get("state") or "").lower()
        log_event(run_id, f"instantly_{label}.poll",
                  status=status, progress=body.get("progress"))
        if status in ("completed", "complete", "done", "finished"):
            return
        if status in ("failed", "cancelled", "error"):
            raise RuntimeError(f"Instantly job failed: {body}")
        time.sleep(interval)


def paginate_and_write(session, run_id, list_id, label, output_path, fieldnames):
    ckpt_name = f"instantly_{label}_paginate_{slugify(list_id)}"
    ckpt = load_checkpoint(run_id, ckpt_name, default={"cursor": None, "total": 0})
    cursor = ckpt["cursor"]
    total = ckpt["total"]
    mode = "a" if output_path.exists() else "w"
    with output_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        while True:
            params = {"list_id": list_id, "limit": 100}
            if cursor:
                params["starting_after"] = cursor
            r = session.get(INSTANTLY_BASE + LIST_LEADS_EP, params=params,
                            headers=auth_headers(), timeout=60)
            if r.status_code >= 400:
                log_event(run_id, f"instantly_{label}.paginate.error",
                          status=r.status_code, body=r.text[:300])
                r.raise_for_status()
            body = r.json()
            leads = body.get("items") or body.get("leads") or body.get("data") or []
            if not leads:
                break
            for l in leads:
                row = build_output_row(l)
                if not row:
                    continue
                writer.writerow(row)
                total += 1
            cursor = body.get("next_starting_after") or body.get("next_cursor")
            save_checkpoint(run_id, ckpt_name, {"cursor": cursor, "total": total})
            if not cursor or len(leads) < 100:
                break
    return total


def build_output_row(l: dict) -> dict | None:
    email = normalize_email(l.get("email") or l.get("work_email") or "")
    status = (l.get("email_verification_status") or
              l.get("verification_status") or "").lower()
    if not email or status not in ("valid", "accept_all"):
        return None
    return {
        "sources": "instantly_verified",
        "external_ids": l.get("id") or "",
        "first_name": (l.get("first_name") or "").strip(),
        "last_name": (l.get("last_name") or "").strip(),
        "full_name": (l.get("full_name") or
                      f'{l.get("first_name","")} {l.get("last_name","")}'.strip()),
        "title": (l.get("title") or l.get("job_title") or "").strip(),
        "linkedin_url": normalize_linkedin(l.get("linkedin_url") or ""),
        "email": email,
        "email_verification_status": status,
        "email_provider": "instantly",
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
        "country": (l.get("country") or "").strip(),
        "state": (l.get("state") or "").strip(),
        "city": (l.get("city") or "").strip(),
        "phone": (l.get("phone") or "").strip(),
    }


def load_leads_for_payload(input_path: Path, mode: str) -> list[dict]:
    with input_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        # In verify mode, only push rows that have a candidate_email.
        if mode == "verify":
            candidate = normalize_email(r.get("candidate_email", ""))
            if not candidate:
                continue
            out.append({
                "first_name": r.get("first_name", ""),
                "last_name": r.get("last_name", ""),
                "email": candidate,
                "company_name": r.get("company_name", ""),
                "company_domain": normalize_domain(r.get("company_domain", "")),
                "linkedin_url": normalize_linkedin(r.get("linkedin_url", "")),
                "title": r.get("title", ""),
            })
        else:  # enrich
            # Skip rows that already have a valid email.
            existing = normalize_email(r.get("email", ""))
            if existing and "@" in existing:
                continue
            out.append({
                "first_name": r.get("first_name", ""),
                "last_name": r.get("last_name", ""),
                "company_name": r.get("company_name", ""),
                "company_domain": normalize_domain(r.get("company_domain", "")),
                "linkedin_url": normalize_linkedin(r.get("linkedin_url", "")),
                "title": r.get("title", ""),
            })
    return out


VERIFIED_FIELDS = [
    "sources", "external_ids", "first_name", "last_name", "full_name",
    "title", "linkedin_url", "email", "email_verification_status",
    "email_provider", "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city", "phone",
]


def main() -> None:
    run_id = arg("run-id", required=True)
    mode = arg("mode", "enrich")
    if mode not in ("enrich", "verify"):
        raise SystemExit("--mode must be enrich or verify")
    interval = float(arg("poll-interval", "30"))
    rd = run_dir(run_id)
    input_path = Path(arg("input", str(rd / "merged.csv")))
    output_path = Path(arg("output", str(rd / "verified.csv")))

    label = mode
    state = load_checkpoint(run_id, f"instantly_email_{label}", default={})
    session = make_session()

    if "list_id" not in state:
        state["list_id"] = create_list(session, run_id, label)
        save_checkpoint(run_id, f"instantly_email_{label}", state)
    list_id = state["list_id"]

    if not state.get("bulk_added"):
        leads = load_leads_for_payload(input_path, mode)
        log_event(run_id, f"instantly_{label}.preparing",
                  input=str(input_path), leads=len(leads))
        if not leads:
            print(f"No leads to {label}.")
            return
        bulk_add(session, run_id, list_id, label, leads)
        state["bulk_added"] = True
        save_checkpoint(run_id, f"instantly_email_{label}", state)

    if not state.get("job_submitted"):
        create_enrichment_job(session, run_id, list_id, label, mode)
        state["job_submitted"] = True
        save_checkpoint(run_id, f"instantly_email_{label}", state)

    if not state.get("completed"):
        poll_until_done(session, run_id, list_id, label, interval)
        state["completed"] = True
        save_checkpoint(run_id, f"instantly_email_{label}", state)

    total = paginate_and_write(session, run_id, list_id, label, output_path,
                               VERIFIED_FIELDS)
    log_event(run_id, f"instantly_{label}.done", total=total, output=str(output_path))
    print(f"Instantly {label} → {total} verified rows → {output_path}")


if __name__ == "__main__":
    main()
