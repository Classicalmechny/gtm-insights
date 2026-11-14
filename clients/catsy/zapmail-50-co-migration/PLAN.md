# Zapmail 50-domain × 150-mailbox provisioning plan

## Goal
- Connect 50 existing Dynadot `.co` domains to Zapmail
- Provision 3 mailboxes per domain = 150 total
- Username pattern (matches old cohort): `elizabeth`, `elizabeth.tah`, `elizabeth.t`
- First/last name: `Elizabeth` / `Tah Bash` → display name "Elizabeth Tah Bash"
- Profile photo: the headshot Elizabeth attached to chat (needs disk save)
- Billing constraint: existing ~100-mailbox subscription should "absorb" 100 of the 150; only the additional ~50 should hit the credit card

## ⚠️ The one critical thing about Zapmail billing

Per Zapmail's [Mailbox Management FAQ](https://help.zapmail.ai/en/articles/9541207-faqs-mailbox-management-in-zapmail):

> "Yes — but only next billing cycle. Once used, a slot is locked for that cycle even if the mailbox is deleted. Slots reset automatically at the next billing renewal."

Translation: deleting the 100 burnt mailboxes today does **not** free their subscription slots until the next renewal. If we provision 150 new mailboxes *now*, all 150 are net-new charges, and the old 100 keep billing until their renewal date.

**There are two viable paths**:

### Path A — wait for the renewal date (zero double-bill)
1. Today: register the 50 domains in Zapmail (free, no mailbox slot consumed)
2. Today: update NS at Dynadot
3. Today: open Intercom in Zapmail dashboard and ask billing to confirm renewal date + any pre-paid swap mechanism
4. On the renewal date: bulk-delete the old 100 burnt mailboxes (Smartlead delete already done; need to delete on Zapmail side too)
5. Renewal +1h: provision 150 mailboxes via API. The first 100 reuse the released slots; the additional 50 hit the card. Net charge: only ~50 new mailboxes.

**Cost on renewal date**: 50 mailboxes × ~$3/mo = $150/mo additional, vs current spend.

### Path B — provision now, accept the gap charge (faster)
1. Today: register 50 domains + update NS at Dynadot
2. Today: provision 150 mailboxes (double-billed for ~30 days with the burnt 100 still on the plan)
3. Today: bulk-delete old 100 in Zapmail to stop them billing at next renewal
4. Today: warmup starts on new mailboxes

**Cost vs Path A**: ~$300 of extra spend for ~30 days of overlap, but you start warming today instead of waiting for the renewal cycle.

### Recommended: Path B if the renewal date is >2 weeks away.
Reason: every day of delay is a day you can't send. The 14-day warmup before any cold sending is the long pole. Spending $300 to start warming 14 days earlier almost always pays back in pipeline.

## Step-by-step execution (Path B)

| # | Step | Script / action | Who does it |
|---|---|---|---|
| 1 | Save Elizabeth photo to `assets/elizabeth.png` | manual (see "what I need from you") | user |
| 2 | Host photo at a public URL (R2/S3/Imgur) | manual or I can do it via a quick CF Worker | user or me |
| 3 | Paste 50 .co domains into `domains.txt` | manual | user |
| 4 | Add 50 domains to Zapmail, capture NS pairs | `01_add_domains.py` | me, once API key is set |
| 5 | Bulk-update NS at Dynadot using `domains_with_ns.csv` | manual UI or Dynadot API | user (or me with Dynadot creds) |
| 6 | Wait 24h for DNS propagation | passive | — |
| 7 | Provision 150 mailboxes (3 per domain) | `02_provision_mailboxes.py` | me |
| 8 | Upload Elizabeth photo to all 150 | `03_set_photos.py` | me |
| 9 | Bulk-delete the 100 burnt mailboxes from Zapmail (stop next-cycle billing) | one-off script | me |
| 10 | Add new 150 to Smartlead and start warmup | Smartlead API | me |

## What I need from you to start

1. **Zapmail API key** — Dashboard → Settings → Integrations → API. Paste into `.env` or just into chat; I'll handle it.
2. **The 50 .co domain names** — paste them as a list into chat; I'll write `domains.txt`.
3. **Elizabeth's photo on disk** — save the attached image to `/Users/anirudhgupta1177/Antigravity/Personal Assistant/clients/catsy/zapmail-50-co-migration/assets/elizabeth.png`. (Claude Code attached images aren't directly file-accessible to me — I see the photo but can't write the bytes to disk.) Also: a public URL works too if you'd rather host it on Drive/S3.
4. **Zapmail billing renewal date** — check Dashboard → Billing → Next renewal. Determines Path A vs Path B. If unclear, message Zapmail Intercom: *"What's our next renewal date, and can deleted-mailbox slots be reused for new mailboxes within the same cycle?"*
5. **Path A or Path B confirmation** once we know the renewal date.

## Why Zapmail and not InboxKit?

You said use Zapmail — happy to comply. Note for the record: [InboxKit (2026 benchmarks)](https://www.inboxkit.com/learn/maildoso-review) lands ~92% inbox vs Zapmail's ~83% on the same test cohort. **Today's session is about replacing burnt domains, not changing platforms — so we stick with Zapmail.** If burn rate stays high after the swap, the next move is to migrate to InboxKit.
