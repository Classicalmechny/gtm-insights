#!/usr/bin/env python3
"""
Dedupe & Merge.

Reads every CSV under output/<run_id>/raw/, normalizes fields, dedupes
by (LinkedIn URL | email | domain+name), picks the most complete row
per match group, and writes merged.csv.

Honors exclusions from icp.json (competitor_domains, customer_domains,
blocklist_domains).

Usage:
  python dedupe_merge.py --run-id <id>
        [--normalize-only]   # skip dedupe step
        [--dry-run]          # don't write merged.csv, just log stats
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict

from _common import (
    arg, append_csv, load_json, log_event, normalize_country,
    normalize_domain, normalize_email, normalize_linkedin, normalize_name,
    run_dir,
)

# Higher = more trusted as canonical when picking from a match group.
SOURCE_PRIORITY = {
    "instantly_supersearch": 100,
    "blitz_people": 90,
    "existing_db_crunchbase": 70,
    "existing_db_gmaps": 60,
    # Pure company sources rarely act as canonical for people-shaped output,
    # but provide context fields. Keep them defined to avoid 0 priority.
    "ocean": 40,
    "blitz_companies": 40,
    # _dm sources sit between people-level and pure company.
    "ocean_dm": 55,
    "blitz_companies_dm": 55,
    "existing_db_crunchbase_dm": 55,
    "existing_db_gmaps_dm": 50,
}

CRITICAL_FIELDS = [
    "first_name", "last_name", "title", "email", "linkedin_url",
    "company_domain", "country",
]

MERGED_FIELDS = [
    "sources", "external_ids",
    "first_name", "last_name", "full_name",
    "title", "linkedin_url",
    "email", "email_verification_status",
    "company_name", "company_domain", "company_linkedin_url",
    "company_industry", "company_employee_count",
    "country", "state", "city", "phone",
]


def normalize_row(row: dict) -> dict:
    out = {k: (v or "").strip() if isinstance(v, str) else v for k, v in row.items()}
    out["first_name"] = normalize_name(out.get("first_name", ""))
    out["last_name"] = normalize_name(out.get("last_name", ""))
    full = out.get("full_name", "") or f'{out["first_name"]} {out["last_name"]}'.strip()
    out["full_name"] = normalize_name(full)
    out["linkedin_url"] = normalize_linkedin(out.get("linkedin_url", ""))
    out["company_linkedin_url"] = normalize_linkedin(out.get("company_linkedin_url", ""))
    out["company_domain"] = normalize_domain(out.get("company_domain", ""))
    out["email"] = normalize_email(out.get("email", ""))
    out["country"] = normalize_country(out.get("country", ""))
    return out


def quality_filters(row: dict, icp: dict) -> str | None:
    """Returns a drop reason string, or None if the row passes."""
    if not (row.get("first_name") or row.get("last_name") or row.get("full_name")):
        return "no_name"
    if not (row.get("company_name") or row.get("company_domain")):
        return "no_company"
    # Detect company URL accidentally in linkedin_url
    ln = row.get("linkedin_url", "")
    if ln and "/company/" in ln:
        return "linkedin_is_company"
    # Title exclusions
    excludes = [t.lower() for t in (icp.get("persona", {}).get("title_exclusions") or [])]
    title_lower = (row.get("title") or "").lower()
    if title_lower and any(e in title_lower for e in excludes):
        return "title_exclusion"
    # Blocklist
    blocklist = set()
    for key in ("competitor_domains", "customer_domains", "blocklist_domains"):
        for d in icp.get("exclusions", {}).get(key, []):
            blocklist.add(normalize_domain(d))
    if row.get("company_domain") in blocklist:
        return "blocklist"
    return None


def match_keys(row: dict) -> list[tuple[str, str]]:
    keys = []
    if row.get("linkedin_url"):
        keys.append(("ln", row["linkedin_url"]))
    if row.get("email"):
        keys.append(("email", row["email"]))
    domain = row.get("company_domain") or ""
    full = row.get("full_name") or f'{row.get("first_name","")} {row.get("last_name","")}'.strip()
    full_norm = re.sub(r"\s+", " ", full.lower()).strip()
    if domain and full_norm:
        keys.append(("dn", f"{domain}|{full_norm}"))
    return keys


def completeness(row: dict) -> int:
    return sum(1 for k in CRITICAL_FIELDS if (row.get(k) or "").strip())


def pick_canonical(group: list[dict]) -> dict:
    """Return a merged row: pick the most complete, fill blanks from others."""
    # Sort by (completeness desc, source priority desc).
    def keyfn(r):
        return (
            -completeness(r),
            -SOURCE_PRIORITY.get(r.get("source", ""), 0),
        )
    group_sorted = sorted(group, key=keyfn)
    canonical = dict(group_sorted[0])
    # Fill blanks from rest (never overwrite non-empty canonical fields).
    for r in group_sorted[1:]:
        for k, v in r.items():
            if not v:
                continue
            if not (canonical.get(k) or "").strip():
                canonical[k] = v
    sources = sorted({r.get("source", "") for r in group if r.get("source")})
    ext_ids = sorted({
        f'{r.get("source","")}:{r.get("external_id","")}'
        for r in group if r.get("external_id")
    })
    canonical["sources"] = ",".join(sources)
    canonical["external_ids"] = ",".join(ext_ids)
    return canonical


def run(run_id: str, normalize_only: bool, dry_run: bool) -> None:
    rd = run_dir(run_id)
    icp = load_json(rd / "icp.json")
    raw_dir = rd / "raw"
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        raise SystemExit(f"No raw CSVs in {raw_dir}")

    rows_by_source = defaultdict(int)
    drops = defaultdict(int)
    all_rows = []

    for f in files:
        with f.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                norm = normalize_row(row)
                reason = quality_filters(norm, icp)
                if reason:
                    drops[reason] += 1
                    continue
                all_rows.append(norm)
                rows_by_source[norm.get("source", "unknown")] += 1

    log_event(run_id, "dedupe_merge.normalized",
              total=len(all_rows), by_source=dict(rows_by_source),
              dropped=dict(drops))

    if normalize_only:
        if not dry_run:
            out = rd / "merged.csv"
            for r in all_rows:
                append_csv(out, [r], MERGED_FIELDS)
            print(f"Normalized {len(all_rows)} rows (no dedupe) → {out}")
        return

    # Union-find over match keys.
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    row_keys = [match_keys(r) for r in all_rows]
    key_to_rep = {}
    for idx, keys in enumerate(row_keys):
        anchor = f"row:{idx}"
        parent[anchor] = anchor
        for k in keys:
            ks = f"{k[0]}:{k[1]}"
            if ks in key_to_rep:
                union(anchor, key_to_rep[ks])
            else:
                key_to_rep[ks] = anchor
                parent[ks] = ks
                union(anchor, ks)

    groups = defaultdict(list)
    for idx, _ in enumerate(all_rows):
        root = find(f"row:{idx}")
        groups[root].append(idx)

    merged_rows = []
    for _, indices in groups.items():
        group = [all_rows[i] for i in indices]
        canon = pick_canonical(group)
        merged_rows.append(canon)

    log_event(run_id, "dedupe_merge.deduped",
              input_count=len(all_rows),
              output_count=len(merged_rows),
              collapsed=len(all_rows) - len(merged_rows))

    if dry_run:
        print(f"DRY RUN — would write {len(merged_rows)} merged rows.")
        return

    out = rd / "merged.csv"
    if out.exists():
        out.unlink()
    for r in merged_rows:
        append_csv(out, [r], MERGED_FIELDS)
    print(f"Merged → {len(merged_rows)} rows → {out}")


def main() -> None:
    run_id = arg("run-id", required=True)
    normalize_only = "--normalize-only" in __import__("sys").argv
    dry_run = "--dry-run" in __import__("sys").argv
    run(run_id, normalize_only, dry_run)


if __name__ == "__main__":
    main()
