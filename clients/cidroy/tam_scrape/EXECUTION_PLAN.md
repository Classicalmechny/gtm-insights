# Cidroy TAM Lead Scrape — Execution Plan

## Objective
Deliver **~17,000 verified cold-email leads** as a single CSV. Every row has the
compulsory `email` + `first_name` + `company_name` (plus 9 free columns:
last_name, full_name, title, company_domain, company_linkedin_url, linkedin_url,
country, state, city, email_verification_status).

## Confirmed spec
| Field | Decision |
|---|---|
| Company size | 1–50 employees |
| Geography | US + Canada |
| Industry | Product-tech only (services / consulting / staffing / nonprofit excluded) |
| Roles | CEO / CTO / Founder / Co-Founder / Owner + any C-suite decision-maker |
| Sourcing | BlitzAPI `/v2/search/people` (unlimited plan → $0) |
| Email | BlitzAPI `/v2/enrichment/email` |
| Verify | MillionVerifier v3, keep `ok` only (~995k credits available) |
| Fit lever | LLM classifier (Deepinfra GPTOSS) → ~85–90% ICP fit |
| Deliverable | single `final.csv` |
| Where it runs | **your VPS**, unattended, ~5–7 hrs |

---

## PHASE 0 — Finalize code *(me, here — ~30–45 min)*
1. **Checkpointing / resumability** — every stage flushes to disk + records progress; a restart resumes from the last checkpoint (safe for a multi-hour run).
2. **LLM classifier stage** — dedupe sourced people to unique companies, classify each once (product-tech scaleup vs services/staffing/nonprofit), drop off-ICP. This is what lifts fit past the ~70% ceiling of industry/name filters.
3. **Same-folder `.env` loading** — so the VPS only needs `run.cjs` + `.env` side by side.
4. **Validate** with a fresh smoke, confirm fit ~85–90%.
5. Hand off deploy-ready `run.cjs`.

## PHASE 1 — Deploy to VPS *(you — ~10 min)*
1. Ensure Node 18+ (`node -v`; install if missing).
2. `mkdir -p ~/cidroy && cd ~/cidroy`; copy `run.cjs` in; create `.env` with the 2 keys.
3. Smoke test: `node run.cjs --smoke 20` → confirms keys + writes a small CSV.

## PHASE 2 — Launch the full run *(you — ~2 min, then walk away)*
```bash
tmux new -s cidroy
node run.cjs --full          # targets 17,000 verified
# Ctrl-b then d  to detach → close laptop / shut down freely
```

## PHASE 3 — Pipeline runs automatically on the VPS *(~5–7 hrs, unattended)*
Leads flow through 5 checkpointed stages:
1. **SOURCE** — BlitzAPI people search, cursor-paginate ~70k candidates; apply ICP + junk-company + title filters; dedupe by LinkedIn URL → `raw_people.csv`.
2. **CLASSIFY** — dedupe to unique companies; LLM tags each product-tech vs off-ICP; drop off-ICP people.
3. **EMAIL** — BlitzAPI finds a work email per surviving person (~5 req/s cap → the slow stage).
4. **VERIFY** — MillionVerifier checks each email; keep `ok` only.
5. **EXPORT** — dedupe by email, enforce compulsory fields, write `final.csv` + `summary.json`.

## PHASE 4 — Retrieve + QA *(you + me — ~15 min)*
1. Download the result (WinSCP drag-drop, or `scp user@VPS:~/cidroy/output/*/final.csv .`).
2. QA: confirm ~17k rows, 100% have email+name+company, all emails `ok`, spot-check 15–20 rows for ICP fit.
3. Import into Instantly / Smartlead.

---

## Outputs (on the VPS, under `~/cidroy/output/<run_id>/`)
- `final.csv` — ⭐ the deliverable
- `summary.json` — funnel counts, yields, fit %, timings
- `run.log` — per-stage progress (for monitoring)
- `raw_people.csv` + checkpoints — resumability artifacts

## Timeline
| Phase | Owner | Time |
|---|---|---|
| 0 — finalize code | me | ~30–45 min |
| 1 — deploy | you | ~10 min |
| 2 — launch | you | ~2 min |
| 3 — pipeline runs | VPS (auto) | ~5–7 hrs |
| 4 — retrieve + QA | you + me | ~15 min |

## Notes / risks
- **Speed floor = BlitzAPI's 5 req/s** on email enrichment; cost is ~$0 (BlitzAPI unlimited; MillionVerifier prepaid).
- Classifier drops ~20–30% of sourced companies → we source proportionally more (baked into the ~70k candidate target). TAM = 168,527, comfortably enough for 17k.
- Fully **resumable** — VPS reboot or network blip → re-run `node run.cjs --full`, continues from checkpoint.
- One open toggle: **LLM classifier IN (recommended, ~85–90% fit) vs OUT (~70% fit, ~1 hr faster).**
