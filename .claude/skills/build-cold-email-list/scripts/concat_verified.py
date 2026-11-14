#!/usr/bin/env python3
"""
Concatenate verified_pass1.csv + verified_pass3.csv → verified.csv.

Pass 1 (Instantly enrich+verify on all merged leads) and Pass 3
(Instantly verify-only on BlitzAPI-found candidate emails) both produce
verified rows, but write to separate files to avoid collision. This
script stitches them together, dedupes by email (Pass 1 wins on
conflict), and writes the canonical verified.csv that Step 7 / 8 read.

Usage:
  python concat_verified.py --run-id <id>
"""
from __future__ import annotations

import csv
from pathlib import Path

from _common import arg, log_event, normalize_email, run_dir

OUT_FIELDS = [
    "sources", "external_ids", "first_name", "last_name", "full_name",
    "title", "linkedin_url", "email", "email_verification_status",
    "email_provider", "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city", "phone",
]


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    run_id = arg("run-id", required=True)
    rd = run_dir(run_id)
    p1 = rd / "verified_pass1.csv"
    p3 = rd / "verified_pass3.csv"
    out = rd / "verified.csv"

    rows_p1 = read_rows(p1)
    rows_p3 = read_rows(p3)

    by_email: dict[str, dict] = {}
    # Pass 1 first so it wins on conflict.
    for r in rows_p1:
        e = normalize_email(r.get("email", ""))
        if not e:
            continue
        r["email"] = e
        r["email_provider"] = r.get("email_provider") or "instantly"
        by_email[e] = r
    for r in rows_p3:
        e = normalize_email(r.get("email", ""))
        if not e or e in by_email:
            continue
        r["email"] = e
        # Pass-3 emails came from BlitzAPI and were re-verified by Instantly.
        r["email_provider"] = "blitz+instantly_verified"
        by_email[e] = r

    if out.exists():
        out.unlink()
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in by_email.values():
            w.writerow(r)

    log_event(run_id, "verified.concat",
              pass1=len(rows_p1), pass3=len(rows_p3),
              final=len(by_email), output=str(out))
    print(f"verified.csv → {len(by_email)} rows (pass1={len(rows_p1)}, "
          f"pass3={len(rows_p3)})")


if __name__ == "__main__":
    main()
