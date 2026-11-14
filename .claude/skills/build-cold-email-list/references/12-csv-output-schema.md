# Reference 12 — Final CSV Output Schema

## Goal
A clean, drop-in CSV the user can paste into Instantly, Smartlead,
Lemlist, Apollo, or any cold-email sender.

## Required Columns (canonical order)

```
first_name
last_name
email
title
company_name
company_domain
linkedin_url
company_linkedin_url
company_industry
company_employee_count
country
state
city
phone
email_verification_status
email_risk
sources
```

These are ALWAYS present (some values may be empty for non-required
fields like `state`, `city`, `phone`).

## Optional Columns (when AI variables enabled)

After the required columns, append one column per AI variable in the
order the user defined them:
```
icebreaker
custom_angle
fit_score
... etc
```

## Optional Columns (delivery.columns_extra)

If the user requested specific extra columns in intake
(`delivery.columns_extra` in `icp.json`), append those at the end.

## Field Hygiene Rules

| Field | Rule |
|-------|------|
| `first_name`, `last_name` | Title case. Strip whitespace. Empty → drop row. |
| `email` | Lowercase. No whitespace. Empty → drop row. |
| `title` | Sentence case allowed; preserve as captured. |
| `company_name` | Preserve case as captured. Strip whitespace. |
| `company_domain` | Lowercase, no protocol, no `www.`, no trailing `/`. |
| `linkedin_url` | `https://linkedin.com/in/<slug>` shape. |
| `company_linkedin_url` | `https://linkedin.com/company/<slug>` shape. |
| `country` | Full name ("United States", not "US"). |
| `phone` | E.164 if possible (`+15555551212`). Otherwise preserve. |
| `email_verification_status` | `"valid"` or `"accept_all"` only. |
| `email_risk` | `"low"` for valid; `"medium"` for accept_all. |
| `sources` | Comma-joined alphabetical: e.g. `"instantly_supersearch,ocean_dm"`. |

## Mandatory Dropped Rows

Drop any row where:
- `email` is empty
- `email_verification_status` is not `valid` or `accept_all`
- `first_name` AND `last_name` both empty
- `company_name` empty
- `company_domain` empty AND no verified email domain to derive it from

## Summary Header (Not in CSV)

Print a summary table to the user when delivering, e.g.:

```
TAM list ready: ./output/2026-05-14_1330_us_saas_founders/final.csv

| Metric                   | Value     |
|--------------------------|-----------|
| Total rows               | 847       |
| Verified emails          | 847 (100%) |
| Accept-all flagged       | 92 (11%)  |
| Sources covered          | 4         |
| AI variables populated   | icebreaker (100%), custom_angle (98%) |
| Run time                 | 23 min    |
| Est. cost                | $42       |
```

## File Encoding
- UTF-8, no BOM.
- Comma-delimited.
- Quote fields containing commas or quotes with double-quotes (RFC 4180).
- Line endings: `\r\n` for maximum tool compatibility.

## Script
`scripts/export_csv.py` — reads `verified.csv` (or `enriched.csv` if AI
vars enabled), enforces schema, writes `final.csv`, prints the summary
table.
