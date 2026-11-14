#!/usr/bin/env python3
"""DESTRUCTIVE — deletes every mailbox in untagged_smtp.csv from Smartlead.

DO NOT RUN without explicit user confirmation. Default is dry-run; pass --confirm
to actually issue DELETE requests.

Pre-flight guard: refuses to delete any mailbox with campaign_count > 0 (i.e. still
attached to a live campaign).
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


def call(method, path):
    url = f"{BASE}{path}{'&' if '?' in path else '?'}api_key={API_KEY}"
    raw = subprocess.check_output(
        ["curl", "-sS", "-X", method, url, "-H", "Content-Type: application/json"],
        timeout=30,
    )
    return json.loads(raw) if raw.strip() else {}


def main():
    confirm = "--confirm" in sys.argv
    with open(os.path.join(DIR, "untagged_smtp.csv")) as f:
        rows = list(csv.DictReader(f))
    in_use = [r for r in rows if int(r.get("campaign_count") or 0) > 0]
    if in_use:
        print(f"REFUSING — {len(in_use)} mailboxes still attached to a campaign:")
        for r in in_use[:10]:
            print(f"  {r['id']}  {r['from_email']}  campaigns={r['campaign_count']}")
        sys.exit(2)

    print(f"{'DELETING' if confirm else 'DRY-RUN — would delete'} {len(rows)} SMTP mailboxes...")
    if not confirm:
        for r in rows[:5]:
            print(f"  would DELETE id={r['id']} {r['from_email']}")
        print("  ...")
        print("(pass --confirm to actually delete)")
        return

    results = []
    for i, r in enumerate(rows, 1):
        try:
            resp = call("DELETE", f"/email-accounts/{r['id']}")
            ok = bool(resp.get("ok"))
        except Exception as e:
            resp = {"error": str(e)}
            ok = False
        results.append({"id": r["id"], "email": r["from_email"], "ok": ok, "response": resp})
        print(f"[{i:3}/{len(rows)}] {'OK' if ok else 'FAIL'}  id={r['id']} {r['from_email']}")
        time.sleep(0.2)

    with open(os.path.join(DIR, "delete_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    succeeded = sum(1 for r in results if r["ok"])
    print(f"\nDeleted {succeeded}/{len(rows)} mailboxes.")


if __name__ == "__main__":
    main()
