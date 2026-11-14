# TechHive — Campaign C — Staff Aug (AI/ML hires US+CA)

**n8n workflow:** [zRIGcUQcB2TBMSAS](https://n8n.intentledsales.com/workflow/zRIGcUQcB2TBMSAS)
**Instantly campaign:** `dfd51d7d-f85f-4ab5-8f4b-8e9d0d507267`
**Cron:** every Monday 09:00 (n8n instance TZ) — published & active.
**RapidAPI:** dedicated paid plan (50K/mo, 10 req/sec) — `8367fed8...`

## Latest validated execution (browser-driven, 2026-05-25)

| Metric | Value |
|---|---|
| Execution ID | `176644` |
| Status | ✅ success |
| Wall time | 10m 2s |
| Stage 5 input (leads with verified email) | 13 |
| Stage 5 uploaded (new ICP-fit) | **10** |
| Stage 5 skipped (already in campaign) | 3 |
| Stage 5 failed | 0 |
| Existing in campaign before run | 5 |
| Campaign total after run | ~15 |

## Pipeline (v7 high-volume)

| Stage | What it does | Concurrency | Typical wall |
|---|---|---|---|
| 1 — JSearch | 8 AI/ML roles × US+CA × 10 pages = 160 queries | 8 | ~1.5–2 min |
| 1b — ICP firmographic filter | BlitzAPI domain→LI + company enrich; keep headcount 1–10 / 11–50, US/CA HQ, exclude regulated/agency industries | 10 | ~3–5 min |
| 2 — DM finder | BlitzAPI Waterfall ICP (Founder → CTO → Head of AI cascade); Employee-Finder fallback | 8 | ~30 s |
| 3 — Email + verify | BlitzAPI find-work-email + free Google DoH MX-check floor (Instantly verify-email tried first, degrades gracefully on 402) | 8 | ~30 s |
| 4 — Personalize | Deepinfra GPT-OSS-20B → `tech_skills`, `company_description`, `usecase` | 6 | ~30–60 s |
| 5 — Upload | Fetch existing campaign leads (dedupe) → push new leads to Instantly campaign with full custom-variable payload + ICP audit fields | 4 | ~10 s |

## Robustness features

- `httpJson()` retries on 429 / 5xx / network errors with exponential backoff (1s → 2s → 4s → 8s → 10s)
- `pMap()` bounded-concurrency map — per-item errors are caught and the worker pool keeps draining
- Per-stage `stats` JSON logged to `console.log` — inspect via the n8n execution view → click stage → Output tab
- `skip_if_in_campaign: true` on Instantly upload + workspace-wide dedupe via `fetchExisting()`
- Each lead carries audit custom variables (`icp_size_bucket`, `icp_industry`, `icp_hq_country`, `icp_employees_li`) so you can confirm ICP fit in the Instantly UI

## Per-lead custom variables (for email template placeholders)

- `{{role_being_hired}}` — normalized role (ML Engineer, NLP Engineer, etc.)
- `{{tech_skills}}` — 2-4 most important tech skills from the job description
- `{{usecase}}` — one-sentence description of what the hire will build
- `{{company_description}}` — one-line description of what the company does
- `{{job_apply_link}}` — JSearch link to the original posting
- `{{job_city}}` — where the posting is for
- `{{job_title_hiring}}` — verbatim job title from posting
- `{{linkedin_url}}` — DM's LinkedIn profile
- `{{person_title}}` — DM's current title
- `{{icp_size_bucket}}` / `{{icp_industry}}` / `{{icp_hq_country}}` — ICP audit (display only)

## How to scale up further (later)

Edit Stage 1 in [n8n/workflow.ts](n8n/workflow.ts):
- Add more roles to `ROLES` — e.g. `Senior ML Engineer`, `Staff AI Engineer`, `LLM Engineer`, `GenAI Engineer`, `MLOps Engineer`
- Add countries — e.g. `UK`, `AU` (also relax `ALLOWED_HQ` in Stage 1b)
- `PAGES_PER_ROLE` is already at 10 — JSearch effectively returns ~5–10 pages per query before going empty

The current 50K/mo RapidAPI plan supports ~160 queries/week × 4 weeks = 640 queries/mo — well within budget.

## Local mirror (Python)

[modules/](modules/) + [workflow.py](workflow.py) — same pipeline in Python for local debugging. Triggered with:
```bash
python3 workflow.py --pages-per-role 3 --per-company-dms 1
```
Outputs intermediate CSVs to `output/<run_id>/`.
