#!/usr/bin/env python3
"""Retry the lead-add call with the corrected settings body."""
import json
import os
import subprocess

API_KEY = "281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq"
BASE = "https://server.smartlead.ai/api/v1"
CAMPAIGN_ID = 3355119
DIR = os.path.dirname(os.path.abspath(__file__))

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
    return json.loads(raw) if raw.strip() else {}


r = call("POST", f"/campaigns/{CAMPAIGN_ID}/leads", {
    "lead_list": LEADS,
    "settings": {
        "ignore_global_block_list": True,
        "ignore_unsubscribe_list": True,
        "ignore_duplicate_leads_in_other_campaign": True,
    },
})
print(json.dumps(r, indent=2))

# Verify campaign is started and leads are attached
status = call("GET", f"/campaigns/{CAMPAIGN_ID}")
print("\nCampaign status:")
print(json.dumps({k: status.get(k) for k in ("id", "name", "status", "created_at", "updated_at")}, indent=2))
