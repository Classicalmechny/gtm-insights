---
name: campaign-optimization
description: |
  Rebalance Instantly per-campaign daily_limit so total = workspace mailbox capacity. Use when the user asks to lower sending limits, allocate capacity, optimize by EPP, prioritize low-EPP campaigns, or rebalance after adding/removing mailboxes or campaigns. Applies to both SaaS and VIP workspaces.
  Trigger phrases: "lower sending limit", "rebalance daily_limit", "allocate capacity", "optimize by EPP", "prioritize low EPP campaigns".
---

# Campaign Capacity Optimization

Recompute per-campaign `daily_limit` so the sum exactly equals workspace mailbox capacity, with two allocation rules:

1. **Signal-based campaigns get a floor of 5,000/day each** (or `capacity ÷ N_signals` if the floor doesn't fit).
2. **Non-signal campaigns split the remainder, weighted by inverse EPP** (Emails Per Positive). Lower EPP = higher allocation. Inactive campaigns (status≠1) are excluded.

## Why this matters

- Without rebalancing, every campaign sits at 50,000 daily_limit (Instantly default) while workspace mailbox capacity is ~30K-60K total. The campaigns compete for the same shared mailboxes; high-priority signal campaigns starve under random scheduling.
- After rebalancing, signal campaigns get guaranteed throughput and bulk-outbound campaigns are throttled in proportion to their efficiency (lower EPP = more capacity).

## Inputs

| Source | Endpoint | What we need |
|---|---|---|
| Workspace mailbox capacity | `GET /accounts?limit=100` (paginate) | sum of `daily_limit` across active mailboxes (`status==1`) |
| Campaign list + status | `GET /campaigns?limit=100` (paginate) | filter to `status==1` (active) |
| EPP per campaign | `GET /campaigns/analytics?limit=100` | `emails_sent_count`, `total_opportunities` |

## Algorithm

```
1. capacity = sum(account.daily_limit for account in accounts if account.status == 1)
2. active_campaigns = [c for c in campaigns if c.status == 1]
3. signals     = [c for c in active_campaigns if c.id in SIGNAL_IDS]
4. non_signals = [c for c in active_campaigns if c.id not in SIGNAL_IDS]

5. signal_floor = 5000
6. signal_need  = signal_floor * len(signals)
7. if signal_need > capacity:
     signal_alloc = capacity // len(signals)    # scale down, no non-signal budget
     non_signal_budget = 0
   else:
     signal_alloc = signal_floor
     non_signal_budget = capacity - signal_need

8. For each non-signal campaign:
     epp = sent / positives  (if sent >= 500 and positives > 0)
     else: epp = workspace median EPP (default fallback)

9. weight[c] = 1 / epp[c]
10. wsum     = sum(weights)
11. alloc[c] = round(non_signal_budget * weight[c] / wsum)
12. Round-adjust: apply rounding delta to highest-weight non-signal so sum == budget exactly

13. PATCH /campaigns/{id} {"daily_limit": alloc}
```

## Fallback EPP for low-data campaigns

A campaign with `sent < 500` OR `positives == 0` has no reliable EPP — using its observed ratio either overweights (e.g. 100 sent / 1 positive = EPP 100) or divides by zero. We fall back to the **workspace median EPP** of the campaigns that DO have data. This gives them a "neutral" weight until they have enough volume to be judged on their own.

## Signal IDs (read from [shared.ts](../../../signal-campaigns/src/lib/shared.ts) `CAMPAIGNS` + `CAMPAIGNS_VIP`)

8 IDs per workspace. Update this list whenever a new signal campaign is added or removed.

## Application (PATCH /campaigns/{id})

`PATCH /campaigns/{id}` accepts `daily_limit` (integer). Returns the updated campaign on success. The response includes the new daily_limit — verify it matches what was sent.

**Gotcha**: `PATCH /campaigns/{id} {"status": 1}` returns HTTP 500. To activate use `POST /campaigns/{id}/activate`. To rebalance daily_limit, PATCH works fine.

## When to re-run this optimization

| Trigger | Why |
|---|---|
| After adding/removing campaigns | Total allocation drifts; rebalance |
| After warming up new mailboxes | Workspace capacity grew; reallocate the gain |
| After 4+ weeks of new data | EPP estimates stabilize; allocations should reflect updated efficiency |
| After deactivating high-EPP campaigns | Budget freed up for low-EPP / signal campaigns |

## Last run (2026-05-19)

| Workspace | Capacity/day | Signal floor (×N active) | Non-signal budget | Total allocated |
|---|---|---|---|---|
| SaaS | 30,645 | 5,000 × 5 = 25,000 | 5,645 | 30,645 (100%) |
| VIP | 59,796 | 5,000 × 4 = 20,000 | 39,796 | 59,796 (100%) |

See [docs/SOPs/Campaign-Capacity-Optimization.md](../../../docs/SOPs/Campaign-Capacity-Optimization.md) for the full allocation table.

## Pitfalls + edge cases

| Edge case | Handling |
|---|---|
| Signal floor × N > workspace capacity | Scale floor to `capacity ÷ N_signals`; non-signal budget = 0 |
| Non-signal campaign with sent < 500 (too small to score) | Use workspace median EPP as fallback |
| Non-signal campaign with positives = 0 | Same fallback — avoid divide-by-zero |
| Rounding leaves total ≠ capacity by 1-3 | Apply delta to highest-weight non-signal to hit exact total |
| Campaign just activated, 0 leads, auto-completes (status=3) | Excluded from active list naturally; will re-enter when re-activated with leads |
| PATCH 500 on `{status: ...}` | Don't try to activate via PATCH; use POST /activate |

## Idempotence

Re-running is safe. Each run reads fresh capacity + analytics + status and re-computes from scratch. No state stored across runs.
