#!/usr/bin/env python3
"""Step 1: connect 50 .co domains to Zapmail.

Per the brain skill zapmail-domain-setup-public:
  - Endpoint: POST /api/v2/domains/connect-domain
  - Header: x-auth-zapmail: <key>
  - Body: {"domainNames": [...]} (max 50 per request)
  - Shared Zapmail NS: pns61.cloudns.net / pns62.cloudns.com / pns63.cloudns.net / pns64.cloudns.uk
  - After connect, poll /v2/domains/assignable until ≥95% are ACTIVE.

Connecting a domain doesn't consume a mailbox slot — slot consumption only
happens when /v2/mailboxes is called. So this step is safe to run today (May 19)
even though renewal isn't until June 2.
"""
import json
import os
import subprocess
import sys
import time

API_KEY = "af49bbb3-fac0-4fa9-88eb-ca8c5baba881"
BASE = "https://api.zapmail.ai/api"
DIR = os.path.dirname(os.path.abspath(__file__))

ZAPMAIL_NS = [
    "pns61.cloudns.net",
    "pns62.cloudns.com",
    "pns63.cloudns.net",
    "pns64.cloudns.uk",
]


def call(method, path, body=None):
    url = f"{BASE}{path}"
    args = [
        "curl", "-sS", "-X", method, url,
        "-H", f"x-auth-zapmail: {API_KEY}",
        "-H", "Content-Type: application/json",
    ]
    if body is not None:
        args += ["-d", json.dumps(body)]
    raw = subprocess.check_output(args, timeout=60)
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw.decode("utf-8", errors="replace")}


def main():
    with open(os.path.join(DIR, "domains.txt")) as f:
        domains = [ln.strip().lower() for ln in f
                   if ln.strip() and not ln.startswith("#")]
    print(f"Connecting {len(domains)} domains to Zapmail...")

    r = call("POST", "/v2/domains/connect-domain", {"domainNames": domains})
    print(json.dumps(r, indent=2)[:3000])

    out = os.path.join(DIR, "connect_response.json")
    with open(out, "w") as f:
        json.dump({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "domains_submitted": domains,
                   "nameservers_to_set_at_dynadot": ZAPMAIL_NS,
                   "response": r}, f, indent=2)
    print(f"\nSaved {out}")
    print("\nZapmail nameservers to set at Dynadot for all 50 domains:")
    for ns in ZAPMAIL_NS:
        print(f"  {ns}")


if __name__ == "__main__":
    main()
