#!/usr/bin/env python3
"""Step 1: register each .co domain inside Zapmail and capture the Cloudflare
nameserver pair Zapmail issues for that domain.

After this script completes, paste `domains_with_ns.csv` into Dynadot's bulk
nameserver update tool. Wait 24h for propagation before running 02_provision_mailboxes.py.
"""
import csv
import json
import os
import sys

from zapmail_client import ZapmailClient

DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    with open(os.path.join(DIR, "domains.txt")) as f:
        domains = [ln.strip().lower() for ln in f
                   if ln.strip() and not ln.startswith("#")]
    if not domains:
        print("domains.txt is empty (only comments). Paste the 50 .co domains first.")
        sys.exit(1)

    c = ZapmailClient()
    out_rows = []
    for i, domain in enumerate(domains, 1):
        # Per docs: POST /v2/domains/name-servers returns the Cloudflare NS pair.
        # This call also registers the domain in Zapmail as "pending connection".
        r = c.call("POST", "/v2/domains/name-servers",
                   {"domainName": domain, "maskForwarding": True})
        ns_list = []
        for k in ("nameservers", "nameServers", "ns", "data"):
            v = r.get(k) if isinstance(r, dict) else None
            if isinstance(v, list):
                ns_list = v
                break
            if isinstance(v, dict):
                ns_list = list(v.values())
                break
        ns_csv = ",".join(ns_list) if ns_list else ""
        ok = "ok" if ns_list else "ERR"
        print(f"[{i:3}/{len(domains)}] {ok}  {domain}  ns={ns_csv}")
        out_rows.append({
            "domain": domain,
            "ns1": ns_list[0] if len(ns_list) > 0 else "",
            "ns2": ns_list[1] if len(ns_list) > 1 else "",
            "raw_response": json.dumps(r)[:500],
        })

    out = os.path.join(DIR, "domains_with_ns.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nWrote {out}")
    print("Next: open Dynadot, bulk-update NS for each domain to the (ns1, ns2) pair above.")


if __name__ == "__main__":
    main()
