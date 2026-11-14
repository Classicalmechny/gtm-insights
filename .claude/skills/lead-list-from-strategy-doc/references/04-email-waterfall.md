# Reference 04 — Email Enrichment Waterfall (4 passes)

## Why the order matters

Cheapest + highest-confidence first. Each pass only processes rows still missing an email.

## Pass 1 — Apollo CSV pre-verified emails
**Free. Pre-verified.**
If user provided Apollo CSV exports, parse and join by LinkedIn URL or (first_name + last_name + company_domain). Keep `Email Status == valid` (drop `accept_all` if you want stricter). ~25-30% of Apollo rows have verified emails.

Script: `scripts/11_ingest_apollo.py`.

## Pass 2 — Storeleads `emails_from_storeleads` (brand-level fallback)
**Free. Brand-level.**
Storeleads exposes a comma/colon-separated `emails` field with public info@/hello@/founder@ addresses on most brands. Use as fallback when no personal email found yet — these still work for cold outreach to small DTC brands.

Prefer `founder@` / `ceo@` / `owner@` / `hello@` over `info@` / `support@`.

```python
emails = parse(brand["emails_from_storeleads"])
chosen = next((e for e in emails if any(k in e for k in ["founder","ceo","owner","hello"])), emails[0] if emails else None)
```

Mark `email_source=storeleads_public_email` so segmentation can choose to deprioritize these.

## Pass 3 — BlitzAPI find-work-email
**$$ per credit. Per-LinkedIn-URL.**

```python
POST https://api.blitz-api.ai/v2/enrichment/email
Header: x-api-key: <BLITZAPI_KEY>
Body: { "person_linkedin_url": "https://linkedin.com/in/..." }
```

Returns `{found, email, all_emails: [...]}`. Hit rate ~25-30% on senior leads at small DTC brands.

Important: Some BlitzAPI DMs (especially from recovered/loose brands) have low recall — their LinkedIn URLs aren't indexed. Don't be surprised if hit rate is 0% on a subset.

Script pattern in `scripts/19_waterfall_round3.py` Step A and `scripts/27_final_blitz_and_waterfall.py`.

## Pass 4 — Instantly Supersearch enrich + verify
**$$. Bulk operation. ~15min latency.**

Submit two jobs (enrich + verify) per list:

```python
POST /api/v2/supersearch-enrichment
Header: Authorization: Bearer <INSTANTLY_KEY>
Body: { "resource_id": "<list_id>", "resource_type": "lead-list",
        "type": "work_email_enrichment", "limit": 5000 }

POST /api/v2/supersearch-enrichment
Body: { "resource_id": "<list_id>", "resource_type": "lead-list",
        "type": "email_verification", "limit": 5000 }
```

Endpoints (verified):
- Create list: `POST /api/v2/lead-lists` body `{ "name": "..." }`
- Bulk add: `POST /api/v2/leads/add` body `{ "list_id": ..., "leads": [...], "skip_if_in_workspace": false }`
- Enrich: `POST /api/v2/supersearch-enrichment` with `type` enum
- List leads: `POST /api/v2/leads/list` (NOT GET!) body `{ "list_id": ..., "limit": 100, "starting_after": ... }`

Use **placeholder emails** when bulk-adding leads without emails: `placeholder_<idx>@<company_domain>`. After enrichment, the real email replaces it.

Hit rate ~10-30% — depends on Apollo DB coverage of that segment.

## Final filtering

```python
final = [p for p in people if p["email"] and (
    p["email_verification_status"] in ("valid","accept_all") or
    p["email_source"] in ("apollo_pre_verified",
                           "instantly_supersearch_verified",
                           "instantly_supersearch_enrich",
                           "storeleads_public_email")
)]
```

Drop everything else. Smartlead/Instantly will auto-verify on campaign upload as a final safety net.

## Lessons

- Apollo's pre-verified emails were under-utilized in initial rounds — pull them FIRST.
- Storeleads' public emails sat in the data for 4 rounds before extraction — +298 emails for free.
- Instantly's poll endpoint has UUID validation quirks; better to poll by reading the leads list directly and checking when email-having row count stabilizes (3 consecutive equal polls).
- For each round, do a fresh waterfall — Instantly DB updates daily so previously-empty leads sometimes get filled.
