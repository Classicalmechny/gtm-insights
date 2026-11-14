# Reference 05 — Instantly Supersearch (Sourcing + Email in One Pass)

## Why This Is The Backbone
Instantly Supersearch is the cheapest single source that returns
ICP-matched people WITH verified work emails. For 95% of B2B ICPs this is
the default backbone — other sources are supplementary.

## Auth
Header: `Authorization: Basic {INSTANTLY_KEY}`
The provided key is already base64-encoded for Basic auth:
`NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==`

Base URL: `https://api.instantly.ai`
All endpoints: see https://developer.instantly.ai/

## Full Pipeline (Lead Sourcing + Work Email Enrichment)

### Step A — Create a Lead List
POST `/api/v2/lead-lists`
Body:
```json
{
  "name": "TAM_<run_id>_supersearch",
  "owned_by": null
}
```
→ returns `id`. Store as `list_id`.

Docs: https://developer.instantly.ai/api-reference/leadlist/create-lead-list

### Step B — Enrich From Supersearch
POST `/api/v2/supersearch-enrichment/enrich-leads-from-supersearch`

**Critical parameters** (must be exact):
```json
{
  "resource_id": "<list_id>",
  "resource_type": "lead-list",
  "enrichment_options": {
    "enrich_work_email": true,
    "verify_work_email": true,
    "include_phone": false,
    "all_signals_enabled": true
  },
  "search_filters": {
    "person_titles": ["Founder", "Co-Founder", "CEO"],
    "person_title_excludes": ["Assistant", "Intern", "Former"],
    "person_seniorities": ["c_suite", "owner", "founder"],
    "person_departments": ["executive"],
    "person_locations": ["United States"],
    "organization_industries": ["computer software", "saas"],
    "organization_employee_counts": ["1-10", "11-50"],
    "organization_locations": ["United States"]
  },
  "skip_workspace_existing_leads": false,
  "max_leads": 2000
}
```

Key rules:
- `skip_workspace_existing_leads`: **must be false** (per source instructions —
  we want full coverage; dedupe happens downstream).
- `all_signals_enabled`: true (turns on every internal signal for max
  coverage).
- `enrich_work_email`: true + `verify_work_email`: true → emails come
  back already verified.

Docs: https://developer.instantly.ai/api-reference/supersearchenrichment/enrich-leads-from-supersearch

### Step C — Poll Enrichment Status
GET `/api/v2/supersearch-enrichment/get-enrichment-for-resource?resource_id=<list_id>&resource_type=lead-list`

Returns a job state. Poll every 30 seconds until status is `completed`
(or `failed`, `cancelled`). Expect 5–30 min for jobs of 500–2000 leads.

Docs: https://developer.instantly.ai/api-reference/supersearchenrichment/get-enrichment-for-resource

### Step D — List Leads & Paginate
GET `/api/v2/leads/list?list_id=<list_id>&limit=100&starting_after=<cursor>`

Paginate via cursor. Capture for each lead:
- first_name, last_name, email, title, linkedin_url
- email_verification_status (keep only `valid` and `accept_all`)
- company_name, company_domain, company_linkedin_url
- company_industry, company_employee_count, country, state, city
- enrichment timestamp + raw response (for debugging)

Docs: https://developer.instantly.ai/api-reference/lead/list-leads

## ICP → Instantly Filter Mapping

Instantly uses Apollo-style filter names. Map ICP fields:

| ICP field | Instantly filter |
|-----------|------------------|
| persona.titles | `person_titles` |
| persona.title_exclusions | `person_title_excludes` |
| persona.seniority | `person_seniorities` |
| persona.departments | `person_departments` |
| firmographics.industries | `organization_industries` |
| firmographics.employee_count_min/max | `organization_employee_counts` (use bucket strings) |
| firmographics.tech_stack_includes | `organization_keyword_tags` or `q_organization_technologies` (check API) |
| geographics.countries | `person_locations` AND `organization_locations` |

Employee count buckets accepted by Instantly: `1-10`, `11-50`, `51-200`,
`201-500`, `501-1000`, `1001-5000`, `5001-10000`, `10001+`. Convert
min/max into the overlapping set of buckets.

## Output Columns (raw/instantly.csv)

```
source                       = "instantly_supersearch"
external_id                  = instantly lead id
first_name
last_name
email                        ← already verified by Instantly
email_verification_status    = "valid" | "accept_all"
title
linkedin_url
company_name
company_domain
company_linkedin_url
company_industry
company_employee_count
country
state
city
enriched_at
raw_json
```

## Cost Notes

- ~$0.01–0.03 per fully enriched lead (verified email + signals).
- 1000 leads ≈ $20–30.
- Far cheaper than running BlitzAPI people search + separate email
  enrichment (~$0.05+ per lead).

## Failure Modes & Retries

- **List creation 401** → wrong/expired key.
- **Enrichment job stuck > 60 min** → cancel and retry with smaller
  `max_leads`.
- **Verification rate < 30%** → broaden filters; usually means filters
  too narrow or industry codes mismatched.
- **Always re-run from cursor** — the script persists pagination cursor
  to disk after every page.

## Script
`scripts/instantly_supersearch_pipeline.py` — full pipeline: create
list, enrich, poll, paginate, write raw CSV. Idempotent, resumable.
