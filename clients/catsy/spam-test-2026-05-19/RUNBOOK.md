# Catsy Smartlead Spam-Test Runbook — 2026-05-19

## Context
Client: **Catsy**. Smartlead workspace API key: `281384eb-44ec-4cf8-a22f-a209e7e76dcd_pqodlmq` (workspace user_id `16363`).

Goal: identify which mailboxes are burnt up (landing in spam) before scaling outbound back up.

## Inventory snapshot
Pulled all 269 mailboxes via `GET /email-accounts` (paginated, limit 100).

| Bucket | How identified | Count | Action |
|---|---|---|---|
| New zapmail (tag `Zapmail 18/04/2026`) | `created_at` date == 2026-04-18, type GMAIL | 51 | SKIP — fresh, not burnt |
| Old zapmail (tag `zapmail`) | type GMAIL, `created_at` 2025-08-03 | 100 | Spam-test candidates |
| Untagged SMTP / private server | type SMTP, or `smtp_host` set | 118 | Delete after user confirmation |

Tag membership cannot be filtered via the public Smartlead REST API — `tag_ids` is not an accepted query param on `/email-accounts`. We classify by `created_at` + `type` instead. The two batches have non-overlapping creation dates so this is reliable.

## Step 1 — Domain reputation pre-check (33 unique sending domains)
Script: `blacklist_check.py`. For each domain: dig against Spamhaus DBL, SURBL multi, URIBL black, then check SPF / DMARC / DKIM (google selector) / MX.

Result: **0 listings, 100% SPF + DMARC + DKIM, all on Google MX**. Expected for fresh Zapmail-provisioned Google Workspace tenants — domain blacklists almost never fire here. Use this check only to catch egregious failures; the campaign test below is the real signal.

## Step 2 — Per-mailbox warmup signals (100 mailboxes)
Script: `warmup_signals.py`. Hits `/email-accounts/{id}/warmup-stats` for each old-zapmail mailbox. The strongest "live burnt" signal is `stats_by_date[*].save_from_spam_count` — non-zero means warmup peers had to rescue this mailbox's emails from spam.

Result: **96/100 at 100% reputation with 0 saves over the last 7 days. 4 with a single save event**: `bestcatsy.com`, `powercatsypro.com`, `primecatsytech.com`, `wearecatsypim.com`. Warmup is forgiving (peer-to-peer Smartlead network), so this is a floor, not a ceiling — real Gmail will reveal the rest.

## Step 3 — Live spam-test campaign
Script: `create_campaign.py` + `fix_leads.py`.

- Campaign ID: **3355119**
- Name: "Spam Test — old zapmail mailboxes — 2026-05-19"
- Dashboard: https://app.smartlead.ai/app/email-campaigns/3355119/analytics
- Senders attached: 100 old-zapmail mailboxes
- Leads: 4 (anirudhgupta1177@gmail.com, anirudh@theorganicbuzz.com, agent@theorganicbuzz.com, anirudh@intentledsales.com)
- Sequence: 1 step, immediate
  - Subject: `hi {{first_name|there}}`
  - Body: short, plain prose, no links, no images
- Schedule: Asia/Bangkok timezone, all 7 days, 00:00–23:59, 3 min min spacing, 200 leads/day cap, no `schedule_start_time` (start immediately)
- Settings: default tracking on (mirrors production), `send_as_plain_text=false`
- Status: ACTIVE

**Read the result this way**: Smartlead's per-lead rotation picks one of the 100 senders for each lead. Each test cycle gives you 4 data points (1 per inbox). To sample more mailboxes, re-run the campaign (or duplicate with new leads using `+slXX` plus-addressing for 100-mailbox coverage in a single shot).

## Step 4 — SMTP/private-server deletion (BLOCKED on user confirmation)
Script: `delete_smtp.py`. Lists 118 mailboxes, 0 currently attached to any campaign — safe to delete.

Default behavior is `--dry-run`. Re-run with `--confirm` to actually delete.

Hard guard: refuses to delete any mailbox where `campaign_count > 0`.

All 39 unique SMTP sending domains follow the `catsy*.com` pattern with smtp_host `smtp.spyairplane.com` (private cold-email infrastructure provider, likely Maildoso or similar) and `cjteku@` username.

## API gotchas surfaced during this run
- `/campaigns/{id}/sequences` must be POST (not PATCH), body wraps a `sequences` array
- `/campaigns/{id}/leads` body settings rejects `skip_community_bounce_list` (it's an internal-only field, not exposed via public API)
- `/campaigns/{id}/settings` rejects `stop_lead_settings: "NEVER"` — valid values are `REPLY_TO_AN_EMAIL`, `OPEN_AN_EMAIL`, `CLICK_ON_A_LINK`. Default behaviour is fine for a spam test.
- `/campaigns/{id}/status` body is `{"status": "START"}` — `"ACTIVE"` is rejected.
- Schedule field is `min_time_btw_emails` on writes, but `min_time_btwn_emails` on reads (typo lives in their response schema).
- Tag membership on email accounts cannot be queried via public API. Use `created_at` + `type` as proxy.

## Files in this workspace
| File | Purpose |
|---|---|
| `fetch_all.py` | Paginate all email accounts |
| `all_accounts.json` | Raw API output (269 accounts) |
| `categorize.py` | Split into new/old/SMTP buckets |
| `new_zapmail.csv`, `old_zapmail.csv`, `untagged_smtp.csv` | Bucketed exports |
| `summary.txt` | Domain + creation-date breakdown |
| `blacklist_check.py`, `blacklist_results.csv`, `blacklist_summary.txt` | DNS reputation checks |
| `warmup_signals.py`, `warmup_signals.csv` | Per-mailbox 7-day warmup spam-save signal |
| `create_campaign.py`, `fix_leads.py`, `campaign_state.json` | Campaign provisioning |
| `monitor.py` | Live status check |
| `delete_smtp.py` | Deletion script (dry-run by default) |
