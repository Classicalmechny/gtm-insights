---
name: lead-list-from-strategy-doc
description: >
  End-to-end lead-list pipeline starting from a campaign strategy document
  (Google Doc URL). Reads the strategy, reverse-prompts the user for any
  ambiguous ICP fields, proposes a source plan, then runs a validated
  multi-source TAM-build + email-enrichment waterfall. Outputs a Full TAM
  CSV + per-campaign CSVs with personalization variables ready for
  Smartlead / Instantly. Use whenever the user provides a strategy/brief
  doc and asks to "build a lead list", "build the TAM", or
  "find leads for [client] campaign".
triggers:
  - build a lead list from strategy doc
  - lead list from strategy document
  - lead list for [client]
  - TAM list from brief
  - parse strategy and find leads
  - outbound list from this doc
tools:
  - Read
  - Write
  - Edit
  - Bash
  - WebFetch
  - WebSearch
  - mcp__claude_ai_Google_Drive__read_file_content
  - mcp__claude_ai_Google_Drive__download_file_content
  - Agent
---

# Lead List From Strategy Doc — Skill

## Purpose

Given (1) a campaign strategy document (Google Doc URL) and optionally
(2) any pre-existing source CSVs (Storeleads, Apollo, Clay exports), produce:

- `AYNA_FULL_TAM.csv` — every person + brand context + campaign tags
- `campaigns_final/campaign_N_<name>.csv` — outbound-ready per-campaign CSVs
- `domains_for_clay/*.csv` — domain list batches for Clay people-search
- `personalization_sample.md` — sample rendered emails per campaign

This skill is the orchestrator. Per-stage detail lives under `references/`,
scripts under `scripts/`, templates under `templates/`. Read references only
when you reach that stage (iceberg technique).

---

## CRITICAL LESSONS FROM PRIOR RUN (Ayna, 6 rounds, 4,671 emails)

Read these BEFORE planning the run. They will save you 5+ wasted rounds.

### 1. **Start permissive, not strict.**
Initial strict niche filter (3+ hits AND 10%+ AND apparel-keyword check)
dropped 21,500 brands. Recovery took 3 iterations (loosened filter → non-apparel
rescue). **Better: start with 1+ niche hit + Storeleads `/Apparel` tag.
Tag confidence tier (high/med/low). Recover gradient as needed.**

### 2. **Apollo + Storeleads public emails come FIRST.**
Apollo CSVs have pre-verified emails (494 in the prior run).
Storeleads has `emails_from_storeleads` field with info@/founder@ (2,010 emails!).
Both were under-utilized in the first 4 rounds. **Order email waterfall:**
1. Apollo pre-verified
2. Storeleads `emails_from_storeleads` (brand-level fallback)
3. BlitzAPI find-work-email by LinkedIn URL
4. Instantly Supersearch enrich + verify (last — costly but fills gaps)

### 3. **Clay returns 30-50% non-ICP garbage.**
Every Clay export had domains like HP, Google, LinkedIn, Chick-fil-A. **Always**
strict-validate `Company Domain` against your TAM domain set before merging.

### 4. **Instantly Supersearch's `technologies` filter is undocumented but works.**
Test it on a small batch first (run 20-lead enrichment, /collections.json each
returned domain). The Apollo-backed DB has 644K+ Shopify Apparel & Fashion
leads — don't run only 1 query with limit=2000. Split by state
(CA/NY/TX/FL/etc.) to bypass per-query caps and unlock 5-10x more leads.

### 5. **Sample-validate-iterate.**
Stage 2 niche filter needed 4 iterations to hit 95% pass rate on 20-sample.
Each iteration was <5min of compute. Never scale to full TAM without sample approval.

### 6. **Centralize the title regex.**
Founder/CEO/Owner alone misses Head of Brand/Creative/E-commerce/DTC and
Director of E-commerce/Marketing/Design/Art. Use `_titles.py` from day 1.
Include exclude-list: Assistant *, Personal Brand Strategist, Intern, Associate.

### 7. **/collections.json is the source of truth, not Storeleads' `collections` field.**
Storeleads' `collections` is mostly null. Every Shopify store exposes
`https://DOMAIN/collections.json` publicly. Use UA rotation + concurrency 15.

### 8. **Intensity-based niche detection.**
A keyword appearing once is noise. Require: ≥3 collection hits AND ≥10% of
collections AND outnumber adult-general (men's/women's) collections OR appears
in brand name/domain.

