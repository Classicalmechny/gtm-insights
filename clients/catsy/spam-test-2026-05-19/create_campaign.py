#!/usr/bin/env python3
"""Create a Smartlead 'spam test' campaign that fires emails from every old_zapmail
mailbox to the 4 user-controlled inboxes immediately.

Workflow (per Smartlead API):
  1. POST /campaigns/create                            -> campaign_id
  2. POST /campaigns/{id}/email-accounts               -> attach senders
  3. POST /campaigns/{id}/sequences                    -> 1-step email
  4. POST /campaigns/{id}/settings                     -> tracking/stop-lead
  5. POST /campaigns/{id}/leads                        -> 4 inboxes
  6. POST /campaigns/{id}/schedule                     -> immediate window
  7. POST /campaigns/{id}/status                       -> START
"""
import csv
import json
import os
import subprocess
import sys
import time

API_KEY = "281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq"
BASE = "https://server.smartlead.ai/api/v1"
DIR = os.path.dirname(os.path.abspath(__file__))

CAMPAIGN_NAME = "Spam Test — old zapmail mailboxes — 2026-05-19"
TIMEZONE = "Asia/Bangkok"   # matches system local (+07), "active right now"
SUBJECT = "hi {{first_name|there}}"
BODY_HTML = (
    "<p>Hi {{first_name|there}},</p>"
    "<p>Hope you're doing well — quick question for you.</p>"
    "<p>Would you be open to a brief chat this week?</p>"
    "<p>Best,<br>{{from_name}}</p>"
)
LEADS = [
    {"email": "anirudhgupta1177@gmail.com", "first_name": "Anirudh", "last_name": "Gupta"},
    {"email": "anirudh@theorganicbuzz.com", "first_name": "Anirudh", "last_name": "Gupta"},
    {"email": "agent@theorganicbuzz.com",   "first_name": "Agent",   "last_name": "Inbox"},
    {"email": "anirudh@intentledsales.com", "first_name": "Anirudh", "last_name": "Gupta"},
]


def call(method, path, body=None):
    url = f"{BASE}{path}{'&' if '?' in path else '?'}api_key={API_KEY}"
    args = ["curl", "-sS", "-X", method, url, "-H", "Content-Type: application/json"]
    if body is not None:
        args += ["-d", json.dumps(body)]
    raw = subprocess.check_output(args, timeout=60)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw.decode("utf-8", errors="replace")}


def step(label):
    print(f"\n=== {label} ===")


def main(dry_run=False, leads_override=None, sender_ids_override=None):
    # Load sender IDs
    if sender_ids_override is not None:
        sender_ids = sender_ids_override
    else:
        with open(os.path.join(DIR, "old_zapmail.csv")) as f:
            sender_ids = [int(r["id"]) for r in csv.DictReader(f)]
    leads = leads_override if leads_override is not None else LEADS

    print(f"Senders to attach: {len(sender_ids)}")
    print(f"Leads: {len(leads)}")
    print(f"Timezone: {TIMEZONE}")
    if dry_run:
        print("(dry-run — exiting before any API call)")
        return

    state = {}

    # 1. Create campaign
    step("Create campaign")
    r = call("POST", "/campaigns/create", {"name": CAMPAIGN_NAME})
    print(json.dumps(r, indent=2)[:600])
    campaign_id = r.get("id") or r.get("campaign_id") or (r.get("data") or {}).get("id")
    if not campaign_id:
        print("ERROR: could not extract campaign_id")
        sys.exit(1)
    state["campaign_id"] = campaign_id
    print(f"campaign_id = {campaign_id}")

    # 2. Attach email accounts (senders)
    step("Attach email accounts (senders)")
    r = call("POST", f"/campaigns/{campaign_id}/email-accounts",
             {"email_account_ids": sender_ids})
    print(json.dumps(r, indent=2)[:600])
    state["attach_response"] = r

    # 3. Save sequence (single step, send immediately)
    step("Save sequence (1 step)")
    r = call("POST", f"/campaigns/{campaign_id}/sequences", {
        "sequences": [{
            "id": None,
            "seq_number": 1,
            "seq_delay_details": {"delay_in_days": 0},
            "subject": SUBJECT,
            "email_body": BODY_HTML,
        }],
    })
    print(json.dumps(r, indent=2)[:600])
    state["sequence_response"] = r

    # 4. Settings — keep default tracking (mirror production), no stop-on-reply
    step("Update settings")
    r = call("POST", f"/campaigns/{campaign_id}/settings", {
        "stop_lead_settings": "NEVER",
        "send_as_plain_text": False,
    })
    print(json.dumps(r, indent=2)[:600])
    state["settings_response"] = r

    # 5. Add leads
    step("Add leads (4 inboxes)")
    r = call("POST", f"/campaigns/{campaign_id}/leads", {
        "lead_list": leads,
        "settings": {
            "ignore_global_block_list": True,
            "ignore_unsubscribe_list": True,
            "ignore_duplicate_leads_in_other_campaign": True,
            "skip_community_bounce_list": True,
        },
    })
    print(json.dumps(r, indent=2)[:1000])
    state["leads_response"] = r

    # 6. Schedule — fire ASAP, all hours, all days, 3-min spacing
    step("Save schedule (active now)")
    r = call("POST", f"/campaigns/{campaign_id}/schedule", {
        "timezone": TIMEZONE,
        "days_of_the_week": [0, 1, 2, 3, 4, 5, 6],
        "start_hour": "00:00",
        "end_hour": "23:59",
        "min_time_btw_emails": 3,
        "max_new_leads_per_day": 200,
        "schedule_start_time": None,
    })
    print(json.dumps(r, indent=2)[:600])
    state["schedule_response"] = r

    # 7. Status -> START
    step("Start campaign")
    r = call("POST", f"/campaigns/{campaign_id}/status", {"status": "START"})
    print(json.dumps(r, indent=2)[:600])
    state["status_response"] = r

    # Save state
    out = os.path.join(DIR, "campaign_state.json")
    with open(out, "w") as f:
        json.dump(state, f, indent=2)
    print(f"\nFull state written to {out}")
    print(f"Campaign dashboard: https://app.smartlead.ai/app/email-campaigns/{campaign_id}/analytics")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
