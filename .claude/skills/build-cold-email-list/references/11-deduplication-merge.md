# Reference 11 — Deduplication & Merge

## Goal
Collapse all `raw/*.csv` into a single `merged.csv` with one row per
unique person. Preserve provenance.

## Match Keys (priority order)

For each row, generate THREE possible match keys, in priority order:

1. **Normalized LinkedIn URL**
   - Lowercase
   - Strip trailing `/`
   - Drop query string and fragment
   - Drop tracking params (`?trk=`, `?lipi=`)
   - Normalize host to `linkedin.com` (drop `www.`, `m.`, country subdomains
     like `de.linkedin.com` → `linkedin.com`)

2. **Normalized email** (if present in source row)
   - Lowercase
   - Strip whitespace

3. **Domain + normalized full name**
   - Domain: lowercase, strip protocol, strip `www.`, strip trailing `/`
   - Full name: `(first_name + " " + last_name).lower().strip()` —
     remove punctuation, collapse multiple spaces

## Match Strategy

Group rows where ANY of the three keys match. For each group:

1. **Pick the most complete row** as the canonical record:
   - Highest count of non-empty critical fields:
     `first_name, last_name, title, email, linkedin_url, company_domain, country`
   - On ties, prefer the row whose `source` returns highest priority:
     `instantly_supersearch > blitz_people > existing_db_* > ocean_dm > clutch_dm > realtor_dm > ...`
     (priority based on data quality)

2. **Fill missing fields** from other rows in the group (best-effort
   merge — never overwrite a non-empty canonical field with a different
   value from a less-trusted row).

3. **Collect provenance**: a `sources` column = comma-joined sorted list
   of all source names in the group.

## Field Normalization (before matching)

- `company_domain`: strip `https?://`, strip `www.`, strip trailing `/`,
  lowercase. If domain has a path (`acme.com/about`), keep only the
  netloc.
- `linkedin_url`: as above; coerce to `https://linkedin.com/in/<slug>`
  shape.
- `first_name`, `last_name`: title-case, strip whitespace, drop trailing
  punctuation. Special handling: handle "Jr.", "III", "MBA", "PhD" by
  moving them out of the last_name into a separate `suffix` field
  (optional).
- `email`: lowercase, strip whitespace.
- `country`: standardize to country full name (e.g. "US" → "United States",
  "UK" → "United Kingdom") using a small ISO-2/ISO-3 lookup table.

## Quality Filters (drop rows that fail)

- No `first_name` AND no `last_name` AND no `full_name` → drop.
- No `company_domain` AND no `company_name` → drop.
- `linkedin_url` looks like a person but the slug has `/company/` → drop
  (it's a company URL, not a person URL).
- Honor `exclusions.blocklist_domains` and `exclusions.customer_domains`
  → drop rows whose `company_domain` matches.
- Drop rows where `title` matches `persona.title_exclusions` (case-
  insensitive substring).

## Output Columns (merged.csv)

```
sources                   # comma-joined: e.g. "instantly_supersearch,ocean_dm"
external_ids              # comma-joined: e.g. "inst:abc123,blitz:xyz789"
first_name
last_name
full_name                 # filled if first/last missing
title
linkedin_url              # normalized
email                     # may be empty — Step 6 fills
email_verification_status # may be empty — Step 6 fills
company_name
company_domain            # normalized
company_linkedin_url
company_industry
company_employee_count
country
state
city
phone                     # if any source provided
```

## Audit

After dedupe, write a per-source stats block to `run.log`:
```json
{
  "step": "dedupe_merge",
  "input_counts": {"instantly": 1500, "ocean_dm": 480, ...},
  "output_count": 1820,
  "dropped_no_name": 15,
  "dropped_no_company": 8,
  "dropped_exclusion": 12,
  "dedupe_collapsed": 125
}
```

## Script
`scripts/dedupe_merge.py` — reads all `raw/*.csv` files in the run
directory, applies normalization + dedupe, writes `merged.csv` + audit
to `run.log`.

Flags:
- `--normalize-only` — just normalize without dedupe (for debugging).
- `--dry-run` — log stats without writing the output file.
