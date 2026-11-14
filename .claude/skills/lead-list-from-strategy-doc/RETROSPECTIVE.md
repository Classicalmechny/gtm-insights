# Retrospective — What I Learned from the Ayna Run

The Ayna lead pipeline took **6 rounds** and ~7 hours to deliver 4,671 verified emails. This document captures inefficiencies and how the v2 skill addresses them.

## What went well

- **Sample-validate-iterate loop** — 4 iterations of 20-sample validation on Stage 2 niche filter got us from 30% → 95% pass rate. Cheap; non-negotiable.
- **Storeleads + /collections.json** — public free niche signal, gave us a real TAM gradient.
- **Instantly's undocumented `technologies` filter** — confirmed via 20-lead test: 95% Shopify accuracy.
- **Storeleads `emails_from_storeleads` field** — free 2,010 brand-level emails once discovered.
- **BlitzAPI employee finder via company LinkedIn URL** — strong recall (~1.7 DMs/brand on niche-confirmed brands).
- **Clay's leadership-title export** — adds Brand/Creative/E-comm/DTC leads not in BlitzAPI.

## What went wrong

### 1. Started too strict; needed 3 iterations to loosen
- Strict filter (3+ hits AND 10%+ AND apparel-keyword check) dropped 21,500 brands.
- Recovery rounds: loosened-filter (+5,018) → non-apparel-rescue (+1,984) → 8,289 TAM
- **Fix in v2**: Start with confidence-tier classification (high/med/low), include `low` if needed.

### 2. Apollo + Storeleads emails surfaced LATE
- Apollo CSV pre-verified emails (494) ingested round 2 instead of round 1.
- Storeleads `emails_from_storeleads` field (2,010 emails!) discovered round 5.
- **Fix in v2**: 4-pass email waterfall ordered cheapest-first (Apollo → Storeleads → BlitzAPI → Instantly).

### 3. Clay returned 30-50% non-ICP garbage
- 321 non-ICP leaks (HP, Google, Equinix, LinkedIn, Chick-fil-A) made it into the pool before strict-validation.
- **Fix in v2**: Validate every Clay lead's `company_domain` against the verified TAM domain set at ingest time. Drop everything not in TAM.

### 4. Instantly multi-query was too narrow
- Used `keyword_filter: ["kidswear"]` etc. — yielded only 5-6 leads per query.
- Apollo's tagging doesn't use those exact words.
- **Fix in v2**: Don't filter by niche keyword. Filter by `subIndustry: Apparel & Fashion + technologies: Shopify + employeeCount + locations`, then split by state (CA/NY/TX/FL/etc.) to bypass per-query cap. Each state-query returns up to 2K — total 10K-20K leads, niche-tagged post-hoc via /collections.json.

### 5. Title list grew incrementally
- Started narrow (Founder/CEO/Owner), expanded twice mid-run.
- Wasted BlitzAPI credits re-querying same brands with new titles.
- **Fix in v2**: Use centralized `_titles.py` from start. Include broad senior set + exclude-list.

### 6. Apparel filter was over-aggressive
- Required ≥4 collection titles matching {top, dress, pants, ...}.
- Dropped Freshly Picked, Bedhead PJs, Robeez, Salt Water Sandals — all legit niche apparel brands.
- **Fix in v2**: Trust Storeleads' `/Apparel` tag. Only drop if hard-non-apparel terms (jewelry, furniture, food, electronics) dominate >40%.

### 7. Ocean.io discovered after key purchased
- Account access errored 403 on basic search.
- **Fix in v2**: Test Ocean.io with a tiny query in Stage 1 before committing to budget for it.

## v2 expected outcome on a similar ICP

| Metric | v1 (Ayna) | v2 (this skill) |
|---|---|---|
| Time to TAM | 3 hours (4 iterations) | 1 hour (1 iteration) |
| Email yield | 4,671 (after 6 rounds) | est 5,500-6,500 (after 2-3 rounds) |
| API spend | ~$300-450 | ~$200-300 |
| Wasted Clay credits | 30-50% of every export | <5% with strict TAM gating |

## Open questions for further optimization

- **Vision API for on-model verification**: Currently we trust Storeleads' brand metadata. For higher confidence, sample 1-2 PDP images per brand and ask a vision model "is this on-model fashion photography?" → maybe 10% of "active" brands actually flat-lay only.
- **Ocean.io with proper account access**: Lookalike from seed niche customers would expand recall.
- **AI niche reclassification**: For ambiguous brands (low confidence tier), use an LLM to read homepage + 3 collection titles and classify niche. ~$0.001/brand at gpt-oss prices.
- **Re-querying Instantly Supersearch monthly**: Apollo DB updates daily; re-running enrichment on previously-empty leads catches new emails.
