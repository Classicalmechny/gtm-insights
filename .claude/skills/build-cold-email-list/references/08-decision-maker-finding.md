# Reference 08 — Decision Maker Finding (BlitzAPI Employee Finder)

## When to Use
Any time a company-only source contributed to the merged list. Sources
that need DM finding:
- Ocean.io (returns companies only)
- BlitzAPI company search (returns companies only)
- Niche directories (often companies only)
- Existing GitHub DB (mostly companies)

People-level sources (Instantly Supersearch, BlitzAPI people search)
already return people — skip this step for those rows.

## Endpoint
BlitzAPI: `POST /people/employee-finder`
Header: `Authorization: Bearer {BLITZAPI_KEY}`

Docs: https://docs.blitz-api.ai/api-reference/people-search/employee-finder

## Payload Shape

```json
{
  "company_domain": "acme.com",
  "title_keywords": ["Founder", "Co-Founder", "CEO"],
  "title_keywords_exclude": ["Assistant", "Intern", "Former"],
  "seniority": ["c_suite", "owner", "founder"],
  "departments": ["executive"],
  "limit": 3
}
```

- `limit` is per-company DM cap. Default 3 (configurable per ICP via
  `persona.dms_per_company`).
- Persona filters come from `icp.json` — re-use exactly what you used
  for people-level sourcing.

## Process

1. Concatenate domains from all company-only raw CSVs. Dedupe.
2. For each domain, call employee-finder with the ICP persona.
3. Collect all returned people into `raw/decision_makers.csv` with
   `source = "<original_source>_dm"` (e.g. `ocean_dm`, `clutch_dm`,
   `existing_db_crunchbase_dm`).
4. Rate limit: 5 RPS. Sleep + exponential backoff on 429.

## Output Columns (raw/decision_makers.csv)

Same schema as `raw/blitz_people.csv`, plus:
```
source                 = "<orig>_dm"
sourced_from_domain    = the domain we queried
```

## Cost Notes
- BlitzAPI charges per person returned. 1000 companies × 3 DMs ≈ 3000
  credits.
- If the ICP says "1 DM per company is enough" (e.g. just the CEO),
  drop `limit` to 1 to save 2/3 of credits.

## Quality Heuristics

- If a company returns 0 DMs matching the persona → keep the company in
  a `no_dm_found.csv` debug file so the user can spot-check.
- If we get an obvious wrong-title hit (employee finder occasionally
  returns adjacent titles) → filter post-fetch using the strict
  title_keywords from `icp.json`.

## Failure Modes

- **Domain has no LinkedIn presence** → BlitzAPI returns empty. Log,
  skip.
- **Domain points to a parent company** (e.g. multi-brand conglomerate)
  → employee finder returns DMs from the wrong subsidiary. Mitigation:
  pass `company_linkedin_url` instead of just `company_domain` when
  available — the script prefers `company_linkedin_url` from the source
  CSV row.

## Script
`scripts/blitz_employee_finder.py` — reads all company-only raw CSVs,
dedupes domains, queries BlitzAPI, writes `raw/decision_makers.csv`.
Idempotent — keeps a checkpoint file of completed domains.
