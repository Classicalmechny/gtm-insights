#!/usr/bin/env python3
"""Per-mailbox warmup signals — best proxy for 'burnt up' status without sending real mail.

Smartlead warmup measures: deliverability rate seen by Smartlead's warmup recipient
network (other Smartlead users). If a mailbox starts landing in spam in OTHER
Smartlead users' inboxes, total_spam_count rises and warmup_reputation drops.

Pulls /email-accounts/{id}/warmup-stats for each old_zapmail mailbox to get the
most recent 7-day rolling signal (richer than the summary in the list endpoint).
"""
import csv
import json
import os
import subprocess
import time

DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY = "281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq"
BASE = "https://server.smartlead.ai/api/v1"


def fetch_warmup(account_id):
    url = f"{BASE}/email-accounts/{account_id}/warmup-stats?api_key={API_KEY}"
    try:
        raw = subprocess.check_output(["curl", "-sS", url], timeout=30)
        return json.loads(raw)
    except Exception as e:
        return {"error": str(e)}


def main():
    with open(os.path.join(DIR, "old_zapmail.csv")) as f:
        rows = list(csv.DictReader(f))

    enriched = []
    for i, r in enumerate(rows, 1):
        acct_id = r["id"]
        stats = fetch_warmup(acct_id)
        ws = stats if isinstance(stats, dict) else {}
        days = ws.get("stats_by_date") or []
        save_spam_7d = sum(int(d.get("save_from_spam_count") or 0) for d in days)
        sent_7d = sum(int(d.get("sent_count") or 0) for d in days)
        reply_7d = sum(int(d.get("reply_count") or 0) for d in days)
        spam_rate = (save_spam_7d / sent_7d) if sent_7d else 0.0
        enriched.append({
            **r,
            "ws_sent_count": ws.get("sent_count"),
            "ws_spam_count": ws.get("spam_count"),
            "ws_inbox_count": ws.get("inbox_count"),
            "ws_warmup_email_received_count": ws.get("warmup_email_received_count"),
            "ws_save_from_spam_7d": save_spam_7d,
            "ws_sent_7d": sent_7d,
            "ws_reply_7d": reply_7d,
            "ws_spam_rate_7d": round(spam_rate, 4),
        })
        if i % 10 == 0 or i == len(rows):
            print(f"[{i:3}/{len(rows)}] {r['from_email']}")
        time.sleep(0.15)

    keys = list(enriched[0].keys())
    with open(os.path.join(DIR, "warmup_signals.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(enriched)

    # Surface the worst-looking mailboxes
    def burnt_score(r):
        try:
            rep = float((r.get("warmup_reputation") or "").rstrip("%")) if r.get("warmup_reputation") else 100
        except Exception:
            rep = 100
        save = int(r.get("ws_save_from_spam_7d") or 0)
        ws_spam = int(r.get("ws_spam_count") or 0)
        return (save, 100 - rep, ws_spam)

    enriched.sort(key=burnt_score, reverse=True)
    print("\nTop 25 most-suspicious mailboxes:")
    print(f"{'from_email':45} {'rep':>5} {'save7d':>7} {'rate7d':>7} {'sent7d':>7} {'reply7d':>7}")
    for r in enriched[:25]:
        print(f"{r['from_email']:45} {str(r['warmup_reputation']):>5} {str(r['ws_save_from_spam_7d']):>7} {str(r['ws_spam_rate_7d']):>7} {str(r['ws_sent_7d']):>7} {str(r['ws_reply_7d']):>7}")

    burnt = [r for r in enriched if int(r.get("ws_save_from_spam_7d") or 0) > 0]
    print(f"\n{len(burnt)} mailboxes show 'save_from_spam' events in last 7 days (live burnt signal).")


if __name__ == "__main__":
    main()
