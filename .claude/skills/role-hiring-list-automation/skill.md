---
name: role-hiring-list-automation
description: >
  Build a fully-automated weekly n8n workflow that scrapes companies hiring
  for a specific list of roles (via JSearch), filters by ICP firmographics
  (BlitzAPI), finds a decision maker, verifies emails, AI-personalizes per
  the hiring signal, and uploads to an Instantly cold-email campaign with
  dedupe. Use whenever the user wants a recurring (Monday-cron) outbound
  pipeline driven by hiring signals — e.g. "campaign targeting companies
  hiring ML engineers", "staff augmentation pitch to companies hiring
  designers", "weekly outbound to anyone hiring [role]", or any
  staff-aug / agency-pitch / candidate-supply outbound angle that triggers
  off a job posting.
triggers:
  - hiring signal campaign
  - companies hiring X automation
  - weekly cron campaign for hiring
  - staff augmentation campaign
  - candidate supply outbound
  - role-based outbound
  - n8n weekly campaign from job postings
  - automate hiring-signal outreach
tools:
  - Read
  - Write
  - Edit
  - Bash
  - mcp__claude_ai_Google_Drive__read_file_content
  - mcp__n8n-mcp__get_sdk_reference
  - mcp__n8n-mcp__validate_workflow
  - mcp__n8n-mcp__create_workflow_from_code
  - mcp__n8n-mcp__update_workflow
  - mcp__n8n-mcp__publish_workflow
  - mcp__n8n-mcp__execute_workflow
  - mcp__n8n-mcp__get_execution
  - mcp__playwright__browser_navigate
  - mcp__playwright__browser_click
  - mcp__playwright__browser_type
  - mcp__playwright__browser_evaluate
  - mcp__playwright__browser_take_screenshot
---

# Role-Hiring-List Automation — Skill

## Purpose

Given a client + strategy doc + list of target roles, ship a production n8n
workflow that **every week** pulls fresh hiring-signal leads into an Instantly
campaign — with verified emails and AI-personalized variables — fully
automated. The first reference deployment is TechHive Campaign C
([clients/techhive/campaign_c_staff_aug_ai_ml/](../../clients/techhive/campaign_c_staff_aug_ai_ml/)).

This skill is the **orchestrator**. The actual code modules are reused
verbatim from the reference deployment — copy them into a new
`clients/<client>/<campaign_slug>/` folder and adjust the per-client config.

---

## When to use

| User intent | Use this skill |
|---|---|
| "Build a weekly cron pipeline that pushes companies hiring [role] into an Instantly campaign" | ✅ Primary |
| "Automate staff-aug outreach to anyone hiring [persona] in [geo]" | ✅ Primary |
| "Set up an n8n workflow that turns hiring signals into cold emails for [client]" | ✅ Primary |
| "Build a one-off lead list" (no recurring trigger) | ❌ Use `build-cold-email-list` instead |
| "Build a lead list from a strategy doc" (no hiring-signal angle) | ❌ Use `lead-list-from-strategy-doc` |
| "Find companies hiring X" (research only, no campaign) | ❌ Use `job-board-scraping` |

---

## Architecture (reference pipeline)

