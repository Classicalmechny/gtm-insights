# Reference 03 — BlitzAPI

LinkedIn-backed API. Three endpoints used by this skill:
- People Search
- Company Search
- Employee Finder (decision-maker enrichment) — see `references/08`
- Find Work Email (enrichment) — see `references/09`

## Auth
Header: `Authorization: Bearer {BLITZAPI_KEY}`

Base URL (per docs): `https://api.blitz-api.ai` (confirm by hitting docs
endpoint first). All endpoints POST JSON. Endpoint paths from docs:
- `/people/search` — people search
- `/company/search` — company search
- `/people/employee-finder` — decision makers at a company
- `/people/find-work-email` — work email enrichment

> Docs: https://docs.blitz-api.ai/

## People Search

Maps the ICP persona + firmographics + geo to a single search.

Payload shape (validate against docs at runtime — fields evolve):

```json
{
  "title_keywords": ["Founder", "Co-Founder", "CEO"],
  "title_keywords_exclude": ["Assistant", "Intern", "Former"],
  "seniority": ["c_suite", "owner", "founder"],
  "departments": ["executive"],
  "industries": ["Software", "Computer Software"],
  "industries_exclude": ["Government", "Non-Profit"],
  "employee_count_min": 2,
  "employee_count_max": 50,
  "countries": ["United States"],
  "limit": 1000,
  "page": 1
}
```

- Page through until `limit` reached or API signals end of results.
- Default `limit` per page: 100. Sleep 250ms between pages to be safe.
- Save raw response shape — we'll normalize later.

## Company Search

Same shape, no person fields. Use when:
- You need a company list first (e.g. to pair with DM finding).
- You're filtering on firmographics that don't slice well via people search.

```json
{
  "industries": ["Marketing & Advertising"],
  "employee_count_min": 5,
  "employee_count_max": 50,
  "countries": ["United States", "Canada"],
  "founded_year_min": 2015,
  "limit": 500,
  "page": 1
}
```

## Output Columns (normalized into raw/blitz_people.csv)

```
source                 = "blitz_people"
external_id            = blitz unique id
first_name
last_name
full_name
title
linkedin_url
company_name
company_domain
company_linkedin_url
company_employee_count
company_industry
country
state
city
raw_json               = full raw response (for debugging only — strip later)
```

For company search → raw/blitz_companies.csv has just the company-side
columns plus `company_domain` as the primary key.

## Rate Limits & Retry

- Default to 5 RPS. If 429 → exponential backoff (1s, 2s, 4s, 8s, then
  raise).
- Persist a checkpoint after every page so retries are cheap.

## Cost Notes

- Each "search hit" returned typically costs 1 credit. People search of
  1000 leads ≈ 1000 credits.
- Company search is usually cheaper per row but you still need DM finding,
  which costs again.

## Script: `scripts/blitz_people_search.py`
Reads `icp.json`, builds the payload, paginates, writes
`raw/blitz_people.csv`. Idempotent — checks for existing CSV and resumes
from last completed page.

## Script: `scripts/blitz_company_search.py`
Same pattern, writes `raw/blitz_companies.csv`.
