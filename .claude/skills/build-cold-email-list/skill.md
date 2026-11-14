---
name: build-cold-email-list
description: >
  Build a production-ready cold email lead list from an ICP (Ideal Customer
  Profile). Routes across multiple lead sources (BlitzAPI, Ocean.io, Instantly
  Supersearch, niche directories, GitHub pre-scraped DB), enriches with
  decision-maker finding, finds + verifies work emails, optionally runs
  AI-variable enrichment with sample-first approval, then delivers a CSV.
  Use whenever the user asks to "build a lead list", "find leads matching X
  ICP", "build a cold email list", "TAM list", or supplies an ICP and asks
  for outbound-ready leads with verified emails.
triggers:
  - build a lead list
  - cold email list
  - lead list for [ICP]
  - find leads matching
  - build cold email leads
  - outbound list
  - TAM list
  - prospect list
  - list-building
  - find decision makers at
  - enrich leads
tools:
  - Read
  - Write
  - Edit
  - Bash
  - WebFetch
  - WebSearch
  - Agent
---

# Build Cold Email List — Skill

## Purpose

Given an ICP (demographics + firmographics + geographics + persona), produce a
CSV of cold-email-ready leads where every row has:
- Verified work email
- Full identity (first name, last name, title, LinkedIn URL)
- Company context (name, domain, industry, employee count, country)
- Optional AI-generated personalization variables (with sample-first approval)

This skill is the orchestrator. The detailed API specs, payload shapes, and
implementation scripts live under `references/` and `scripts/` — read them
on demand, do NOT pre-load all of them. (Iceberg technique — see Section 9
of project CLAUDE.md.)

---

## API KEYS (load from env, never hardcode in outputs)

Read keys at the start of any run by sourcing the project `.env`. If a key is
missing there, fall back to the values below (stored in this skill so the
skill remains executable even if env is not configured):

```
BLITZAPI_KEY      = blitz_mkbWaJvTNLHs525Aegh4W9gt
BETTERCONTACTS    = d1694d3b44010ee6ec43
FIRECRAWL_KEY     = Fc-485dfe05cfe64a2685123ead2719f604
DEEPINFRA_KEY     = wOaRky1fcun3LBqaVTzA6zU4IQ6Y7FSF
INSTANTLY_KEY     = NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==
```

**Env-only keys (no fallback — must be exported before running):**
```
OCEAN_KEY         # Ocean.io v3 token (UNLOCKED 2026-05-25). Get from ~/brain/.env on VPS.
RAPIDAPI_KEY      # RapidAPI Hub key for realtime-linkedin-bulk-data. Same source.
```

Scripts in this skill already read these from env first, falling back to
hardcoded defaults — see `scripts/_common.py`. `OCEAN_KEY` and `RAPIDAPI_KEY`
have NO hardcoded fallback (credential rotation discipline) — `export` them
before running, or the run will SystemExit with "Missing API key".

---

## EXECUTION FLOW (High Level)

```
USER ICP
   │
   ▼
[1] INTAKE  ── reverse-prompt for any missing ICP fields → write icp.json
   │
   ▼
[2] ROUTE   ── pick the right combination of sources based on ICP
   │
   ▼
[3] SOURCE  ── run selected sources IN PARALLEL → raw_*.csv files
   │           BlitzAPI people / company search
   │           Ocean.io lookalikes (if user supplied seed domains)
   │           Instantly Supersearch (broad Apollo-like DB)
   │           Niche directories (Firecrawl + custom scripts)
   │           GitHub pre-scraped DB (Crunchbase + Google Maps US)
   │
   ▼
[4] DM FIND ── for company-only sources, find decision makers
   │           via BlitzAPI employee finder matching the persona
   │
   ▼
[5] DEDUPE  ── merge all sources, dedupe by LinkedIn URL / email / domain+name
   │
   ▼
[6] EMAILS  ── waterfall: Instantly Supersearch (incl. verification)
   │           → BlitzAPI find-work-email for misses → re-verify via Instantly
   │           Drop all unverified / "risky" emails
   │
   ▼
[7] AI VARS ── (optional) if user asked for AI variables:
   │           - confirm variables + prompts
   │           - run on 5 sample leads → show output → wait for approval
   │           - on approval, run across full verified list with fallbacks
   │
   ▼
[8] EXPORT  ── final CSV with consistent schema → deliver path to user
```

Each numbered step has a dedicated reference file under `references/`. Read
the reference file for a step ONLY when you reach that step.

---

## STEP 1 — INTAKE

**Goal:** capture a complete, structured ICP before spending any tokens or
API calls.

Read `references/01-icp-intake.md` for the intake template and the required
fields. Then:

