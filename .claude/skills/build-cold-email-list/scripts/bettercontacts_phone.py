#!/usr/bin/env python3
"""
Bettercontacts phone enrichment (one-off use).

NOT part of the default pipeline — only run when the user explicitly asks
for phone numbers on top of the email list.

Reads an input CSV (default: verified.csv or final.csv), enriches phone
numbers via Bettercontacts, writes <input>.with_phone.csv.

Bettercontacts API docs: https://bettercontact.rocks (check current docs
for exact endpoint shape — adjust below if changed).

Usage:
  python bettercontacts_phone.py --run-id <id>
        [--input output/<run>/verified.csv]
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from _common import (
    arg, get_key, load_checkpoint, log_event, make_session,
    normalize_domain, normalize_linkedin, run_dir, save_checkpoint,
)

BC_BASE = "https://app.bettercontact.rocks/api/v2"
# Bettercontacts has both async batch and single-lookup endpoints. We use
# single-lookup for simplicity and to surface failures per lead.
SINGLE_EP = "/async"   # adjust if API renames


def lookup_phone(session, headers, lead: dict) -> tuple[str, dict]:
    payload = {
        "data": [{
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company": lead.get("company_name", ""),
            "company_domain": normalize_domain(lead.get("company_domain", "")),
            "linkedin_url": normalize_linkedin(lead.get("linkedin_url", "")),
        }],
        "enrich_email_address": False,
        "enrich_phone_number": True,
    }
    r = session.post(BC_BASE + SINGLE_EP, json=payload,
                     headers=headers, timeout=60)
    if r.status_code == 429:
        time.sleep(5)
        return "", {"error": "rate_limited"}
    if r.status_code >= 400:
        return "", {"error": r.text[:200], "status": r.status_code}
    body = r.json()
    # Async response — caller may need to poll job, but for small volumes
    # the endpoint returns immediate results for single-row payloads.
    phone = ""
    try:
        results = body.get("data") or body.get("results") or []
        if results:
            phone = (results[0].get("phone") or
                     results[0].get("phone_number") or "")
    except Exception:
        pass
    return phone, body


def main() -> None:
    run_id = arg("run-id", required=True)
    rd = run_dir(run_id)
    input_path = Path(arg("input", str(rd / "verified.csv")))
    out_path = input_path.with_suffix(".with_phone.csv")
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    with input_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("No rows.")
        return

    fields = list(rows[0].keys())
    for col in ["phone_enriched", "phone_source", "phone_raw"]:
        if col not in fields:
            fields.append(col)

    ckpt_name = f"bc_phone_{input_path.stem}"
    ckpt = load_checkpoint(run_id, ckpt_name, default={"done_index": -1})
    start = ckpt["done_index"] + 1
    log_event(run_id, "bc_phone.start",
              input=str(input_path), total=len(rows), start=start)

    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('BETTERCONTACTS')}",
        "Content-Type": "application/json",
    }

    mode = "a" if out_path.exists() else "w"
    with out_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        for i, row in enumerate(rows):
            if i < start:
                continue
            row.setdefault("phone_enriched", "")
            row.setdefault("phone_source", "")
            row.setdefault("phone_raw", "")
            if row.get("phone"):  # already have one from source
                writer.writerow(row)
                save_checkpoint(run_id, ckpt_name, {"done_index": i})
                continue
            phone, body = lookup_phone(session, headers, row)
            row["phone_enriched"] = phone
            row["phone_source"] = "bettercontacts" if phone else ""
            row["phone_raw"] = json.dumps(body, ensure_ascii=False) if phone else ""
            writer.writerow(row)
            save_checkpoint(run_id, ckpt_name, {"done_index": i})
            time.sleep(0.2)

    log_event(run_id, "bc_phone.done", output=str(out_path))
    print(f"Bettercontacts phone enrichment → {out_path}")


if __name__ == "__main__":
    main()
