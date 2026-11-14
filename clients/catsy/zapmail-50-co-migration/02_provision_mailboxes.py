#!/usr/bin/env python3
"""Step 2: provision 3 mailboxes per domain (150 total) via POST /v2/mailboxes.

Run AFTER:
  - 01_add_domains.py succeeded
  - Dynadot NS update propagated (24h)
  - Zapmail dashboard shows each domain as "connected" / healthy

Hard rules surfaced by Zapmail docs:
  - 5 mailboxes/domain max (we use 3, fine)
  - New mailbox assignment to a workspace is only allowed in first 24h
    of domain connection (so don't delay this step too long)
  - Profile picture is NOT settable at creation — handled in step 03

Username pattern: elizabeth / elizabeth.tah / elizabeth.t
First/last name: Elizabeth / Tah Bash
"""
import csv
import json
import os
import sys
from collections import defaultdict

from zapmail_client import ZapmailClient

DIR = os.path.dirname(os.path.abspath(__file__))

USERNAMES = ["elizabeth", "elizabeth.tah", "elizabeth.t"]
FIRST_NAME = "Elizabeth"
LAST_NAME = "Tah Bash"


def get_domain_ids(c: ZapmailClient):
    """List domains in the workspace to find each domain's internal ID."""
    r = c.call("GET", "/v2/domains?limit=500")
    items = []
    if isinstance(r, dict):
        for k in ("data", "domains", "items", "results"):
            if isinstance(r.get(k), list):
                items = r[k]
                break
    elif isinstance(r, list):
        items = r
    mapping = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("domainName") or it.get("name") or "").lower()
        did = it.get("id") or it.get("domainId") or it.get("_id")
        if name and did:
            mapping[name] = did
    return mapping


def main():
    with open(os.path.join(DIR, "domains.txt")) as f:
        domains = [ln.strip().lower() for ln in f
                   if ln.strip() and not ln.startswith("#")]

    c = ZapmailClient()
    domain_ids = get_domain_ids(c)
    missing = [d for d in domains if d not in domain_ids]
    if missing:
        print(f"WARN: {len(missing)} domain(s) not found in Zapmail workspace:")
        for d in missing[:10]:
            print(f"  {d}")
        if "--force" not in sys.argv:
            print("Pass --force to proceed for the ones we can find.")
            sys.exit(1)

    results = []
    for domain in domains:
        did = domain_ids.get(domain)
        if not did:
            continue
        body = {
            str(did): [
                {
                    "firstName": FIRST_NAME,
                    "lastName": LAST_NAME,
                    "mailboxUsername": u,
                    "domainName": domain,
                }
                for u in USERNAMES
            ]
        }
        r = c.call("POST", "/v2/mailboxes", body)
        ok = bool(r.get("ok") or r.get("success") or r.get("data"))
        print(f"{'OK' if ok else 'ERR'}  {domain}  -> {json.dumps(r)[:200]}")
        results.append({"domain": domain, "domain_id": did, "ok": ok, "response": json.dumps(r)[:500]})

    out = os.path.join(DIR, "provision_results.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    succeeded = sum(1 for r in results if r["ok"])
    print(f"\nProvisioned {succeeded}/{len(results)} domains × 3 = {succeeded*3} mailboxes")
    print(f"Trace: {out}")


if __name__ == "__main__":
    main()
