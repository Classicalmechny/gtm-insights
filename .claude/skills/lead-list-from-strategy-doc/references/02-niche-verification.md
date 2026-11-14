# Reference 02 — Niche Verification via /collections.json

## Why this matters

Every Shopify store exposes `https://DOMAIN/collections.json?limit=250` as a
public, unauthenticated JSON endpoint returning the store's full collection
list with titles + handles. This is the **richest niche signal available**.

## Fetcher requirements
- UA rotation (5+ realistic browser UAs)
- Retry on 429/503/520-524 with exponential backoff (3 attempts)
- Try `domain` AND `www.domain` (Shopify configs vary)
- Concurrency 15 — beyond that triggers Cloudflare bot-block
- Expect ~95% success rate; ~5% need fallbacks

## Fallback chain (when /collections.json blocked)
1. **BlitzAPI company enrichment** (`POST /v2/enrichment/company` with `company_linkedin_url`)
2. **Instantly Supersearch company enrichment** (final fallback)
3. If all 3 fail → drop the brand (better than a guessed niche)

## Classification rules (intensity-based, NOT keyword-presence)

```python
threshold = max(3, round(0.10 * n_collections))   # ≥3 hits AND ≥10%
n_adult_general = count of "men's / women's" collections

niche_assigned if:
    niche_hit_count >= threshold
    AND (niche_hit_count >= n_adult_general OR niche_keyword in brand_name/domain)
```

Plus bonus rule: if niche keyword appears in `merchant_name` or `domain` AND
≥2 collection hits, assign even if below intensity threshold.

## Apparel-focus filter (DON'T over-tighten)

**Wrong (drops 1,984 real apparel brands):** Require `n_apparel >= 4 AND n_apparel > n_non_apparel`.

**Right:** Trust Storeleads' `categories` field (=`/Apparel` for all brands in the dataset). Only drop if **hard-non-apparel-keyword count > 40% AND >= 5 collections** (jewelry, furniture, food, electronics, supplements, etc.).

Real apparel brands often use collection names like:
- "Spring '26", "Capsule", "The Edit"
- "$10 and Under", "Bestsellers", "New Arrivals"
- "Cocoon Swaddles" (legit kidswear, no apparel keyword)
- These will NOT match a generic {top, dress, pants, ...} apparel filter.

## Multi-brand retailer detection (flag, do NOT drop)

Maintain a starter list of external apparel brand names (Disney, Carter's,
Panache, Fantasie, Nike, Levi's, etc.). Count collection titles matching them.
If ≥3 hits → flag `is_multi_brand_retailer = yes`. Don't filter — segmentation handles it.

## Confidence tier (preferred over binary drop)

| Tier | Criteria |
|---|---|
| high | ≥10 niche hits AND niche keyword in brand name/domain |
| medium | ≥3 niche hits AND ≥10% of collections |
| low | ≥1 niche hit OR brand name/domain match |

Initial filter: **medium+**. Recovery rounds: include **low** if needed.

## Sample-validate-iterate loop

1. Run filter on first 500 brands.
2. Pull 20 samples **stratified across niches** (1 per niche minimum, then proportional).
3. For each sample, WebFetch homepage. Check:
   - Single DTC fashion brand or multi-brand retailer?
   - Auto-detected niche correct?
   - On-model imagery on PDPs?
4. Compute pass rate. <90% → identify failure pattern, adjust regex/threshold/competitive-check, re-run 500, re-validate with 20 fresh samples.
5. Scale to full TAM only after ≥90% pass.

## Lessons (don't repeat)

- "Boys" / "Girls" / "Kids" appears as size-divisions in adult brands → too noisy without intensity + competitive check.
- A single "Loungewear" sub-collection at a general fashion brand causes innerwear false-tag.
- BlitzAPI fallback classification on description text is much more permissive than collection-title — REQUIRE multiple keyword hits OR domain/name match before assigning.
- For "kid" appearing in domains like "KidSuper" (streetwear), use word-boundary regex.

## Script
`scripts/03_collections_enrich.py` — adapted from Ayna run. Reads ICP for niche taxonomy, applies intensity rules, fallback chain, multi-tier confidence.