```
┌────────────────┐
│ Cron (Monday)  │
│ 09:00 weekly   │
└───────┬────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 1 — JSearch scrape                                     │
│ N roles × M countries × P pages = N×M×P queries              │
│ Concurrency 8, 429/5xx retry w/ exponential backoff          │
│ Dedupe by domain, drop excluded employers (FAANG/staffing)   │
└───────┬──────────────────────────────────────────────────────┘
        ▼ ~hundreds of unique companies
┌──────────────────────────────────────────────────────────────┐
│ Stage 1b — ICP firmographic filter (BlitzAPI)                │
│ For each: domain→LI + company-enrich (parallel x10)          │
│ Keep: size buckets ∈ {ALLOWED}, HQ ∈ {ALLOWED_HQ},           │
│       industry ∉ {EXCLUDE_INDUSTRY}                          │
└───────┬──────────────────────────────────────────────────────┘
        ▼ ~tens of qualified companies
┌──────────────────────────────────────────────────────────────┐
│ Stage 2 — DM finder (BlitzAPI Waterfall ICP)                 │
│ Cascade: Founder/CEO → CTO/VP Eng → Head of AI/Director Eng  │
│ Employee-Finder fallback                                     │
└───────┬──────────────────────────────────────────────────────┘
        ▼ ~tens of decision makers
┌──────────────────────────────────────────────────────────────┐
│ Stage 3 — Email + verification                               │
│ BlitzAPI find-work-email by person LI URL                    │
│ Instantly verify-email (if credits) → MX-check floor         │
└───────┬──────────────────────────────────────────────────────┘
        ▼ ~tens of leads w/ verified emails
┌──────────────────────────────────────────────────────────────┐
│ Stage 4 — AI personalization (Deepinfra GPT-OSS-20B)         │
│ Extract from job description: tech_skills, usecase,          │
│   company_description, normalized role_being_hired           │
└───────┬──────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 5 — Instantly campaign upload                          │
│ Fetch existing campaign leads → dedupe                       │
│ POST /api/v2/leads w/ custom_variables for template          │
│ skip_if_in_workspace: false (cross-campaign dedupe DISABLED) │
│ skip_if_in_campaign: true  (in-campaign dedupe ON)           │
└──────────────────────────────────────────────────────────────┘
```

Reference Instantly upload payload — **`skip_if_in_workspace: false` MUST stay
false**. The user runs multiple Instantly campaigns per workspace and wants
the same lead to be reachable in multiple campaigns (different angles).
The `fetchExisting()` pre-check + `skip_if_in_campaign: true` is enough to
prevent re-adding the same lead to the same campaign on weekly re-runs.

---

## EXECUTION FLOW

### Step 0 — Read the strategy doc + reverse-prompt for missing fields

Required inputs from the user:
- Strategy doc URL (Google Doc) OR the campaign brief inline
- Client name + Instantly workspace API key
- Target campaign — existing campaign ID OR "create one for me with this
  template subject + body"

Reverse-prompt for these if not given:
- **Role keywords** (the list to feed JSearch — e.g. `["Machine Learning
  Engineer","ML Engineer","NLP Engineer", ...]`). Aim for 5-10 variants of
  the same persona to maximize JSearch coverage.
- **Countries** (2-letter codes, e.g. `["US","CA"]`)
- **ICP headcount buckets** (from strategy doc; e.g. `["1-10","11-50"]` for
  TechHive Campaign C)
- **Industries to exclude** (regulated, mega-corp, agency-competitor)
- **Decision-maker cascade** (Founder/CEO first, then CTO, then Head of X)
- **Personalization variables** (what the email template references —
  typically `role_being_hired`, `tech_skills`, `usecase`,
  `company_description`)

Save to `clients/<client>/<campaign_slug>/icp.json`.

### Step 1 — Stand up the project directory

```
clients/<client>/<campaign_slug>/
├── .env                    # client-specific API keys (gitignored)
├── icp.json                # the Step 0 spec
├── modules/                # copy from the reference deployment
│   ├── _common.py
│   ├── job_scraper.py
│   ├── company_filter.py
│   ├── dm_finder.py
│   ├── email_enricher.py
│   ├── personalizer.py
│   └── instantly_uploader.py
├── workflow.py             # Python orchestrator (sequential)
├── n8n/
│   └── workflow.ts         # n8n SDK source-of-truth
└── FINAL_STATUS.md         # handoff doc
```

**Always copy modules from the reference deployment** —
[clients/techhive/campaign_c_staff_aug_ai_ml/modules/](../../clients/techhive/campaign_c_staff_aug_ai_ml/modules/) —
rather than rewriting from scratch. Edit only the per-client config
(`ROLES`, `COUNTRIES`, `ALLOWED` size buckets, `EXCLUDE_INDUSTRY`, the
waterfall `CASCADE`, the Instantly campaign ID).

