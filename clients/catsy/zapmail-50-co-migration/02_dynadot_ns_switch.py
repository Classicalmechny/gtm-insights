#!/usr/bin/env python3
"""Step 2: bulk-switch nameservers on Dynadot for all 50 .co domains.

Per the brain skill zapmail-domain-setup-public, Dynadot's set_ns command
accepts comma-separated domain lists (up to 100 per request). Critical: must
use safe=',' in urlencode to avoid the %2C bug.

Requires: DYNADOT_API_KEY in env (Dynadot Dashboard -> Tools -> API).
Also: the Dynadot account must whitelist the IP you call from.
"""
import json
import os
import subprocess
import sys
import urllib.parse

DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY = os.environ.get("DYNADOT_API_KEY")

ZAPMAIL_NS = [
    "pns61.cloudns.net",
    "pns62.cloudns.com",
    "pns63.cloudns.net",
    "pns64.cloudns.uk",
]


def main():
    if not API_KEY:
        print("ERROR: set DYNADOT_API_KEY env var first")
        sys.exit(1)
    with open(os.path.join(DIR, "domains.txt")) as f:
        domains = [ln.strip().lower() for ln in f
                   if ln.strip() and not ln.startswith("#")]

    # Sanity: confirm Dynadot wallet/auth works
    bal_url = f"https://api.dynadot.com/api3.json?key={API_KEY}&command=account_info"
    bal = subprocess.check_output(["curl", "-sS", bal_url], timeout=30)
    print("Dynadot auth check:", bal.decode("utf-8", "replace")[:200])

    # Batch in groups of 100 (we only have 50, so one call)
    BATCH = 100
    for i in range(0, len(domains), BATCH):
        chunk = domains[i:i + BATCH]
        params = {
            "key": API_KEY,
            "command": "set_ns",
            "domain": ",".join(chunk),
            "ns0": ZAPMAIL_NS[0],
            "ns1": ZAPMAIL_NS[1],
            "ns2": ZAPMAIL_NS[2],
            "ns3": ZAPMAIL_NS[3],
        }
        # safe=',' is REQUIRED to avoid Dynadot encoding bug
        qs = urllib.parse.urlencode(params, safe=",")
        url = f"https://api.dynadot.com/api3.json?{qs}"
        r = subprocess.check_output(["curl", "-sS", url], timeout=60)
        text = r.decode("utf-8", "replace")
        print(f"\nBatch {i // BATCH + 1} ({len(chunk)} domains):")
        print(text[:1000])
        try:
            parsed = json.loads(text)
            print("Parsed status:", parsed.get("SetNsResponse", {}).get("Status"))
        except Exception:
            pass

    print("\nWait 15-20 minutes for DNS propagation, then run 03_poll_assignable.py")


if __name__ == "__main__":
    main()