### 9. **The /collections.json apparel filter is risky.**
Keyword count of {"shirt", "dress", "pants", ...} drops legitimate brands that
use collection names like "Spring '26", "$10 and Under", "Bestsellers".
**Recovery rule:** Storeleads `/Apparel` tag + ≥1 niche hit is sufficient
unless dominated by hard-non-apparel terms (jewelry, furniture, food).

### 10. **Multi-brand retailers: tag, don't drop.**
Many lingerie/kids retailers carry multiple external brands. Tag
`is_multi_brand_retailer=yes` based on external-brand-name match count in
collections. Let downstream segmentation decide. (Per typical user feedback,
they want these kept.)

---

## EXECUTION FLOW

```
[0] INPUT          ── strategy doc URL → reverse-prompt for ambiguous fields
                                      → write icp.json
   │
   ▼
[1] PROPOSE PLAN   ── source mix + cost estimate + expected yield
   │                → user approval
   ▼
[2] STAGE 1        ── Pre-filter source CSV (e.g. Storeleads) by firmographics
   │                → raw/storeleads.csv (10K-100K candidates)
   ▼
[3] STAGE 2        ── Niche verification via /collections.json
   │                → 20-sample validation loop (iterate until 95% pass)
   │                → output/raw/storeleads_verified.csv (TAM)
   ▼
[4] STAGE 3        ── People sourcing (parallel)
   │                  (a) Apollo CSV ingest if provided
   │                  (b) BlitzAPI employee finder
   │                  (c) Instantly Supersearch sourcing
   │                  (d) Clay export ingest (strict domain-validated)
   │                → output/people_all.csv (deduped pool)
   ▼
[5] STAGE 4        ── Email waterfall (4 passes)
   │                  Pass 1: Apollo pre-verified emails
   │                  Pass 2: Storeleads public emails (info@/founder@)
   │                  Pass 3: BlitzAPI find-work-email
   │                  Pass 4: Instantly Supersearch enrich + verify
   │                → output/verified.csv
   ▼
[6] STAGE 5        ── AI personalization variables (sample-approval gated)
   │                → output/enriched.csv
   ▼
[7] STAGE 6        ── Segment by campaign (one CSV per campaign)
   │                → output/campaigns_final/*.csv
   ▼
[8] STAGE 7        ── Export Full TAM + Clay domain batches
                    → output/AYNA_FULL_TAM.csv
                    → output/domains_for_clay/*.csv
```

---

## STAGE 0 — INPUT & ICP

**Goal:** parse strategy doc into structured `icp.json` and clarify ambiguities
before spending any tokens or API credits.

### Inputs from user
- **Required**: strategy doc URL (Google Doc) OR pasted text
- **Optional**: prior CSV files (Storeleads, Apollo exports, Clay exports)
- **Optional**: API keys for the run (else read from `.env`)

### Read the strategy doc
- For Google Doc URLs: use `mcp__claude_ai_Google_Drive__read_file_content`
  with the file ID (extracted from URL)
- For PDFs: use Read with `pages` parameter
- For pasted text: parse directly

### Extract ICP fields
Map to template at `templates/icp_template.json`:

```json
{
  "client": "...",
  "campaign": "...",
  "geographics": { "countries": [...] },
  "firmographics": {
    "industries": [...],
    "industries_exclude": [...],
    "employee_count_min": 5, "employee_count_max": 50,
    "tech_stack_includes": ["Shopify", "Shopify Plus"],
    "revenue_band_annual_usd": { "min": 600000, "max": 18000000 }
  },
  "persona": {
    "titles": [ ... ],
    "title_exclusions": [...],
    "seniority": [...],
    "dm_cap_per_company": null
  },
  "company": {
    "categories_niche": [...],
    "must_have": [...]
  },
  "personalization_variables": { ... },
  "campaigns": [ { "id": 1, "name": "...", "audience": "..." }, ... ]
}
```

### Reverse-prompt for ambiguous fields
Run ONE consolidated reverse prompt with multiple-choice options.
Common ambiguous slots in fashion / DTC briefs:
- Storefront platform: Shopify only? Or also WooCommerce/BigCommerce?
- Revenue band: strict from brief, or looser ±20%?
- Multi-brand retailers: drop or keep?
- Flat-lay-only brands: drop or keep?
- DM cap per company: 1 / 2 / 3 / unlimited?
- Sample size for validation loop: 10 / 15 / 20?

Write the final ICP to `output/<run_id>/icp.json`. Confirm in a compact
table to the user and get explicit approval before moving on.

