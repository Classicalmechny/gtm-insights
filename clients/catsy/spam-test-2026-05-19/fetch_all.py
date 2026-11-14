#!/usr/bin/env python3
"""Paginate all Smartlead email accounts."""
import json
import os
import time
import subprocess

API_KEY = "281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq"
BASE = "https://server.smartlead.ai/api/v1"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_accounts.json")


def fetch_page(offset, limit=100):
    url = f"{BASE}/email-accounts/?api_key={API_KEY}&limit={limit}&offset={offset}"
    raw = subprocess.check_output(["curl", "-sS", url], timeout=60)
    return json.loads(raw)


def main():
    all_accounts = []
    offset = 0
    limit = 100
    while True:
        page = fetch_page(offset, limit)
        if not isinstance(page, list):
            print("Unexpected response:", page)
            break
        all_accounts.extend(page)
        print(f"offset={offset} fetched={len(page)} total={len(all_accounts)}")
        if len(page) < limit:
            break
        offset += limit
        time.sleep(0.4)
    with open(OUT, "w") as f:
        json.dump(all_accounts, f, indent=2)
    print(f"Saved {len(all_accounts)} accounts → {OUT}")


if __name__ == "__main__":
    main()
