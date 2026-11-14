---
name: smartlead-spam-test
description: >
  Run a full deliverability audit on a Smartlead workspace: classify mailboxes,
  pull warmup signals, DNS-check sending domains, and provision a live demo
  campaign that fires from suspect mailboxes to user-controlled inboxes. Also
  handles bulk-deletion of stale SMTP/private-server mailboxes with a guarded
  confirmation flow.
triggers:
  - smartlead spam test
  - check if mailboxes are burnt
  - mailbox deliverability audit
  - spam test mailboxes
  - smartlead mailbox cleanup
  - smartlead delete mailboxes
tools:
  - Bash
  - Write
  - Edit
  - Read
  - WebFetch
---

# Smartlead Spam-Test Skill

## Overview
The user is shipping cold email through Smartlead and suspects some sending mailboxes are burnt (landing in spam). This skill produces three artefacts:
1. A classified mailbox inventory (which are fresh, which are suspect, which should be deleted)
2. Domain + warmup reputation signals for the suspect mailboxes
3. A live "spam test" Smartlead campaign that sends from those mailboxes to inboxes the user controls, so the user can eyeball spam/primary placement

## Inputs the skill needs
- **Smartlead API key** (workspace-scoped, e.g. `<uuid>_<suffix>`)
- **Which mailboxes to audit** — usually expressed as a Smartlead tag name (e.g. `zapmail`)
- **Which mailboxes to skip** — another Smartlead tag (e.g. `Zapmail 18/04/2026` for a known-fresh batch)
- **Recipient inboxes** the user owns — for inbox-placement verification
- **Whether to also clean up SMTP/private mailboxes** — boolean + confirmation

## Critical constraint
Smartlead's public REST API does **not** expose tag membership on email accounts (`/email-accounts` accepts no `tag_ids` filter, and the single-account response has no `tags` field). Classify by `created_at` date + `type` instead — most "tagged" cohorts are actually creation-date cohorts (e.g. a bulk Zapmail provisioning run all has the same `created_at` date).

## Step-by-step process

### 1. Pull and classify mailboxes
- Paginate `GET /api/v1/email-accounts/?limit=100&offset=N` until fewer than 100 returned
- Bucket by:
  - `type == "SMTP"` or `smtp_host` set → "SMTP/private" cohort (deletion candidates)
  - `created_at[:10]` matches the "skip" cohort date → SKIP
  - Everything else of type GMAIL/OUTLOOK → audit candidates
- Export each bucket as CSV with `id`, `from_email`, `type`, `created_at`, `warmup_reputation`, `warmup_total_spam_count`, `is_smtp_success`, `campaign_count`
- Present counts back to user before any destructive action

### 2. Domain-level reputation checks (cheap, run on all audit-candidate domains)
For each unique sending domain:
- DNS lookup against `<domain>.dbl.spamhaus.org`, `<domain>.multi.surbl.org`, `<domain>.black.uribl.com` — listed = blocklisted
- Verify SPF (`<domain>` TXT contains `v=spf1`)
- Verify DMARC (`_dmarc.<domain>` TXT contains `v=dmarc1`)
- Verify DKIM published (try selectors `google`, `smartlead`, `default`, `selector1`, `k1` at `<selector>._domainkey.<domain>`)
- Verify MX records published

For Zapmail-provisioned Google Workspace domains, expect 100% pass — this check only catches egregious failures. Real signal is the campaign test.

### 3. Per-mailbox warmup signals
For each audit-candidate mailbox: `GET /api/v1/email-accounts/{id}/warmup-stats`. The 7-day window of `stats_by_date[*].save_from_spam_count` is the strongest "live burnt" proxy — non-zero means warmup peers rescued emails from spam. Rank by save count descending. Note: warmup is peer-to-peer Smartlead inboxes, much more forgiving than real Gmail/Workspace. Treat zero saves as a *floor*, not a *ceiling*.

