#!/usr/bin/env python3
"""Categorize Smartlead mailboxes into three buckets:
  - new_zapmail (created 2026-04-18, tag 'Zapmail 18/04/2026', SKIP)
  - old_zapmail (Gmail/Outlook, created on other dates, tag 'zapmail', SPAM TEST candidates)
  - untagged_smtp (type SMTP or has smtp_host, candidates for deletion)
Outputs:
  - new_zapmail.csv
  - old_zapmail.csv
  - untagged_smtp.csv
  - summary.txt
"""
import csv
import json
import os
from collections import Counter

DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(DIR, "all_accounts.json")) as f:
    accounts = json.load(f)

new_zapmail = []
old_zapmail = []
untagged_smtp = []
other = []

NEW_DATE = "2026-04-18"

for a in accounts:
    created = a.get("created_at", "")[:10]
    typ = a.get("type", "")
    smtp_host = a.get("smtp_host")
    row = {
        "id": a.get("id"),
        "from_email": a.get("from_email"),
        "from_name": a.get("from_name"),
        "type": typ,
        "smtp_host": smtp_host,
        "created_at": a.get("created_at"),
        "updated_at": a.get("updated_at"),
        "is_smtp_success": a.get("is_smtp_success"),
        "warmup_status": (a.get("warmup_details") or {}).get("status"),
        "warmup_reputation": (a.get("warmup_details") or {}).get("warmup_reputation"),
        "warmup_total_spam_count": (a.get("warmup_details") or {}).get("total_spam_count"),
        "warmup_total_sent_count": (a.get("warmup_details") or {}).get("total_sent_count"),
        "warmup_blocked_reason": (a.get("warmup_details") or {}).get("blocked_reason"),
        "message_per_day": a.get("message_per_day"),
        "custom_tracking_domain": a.get("custom_tracking_domain"),
        "campaign_count": a.get("campaign_count"),
    }

    if typ == "SMTP" or smtp_host:
        untagged_smtp.append(row)
    elif created == NEW_DATE:
        new_zapmail.append(row)
    elif typ in ("GMAIL", "OUTLOOK", "GOOGLE", "GOOGLE_OAUTH", "MICROSOFT", "MICROSOFT_OAUTH"):
        old_zapmail.append(row)
    else:
        other.append(row)


def write_csv(rows, path):
    if not rows:
        with open(path, "w") as f:
            f.write("(empty)\n")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


write_csv(new_zapmail, os.path.join(DIR, "new_zapmail.csv"))
write_csv(old_zapmail, os.path.join(DIR, "old_zapmail.csv"))
write_csv(untagged_smtp, os.path.join(DIR, "untagged_smtp.csv"))
write_csv(other, os.path.join(DIR, "other.csv"))


# Summary
lines = []
lines.append(f"Total accounts: {len(accounts)}")
lines.append("")
lines.append(f"NEW zapmail (created {NEW_DATE}, tag 'Zapmail 18/04/2026', SKIP): {len(new_zapmail)}")
lines.append(f"OLD zapmail (Gmail/Outlook, other dates, tag 'zapmail', SPAM-TEST): {len(old_zapmail)}")
lines.append(f"Untagged SMTP/private server (DELETE candidates): {len(untagged_smtp)}")
lines.append(f"Other (unclassified): {len(other)}")
lines.append("")

# Type breakdown
type_counter = Counter(a.get("type") for a in accounts)
lines.append("Type breakdown across ALL accounts:")
for t, c in type_counter.most_common():
    lines.append(f"  {t}: {c}")
lines.append("")

# Creation date breakdown for non-SMTP accounts
lines.append("Creation date breakdown for non-SMTP accounts:")
date_counter = Counter(
    a.get("created_at", "")[:10] for a in accounts if a.get("type") != "SMTP" and not a.get("smtp_host")
)
for d, c in sorted(date_counter.items()):
    lines.append(f"  {d}: {c}")
lines.append("")

# Domain breakdown for old_zapmail
lines.append("Domain breakdown for OLD zapmail (spam-test candidates):")
domain_counter = Counter(r["from_email"].split("@", 1)[1].lower() for r in old_zapmail if r["from_email"] and "@" in r["from_email"])
for d, c in domain_counter.most_common(50):
    lines.append(f"  {d}: {c}")

# Domain breakdown for untagged_smtp
lines.append("")
lines.append("Domain breakdown for UNTAGGED SMTP/private (delete candidates):")
smtp_domain_counter = Counter(r["from_email"].split("@", 1)[1].lower() for r in untagged_smtp if r["from_email"] and "@" in r["from_email"])
for d, c in smtp_domain_counter.most_common(50):
    lines.append(f"  {d}: {c}")

with open(os.path.join(DIR, "summary.txt"), "w") as f:
    f.write("\n".join(lines))

print("\n".join(lines))
