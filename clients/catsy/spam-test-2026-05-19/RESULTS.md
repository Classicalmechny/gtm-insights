# Catsy Spam-Test Results — 2026-05-19

## Live campaign — DONE
- Campaign ID: `3355119` · status COMPLETED · https://app.smartlead.ai/app/email-campaigns/3355119/analytics
- 4 emails sent in 15 seconds (08:23:16 → 08:23:31 UTC, 19 May 2026)
- 0 bounces, 0 blocks, 3 already open-tracked

### Sender → inbox map (check these 4 inboxes now)
| Inbox to check | Sender used | Pre-flight warmup flag |
|---|---|---|
| anirudhgupta1177@gmail.com | elizabeth.t@wearecatsypim.com | ⚠️ 1× save-from-spam in last 7 days |
| anirudh@theorganicbuzz.com | elizabeth.t@teamcatsyapp.com | clean |
| agent@theorganicbuzz.com   | elizabeth.t@gocatsytech.com  | clean |
| anirudh@intentledsales.com | elizabeth.tah@mycatsyhub.com | clean |

Subject: `hi` (the `{{first_name|there}}` fallback rendered empty — Smartlead doesn't support pipe-fallback. Use bare `{{first_name}}` next time and ensure lead has a first_name.)

## Inventory
| Bucket | Count | Action |
|---|---|---|
| New zapmail (created 2026-04-18, tag `Zapmail 18/04/2026`) | 51 | SKIP per your instructions |
| Old zapmail (created 2025-08-03, type GMAIL) | 100 | All attached as senders to the test campaign |
| Untagged SMTP / private server (smtp.spyairplane.com) | 118 | **Awaiting your confirmation to delete** |

## Pre-flight signals on the 100 old zapmail mailboxes
- **Domain blacklists (Spamhaus DBL, SURBL multi, URIBL black) on all 33 unique sending domains**: 0 listings.
- **SPF / DMARC / DKIM (google selector)**: 100% published.
- **MX**: 100% on Google Workspace.
- **Warmup 7-day save-from-spam**: 96/100 clean, 4 flagged with 1 event each:
  - elizabeth@bestcatsy.com
  - elizabeth.tah@powercatsypro.com
  - elizabeth.t@primecatsytech.com
  - **elizabeth.t@wearecatsypim.com** (the one Smartlead just used to mail your Gmail — first real-world data point on the next inbox check)

Domain-level checks are noisy for fresh Workspace tenants. The campaign you're about to read in your 4 inboxes is the real signal.

## Coverage caveat
4 leads × 100 mailboxes = Smartlead tested 4 of 100 senders this cycle. To audit all 100, either:
- Re-run the campaign daily for ~25 days (Smartlead picks different senders each run), OR
- Plus-address the 4 inboxes 25× each → 100 leads → all 100 senders tested in one batch (~5 hours of sending at 3-min spacing). I can fire that off whenever you say go.

## SMTP/private-server cleanup — BLOCKED on your confirmation
**118 mailboxes** matching `type=SMTP` + `smtp_host=smtp.spyairplane.com`, username `cjteku@catsy*.com` across 39 unique domains. **0** are currently attached to any campaign (safe to delete).

Sample of what would be deleted:
```
id=8138993   cjteku@catsyaccelerate.com   smtp.spyairplane.com
id=8138991   cjteku@catsyadminpanel.com   smtp.spyairplane.com
id=8138987   cjteku@catsyai.com           smtp.spyairplane.com
id=8138981   cjteku@catsyautomate.com     smtp.spyairplane.com
id=8138979   cjteku@catsycode.com         smtp.spyairplane.com
... (113 more)
```
Full list in `untagged_smtp.csv` (118 rows).

**Reply "delete them" or "yes, delete the 118 SMTP mailboxes" and I'll run `python3 delete_smtp.py --confirm`.** I'll write delete_results.json after.

## Files produced
Workspace: `/Users/anirudhgupta1177/Antigravity/Personal Assistant/clients/catsy/spam-test-2026-05-19/`

- `RUNBOOK.md` — full step-by-step including API gotchas
- `RESULTS.md` — this file
- `all_accounts.json`, `*_zapmail.csv`, `untagged_smtp.csv`, `summary.txt`
- `blacklist_results.csv`, `blacklist_summary.txt`
- `warmup_signals.csv`
- `campaign_state.json` (campaign 3355119 provisioning trace)
- `create_campaign.py`, `fix_leads.py`, `monitor.py`, `show_senders.py`, `delete_smtp.py`

## Reusable skill registered
- `.claude/skills/smartlead-spam-test/skill.md` — fire next time with "spam test smartlead mailboxes" / "check if mailboxes are burnt".
