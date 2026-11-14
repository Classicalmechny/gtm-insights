#!/usr/bin/env python3
"""
BlitzAPI Find Work Email — Pass 2 fallback.

Input: merged.csv (or any CSV passed via --input) — for rows missing an
email, call BlitzAPI find-work-email and append the candidate. These
candidates are NOT verified — they must be re-verified by Instantly
(Pass 3) before being included in final.csv.

Output: <input_path>.with_blitz_emails.csv (same rows + candidate_email,
        candidate_email_source = "blitz")

Usage:
  python blitz_email_enrichment.py --run-id 2026-05-14_1330_xxx
        [--input output/<run>/merged.csv]

Docs: https://docs.blitz-api.ai/api-reference/people-enrichment/find-work-email
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from _common import (
    arg, get_key, load_checkpoint, log_event, make_session,
    normalize_domain, normalize_email, normalize_linkedin, run_dir,
    save_checkpoint,
)

BLITZ_BASE = "https://api.blitz-api.ai"
ENDPOINT = "/people/find-work-email"


def find_email(session, headers, lead: dict) -> tuple[str, dict]:
    payload = {
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "company_domain": normalize_domain(lead.get("company_domain", "")),
    }
    ln = normalize_linkedin(lead.get("linkedin_url", ""))
    if ln:
        payload["linkedin_url"] = ln

    r = session.post(BLITZ_BASE + ENDPOINT, json=payload, headers=headers, timeout=45)
    if r.status_code == 429:
        time.sleep(5)
        return "", {"error": "rate_limited"}
    if r.status_code >= 400:
        return "", {"error": r.text[:200], "status": r.status_code}
    body = r.json()
    email = body.get("email") or body.get("work_email") or ""
    return normalize_email(email), body


def main() -> None:
    run_id = arg("run-id", required=True)
    rd = run_dir(run_id)
    input_path = Path(arg("input", str(rd / "merged.csv")))
    out_path = input_path.with_suffix(".with_blitz_emails.csv")

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    with input_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("No rows in input.")
        return

    fieldnames = list(rows[0].keys())
    for col in ["candidate_email", "candidate_email_source",
                "candidate_email_raw"]:
        if col not in fieldnames:
            fieldnames.append(col)

    ckpt_name = f"blitz_email_{input_path.stem}"
    ckpt = load_checkpoint(run_id, ckpt_name, default={"done_index": -1})
    start = ckpt["done_index"] + 1
    log_event(run_id, "blitz_email.start",
              input=str(input_path), total=len(rows), start_index=start)

    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('BLITZAPI_KEY')}",
        "Content-Type": "application/json",
    }

    mode = "a" if out_path.exists() else "w"
    with out_path.open(mode, newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        for i, row in enumerate(rows):
            if i < start:
                continue
            # Skip if email already present and looks valid.
            email_existing = normalize_email(row.get("email", ""))
            if email_existing and "@" in email_existing:
                row.setdefault("candidate_email", "")
                row.setdefault("candidate_email_source", "")
                row.setdefault("candidate_email_raw", "")
                writer.writerow(row)
                save_checkpoint(run_id, ckpt_name, {"done_index": i})
                continue
            # Need name + domain to query.
            if not (row.get("first_name") and row.get("last_name") and row.get("company_domain")):
                writer.writerow(row)
                save_checkpoint(run_id, ckpt_name, {"done_index": i})
                continue

            email, body = find_email(session, headers, row)
            row["candidate_email"] = email
            row["candidate_email_source"] = "blitz" if email else ""
            row["candidate_email_raw"] = json.dumps(body, ensure_ascii=False) if email else ""
            writer.writerow(row)
            save_checkpoint(run_id, ckpt_name, {"done_index": i})
            time.sleep(0.2)

    log_event(run_id, "blitz_email.done", out_path=str(out_path))
    print(f"BlitzAPI email enrichment → {out_path}")


if __name__ == "__main__":
    main()