1. Parse whatever the user already gave you against the intake template.
2. For each missing or ambiguous field, generate ONE consolidated reverse
   prompt with multiple-choice options where possible (per Section 6 of
   project CLAUDE.md). Do NOT ask field-by-field.
3. Write the final ICP to `./output/<run_id>/icp.json` using the schema in
   the reference file. Use `<run_id>` = `YYYY-MM-DD_HHMM_<slug>` where slug
   is a 3-word descriptor of the ICP (e.g. `us_saas_founders`).
4. Confirm the ICP back to the user in a single compact table and get
   explicit approval before moving on.

**Stop conditions:** if the ICP target audience is < ~50 likely leads
worldwide, flag it — list-building economics break below that.

---

## STEP 2 — ROUTE

**Goal:** decide which sources to use. Do NOT use all sources by default —
each costs money. Read `references/02-source-routing.md` for the full
routing decision tree. Quick summary:

| ICP Signal | Use this source |
|------------|-----------------|
| Any B2B with identifiable titles (most cases) | **Instantly Supersearch** (gives leads + verified emails in one call) |
| User supplied 3+ seed customer domains | **Ocean.io lookalikes** (v3 unlocked 2026-05-25 — 44K-class TAM unlocks per seed set) |
| Persona is LinkedIn-findable, niche title | **BlitzAPI people search** |
| Need company list first, then DMs | **BlitzAPI company search** + employee finder |
| Niche industry with known public directory (realtors, agencies, e-commerce stores, doctors, lawyers) | **Niche directory scraping** (Firecrawl) |
| SaaS / startup / VC-backed | **Existing GitHub DB** (Crunchbase) |
| US local services (restaurants, gyms, plumbers etc.) | **Existing GitHub DB** (Google Maps) |
| Engagement-based ICP (likers/commenters of competitor or influencer posts) | **Trigify** (find posts) → **RapidAPI LinkedIn Bulk** (scrape engagement + resolve URNs) → BlitzAPI |
| Have obfuscated `ACoAA…` LinkedIn URNs from Trigify | **RapidAPI LinkedIn Bulk** profile resolve (URN → clean vanity URL + firmographics) |
| Long-tail company with no Apollo coverage | **RapidAPI LinkedIn Bulk** company employee finder |

Default combination: `Instantly Supersearch` + one secondary source for
coverage. Write the chosen plan to `./output/<run_id>/source_plan.json`
and show it to the user before executing.

---

## STEP 3 — SOURCE (Parallel)

**Goal:** maximize coverage by running selected sources concurrently. Each
source dumps raw rows into `./output/<run_id>/raw/<source>.csv` with the
source's native schema preserved (we normalize later).

For each source in the plan, read its reference file then invoke its script:

| Source | Reference | Script |
|--------|-----------|--------|
| BlitzAPI people search | `references/03-blitzapi.md` | `scripts/blitz_people_search.py` |
| BlitzAPI company search | `references/03-blitzapi.md` | `scripts/blitz_company_search.py` |
| Ocean.io lookalikes | `references/04-ocean-io.md` | `scripts/ocean_lookalike.py` |
| Instantly Supersearch | `references/05-instantly-supersearch.md` | `scripts/instantly_supersearch_pipeline.py` |
| Niche directories | `references/06-niche-directories.md` | (Firecrawl, sometimes custom) |
| Existing DB | `references/07-existing-database.md` | `scripts/existing_db_filter.py` |
| RapidAPI LinkedIn Bulk (URN resolve + post-engagement + profile enrich + employee finder) | `references/09-rapidapi-linkedin-bulk.md` | MCP-first (`rapidapi-linkedin-bulk-scraper`); direct HTTPS as fallback |

Run sources in parallel by launching each script in the background with
`run_in_background=True` and monitoring completion. Most APIs are slow
(Instantly polls for minutes, Ocean batches). Plan for 5–30 minutes wall
time at this step depending on list size.

**Critical:** every source's raw CSV MUST include a `source` column with
the source name. We need this for provenance in the final CSV and for
debugging source quality later.

---

## STEP 4 — DECISION MAKER FINDING

**Goal:** for any company-only source (Ocean.io, BlitzAPI company search,
niche directories, existing DB), find the persona's decision makers at
each company.

Read `references/08-decision-maker-finding.md`. The implementation:

1. Concatenate all company-only sources' domains into one list, dedupe.
2. For each company, call BlitzAPI employee finder with the persona's
   title keywords + seniority filters from the ICP.
3. Cap at N decision makers per company (default 3 — configurable per ICP).
4. Write to `./output/<run_id>/raw/decision_makers.csv` with `source`
   column = original source name + `_dm`.

Skip this step entirely if the sourcing plan only used people-level
sources (Instantly Supersearch, BlitzAPI people search). Those already
return people.