### Step 2 — Validate Python locally first (smoke test, ~5 leads)

Per the workspace rule "build entire workflow in your environment and try
it out — once validated, then only create it on n8n":

```bash
cd clients/<client>/<campaign_slug>
python3 workflow.py --smoke   # 1 role, US only, 1 page, cap 5 companies
```

Check that:
- ≥1 lead landed in the target Instantly campaign
- The `payload.custom_variables.icp_size_bucket` field is populated and
  matches the strategy doc ICP

Only proceed to n8n when local validation passes.

### Step 3 — Probe APIs from inside the n8n sandbox

n8n's Code-node sandbox has notable constraints that will silently break
naive code:

| Constraint | Workaround |
|---|---|
| `fetch` is NOT defined | Use `require('https')` — see `HELPERS` in the reference workflow |
| `URL` global is NOT defined | Use `require('url').URL` |
| `EXECUTIONS_TIMEOUT` is typically 300s but may be longer on self-hosted | Test once; if it cancels at exactly 5m, the env var caps it |
| Outbound calls inherit the n8n server's IP — RapidAPI shared keys may hit hard rate limits there | Use a **dedicated paid RapidAPI plan** for JSearch (10 req/s); the shared team key on `.mcp.json/rapidapi-linkedin-bulk` is fine for BlitzAPI |
| `Instantly /api/v2/leads/list` is flaky and intermittently returns 0 items | Retry up to 15× with 1s backoff in any verification script |

### Step 4 — Generate n8n workflow code

Use the SDK pattern from the reference `n8n/workflow.ts`. Key rules:

1. **One Code node per pipeline stage** (NOT per HTTP call — that explodes
   the node count for waterfall logic). Each stage is `mode:
   'runOnceForAllItems'` + `language: 'javaScript'`.
2. **Inject the `HELPERS` block at the top of every stage** — defines
   `httpJson()` with retry, `pMap()` for bounded concurrency, `sleep()`.
3. **Concurrency tuning** (validated 2026-05-25 against TechHive
   deployment, n8n exec 176644, 10m wall time):
   - Stage 1 (JSearch, paid plan): 8
   - Stage 1b (BlitzAPI, generous): 10
   - Stage 2 (BlitzAPI Waterfall): 8
   - Stage 3 (BlitzAPI email + Google DoH): 8
   - Stage 4 (Deepinfra LLM): 6
   - Stage 5 (Instantly upload): 4
4. **Always validate with `mcp__n8n-mcp__validate_workflow` before
   `create_workflow_from_code`**.
5. **Schedule trigger:** `field: 'weeks'`, `triggerAtDay: [1]` (Monday),
   `triggerAtHour: 9`, `triggerAtMinute: 0`.
6. Each stage MUST end with `console.log('STAGE_N stats:', JSON.stringify(stats))`
   so the user can inspect what happened per stage in the execution UI.

### Step 5 — Browser-drive the validation

Log into n8n, navigate to the workflow, click the "Execute workflow" button,
watch the execution panel update. **Do not declare done until you see the
"Succeeded in Xm Ys" entry in the executions list AND `uploaded > 0` in
Stage 5's output.**

The reference deployment took 10m to complete with concurrency-8 / 10-pages
config. Plan to wait 8-12 min after triggering.

Common debug paths:
- Stage 1 finishes in <5s with `data.main: [[]]` → JSearch rate-limited
  (probably 429). Check the response headers via a local probe with the same
  key. If quota exhausted, see Step 6.
- Stage 1 hangs >5 min then cancels → too aggressive concurrency causing
  retry pile-ups. Drop concurrency by half and retry.
- Stage 5 `uploaded: 0, skipped_in_campaign: N` → leads exist already.
  Confirm the workflow ran the Stage 4 personalizer to update variables
  on the existing leads (it can't — they're already there).