### Stop conditions
- TAM < ~50 likely leads worldwide → flag (list-building economics break)
- Brief is too vague (no niche, no titles, no geography) → ask for revision

---

## STAGE 1 — PROPOSE SOURCE PLAN

**Goal:** decide source mix + estimate cost/yield, get user OK before spending.

### Source matrix (verified working 2026-05-22)

| Source | Has people? | Has email? | Native tech filter? | Cost | Notes |
|--------|-------------|------------|--------------------|------|-------|
| Storeleads CSV (client-provided) | ❌ brand-only | ✅ public `emails_from_storeleads` field | ✅ Shopify-only by definition | Free | Pre-filtered Shopify universe |
| Shopify `/collections.json` | ❌ | ❌ | n/a | Free, fast | Per-domain probe (~10/sec, UA rotation) |
| **Ocean.io v3 `/search/companies`** (UNLOCKED 2026-05-25) | ❌ → use Blitz/Instantly downstream | ❌ | ✅ via `technologies.apps.anyOf` | 1 credit per company | **Company discovery + lookalike. Seeded with 3-6 customer/aspirational domains → tens of thousands of lookalikes. Use as the PRIMARY company-discovery source when seed domains exist.** |
| **Ocean.io v2 `/lookup/companies`** | ❌ | ❌ | n/a (returns tech array) | 1 credit per company | Brand enrichment by domain — returns rich `industries` array (e.g. "Lingerie", "Childrenswear") + `technologies` + `companySize` + `revenue`. Use for niche reclassification + `/collections.json` fallback. |
| BlitzAPI employee finder | ✅ via company LinkedIn URL | ❌ | n/a | $$ per credit | Needs company LinkedIn URL |
| BlitzAPI find-work-email | ✅ by person LinkedIn URL | ✅ | n/a | $$ per credit | Best for personal emails |
| Instantly Supersearch | ✅ | ✅ verified | ✅ `technologies:["Shopify"]` (undocumented) | $$ ($0.02/lead) | Apollo-DB-backed |
| **RapidAPI Realtime LinkedIn Bulk** (added 2026-05-25) | ✅ via profile / post-engagement endpoints | ❌ (pair with BlitzAPI for emails) | n/a | $ metered per-call | **MCP `rapidapi-linkedin-bulk-scraper` (local) + `rapidapi-linkedin-bulk` (VPS). Use for: (1) resolving Trigify `ACoAA…` obfuscated URNs to clean `linkedin.com/in/<vanity>` URLs, (2) scraping post engagement (likers + commenters + repost-ers) from a competitor/influencer post, (3) employee finder on a company URL, (4) bulk profile enrichment (headline/company/title/location).** See `references/06-rapidapi-linkedin-bulk.md`. |
| Apollo CSV exports (client-provided) | ✅ | ✅ partially | ✅ pre-filtered | Free | Pre-verified subset of Apollo DB |
| Clay export (client-runs) | ✅ via LinkedIn search | ❌ | ❌ noisy | Free to skill | Validate strictly against TAM |

### Sources that DO NOT have tech filter (skip if user requires Shopify-only)
- BlitzAPI Company Search (no tech-stack filter in v2 schema)

### Cost estimator
For an Ayna-sized run (10K niche brands):
- Storeleads + /collections.json: $0 (instant)
- BlitzAPI employee finder × 10K: ~$100-200
- BlitzAPI find-work-email × 5K: ~$50-100
- Instantly Supersearch × 5K leads: ~$100-150
- Total: ~$250-450 for 4K-5K verified emails

### Output: `source_plan.json`
Show the plan as a compact table to the user before executing. If estimated
cost >$100, get explicit approval.

---

## STAGE 2 — NICHE VERIFICATION via /collections.json + Ocean.io

Read `references/02-niche-verification.md` and `references/05-ocean-enrichment.md`.