---

## STEP 5 — DEDUPE & MERGE

**Goal:** collapse all `raw/*.csv` into a single `./output/<run_id>/
merged.csv` with one row per unique person.

Read `references/11-deduplication-merge.md`. Match keys, in priority order:
1. LinkedIn URL (normalized — strip trailing slash, lowercase, drop tracking params)
2. Email if already present from source
3. Company domain + normalized full name (lowercase, no punctuation)

For each match group, prefer the most complete row (highest field
fill-rate). Preserve provenance via a `sources` column = comma-joined list
of all source names that contributed.

Use `scripts/dedupe_merge.py`.

---

## STEP 6 — EMAIL FINDING & VERIFICATION

**Goal:** every row in the final CSV has a deliverable, verified work email.

Read `references/09-email-enrichment.md` for the full waterfall logic.
This step is a three-pass waterfall — DO NOT confuse it with Step 3's
supersearch sourcing.

> ⚠️ **Common error to avoid:** `instantly_supersearch_pipeline.py`
> (Step 3) calls `/enrich-leads-from-supersearch` which generates *new*
> leads from filters. It does NOT enrich existing leads. For Step 6 you
> MUST use `instantly_email_enrichment_pipeline.py`, which uses
> `/api/v2/supersearch-enrichment` against an EXISTING lead-list of
> leads you bulk-added.

### Exact commands (run in order)

**Pass 1 — Enrich + verify all merged leads via Instantly**
```bash
python scripts/instantly_email_enrichment_pipeline.py \
    --run-id <run_id> \
    --mode enrich \
    --input  output/<run_id>/merged.csv \
    --output output/<run_id>/verified_pass1.csv
```
Behaviour: creates Instantly list → bulk-adds leads → submits enrichment
job with `enrich_work_email:true` + `verify_work_email:true` → polls →
paginates → keeps only `valid` and `accept_all`.

**Pass 2 — BlitzAPI fallback for Pass-1 misses**

Compute the Pass-1 misses set:
```bash
python scripts/blitz_email_enrichment.py \
    --run-id <run_id> \
    --input output/<run_id>/merged.csv
```
This writes `output/<run_id>/merged.with_blitz_emails.csv` with the
extra `candidate_email` column for rows that didn't already have a
deliverable email.

**Pass 3 — Re-verify Pass-2 finds via Instantly**

Critical: pass the Pass-2 output as `--input` and a SEPARATE
`--output` so it doesn't collide with Pass 1.

```bash
python scripts/instantly_email_enrichment_pipeline.py \
    --run-id <run_id> \
    --mode verify \
    --input  output/<run_id>/merged.with_blitz_emails.csv \
    --output output/<run_id>/verified_pass3.csv
```

**Concatenate and dedupe to final verified.csv**

```bash
python scripts/concat_verified.py --run-id <run_id>
```
This stitches `verified_pass1.csv` and `verified_pass3.csv`, dedupes by
email (Pass 1 wins on conflict), and writes the canonical
`output/<run_id>/verified.csv`.

### Acceptance
Drop everything not in `{valid, accept_all}`. Every row in
`verified.csv` MUST have a non-empty email.

---

## STEP 7 — AI VARIABLE ENRICHMENT (Optional)

**Goal:** add personalization variables (icebreakers, custom angles,
relevance scores, etc.) — ONLY if the user asked for them.

Read `references/10-ai-variable-enrichment.md`. The flow:

1. If the user did NOT mention AI variables in intake, ask once explicitly:
   "Do you want AI personalization variables (e.g. icebreaker, custom
   opener, relevance score)? [yes/no]"
2. If yes, collect:
   - List of variable names
   - One prompt per variable (with placeholders like `{first_name}`,
     `{company_name}`, `{title}`, `{linkedin_url}`, `{company_domain}`)
   - For any prompt that needs web context: confirm we should
     Firecrawl-scrape the company website / the lead's LinkedIn first.
3. **Persist the spec** to `./output/<run_id>/ai_spec.json` using the
   shape in `templates/ai_variable_spec.example.json`. This file is the
   single source of truth for variable names — both
   `deepinfra_ai_enrich.py` (during processing) AND `export_csv.py`
   (when ordering final columns) read from it.
4. **Sample-first:** run all variable prompts on 5 sample leads using
   Deepinfra GPTOSS 20B:
   ```bash
   python scripts/deepinfra_ai_enrich.py \
       --run-id <run_id> --mode sample \
       --spec output/<run_id>/ai_spec.json --n 5
   ```
   Show the user the resulting `ai_samples.md`. Wait for explicit
   approval before continuing.