### Step 6 — Top-up checklist (before next Monday)

The pipeline depends on paid API quota. Before scheduling for production:

| API | Endpoint | Cost signal |
|---|---|---|
| RapidAPI JSearch | `jsearch.p.rapidapi.com` | `X-RateLimit-Requests-Remaining` header — needs ≥160/run |
| BlitzAPI | `api.blitz-api.ai` | Per-credit; ~3 credits per qualified lead (domain→LI + enrich + waterfall + email) |
| Instantly Supersearch + Verify | `api.instantly.ai` | If at 402, MX-check floor handles verification |
| Deepinfra | `api.deepinfra.com` | ~$0.0005 per lead |

### Step 7 — Publish + commit + push

```js
mcp__n8n-mcp__publish_workflow({ workflowId: '<id>' })
```

Then update [`.mcp.json`](../../.mcp.json) if a new API key was provisioned,
write a `FINAL_STATUS.md` next to the workflow, and commit + push:

```bash
git add .mcp.json .gitignore clients/<client>/<campaign_slug>/
git commit -m "Add <client> Campaign — weekly hiring-signal automation"
git push origin main
```

---

## CHECKLIST BEFORE DECLARING DONE

- [ ] Strategy doc parsed → `icp.json` written + reverse-prompted user for any ambiguities
- [ ] Per-client folder under `clients/<client>/<slug>/` with copied modules
- [ ] Python smoke test added ≥1 lead to the target Instantly campaign
- [ ] n8n workflow created + published (cron-armed for Monday 09:00)
- [ ] Manual browser execution succeeded (`uploaded > 0`)
- [ ] Each Instantly lead carries `payload.custom_variables.icp_*` audit fields matching the strategy-doc ICP
- [ ] `skip_if_in_workspace: false` in the Stage 5 payload (cross-campaign dedupe DISABLED — user runs multiple campaigns per workspace)
- [ ] `FINAL_STATUS.md` written with the workflow URL, latest exec ID + result, scale-up instructions
- [ ] `.env` + `output/` are gitignored
- [ ] Pushed to GitHub

---

## REFERENCE DEPLOYMENT (TechHive Campaign C)