### 4. Provision the live spam-test campaign
Smartlead workflow (every request needs `?api_key=...`, all POST, `Content-Type: application/json`):
1. `POST /campaigns/create` → `{"name": "Spam Test — <cohort> — <YYYY-MM-DD>"}` → extract `id`
2. `POST /campaigns/{id}/email-accounts` → `{"email_account_ids": [<all audit-candidate ids>]}`
3. `POST /campaigns/{id}/sequences` → `{"sequences": [{"id": null, "seq_number": 1, "seq_delay_details": {"delay_in_days": 0}, "subject": "hi {{first_name|there}}", "email_body": "<short plain prose, no links/images>"}]}`
4. `POST /campaigns/{id}/settings` → `{"send_as_plain_text": false}` (do NOT send `stop_lead_settings: "NEVER"` — invalid; valid values are REPLY_TO_AN_EMAIL / OPEN_AN_EMAIL / CLICK_ON_A_LINK; omit to keep default)
5. `POST /campaigns/{id}/leads` → `{"lead_list": [{email,first_name,last_name}, …], "settings": {"ignore_global_block_list": true, "ignore_unsubscribe_list": true, "ignore_duplicate_leads_in_other_campaign": true}}` (do NOT include `skip_community_bounce_list` — rejected)
6. `POST /campaigns/{id}/schedule` → `{"timezone": "<active TZ>", "days_of_the_week": [0,1,2,3,4,5,6], "start_hour": "00:00", "end_hour": "23:59", "min_time_btw_emails": 3, "max_new_leads_per_day": 200, "schedule_start_time": null}`
7. `POST /campaigns/{id}/status` → `{"status": "START"}` (NOT "ACTIVE")

### 5. Coverage planning
With N mailboxes and L leads, Smartlead picks one sender per lead → only L mailboxes are tested per cycle. Options when N >> L:
- Run the campaign daily for several days (Smartlead picks different senders)
- Plus-address the user's inboxes (`anirudh+sl01@example.com`) and add N leads so each mailbox sends ~1 email
- Split into multiple smaller campaigns

Default to the user's exact lead list unless they explicitly ask for broader coverage — plus-addressing in Workspace tenants depends on admin settings.

### 6. Deletion flow (gated)
The deletion script must:
- Default to dry-run; require an explicit `--confirm` flag
- Hard-refuse to delete any mailbox with `campaign_count > 0`
- Print id + email + reason for each refusal before exiting
- Always surface counts + sample to the user and **stop for confirmation** before running with `--confirm`

DELETE endpoint: `DELETE /api/v1/email-accounts/{id}?api_key=...`

## API gotchas to memorize
- Tag membership: NOT in public API. Classify by `created_at` + `type`.
- `/campaigns/{id}/status` accepts `START` / `PAUSED` / `STOPPED`, not `ACTIVE`.
- Schedule write field: `min_time_btw_emails`. Read field: `min_time_btwn_emails`. (Smartlead's response typo.)
- Day-of-week indexing: `0=Sun … 6=Sat` per endpoint spec (other doc pages say `1=Mon … 7=Sun` — ignore those).
- Lead settings rejects `skip_community_bounce_list`.
- Settings `stop_lead_settings` does NOT accept `"NEVER"`. Omit if you want default.
- `urllib.request` on Python often gets 403 from Smartlead. Use `subprocess.check_output(["curl", ...])` instead.
- `min_time_btw_emails` minimum is 3 minutes.

## Output structure
Create `<workspace>/clients/<client>/spam-test-<YYYY-MM-DD>/` containing:
- `fetch_all.py`, `all_accounts.json`
- `categorize.py`, `<cohort>.csv` files, `summary.txt`
- `blacklist_check.py`, `blacklist_results.csv`, `blacklist_summary.txt`
- `warmup_signals.py`, `warmup_signals.csv`
- `create_campaign.py`, `fix_leads.py`, `campaign_state.json`
- `monitor.py`
- `delete_smtp.py` (dry-run by default)
- `RUNBOOK.md` — end-to-end narrative for the human to skim

## Edge cases
- **All-fresh workspace, no burnt signal anywhere**: still run the campaign — domain reputation and warmup are both noisy proxies. Real inbox placement is ground truth.
- **Workspace has client_id sub-accounts**: pass `client_id=<id>` on `/campaigns/create` so the campaign lives in the right sub-workspace.
- **Mailboxes have very low `message_per_day` (1-3)**: the test campaign may not drain fast. Either temporarily PATCH each mailbox to a higher limit or accept a slower rollout.
- **Workspace plus-addressing not supported on recipient Workspace**: plus-tagged leads will bounce. Test with one before scaling.
- **Public API rejects `--include-tags`**: stop trying. Just classify by `created_at`.
