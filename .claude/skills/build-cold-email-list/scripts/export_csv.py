#!/usr/bin/env python3
"""
Final CSV Export.

Reads enriched.csv if present (Step 7 was run), otherwise verified.csv.
Enforces the canonical schema (reference 12), normalizes fields, drops
rows missing any required field, writes final.csv, and prints a summary
table.

Usage:
  python export_csv.py --run-id <id>
"""
from __future__ import annotations

import csv
from collections import Counter

from _common import (
    arg, load_json, log_event, normalize_country, normalize_domain,
    normalize_email, normalize_linkedin, normalize_name, run_dir,
)

REQUIRED_COLS = [
    "first_name", "last_name", "email", "title",
    "company_name", "company_domain",
    "linkedin_url", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city",
    "phone",
    "email_verification_status", "email_risk",
    "sources",
]


def main() -> None:
    run_id = arg("run-id", required=True)
    rd = run_dir(run_id)

    icp = {}
    icp_path = rd / "icp.json"
    if icp_path.exists():
        icp = load_json(icp_path)

    # AI variable column names come from ai_spec.json (single source of truth
    # if it exists), otherwise from icp.ai_variables.variables.
    ai_spec_path = rd / "ai_spec.json"
    if ai_spec_path.exists():
        spec = load_json(ai_spec_path)
        spec_vars = [v.get("name", "") for v in spec.get("variables", []) if v.get("name")]
        if spec_vars:
            icp.setdefault("ai_variables", {})["variables"] = [
                {"name": n} for n in spec_vars
            ]

    enriched_path = rd / "enriched.csv"
    verified_path = rd / "verified.csv"
    if enriched_path.exists():
        source_path = enriched_path
    elif verified_path.exists():
        source_path = verified_path
    else:
        raise SystemExit("Neither enriched.csv nor verified.csv exists.")

    with source_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise SystemExit(f"{source_path} is empty.")

    # AI variable columns to append (from icp.ai_variables).
    ai_vars = [v.get("name", "") for v in icp.get("ai_variables", {}).get("variables", [])]
    extra_cols = icp.get("delivery", {}).get("columns_extra", [])

    out_cols = REQUIRED_COLS + ai_vars + extra_cols
    # Dedupe column order while preserving first appearance.
    seen = set()
    final_cols = []
    for c in out_cols:
        if c not in seen:
            seen.add(c)
            final_cols.append(c)

    # Hygiene + drop bad rows.
    cleaned = []
    drops = Counter()
    source_counts = Counter()
    ver_status_counts = Counter()
    risk_counts = Counter()
    ai_var_fill = {v: 0 for v in ai_vars}

    for r in rows:
        email = normalize_email(r.get("email", ""))
        status = (r.get("email_verification_status") or "").lower()
        if not email or "@" not in email:
            drops["no_email"] += 1
            continue
        if status not in ("valid", "accept_all"):
            drops["unverified"] += 1
            continue
        first = normalize_name(r.get("first_name", ""))
        last = normalize_name(r.get("last_name", ""))
        if not first and not last:
            drops["no_name"] += 1
            continue
        if not (r.get("company_name") or r.get("company_domain")):
            drops["no_company"] += 1
            continue

        domain = normalize_domain(r.get("company_domain", ""))
        if not domain and "@" in email:
            domain = email.split("@", 1)[1]
        out = {
            "first_name": first,
            "last_name": last,
            "email": email,
            "title": (r.get("title") or "").strip(),
            "company_name": (r.get("company_name") or "").strip(),
            "company_domain": domain,
            "linkedin_url": normalize_linkedin(r.get("linkedin_url", "")),
            "company_linkedin_url": normalize_linkedin(r.get("company_linkedin_url", "")),
            "company_industry": (r.get("company_industry") or "").strip(),
            "company_employee_count": (r.get("company_employee_count") or "").strip(),
            "country": normalize_country(r.get("country", "")),
            "state": (r.get("state") or "").strip(),
            "city": (r.get("city") or "").strip(),
            "phone": (r.get("phone") or "").strip(),
            "email_verification_status": status,
            "email_risk": "low" if status == "valid" else "medium",
            "sources": (r.get("sources") or r.get("source") or "").strip(),
        }
        for v in ai_vars:
            val = (r.get(v) or "").strip()
            out[v] = val
            if val:
                ai_var_fill[v] += 1
        for c in extra_cols:
            out[c] = (r.get(c) or "").strip()
        cleaned.append(out)

        source_counts[out["sources"]] += 1
        ver_status_counts[status] += 1
        risk_counts[out["email_risk"]] += 1

    out_path = rd / "final.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=final_cols, extrasaction="ignore",
                           quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        w.writeheader()
        for row in cleaned:
            w.writerow(row)

    summary = {
        "total_rows": len(cleaned),
        "verified_status_breakdown": dict(ver_status_counts),
        "risk_breakdown": dict(risk_counts),
        "source_breakdown": dict(source_counts),
        "ai_variable_fill_rate": {
            v: f"{ai_var_fill[v]}/{len(cleaned)}" for v in ai_vars
        },
        "drops": dict(drops),
        "input_path": str(source_path),
        "output_path": str(out_path),
    }
    log_event(run_id, "export.done", **summary)

    print("\n=== Final CSV ===")
    print(f"Output: {out_path}")
    print(f"Rows: {len(cleaned)}")
    if drops:
        print(f"Dropped during export: {dict(drops)}")
    print(f"Verification: {dict(ver_status_counts)}")
    print(f"Sources: {dict(source_counts)}")
    if ai_vars:
        print(f"AI variable fill rates: {summary['ai_variable_fill_rate']}")


if __name__ == "__main__":
    main()
