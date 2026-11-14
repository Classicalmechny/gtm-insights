# Reference 07 — Existing Pre-Scraped Database (GitHub)

## Source
Repo: https://github.com/growthenginenowoslawski/coldoutboundskills/tree/main/Common%20Outbound%20Lists

This is a free, pre-scraped dataset with two main subsets:

| Subset | What it covers | When to use |
|--------|----------------|-------------|
| Crunchbase | SaaS, startups, VC-funded B2B companies | Any ICP where the target is "tech / SaaS / startup / scale-up" |
| Google Maps US | US local businesses across most consumer / SMB verticals | Any US-local-services ICP (restaurants, gyms, plumbers, dentists, retail, etc.) |

## Why Start Here
- **Free.** Zero per-lead cost.
- **High coverage** for the two segments above.
- **Massive head start** before paid sources.

## How To Use

1. **First run / cache check:** if not already cached locally at
   `~/.cache/cold-outbound-db/`, clone the repo (or download the
   relevant CSV files).
   ```
   git clone https://github.com/growthenginenowoslawski/coldoutboundskills \
       ~/.cache/cold-outbound-db
   ```
   (Skill script does this automatically and only refreshes weekly.)

2. **Filter locally** with pandas — no API call needed. Apply the ICP's
   firmographics + geographics directly to the CSV. Example filters:
   - Crunchbase: `industry`, `total_funding_usd`, `employee_count`,
     `country`, `last_funding_at`.
   - Google Maps: `category`, `state`, `city`, `rating`, `review_count`,
     `phone`, `website`.

3. **Output to `raw/existing_db_<subset>.csv`** with the canonical schema
   (see below). Crunchbase rows usually have just company info →
   downstream Step 4 (decision-maker finding) adds people. Google Maps
   rows are companies + sometimes owner names.

## Schema After Filtering (raw/existing_db_*.csv)

```
source                = "existing_db_crunchbase" | "existing_db_gmaps"
external_id           = row id from source
company_name
company_domain        (Crunchbase: from website column; Maps: derived from website URL)
company_industry      (Crunchbase: category; Maps: vertical/category)
company_employee_count
country / state / city
phone                 (Maps: present; Crunchbase: rarely)
website
funding_total         (Crunchbase only)
last_funding_at       (Crunchbase only)
rating                (Maps only)
review_count          (Maps only)
raw_json
```

For Google Maps rows that already include an owner name, also capture
`full_name` so we can match it during DM finding instead of paying for a
fresh lookup.

## Routing Hints
- If ICP says "B2B SaaS" → start with Crunchbase subset.
- If ICP says "US local <vertical>" → start with Google Maps subset.
- If both apply (rare) → use both, dedupe by domain in Step 5.

## Caching Behavior
- Refresh local cache weekly. Store a `last_refreshed` timestamp at
  `~/.cache/cold-outbound-db/.last_refreshed`.
- If cache is stale and we're online, the script refreshes automatically.
- If offline, use stale cache and log a warning.

## Failure Modes
- **GitHub rate limit on clone** → fall back to direct CSV download URLs.
- **Schema drift** (columns renamed in repo) → log a warning, attempt
  best-effort column mapping, ask user to verify counts.

## Script
`scripts/existing_db_filter.py` — clones/updates cache, applies ICP
filters, writes `raw/existing_db_<subset>.csv`. Idempotent.
