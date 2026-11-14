# Lead-List-From-Strategy-Doc — Process Log (Ayna run)

> Source material for extracting a reusable skill: `build-lead-list-from-strategy-doc`.
> This document captures every decision made, why it was made, and what worked vs failed.

---

## INPUT
- **Strategy doc** (Google Doc): Campaign brief for Ayna by IntentLedSales.
- **Storeleads CSV** (provided by client, Google Drive): 746MB, 828,953 rows of Shopify apparel stores worldwide with 54 columns of firmographic + tech-stack data.

## SOURCES — Tech-stack-filter capability matrix (CORRECTED 2026-05-21)

| Source | Tech-stack filter? | Notes |
|---|---|---|
| **Storeleads CSV** | ✅ Inherent (Shopify-only dataset) | Primary source for known Shopify apparel. |
| **Instantly Supersearch** | ✅ `technologies: ["Shopify"]` (undocumented but verified working — 95% Shopify on 20-lead test) | Use this. Auth = Bearer (not Basic as in old docs). |
| **Ocean.io Lookalike** | ⚠️ No tech filter; lookalike of seed Shopify domains would lean Shopify | Account on test plan returned 403 "not allowed" — need plan upgrade. |
| **BlitzAPI Company Search** | ❌ No tech filter in v2 schema | Skip. |
| **BlitzAPI People Search** | ✅ Via `company.linkedin_url` filter against Storeleads' LinkedIn list | Used for DM finding (Stage 4). |

## OUTPUT
- `clients/ayna/output/2026-05-21_ayna_niche_fashion/raw/storeleads_verified.csv` — TAM with niche tags
- `clients/ayna/output/2026-05-21_ayna_niche_fashion/raw/decision_makers.csv` — founders/CEOs
- `clients/ayna/output/2026-05-21_ayna_niche_fashion/verified.csv` — emails verified
- `clients/ayna/output/2026-05-21_ayna_niche_fashion/enriched.csv` — + personalization
- `clients/ayna/output/2026-05-21_ayna_niche_fashion/campaigns/*.csv` — segmented per-campaign

---

## THE WORKFLOW (8 STAGES)

```
[0] PARSE STRATEGY DOC  → icp.json
[1] PRE-FILTER source CSV → storeleads.csv + storeleads_unmatched.csv
[2] VERIFY niche via /collections.json + fallbacks  → storeleads_verified.csv
    ↳ ITERATE: 20-sample → validate → tweak filters → re-sample → repeat
[3] (Skipped — non-Shopify augmentation not in scope)
[4] FIND DECISION MAKERS via BlitzAPI employee finder  → decision_makers.csv
[5] EMAIL ENRICHMENT WATERFALL  → verified.csv
[6] SEGMENT into campaign lists  → campaigns/*.csv
[7] AI PERSONALIZATION VARIABLES (sample-approval gated)  → enriched.csv
[8] EXPORT per-campaign CSVs ready for Instantly/Smartlead
```

---

## STAGE 0 — Parse Strategy Doc → icp.json

Read the strategy doc and extract every ICP attribute mentioned. The brief usually has:

| Attribute | Where in brief |
|---|---|
| Geography | "Geography" lever, persona section |
| Revenue band | "Revenue band" lever |
| Headcount proxy | "Headcount" lever |
| Categories (niches) | "Category" lever + targeting-signals section |
| Storefront platform | Targeting-signals ("Shopify or Shopify Plus") |
| Decision-maker titles | "Persona" section |
| Compulsory filters | "Targeting Signals (Compulsory Filters)" section |
| Personalization variables | "Personalization Variables & Data Sources" table |
| Campaigns | "Campaign Portfolio" table |

**Write everything to `icp.json`** before any sourcing. This is the source of truth for downstream filtering.

**Critical:** Map "8 specific categories" to a regex taxonomy. For Ayna we had:
kidswear, innerwear/lingerie, plus-size, inclusive sizing, maternity, modest/religious, adaptive, athleisure.

---

