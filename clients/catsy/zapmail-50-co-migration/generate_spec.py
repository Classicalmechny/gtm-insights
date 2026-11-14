#!/usr/bin/env python3
"""Build the 150-mailbox provisioning spec for Zapmail.

Username pattern observed on the old 100-mailbox cohort:
  - <domain>: elizabeth, elizabeth.tah, elizabeth.t
  - from_name on all: "Elizabeth Tah Bash"

Input:  domains.txt (one .co domain per line, no protocol)
Output: mailboxes.csv with one row per (domain, username) pair

Run after populating domains.txt with the 50 Dynadot .co domain names.
"""
import csv
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
DOMAINS_FILE = os.path.join(DIR, "domains.txt")
OUT = os.path.join(DIR, "mailboxes.csv")

USERNAMES = ["elizabeth", "elizabeth.tah", "elizabeth.t"]
FIRST_NAME = "Elizabeth"
LAST_NAME = "Tah Bash"  # combined; Zapmail wants firstName + lastName fields


def main():
    if not os.path.exists(DOMAINS_FILE):
        print(f"ERROR: missing {DOMAINS_FILE}")
        print("Create it with one .co domain per line (no http://, no trailing slash).")
        sys.exit(1)
    with open(DOMAINS_FILE) as f:
        domains = [ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")]
    if len(domains) != 50:
        print(f"WARN: expected 50 domains, got {len(domains)}")

    rows = []
    for d in domains:
        for u in USERNAMES:
            rows.append({
                "domain": d,
                "username": u,
                "from_email": f"{u}@{d}",
                "first_name": FIRST_NAME,
                "last_name": LAST_NAME,
                "profile_picture_path": "assets/elizabeth.png",
                "billing_source": "swap_old"   # first 100 = swap; last 50 = card
            })

    # Mark last 50 (10 domains × 5? no — last 50 mailboxes = last 17 domains' 3 each = 51, close enough)
    # User said: 100 swap + ~50 new = 150. So flag the trailing 50 as card-charged.
    for r in rows[-50:]:
        r["billing_source"] = "card"

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} mailboxes -> {OUT}")
    swap = sum(1 for r in rows if r["billing_source"] == "swap_old")
    card = sum(1 for r in rows if r["billing_source"] == "card")
    print(f"  swap_old (covered by old subscription): {swap}")
    print(f"  card     (net-new, charge card on file): {card}")


if __name__ == "__main__":
    main()
