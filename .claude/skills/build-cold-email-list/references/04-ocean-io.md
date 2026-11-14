# Reference 04 — Ocean.io Lookalike Companies

## When to Use
User has 3+ existing customer / aspirational account domains. Ocean.io's
core capability is finding lookalike companies based on seed domains. Far
better than industry filters alone for an ICP defined by "find more
companies like these".

## Auth
Header: `Authorization: Bearer {OCEAN_KEY}`
Or per docs, the API key may go in a header like `Api-Key`. Confirm by
reading the live docs at: https://app.ocean.io/docs/searchCompaniesV3

## Endpoint
POST `https://app.ocean.io/api/v3/companies/search`

(The skill script verifies this against the live OpenAPI spec before
issuing requests.)

## Payload Shape (key fields only)

```json
{
  "lookalike": {
    "domains": ["acme.com", "ride.io", "juno.app"]
  },
  "filters": {
    "industries": ["Software"],
    "employeeCount": { "min": 10, "max": 500 },
    "countries": ["US", "CA"],
    "foundedYear": { "min": 2015 }
  },
  "limit": 500,
  "offset": 0
}
```

The lookalike vector pulls semantically-similar companies. Filters then
constrain to ICP-conformant ones.

## Process

1. Read seed domains from `icp.json` (`seed_domains` field).
2. Build filters from ICP firmographics + geographics.
3. Paginate with `offset`. Default page size 100. Sleep 500ms between
   pages.
4. For each company, capture:
   - domain, name, linkedin_url, industry, employee_count, country,
     founded_year, hq_city, hq_state
   - `lookalike_score` if returned (use for sorting later)
5. Write `raw/ocean.csv`.

**Ocean returns companies, not people.** You MUST follow up with BlitzAPI
employee finder (Step 4 / reference 08) to find decision makers.

## Cost Notes

- Ocean charges per company returned. 500 companies ≈ 500 credits.
- Use `lookalike_score` to keep only top matches if budget-constrained
  (e.g. keep top 200 of 500).

## Output Columns (raw/ocean.csv)

```
source             = "ocean"
external_id        = ocean company id
company_name
company_domain
company_linkedin_url
company_industry
company_employee_count
country
state
city
founded_year
lookalike_score
raw_json
```

## Script
`scripts/ocean_lookalike.py` — reads `icp.json`, validates seed domain
presence, paginates, writes `raw/ocean.csv`. Idempotent.

## Failure Modes

- **No seeds in ICP** → skip Ocean entirely; log skip reason to run.log.
- **All seeds invalid** → warn user, ask for new seeds, do NOT fall back
  to industry-only search (defeats Ocean's value vs. cheaper sources).
- **API 401** → check key in env; key value: `api_b75MFh_SJ06S1LlUqBSmZeLjujOJSnH3MrQzI9x`.