- **Client:** TechHive (custom software & SaaS agency, Surat IN)
- **Campaign angle:** Staff augmentation — "Saw you're hiring [role]. I have 2-3 pre-vetted candidates ready to join in 2 days who are great with [tech_skills]"
- **Roles:** 8 AI/ML engineer variants (Machine Learning Engineer, ML Engineer, Deep Learning Engineer, NLP Engineer, Computer Vision Engineer, AI Research Engineer, Applied AI Engineer, AI Engineer)
- **Geo:** US + CA
- **ICP size:** 1-10 / 11-50 employees (per strategy doc Campaign C)
- **n8n workflow:** [zRIGcUQcB2TBMSAS](https://n8n.intentledsales.com/workflow/zRIGcUQcB2TBMSAS)
- **Instantly campaign:** `dfd51d7d-f85f-4ab5-8f4b-8e9d0d507267`
- **Latest validated exec:** `176644` (2026-05-25, 10m 2s, +10 ICP-fit leads)

Project files: [clients/techhive/campaign_c_staff_aug_ai_ml/](../../clients/techhive/campaign_c_staff_aug_ai_ml/)

---

## SECOND REFERENCE DEPLOYMENT (QSET — multi-region, 50+ ICP)

- **Client:** QSET / Chhatrapati Technologies LLP (eng staff-aug + AI/ML, https://qset.in)
- **Angle:** "Saw {{company_name}} is hiring a {{open_role}} — vetted senior {{open_role_category}} engineer embedded in 5-10 days."
- **Roles:** 57 eng titles (Full Stack/Backend/Frontend/DevOps/Data/AI-ML). Leadership titles are DM-cascade targets, NOT scrape queries.
- **Geo:** US/UK/CA/AU. **ICP size: 50+ (drop <50 AND 10,000+)** — the INVERSE of TechHive.
- **n8n workflow:** [9hGX0ADTGoiKsRt7](https://n8n.intentledsales.com/workflow/9hGX0ADTGoiKsRt7) · 2026-06-18: 904 companies → 273 qualified → 725 DMs (3/company) → 394 verified → ~407 uploaded across 5 regions.
- **DM cascade:** senior decision-makers ONLY (Founder/CEO/President → CxO/VP → Director/Head/Eng-Mgr), no recruiters, up to 3/company.
- **5 per-region Instantly campaigns:** US `1417b6e0-…` & CA `3d5ec0c1-…` (America/Detroit), UK `0f00b9cc-…` (Europe/Isle_of_Man), EMEA-ex-UK `5083f478-…` (Europe/Belgrade), AU/NZ `8978f440-…` (Australia/Melbourne). Keys hardcoded server-side (client wanted zero-touch); GitHub copy stays `$env`.
- Project files: [clients/qset/job_scraping_eng_hiring/](../../clients/qset/job_scraping_eng_hiring/)

### Generalizations learned (apply per-client)

1. **ICP size is arbitrary, not fixed.** Parameterize as confirmed-too-small / confirmed-too-big drop sets + an employees-on-LinkedIn floor/ceiling; **keep + flag** unknown headcount (never drop on missing data). TechHive kept 1-10/11-50; QSET keeps 51-200…5001-10000.
2. **Industry excludes flip per client.** QSET *targets* healthcare/fintech/retail (TechHive excluded them) and only drops staffing/recruiting/outsourcing/gov. Always re-derive from the brief.
3. **Personalization can be deterministic (no LLM).** When the hiring signal itself is the hook, derive `open_role`/`open_role_category`/`job_count` from the JSearch data — skip Deepinfra/Firecrawl entirely (cheaper, zero LLM variance). Title-case + fix acronyms (AI/ML/AWS/.NET/CI-CD) since `open_role` is email-facing.
4. **Enrichment provider is a choice.** Blitz find-email + **MillionVerifier** (keep `ok`/`catch_all`) is the proven, synchronous path. Instantly SuperSearch waterfall is async (create lead-list → `/api/v2/supersearch-enrichment` → poll → paginate) — only use if asked.
5. **Multi-region campaigns by timezone.** Route each lead to a regional campaign by company HQ (fallback job country) so each region sends in business hours. Instantly's timezone enum uses representative cities — **probe before trusting**: US/CA Eastern=`America/Detroit`, UK=`Europe/Isle_of_Man`, AU=`Australia/Melbourne`, EMEA/CET=`Europe/Belgrade` (NOT New_York/London/Sydney/Berlin/Paris — those 400). Routing example (QSET): GB→UK, CA→CA, AU/NZ→AU, EU+ME+Africa→EMEA, else US. Pre-create ALL region campaigns each run (`ensureAllRegionCampaigns`) so empty regions still exist; `ensureCampaign` is find-by-name-or-create (idempotent across weekly runs).
6. **NEVER commit API keys.** n8n Code nodes read keys via `$env.RAPIDAPI_KEY` etc.; the committed `workflow.ts` and the `create_workflow_from_code` payload must contain NO secrets (the auto-mode classifier blocks it, and RULE-002 forbids it). Set the 4 vars on the n8n instance; real values live only in the gitignored client `.env`. (The old TechHive workflow hardcoded keys — do not copy that.)
7. **Local mirror = Node when no Python.** If the host lacks Python, write the mirror as CommonJS `.cjs` using `require('https')` — it's a *more* faithful n8n mirror than Python (same sandbox constraints) and the n8n Code nodes are literally this code inlined. See `clients/qset/job_scraping_eng_hiring/local_runner/`.
8. **scheduleTrigger-only workflows can't be manually run via the `execute_workflow` API** (returns a ~100ms no-op `success`). Verify either by browser-driving "Execute workflow" or by trusting the local mirror run (identical code) + confirming `$env` is set.
