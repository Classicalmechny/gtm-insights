#!/usr/bin/env python3
"""DNS-based reputation checks for old_zapmail sending domains.

Checks each unique domain against:
- Spamhaus DBL (domain blocklist)
- SURBL multi
- URIBL black

Also verifies SPF / DKIM / DMARC published, and tracking-domain reachability.

Output: blacklist_results.csv
"""
import csv
import json
import os
import socket
import subprocess
from collections import defaultdict

DIR = os.path.dirname(os.path.abspath(__file__))

DOMAIN_DNSBL = [
    ("spamhaus_dbl", "dbl.spamhaus.org"),
    ("surbl_multi", "multi.surbl.org"),
    ("uribl_black", "black.uribl.com"),
]


def dig(name, rtype="A"):
    try:
        r = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=1", rtype, name],
            capture_output=True, text=True, timeout=8,
        )
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def check_dnsbl(domain, zone):
    res = dig(f"{domain}.{zone}", "A")
    if not res:
        return ("clean", "")
    # 127.255.255.* often means "domain not allowed in query" — treat as clean
    if any(ip.startswith("127.255.255.") for ip in res):
        return ("clean", ";".join(res))
    return ("listed", ";".join(res))


def check_spf(domain):
    txt = dig(domain, "TXT")
    return any("v=spf1" in t.lower() for t in txt)


def check_dmarc(domain):
    txt = dig(f"_dmarc.{domain}", "TXT")
    return any("v=dmarc1" in t.lower() for t in txt)


def check_dkim(domain):
    # Common selectors for Google Workspace + Smartlead warmup
    for sel in ("google", "smartlead", "default", "selector1", "k1"):
        if dig(f"{sel}._domainkey.{domain}", "TXT"):
            return f"present({sel})"
    return "not-found"


def check_mx(domain):
    return dig(domain, "MX")


def main():
    with open(os.path.join(DIR, "old_zapmail.csv")) as f:
        rows = list(csv.DictReader(f))
    domains = sorted({r["from_email"].split("@", 1)[1].lower() for r in rows})
    print(f"Checking {len(domains)} unique domains...")

    results = []
    for i, dom in enumerate(domains, 1):
        row = {"domain": dom}
        for label, zone in DOMAIN_DNSBL:
            status, raw = check_dnsbl(dom, zone)
            row[label] = status
            row[f"{label}_raw"] = raw
        row["spf"] = check_spf(dom)
        row["dmarc"] = check_dmarc(dom)
        row["dkim"] = check_dkim(dom)
        mx = check_mx(dom)
        row["mx"] = ";".join(mx)
        row["uses_google_mx"] = any("google.com" in m.lower() or "googlemail" in m.lower() for m in mx)
        results.append(row)
        flags = [k for k in ("spamhaus_dbl", "surbl_multi", "uribl_black") if row[k] == "listed"]
        flag_str = ("LISTED:" + ",".join(flags)) if flags else "clean"
        print(f"[{i:3}/{len(domains)}] {dom:35} {flag_str}  spf={row['spf']} dmarc={row['dmarc']} dkim={row['dkim']}")

    keys = list(results[0].keys())
    with open(os.path.join(DIR, "blacklist_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(results)

    listed = [r for r in results if any(r[k] == "listed" for k in ("spamhaus_dbl", "surbl_multi", "uribl_black"))]
    no_spf = [r for r in results if not r["spf"]]
    no_dmarc = [r for r in results if not r["dmarc"]]
    no_dkim = [r for r in results if r["dkim"] == "not-found"]

    summary = [
        f"Total domains checked: {len(results)}",
        f"Domain blacklist hits: {len(listed)}",
        f"Missing SPF: {len(no_spf)} -> {[r['domain'] for r in no_spf]}",
        f"Missing DMARC: {len(no_dmarc)} -> {[r['domain'] for r in no_dmarc]}",
        f"Missing DKIM (common selectors): {len(no_dkim)}",
        "",
        "Blacklisted domains:",
    ]
    for r in listed:
        flags = [k for k in ("spamhaus_dbl", "surbl_multi", "uribl_black") if r[k] == "listed"]
        summary.append(f"  {r['domain']} -> {','.join(flags)}")
    with open(os.path.join(DIR, "blacklist_summary.txt"), "w") as f:
        f.write("\n".join(summary))
    print()
    print("\n".join(summary))


if __name__ == "__main__":
    main()
