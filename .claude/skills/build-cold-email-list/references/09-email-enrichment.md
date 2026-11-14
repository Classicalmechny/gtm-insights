# Reference 09 — Email Enrichment & Verification

## Goal
Every row in the final CSV has a deliverable, verified work email. A bad
email kills sender reputation — drop unverified rows ruthlessly.

## Waterfall (in order)

### Pass 1 — Instantly Supersearch (Primary)

Even for leads that came in WITHOUT emails (from Ocean, BlitzAPI, directories,
existing DB, decision_makers.csv), Instantly can enrich+verify in one pass.

Process:

1. **Create a new Instantly list** for enrichment.
   `POST /api/v2/lead-lists` with name `TAM_<run_id>_enrich`. Save `list_id`.

   Docs: https://developer.instantly.ai/api-reference/leadlist/create-lead-list

2. **Bulk add leads** to the list.
   `POST /api/v2/leads/add-leads-to-campaign-or-list` (or
   `/api/v2/leads/bulk` — check API reference for exact path)
   Body:
   ```json
   {
     "list_id": "<list_id>",
     "leads": [
       {
         "first_name": "...",
         "last_name": "...",
         "company_name": "...",
         "company_domain": "...",
         "linkedin_url": "...",
         "title": "..."
       },
       ...
     ],
     "skip_workspace_existing_leads": false
   }
   ```
   Notes:
   - **skip_workspace_existing_leads must be false** (per spec).
   - Batch in groups of 500.

   Docs: https://developer.instantly.ai/api-reference/lead/add-leads-in-bulk-to-a-campaign-or-list

3. **Create an enrichment job** that does both work email + verification:
   `POST /api/v2/supersearch-enrichment` (the "create-an-enrichment"
   endpoint).
   Body:
   ```json
   {
     "resource_id": "<list_id>",
     "resource_type": "lead-list",
     "enrichment_options": {
       "enrich_work_email": true,
       "verify_work_email": true
     }
   }
   ```

   Docs: https://developer.instantly.ai/api-reference/supersearchenrichment/create-an-enrichment

4. **Poll status**:
   `GET /api/v2/supersearch-enrichment/get-enrichment-for-resource?resource_id=<list_id>&resource_type=lead-list`
   Every 30s until `completed`.

5. **List leads & paginate**:
   `GET /api/v2/leads/list?list_id=<list_id>&limit=100&starting_after=<cursor>`
   Capture `email` + `email_verification_status`.

### Pass 2 — BlitzAPI Fallback (For Pass-1 Misses)

For leads from Pass 1 with empty email or `risky`/`invalid` status:

POST BlitzAPI `/people/find-work-email`
Header: `Authorization: Bearer {BLITZAPI_KEY}`
Payload:
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "company_domain": "acme.com",
  "linkedin_url": "https://linkedin.com/in/johndoe"  // optional but improves accuracy
}
```

Docs: https://docs.blitz-api.ai/api-reference/people-enrichment/find-work-email

Response gives a candidate email (and sometimes confidence score). BlitzAPI
does NOT verify deliverability — the email may bounce. ALWAYS re-verify in
Pass 3 before keeping.

### Pass 3 — Re-Verify Pass-2 Finds via Instantly

Add BlitzAPI-found emails to a third Instantly list and run
verification-only:
- Same `POST /api/v2/supersearch-enrichment` but with
  `enrich_work_email: false, verify_work_email: true`.
- Poll, paginate, keep verified.

## Acceptance Criteria

Keep:
- `valid` — full deliverable, highest confidence.
- `accept_all` — domain catches all; flag in CSV column
  `email_risk = "accept_all"` so user knows.

Drop:
- `risky`
- `invalid`
- `unknown`
- empty / null

## Output Files (separate per pass; concatenated at the end)

| Pass | Output file |
|------|-------------|
| Pass 1 | `verified_pass1.csv` (Instantly enrich+verify on merged leads) |
| Pass 2 | `merged.with_blitz_emails.csv` (BlitzAPI candidate emails, NOT verified) |
| Pass 3 | `verified_pass3.csv` (Instantly verify-only on Pass-2 candidates) |
| Final  | `verified.csv` = concat of pass1 + pass3 (run `scripts/concat_verified.py`) |

Schema enforced (in all verified_*.csv and verified.csv):
```
email                       (lowercase, no whitespace, non-empty)
email_verification_status   = "valid" | "accept_all"
email_provider              = "instantly" (Pass 1) | "blitz+instantly_verified" (Pass 3)
```

> The two passes write to DIFFERENT files on purpose — sharing a single
> output file collides with the pagination checkpoint
> (`instantly_email_<mode>_paginate_<list_id>`) and produces duplicate
> headers / mis-ordered rows.

## Cost Notes

- Instantly verification: included in enrichment cost (no extra fee).
- BlitzAPI find-work-email: ~1 credit per hit.
- Re-verification via Instantly (Pass 3): adds a small per-email cost.

Total per verified lead waterfall cost: usually $0.02–0.05.

## Failure Modes

- **Pass-1 verification rate < 30%** → check that domains aren't garbage
  (e.g. social media URLs in `company_domain`). Run `scripts/dedupe_merge.py
  --normalize-only` first to clean.
- **Pass-2 BlitzAPI 404 (no email found)** → drop the lead.
- **Pass-3 verification fails for Pass-2 finds** → drop the lead. Don't
  keep "guessed" emails just because we paid for them.
- **All passes empty** → row never makes it to `verified.csv`. That's correct.

## Scripts

- `scripts/instantly_email_enrichment_pipeline.py` — handles Pass 1 and
  Pass 3 (both create-list + bulk-add + enrichment + poll + paginate).
- `scripts/blitz_email_enrichment.py` — handles Pass 2.
