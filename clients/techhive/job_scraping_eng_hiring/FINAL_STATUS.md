# TechHive — Job Scraping → Eng Hiring → Cold Email (multi-region weekly)

Exact clone of the QSET pipeline (see `clients/qset/job_scraping_eng_hiring/`),
**with one change: the ICP is SMALL companies (1–50 employees)** instead of 50+.
Same regions, roles, DM cascade, enrichment, sequence, and weekly cron.

- **Client:** TechHive (custom software & SaaS agency). Staff-aug angle, signature `Partnerships {{RANDOM | @TechHive | - TechHive}}`.
- **The only differentiator vs QSET:** Stage 1b keeps `1-10` / `11-50` employee companies and **drops everything 51+** (`SIZE_TOO_BIG` = 51-200 … 10001+, `EMP_CEIL = 50`). Verified live: seed dropped 1,112 companies as 51+, kept 175 sub-50.
- Every lead carries the size differentiator as custom vars: `icp_size_bucket` (e.g. `11-50`), `icp_employees_li` (e.g. `29`), `icp_headcount_verified`.

## Deployed artifacts
- **n8n workflow:** [`8NH5Kd69Aan6QBT9`](https://n8n.intentledsales.com/workflow/8NH5Kd69Aan6QBT9) — published, Monday 09:00 cron, keys hardcoded server-side (runs unattended). Git copy is `$env` (secret-free).
- **5 Instantly campaigns** (TechHive workspace, all **ACTIVE**, 159-mailbox TechHive pool each):

| Region | Campaign ID | Timezone | Leads |
|---|---|---|---|
| US | `12130179-48a5-41cc-a20c-136f14a87dfe` | America/Detroit | 105 |
| CA | `40cb1709-dc25-4f87-b49d-1c050aaf0289` | America/Detroit | 5 |
| UK | `4c3ffdda-c612-409c-a4f4-fa6e3f0ff8a8` | Europe/Isle_of_Man | 4 |
| EMEA | `6819585d-eeec-4c7f-9586-f81e748daed3` | Europe/Belgrade | 3 |
| AU | `cecf84e1-57dc-426a-a19a-592f2f9cf791` | Australia/Melbourne | 3 |

**Seed (date_posted=all, 2026-06-18):** 2,107 companies → 175 qualified (1–50) → 175 DMs → **120 verified → 120 uploaded, 0 failed.**

## Secrets & operation
- TechHive Instantly key lives in this folder's gitignored `.env` as `INSTANTLY_KEY` (reusable for all TechHive Instantly ops from Claude Code — no need to re-paste).
- n8n keys hardcoded server-side; committed `workflow.ts` stays `$env`.
- Shared RapidAPI / Blitz / MillionVerifier keys (same as QSET).

## Local runner
`local_runner/` — same CommonJS pipeline as QSET. `node run.cjs` (full), `--smoke`, `resume_from_qualified.cjs`, `assign_and_launch.cjs` (assign pool + activate). Keys auto-load from `.env`.

## Caveats (same as QSET)
- Replies need a human; Blitz/RapidAPI/MillionVerifier credits need top-ups; mailboxes are warming (watch deliverability); no failure alerting; first real n8n run is next Monday (logic proven locally, n8n run not yet observed end-to-end).