## STAGE 1 — Pre-Filter the Source CSV (Storeleads)

Storeleads is a partial source of truth — confirms US + apparel + revenue band + Shopify
status, but its `collections` column is sparse so niche detection on Storeleads fields
alone is noisy.

### Filters applied at this stage
1. `status == "Active"`
2. `company_location` contains ", USA"  (US-only)
3. `estimated_monthly_sales` parses to $50K – $1.5M monthly (= $0.6M – $18M annual)
4. **NO niche keyword filter here** — too noisy, do it in Stage 2

### Output
- `raw/storeleads.csv` — brands that pass TAM gate (Stage 1.5: also had a niche-keyword match for the seed list)
- `raw/storeleads_unmatched.csv` — in-band but no keyword hit on Storeleads fields. These go to Stage 2 for storefront verification.

In the Ayna run:
- 828,953 rows total
- 315,030 US + Active
- **22,850 in revenue band** ← this is the Stage 2 input

### Counter-intuitive lesson
**Do NOT trust Storeleads' `categories` or `collections` field for niche tagging.**
- `categories` is usually just `/Apparel` (too coarse)
- `collections` is null on most rows
- Storeleads' `merchant_name` and `most_recent_product_title` ARE useful but noisy on their own

The result: keyword-tagging against Storeleads alone gave a **30% pass rate** on manual validation — too many multi-brand retailers, non-apparel stores, and weak keyword hits ("loungewear" → tagged innerwear) slipped through.

---

## STAGE 2 — Verify niche via Shopify `/collections.json`

This is the core insight of the whole workflow.

### Why `/collections.json`
Every Shopify store exposes `https://DOMAIN/collections.json?limit=250` as a public,
unauthenticated JSON endpoint returning the store's full collection list with titles
and handles. This is the **richest signal available** for what the store actually sells
— far richer than Storeleads' `collections` field which is mostly null.

### Fetcher requirements
- UA rotation (5+ realistic browser UAs)
- Retry on 503/429/520-524 with exponential backoff (3 attempts)
- Try `domain` AND `www.domain` (Shopify configs vary)
- Concurrency 15 — beyond that triggers Shopify/Cloudflare bot-block
- Expect ~95% success rate on healthy stores; ~5% need fallbacks

### Fallback chain (when /collections.json blocked)
1. **BlitzAPI company enrichment** (`POST /v2/enrichment/company` with `company_linkedin_url`)
   - Returns description, industry, specialties → classify from text
2. **Instantly Supersearch company enrichment** (final fallback)
3. If all 3 fail → drop the brand (better than a guessed niche)

### Classification: intensity-based, NOT keyword-presence
This is the second key insight. **A niche keyword appearing once is meaningless.**
A general fashion brand has a "Boys" sub-section; a kidswear brand has 50 collections
specific to kids ages, fits, and themes.

#### Rules that work
```python
threshold = max(3, round(0.10 * n_collections))   # ≥3 hits AND ≥10%
n_adult_general = count of "men's / women's" collections
niche assigned only if:
    niche_hit_count >= threshold
    AND (niche_hit_count >= n_adult_general OR niche_keyword in brand_name/domain)
```

Plus:
- Bonus: if niche keyword is in `merchant_name` or `domain` AND ≥2 collection hits → assign.
- BlitzAPI fallback STRICTLY: assign niche only if ≥2 description hits OR domain/name match.

#### Apparel-focus check (kill jewelry/furniture/merch stores)
- Compute `n_apparel` = # collections matching apparel keywords (tops, pants, dresses, …)
- Compute `n_non_apparel` = # collections matching non-apparel keywords (jewelry, furniture, goggles, …)
- Require `n_apparel >= 4 AND n_apparel > n_non_apparel`

