#!/usr/bin/env python3
"""Find which 4 senders Smartlead picked for the spam-test campaign."""
import json
import subprocess

API_KEY = "281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq"
BASE = "https://server.smartlead.ai/api/v1"
CAMPAIGN_ID = 3355119


def call(path):
    url = f"{BASE}{path}{'&' if '?' in path else '?'}api_key={API_KEY}"
    raw = subprocess.check_output(["curl", "-sS", url], timeout=30)
    return json.loads(raw) if raw.strip() else {}


# Per-lead message-history endpoint
leads_resp = call(f"/campaigns/{CAMPAIGN_ID}/leads?limit=100&offset=0")
print(f"Total leads: {leads_resp.get('total_leads')}\n")

for entry in leads_resp.get("data", []):
    lead = entry["lead"]
    lead_id = lead["id"]
    email = lead["email"]
    print(f"--- Lead {email} (id={lead_id}) status={entry['status']} ---")
    history = call(f"/campaigns/{CAMPAIGN_ID}/leads/{lead_id}/message-history")
    msgs = history.get("history") or history.get("data") or []
    if isinstance(msgs, dict):
        msgs = [msgs]
    for m in msgs:
        from_addr = m.get("email_account") or m.get("from") or m.get("email_account_id") or m
        if isinstance(from_addr, dict):
            from_addr = from_addr.get("from_email") or from_addr.get("email") or from_addr
        print(f"  msg type={m.get('type')} sent={m.get('time') or m.get('created_at')} from={from_addr} open_count={m.get('open_count')} subject={m.get('subject')}")
