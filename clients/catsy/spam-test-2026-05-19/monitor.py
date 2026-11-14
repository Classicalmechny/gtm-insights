#!/usr/bin/env python3
"""Show real-time send progress + which mailboxes Smartlead actually used."""
import json
import os
import subprocess

API_KEY = "281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq"
BASE = "https://server.smartlead.ai/api/v1"
CAMPAIGN_ID = 3355119


def call(path):
    url = f"{BASE}{path}{'&' if '?' in path else '?'}api_key={API_KEY}"
    raw = subprocess.check_output(["curl", "-sS", url], timeout=30)
    return json.loads(raw) if raw.strip() else {}


def main():
    c = call(f"/campaigns/{CAMPAIGN_ID}")
    print("Campaign:", c.get("name"), "status:", c.get("status"))
    analytics = call(f"/campaigns/{CAMPAIGN_ID}/analytics")
    print("\nAnalytics:")
    print(json.dumps(analytics, indent=2)[:2000])

    leads = call(f"/campaigns/{CAMPAIGN_ID}/leads?limit=50&offset=0")
    print("\nLeads:")
    print(json.dumps(leads, indent=2)[:2000])


if __name__ == "__main__":
    main()