#### Multi-brand retailer detection (flag, do NOT drop per ICP)
- Maintain a list of external brand names (Disney, Nike, Carter's, Panache, Fantasie, etc.)
- Count collection titles matching external brands
- If ≥3 → flag `is_multi_brand_retailer = yes`
- This is a **tag**, not a filter — Ayna keeps multi-brand retailers in the TAM.

### Result on Ayna run
- Verified 41% of in-band brands (~9,400 of 22,850)
- 95% pass rate on 20-sample validation (vs 30% with keyword-only)

---

## STAGE 2 — Sample-Validate-Iterate Loop (the most important habit)

**ALWAYS run a 20-sample validation before scaling.**

### Loop
1. Run Stage 2 filter on first 500 brands.
2. Pull 20 samples **stratified across niches** (at least 1 per niche, then proportional fill).
3. For each sample, fetch the brand's homepage and check:
   - Is it really a single DTC fashion brand (or multi-brand retailer)?
   - Is the auto-detected niche correct?
   - Does it have on-model imagery on PDPs?
4. Compute pass rate. If <90%, identify failure patterns:
   - Mis-categorization → adjust regex / add competitive check
   - Non-apparel slipping through → expand non-apparel-terms list
   - Multi-brand retailer mis-classified → re-tune (or accept per ICP)
5. Re-run on 500 and re-validate with 20 new samples.
6. Repeat until pass rate ≥90%.
7. Only then scale to full TAM.

### Why this is non-negotiable
On the Ayna run, we iterated 4 times:
- **v1** (Storeleads keyword only): 30% pass — multi-brand retailers, jewelry stores, accessories all slipped through.
- **v2** (+ /collections.json + apparel filter): 78% pass — but kids/boys sub-sections in general brands caused over-tagging.
- **v3** (+ intensity threshold): 47% pass (tighter), 65% pass-rate.
- **v4** (+ competitive check vs men's/women's collections + strict fallback): **95% pass** ✅

Each iteration cost <5 minutes of compute but lifted quality dramatically.
Skipping this loop is the #1 cause of bad cold-email lists.

---

## STAGE 4 — Find Decision Makers (Founders/CEOs)

Use BlitzAPI employee finder per domain.

**ICP-driven configuration**:
- `title_keywords`: from `icp.persona.titles` (e.g. Founder, CEO, Co-Founder, Owner)
- `limit`: from `icp.persona.dm_cap_per_company` (null = no cap, per Ayna ICP)
- `company_linkedin_url`: pass when available (Storeleads has it for most)

**Runtime**: ~0.5-2s per company. With concurrency 10 on 9K companies: ~25 min.

---

## STAGE 5 — Email Enrichment Waterfall

Standard waterfall from the `build-cold-email-list` skill:
1. **Pass 1** — Instantly Supersearch enrichment (bulk add → enrich-from-list → poll)
2. **Pass 2** — BlitzAPI find-work-email for Pass-1 misses
3. **Pass 3** — Instantly re-verify Pass-2 candidates
4. **Concat & dedupe** by email (Pass-1 wins). Drop anything not `valid` or `accept_all`.

---

## STAGE 6 — Segment into Campaign Lists

For Ayna, 4 campaigns:
| Campaign | Slice (SQL-style filter) |
|---|---|
| 1 Free Sample | ALL niche-tagged brands |
| 2 Cost-Per-SKU Math | ALL niche-tagged brands (fallback rotation) |
| 3 Representation Promise | `primary_niche IN (plus_size, inclusive, maternity, adaptive, modest, kidswear, innerwear)` |
| 4 Drop Velocity | `products_created_30 >= 10 OR products_created_90 >= 30` |

A brand can appear in multiple campaigns (Campaign 1 + 3 + 4 for example) — Smartlead/Instantly handles per-list rotation.

---

## STAGE 7 — AI Personalization Variables (sample-approval gated)

Variables per the strategy doc's variables table:
- `{{first_name}}`, `{{company_name}}` — direct from sourcing
- `{{category}}` — auto-detected niche label, formatted human-readable
  (e.g. `kidswear` → `kidswear`, `innerwear` → `lingerie`, `plus_size` → `plus size`, etc.)
- `{{storefront_url}}` — direct from Storeleads
- `{{drop_cadence}}` — computed for Campaign 4 only

### Sample-first approval
1. Generate variables on 5-10 sample leads.
2. Show the user the sample output.
3. Get explicit approval.
4. Only then scale to the full list.

**Never run AI enrichment on the full list before sample approval.** A bad prompt costs $$$.

---

## KEY LEARNINGS (the WHY behind decisions)

### 1. The source CSV is a pre-filter, NOT a source of truth
Storeleads gave us the universe (US Shopify apparel in revenue band), but its
per-row tagging is sparse and noisy. The storefront itself (via `/collections.json`)
is the ground truth.

### 2. Intensity > Presence
A keyword appearing 1-2 times is noise. A keyword appearing 20% of all collections is signal.

### 3. Competitive check kills false positives
A general apparel brand with "Boys" and "Girls" sub-sections will hit kidswear keywords. But
those 2 hits are dwarfed by 50 men's/women's collections. Comparing niche-count to
adult-general-count distinguishes "kid-focused brand" from "general brand with kid section."

### 4. Fallback chains must be STRICTER than primary source
When `/collections.json` is blocked, the fallback uses brand description. Description-based
classification is much more permissive (free-text matching), so it must require **higher
confidence** (multiple keyword hits OR domain match) to avoid noise from words like "boy" in
brand names ("Local Boy Outfitters" → not kidswear).

### 5. Validate 20 samples before scaling, EVERY iteration
The cost of validating 20 (= ~10 min of agent time) is trivial compared to the cost of
running 22K enrichments on bad filters and getting a low-quality list.

### 6. User decisions matter (negotiate them upfront)
For Ayna:
- Multi-brand retailers? **Keep** (per user) — they're still Ayna customers
- Flat-lay-only? **Keep** (per user) — Ayna handles flat-lay too
- DM cap? **None** (per user) — all founders/co-founders/owners
- Non-Shopify augmentation? **Skip** (ICP says Shopify-only)

These get baked into icp.json and prevent re-litigation mid-run.

---

## ARTIFACTS DIRECTORY (Ayna run)

```
clients/ayna/
├── storeleads_apparel.csv                       # source (746MB, gitignored)
├── scripts/
│   ├── 01_storeleads_filter.py                  # Stage 1
│   ├── 02_sample_pull.py                        # 20-sample stratified picker
│   └── 03_collections_enrich.py                 # Stage 2 + fallback chain
└── output/2026-05-21_ayna_niche_fashion/
    ├── icp.json                                 # Stage 0
    ├── raw/
    │   ├── storeleads.csv                       # Stage 1 keyword-matched seed
    │   ├── storeleads_unmatched.csv             # Stage 1 recall recovery set
    │   ├── storeleads_verified.csv              # Stage 2 final tagged TAM
    │   ├── storeleads_dropped.csv               # Stage 2 drops (debugging)
    │   └── decision_makers.csv                  # Stage 4
    ├── checkpoints/
    │   └── collections_probe.json
    ├── sample_20_pretty.md                      # validation rounds
    ├── sample_20_v2.json, sample_20_v3.json, sample_20_v4.json
    ├── verified.csv                             # Stage 5
    ├── enriched.csv                             # Stage 7
    └── campaigns/                               # Stage 6
        ├── 1_free_sample.csv
        ├── 2_cost_per_sku.csv
        ├── 3_representation.csv
        └── 4_drop_velocity.csv
```

---

## NEXT STEP: turn this into a reusable skill

When converting to a skill, parameterize:
1. **The strategy doc parser** — extract ICP slots from any campaign brief
2. **The source CSV adapter** — schema-map any vendor CSV (Storeleads, StorePilot, Apollo Companies, etc.) to a canonical pre-filtered format
3. **Niche taxonomy** — load from ICP, not hardcoded
4. **Storefront verifier** — generic Shopify verifier; need adapters for WooCommerce / BigCommerce / headless
5. **Campaign segmentation rules** — load from ICP's "campaigns" section

Skill name suggestion: `lead-list-from-strategy-doc` (subsumes `build-cold-email-list`).