Key points:
- Use intensity-based detection (not keyword-presence)
- Iterate via 20-sample validation until 95% pass
- Tag confidence tier (high/medium/low) instead of binary drop
- Use Storeleads `/Apparel` tag as apparel-focus signal (don't require ≥4 apparel-keyword collections)
- Hard non-apparel exclude only (jewelry, furniture, food, electronics)
- **Run Ocean.io `/v2/lookup/companies` on the same domains in parallel** — adds rich `industries` array (e.g. "Lingerie", "Childrenswear", "Maternity") that often catches niches missed by /collections.json regex
- For brands where /collections.json fails (no_data), Ocean.io industries become the primary niche signal

Scripts:
- `scripts/03_collections_enrich.py` (parameterized for any niche)
- `scripts/29_ocean_enrich.py` (Ocean.io v2 brand enrichment by domain)
- `scripts/30_ocean_lookalike_search.py` (Ocean.io **v3 lookalike + filter search** — primary company-discovery source when seed domains exist)

### Sample-validate-iterate loop
```
Run filter on 500 brands → pull 20 stratified samples → WebFetch each →
classify pass/fail → if <90% pass, identify failure pattern → tighten/loosen →
re-run on 500 → re-validate → repeat until ≥90% pass → scale to full TAM
```

---

## STAGE 3 — PEOPLE SOURCING (parallel)

Read `references/03-people-sourcing.md`.

Run all available sources in parallel. Each writes to `output/raw/<source>.csv`
with the source name in the `source` column.

For each source: read its reference + invoke the script:

| Source | Reference | Script |
|--------|-----------|--------|
| Storeleads-based DM finding (BlitzAPI) | `references/03a-blitz-dm.md` | `scripts/06_blitz_employee_finder.py` |
| Apollo CSV ingest | `references/03b-apollo-ingest.md` | `scripts/11_ingest_apollo.py` |
| Clay export ingest (strict) | `references/03c-clay-strict.md` | `scripts/26_clay_strict_ingest.py` |
| Instantly Supersearch | `references/03d-instantly-supersearch.md` | `scripts/05_instantly_supersearch.py` |
| RapidAPI LinkedIn Bulk (URN resolve + post-engagement + profile enrich + employee finder) | `references/06-rapidapi-linkedin-bulk.md` | MCP-first (`rapidapi-linkedin-bulk-scraper`); direct HTTPS as fallback |

**Critical:** All sources must dedupe by:
1. Email (lowercased)
2. LinkedIn URL (normalized, lowercased, trailing-slash stripped)
3. (first_name, last_name, company_domain) tuple

**Title filter:** load from `scripts/_titles.py`. Centralized for all sources.

---

## STAGE 4 — EMAIL WATERFALL (4 passes)

Read `references/04-email-waterfall.md`.

```
Pass 1: Apollo pre-verified emails           (free, from CSV)
Pass 2: Storeleads emails_from_storeleads    (free, brand-level fallback)
Pass 3: BlitzAPI find-work-email             ($, per LinkedIn URL)
Pass 4: Instantly Supersearch enrich+verify  ($$, last resort)
```

Each pass operates only on rows still missing an email. Save intermediate
CSVs so the pipeline is resumable.

### Email confidence
- `valid` / `accept_all` from Instantly: high-confidence personal
- `valid` from Apollo: high-confidence personal
- BlitzAPI find-work-email (no separate verify): medium-confidence personal
- Storeleads public: brand-level fallback (info@/founder@) — usable for
  cold outreach to small brands; mark `email_source=storeleads_public_email`

---

## STAGE 5 — AI PERSONALIZATION VARIABLES (sample-approval gated)

Most personalization variables for niche-fashion campaigns are
**deterministic** (no LLM needed):
- `{{first_name}}` — from row
- `{{company_name}}` — from row
- `{{category}}` — niche → human-readable label (kidswear → "kidswear",
  innerwear → "intimates and lingerie", plus_size → "plus size", etc.)
- `{{storefront_url}}` — `https://` + company_domain
- `{{drop_cadence}}` — from Storeleads products_created_30/90

For variables needing inference (e.g. icebreakers based on store content):
1. Run on 5 sample leads via Deepinfra GPTOSS or similar cheap LLM
2. Show `ai_samples.md` to user
3. Wait for explicit approval
4. Then run across full list with declared fallback

Script: `scripts/10_personalization_sample.py` for deterministic; for AI,
adapt build-cold-email-list/scripts/deepinfra_ai_enrich.py.

---

## STAGE 6 — SEGMENT BY CAMPAIGN

Read campaigns from `icp.json`. For each campaign, write a CSV with:
- Core fields (first_name, last_name, email, title, company_name, etc.)
- Campaign-specific personalization columns (e.g. drop_cadence for "Drop Velocity")

Script: `scripts/09_segment_campaigns.py`

---

## STAGE 7 — EXPORT DELIVERABLES

Write deliverables:
- `AYNA_FULL_TAM.csv` (or `<client>_FULL_TAM.csv`) — every person + brand context + campaign tags
- `campaigns_final/campaign_N_<name>.csv` — outbound-ready per-campaign
- `domains_for_clay/batch_*.csv` — domain lists (split into 10K batches if needed) + per-niche split
- `personalization_sample.md` — sample rendered emails

Script: `scripts/28_final_deliverables.py`

---

## RULES (always apply)

1. **Reverse-prompt early.** Get ICP clarity BEFORE running anything.
2. **Cost-aware sourcing.** Log expected cost. >$100 → explicit user OK.
3. **Save everything to disk.** Every stage writes to
   `output/<run_id>/`. Resumable on session restart.
4. **Idempotent scripts.** All scripts in `scripts/` re-read prior outputs
   and skip already-done work.
5. **Sample-validate before scaling.** Stage 2 + Stage 5 use the 20-sample loop.
6. **Never invent emails.** If verification fails or recall is empty, drop the
   row — don't guess.
7. **Strict-validate Clay exports.** Every Clay lead's company_domain must be
   in the verified TAM set.
8. **Trust Storeleads' `/Apparel` tag.** It's already pre-filtered Shopify apparel.
9. **Keep multi-brand retailers** unless user explicitly says drop.
10. **Document decisions.** Append to `run.log` with timestamps + counts at every stage.

---

## OUTPUT DIRECTORY LAYOUT

```
output/<run_id>/
├── icp.json                        # Stage 0 (source of truth)
├── source_plan.json                # Stage 1 (approved plan)
├── raw/
│   ├── storeleads_verified.csv     # Stage 2 — niche-verified TAM
│   ├── storeleads_dropped.csv      # Stage 2 — debug
│   ├── apollo.csv                  # Stage 3a
│   ├── decision_makers.csv         # Stage 3b (BlitzAPI DMs)
│   ├── clay_strict.csv             # Stage 3c (Clay strict-validated)
│   └── instantly.csv               # Stage 3d (Instantly Supersearch)
├── checkpoints/                    # Resumability
├── sample_20.csv + .md             # Validation samples
├── people_merged.csv               # Stage 3 union
├── verified.csv                    # Stage 4 (final email-having set)
├── enriched.csv                    # Stage 5 (+ AI vars if used)
├── campaigns_final/                # Stage 6
│   └── campaign_N_*.csv
├── <CLIENT>_FULL_TAM.csv           # Stage 7 (full database)
├── domains_for_clay/               # Stage 7 (for further people-search)
│   ├── batch_v3_all_niche.csv
│   ├── batch_v3_enriched.csv
│   └── by_niche/
├── personalization_sample.md       # Sample renders
└── run.log
```

---

## RESUMING A RUN

If user says "continue [client] list":
1. Read `output/<run_id>/run.log`
2. Determine last completed stage
3. Resume from next stage using on-disk artifacts

---

## CHECKLIST BEFORE DECLARING DONE

- [ ] `output/<run_id>/<CLIENT>_FULL_TAM.csv` exists
- [ ] Every row has: first_name, last_name, title, company_name, company_domain
- [ ] `campaigns_final/*.csv` exist for every campaign in icp.json
- [ ] Every lead in campaign CSVs has a non-empty `email`
- [ ] `domains_for_clay/*.csv` exist for further people-search
- [ ] `personalization_sample.md` exists and renders correctly
- [ ] `run.log` has a closing entry with total counts + email source breakdown
- [ ] User-facing message includes absolute paths to deliverables
- [ ] No hardcoded API keys in any output file

---

## DELTA FROM PRIOR (ad-hoc) RUN

| Aspect | Prior run | This skill |
|---|---|---|
| Niche filter | strict → loosened 3x | start permissive, tier confidence |
| Source order | random (Storeleads first) | Apollo+Storeleads-emails FIRST, then BlitzAPI, then Instantly |
| Title list | started narrow, expanded mid-run twice | centralized `_titles.py` from start |
| Clay validation | found 30-50% non-ICP leak after the fact | strict-validate against TAM at ingest |
| Instantly multi-query | tried niche keyword_filter (too narrow) | split by state (CA/NY/TX/etc.), not by keyword |
| Apparel filter | drove false-positive drops | trust Storeleads `/Apparel` tag |
| Storeleads public emails | discovered round 5 | use in Pass 2 of email waterfall |
| Validation loop | 4 iterations to find right thresholds | template thresholds, faster convergence |

Expected outcome on a similar-sized ICP: ~5,000-6,000 verified emails in
3-4 hours wall time + 1 hour of agent reasoning, vs the 7+ hours of the
ad-hoc run.
