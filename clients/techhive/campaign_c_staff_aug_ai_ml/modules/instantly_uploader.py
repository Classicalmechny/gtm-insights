"""
Push personalized leads to an existing Instantly campaign.

Uses /api/v2/leads/list to dedupe against leads already in the campaign,
then /api/v2/leads to insert the new ones with custom variables matching
the email-template placeholders.

Custom variable map (placeholder → row key):
  {{role_being_hired}}      role_being_hired
  {{tech_skills}}           tech_skills
  {{usecase}}               usecase
  {{company_description}}   company_description
  {{job_apply_link}}        job_apply_link
  {{job_city}}              job_city
"""
from __future__ import annotations

import json
import time

from _common import (
    env, log_event, make_session, normalize_email, run_dir, write_csv,
)

INSTANTLY_BASE = "https://api.instantly.ai"
EP_LIST_LEADS = "/api/v2/leads/list"
EP_CREATE_LEAD = "/api/v2/leads"


def _headers() -> dict:
    return {"Authorization": f"Bearer {env('INSTANTLY_KEY')}",
            "Content-Type": "application/json"}


def fetch_existing_emails(session, campaign_id: str) -> set[str]:
    """Get all email addresses already in the campaign so we can dedupe."""
    emails: set[str] = set()
    cursor = None
    while True:
        params = {"campaign_id": campaign_id, "limit": 100}
        if cursor:
            params["starting_after"] = cursor
        r = session.post(INSTANTLY_BASE + EP_LIST_LEADS,
                         json={"campaign": campaign_id, "limit": 100,
                               "starting_after": cursor},
                         headers=_headers(), timeout=30)
        if r.status_code >= 400:
            # Try GET style as fallback
            r = session.get(INSTANTLY_BASE + EP_LIST_LEADS,
                            params=params, headers=_headers(), timeout=30)
        if r.status_code >= 400:
            break
        body = r.json()
        items = body.get("items") or body.get("data") or body.get("leads") or []
        if not items:
            break
        for l in items:
            e = normalize_email(l.get("email") or "")
            if e:
                emails.add(e)
        cursor = body.get("next_starting_after") or body.get("next_cursor")
        if not cursor or len(items) < 100:
            break
    return emails


def upload_one(session, campaign_id: str, lead: dict) -> tuple[bool, dict]:
    """POST a single lead to /api/v2/leads with campaign + custom_variables."""
    payload = {
        "campaign": campaign_id,
        "email": lead["email"],
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "company_name": lead.get("company_name", ""),
        "website": lead.get("company_domain", ""),
        "personalization": "",  # could insert hero opening line
        "phone": "",
        "lt_interest_status": 0,
        # Cross-campaign dedupe disabled — same lead can appear in this campaign
        # even if it lives in another campaign in the workspace.
        "skip_if_in_workspace": False,
        # In-campaign dedupe ON — prevents re-adding the same lead to THIS
        # campaign on weekly re-runs. The fetchExisting() check above is the
        # belt-and-suspenders pre-check.
        "skip_if_in_campaign": True,
        "verify_leads_for_lead_finder": False,
        "verify_leads_on_import": False,
        "custom_variables": {
            "role_being_hired": lead.get("role_being_hired", "AI Engineer"),
            "tech_skills": lead.get("tech_skills", "Python, ML stack"),
            "usecase": lead.get("usecase", ""),
            "company_description": lead.get("company_description", ""),
            "job_apply_link": lead.get("job_apply_link", ""),
            "job_city": lead.get("job_city", ""),
            "job_title_hiring": lead.get("job_title_hiring", ""),
            "linkedin_url": lead.get("linkedin_url", ""),
            "person_title": lead.get("title", ""),
            # Qualification audit (lets you confirm ICP-fit in Instantly UI)
            "icp_size_bucket": lead.get("company_size_bucket", ""),
            "icp_industry": lead.get("company_industry", ""),
            "icp_hq_country": lead.get("company_hq_country", ""),
            "icp_employees_li": str(lead.get("company_employees_on_linkedin", "")),
        },
    }
    r = session.post(INSTANTLY_BASE + EP_CREATE_LEAD,
                     json=payload, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        return False, {"status": r.status_code, "body": r.text[:300]}
    return True, r.json()


def upload(run_id: str, leads: list[dict], campaign_id: str | None = None,
           dedupe_against_campaign: bool = True,
           sleep_between: float = 0.3) -> dict:
    campaign_id = campaign_id or env("INSTANTLY_CAMPAIGN_ID")
    session = make_session()
    out_dir = run_dir(run_id) / "stage5_uploaded"
    out_dir.mkdir(exist_ok=True)

    existing: set[str] = set()
    if dedupe_against_campaign:
        existing = fetch_existing_emails(session, campaign_id)
        log_event(run_id, "upload.existing_in_campaign",
                  count=len(existing), campaign=campaign_id)

    uploaded, skipped_dup, failed = [], [], []
    for lead in leads:
        email = normalize_email(lead.get("email", ""))
        if not email:
            continue
        if email in existing:
            skipped_dup.append(lead)
            continue
        ok, resp = upload_one(session, campaign_id, lead)
        if ok:
            uploaded.append({**lead, "instantly_lead_id": resp.get("id", "")})
            existing.add(email)
            log_event(run_id, "upload.ok", email=email,
                      instantly_id=resp.get("id"))
        else:
            failed.append({**lead, "upload_error": json.dumps(resp)})
            log_event(run_id, "upload.fail", email=email, **resp)
        time.sleep(sleep_between)

    stats = {
        "input": len(leads),
        "uploaded": len(uploaded),
        "skipped_already_in_campaign": len(skipped_dup),
        "failed": len(failed),
        "campaign_id": campaign_id,
    }
    log_event(run_id, "upload.done", **stats)

    # Save audit CSVs
    if uploaded:
        write_csv(out_dir / "uploaded.csv", uploaded, list(uploaded[0].keys()))
    if failed:
        write_csv(out_dir / "failed.csv", failed, list(failed[0].keys()))
    if skipped_dup:
        write_csv(out_dir / "skipped_duplicates.csv", skipped_dup,
                  list(skipped_dup[0].keys()))
    return stats


if __name__ == "__main__":
    import sys, csv
    run_id = sys.argv[1] if len(sys.argv) > 1 else "smoketest"
    src = run_dir(run_id) / "stage4_personalized" / "leads_personalized.csv"
    with src.open() as f:
        leads = list(csv.DictReader(f))
    print(f"Uploading {len(leads)} leads to campaign {env('INSTANTLY_CAMPAIGN_ID')}...")
    stats = upload(run_id, leads)
    print(json.dumps(stats, indent=2))