5. On approval: run prompts across the full verified list.
   ```bash
   python scripts/deepinfra_ai_enrich.py \
       --run-id <run_id> --mode full \
       --spec output/<run_id>/ai_spec.json --concurrency 8
   ```
   Include a fallback string per variable in the spec (defaults to `""`
   — but for icebreakers we default to a generic by-industry line so no
   row is ever blank).
6. Output: `./output/<run_id>/enriched.csv`.

**Never** run AI enrichment on the full list before sample approval.
Showing 5 samples first saves 95%+ of cost on bad prompts.

---

## STEP 8 — EXPORT

**Goal:** deliver a single, clean CSV the user can paste into Instantly,
Smartlead, Lemlist, etc.

Read `references/12-csv-output-schema.md` for the exact column order and
naming conventions. Use `scripts/export_csv.py` to:
1. Reorder columns to the canonical schema.
2. Strip internal-only fields (raw API responses, debug columns).
3. Title-case names, lowercase emails, normalize domains.
4. Drop rows missing any required field.
5. Save to `./output/<run_id>/final.csv` AND print a one-screen summary
   to the user:
   - Total rows in final
   - Coverage by source
   - % verified
   - % with each AI variable (if applicable)
   - Path to the file

---

## RULES (Always Apply)

1. **Cost-aware sourcing.** Before any paid API call, log the expected
   request count to the user. If it exceeds 5,000 person-lookups OR 1,000
   AI enrichments, ASK before proceeding.
2. **Save everything to disk.** Conversation memory is volatile — every
   step writes its output to `./output/<run_id>/`. If the session restarts,
   the run can be resumed by reading the `run_id` directory.
3. **Idempotent scripts.** All scripts in `scripts/` re-read prior outputs
   and skip work that's already done. Safe to re-run after any failure.
4. **Never invent emails.** If verification fails, the row is dropped, not
   guessed. A bad email kills sender reputation.
5. **Never invent AI variable output.** If a Deepinfra call fails, use the
   declared fallback. Do not let the model fabricate facts.
6. **Always reverse-prompt before AI variable enrichment.** Sample-first,
   approval-gated, always.
7. **Be conservative with bulk credits.** Instantly enrichment, BlitzAPI
   credits, and Bettercontacts credits are paid per lead. Cap runs by
   default at 2,000 leads unless the ICP explicitly justifies more.
8. **Source from cheapest first.** Existing DB (free) → Instantly (cheap +
   covers email) → BlitzAPI (per-credit) → Ocean.io (per-credit) →
   directories (Firecrawl credits). Skip expensive sources if cheap ones
   already cover the ICP.

---

## OUTPUT DIRECTORY LAYOUT

```
./output/<run_id>/
├── icp.json                 # Approved ICP (Step 1)
├── source_plan.json         # Approved source plan (Step 2)
├── raw/                     # One CSV per source (Step 3, 4)
│   ├── instantly.csv
│   ├── blitz_people.csv
│   ├── ocean.csv
│   ├── decision_makers.csv
│   └── ...
├── merged.csv               # Deduped union (Step 5)
├── merged.with_blitz_emails.csv  # Pass-2 BlitzAPI candidate emails (Step 6)
├── verified_pass1.csv       # Pass-1 verified (Step 6)
├── verified_pass3.csv       # Pass-3 verified (Step 6)
├── verified.csv             # Concatenated, final verified set (Step 6)
├── ai_spec.json             # AI variable spec (Step 7) — source of truth
├── ai_samples.md            # Sample variable preview (Step 7)
├── enriched.csv             # Verified + AI variables (Step 7)
├── final.csv                # ⭐ DELIVERABLE (Step 8)
└── run.log                  # Per-step timings, counts, errors
```

Every step writes a JSON line to `run.log` with timestamp, step name,
input count, output count, and any errors. Use this to debug and to give
the user a transparent summary at the end.

---

## RESUMING A PARTIALLY-COMPLETED RUN

If the user comes back and says "continue the list from earlier" or
references a previous run:

1. Ask for the `run_id` (or scan `./output/` for recent ones).
2. Read `run.log` to determine the last completed step.
3. Resume from the next step using the existing on-disk artifacts.

This is why every step is idempotent and writes to disk before completing.

---

## CHECKLIST BEFORE DECLARING DONE

- [ ] `final.csv` exists at the path
- [ ] Every row has: first_name, last_name, title, company_name, company_domain, email
- [ ] Every email passed Instantly verification (`valid` or `accept_all`)
- [ ] If AI variables were requested: every row has every variable populated (either real or fallback)
- [ ] Summary printed to the user (row count, source mix, verification rate)
- [ ] `run.log` has a closing entry with total wall time and total API cost estimate
- [ ] User-facing message includes the **absolute path** to `final.csv`
