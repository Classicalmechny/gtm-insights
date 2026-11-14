# QSET — Job Scraping → Eng Hiring → Cold Email (multi-region weekly)

**Client:** QSET / Chhatrapati Technologies LLP — https://qset.in
**Angle:** Staff augmentation. "Saw you're hiring a {{open_role}} — we embed a vetted senior {{open_role_category}} engineer in 5–10 days, overlapping your hours."
**Built + validated:** 2026-06-18 (local Node runs) — deployed to n8n same day.

---

## What it does (6 stages, Mondays)

| Stage | Action | Engine |
|---|---|---|
| 1 | Scrape 57 eng-role titles × US/UK/CA/AU, last 7 days, dedupe by domain, drop FAANG/enterprise/IT-services/staffing/reposter employer names | RapidAPI **JSearch** (paid, 10 req/s) |
| 1b | **ICP filter — KEEP 50+ employees, DROP <50 and 10,000+**, drop staffing/recruiting/gov industries, geo US/UK/CA/AU/EU; unknown headcount kept + flagged | **Blitz** domain→LI + company-enrich |
| 2 | Find up to 2 decision-makers/company. Cascade: Founder/CEO → CTO/VP Eng → Dir/Head Eng/AI/Platform → recruiting | **Blitz** waterfall-ICP → employee-finder fallback |
| 3 | Find work email, verify, keep only `valid`/`catch_all` (drop risky/invalid/unknown) | **Blitz** find-email + **MillionVerifier** (Google-DoH MX floor on MV error) |
| 4 | Personalize — `open_role`, `open_role_category` (Full Stack/Backend/Frontend/DevOps/Data Eng/AI-ML), `job_count`. **Deterministic, no LLM** | from the hiring signal |
| 5 | Route each lead to its **regional Instantly campaign by HQ** (US/UK/CA/AU), find-or-create campaign + 4-email sequence, dedupe, upload | **Instantly** v2 |

`skip_if_in_workspace: false` (no cross-campaign dedupe — leads reachable across campaigns) · `skip_if_in_campaign: true` (no re-adding the same person to the same campaign on weekly re-runs).

---

## Deployed artifacts

- **n8n workflow:** [`9hGX0ADTGoiKsRt7`](https://n8n.intentledsales.com/workflow/9hGX0ADTGoiKsRt7) — published, cron-armed **Monday 09:00**, runs **unattended** (keys hardcoded server-side per client request; see secrets note).
- **5 Instantly campaigns** (all **paused/draft** — assign mailboxes + activate to send). DM = senior decision-makers only (CxO/VP/President/Director/Head), up to 3/company:

| Region | Campaign | ID | Timezone | Leads |
|---|---|---|---|---|
| US | QSET - Job Scraping - Eng Hiring [US] | `1417b6e0-f82a-429e-92c7-d0b37c18b424` | America/Detroit | ~317 |
| CA | QSET - Job Scraping - Eng Hiring [CA] | `3d5ec0c1-efb9-4e2e-a132-68c18d9180c9` | America/Detroit | ~73 |
| UK | QSET - Job Scraping - Eng Hiring [UK] | `0f00b9cc-69df-48e3-a823-8639f57e217b` | Europe/Isle_of_Man | ~7 |
| EMEA (ex-UK) | QSET - Job Scraping - Eng Hiring [EMEA] | `5083f478-3eca-465f-90b9-1c70fd96c5d0` | Europe/Belgrade (CET) | 7 |
| AU/NZ | QSET - Job Scraping - Eng Hiring [AU] | `8978f440-5156-493a-a99a-8651f4e29eef` | Australia/Melbourne | 2 |

**Seed (904 co → 273 qualified) + DM-expansion runs (2026-06-18):** 725 decision-makers → 394 verified → **~407 leads uploaded across 5 regions, 0 failed.** Routing: company HQ → region (EU/ME/Africa→EMEA, NZ→AU, unknown→US).

---

## Secrets & how it runs unattended

- **n8n (server-side):** keys are **hardcoded** in the deployed workflow (client asked for zero-touch operation) — so the Monday cron just runs. These live only in n8n, never in git.
- **GitHub (`n8n/workflow.ts`):** the committed copy reads keys from `$env.*` and contains **no secrets** (RULE-002). To regenerate the server-side build, substitute the 4 keys from `.env`.
- **Local runner:** loads keys from the gitignored `.env`.

**Timezone:** the cron fires at the n8n instance timezone. For exact 09:00 **UTC**, set the workflow's timezone to UTC in n8n settings.

---

## Local mirror / re-run (canonical validation path)

`local_runner/` is CommonJS using `require('https')` — **identical logic to the n8n Code nodes** (the n8n stages are this code inlined). Run locally with Node (keys auto-loaded from `.env`):

```bash
cd local_runner
node run.cjs --smoke                 # ~8 roles, US, tiny funnel, creates/uses campaigns
node run.cjs                         # FULL: 57 roles × US/UK/CA/AU × 3 pages, per-region upload
node run.cjs --pages 2 --cap 1500 --per-company 1 --date-posted month   # bounded seed
node upload_only.cjs ../output/<run>/stage4_personalized.csv            # re-upload only (no Blitz spend)
```

Outputs (gitignored): `output/<run>/stage{1..5}*.csv` + `summary.json`.

## Cost per full weekly run (57 roles × 4 geos × 3 pages)
- JSearch ~684 queries (~70s; within 50K/mo paid plan)
- **Blitz ~5–6k credits** (2 calls/company at the filter is the driver) — top up before relying on it
- MillionVerifier ~250 verifications · ~350–500 verified leads/run

## Scale levers (edit `local_runner/lib.cjs` + redeploy n8n)
- `ROLES`, `COUNTRIES`, `PAGES_PER_ROLE` (Stage 1) · `PER_COMPANY` 1→3 (Stage 2)
- ICP filter (`SIZE_TOO_SMALL/BIG`, `ALLOWED_HQ`, `EXCLUDE_INDUSTRY`) · `REGIONS` map (Stage 5)
