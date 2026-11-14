# Reference 05 — Ocean.io (v3 search + lookalike UNLOCKED 2026-05-25)

## Status (verified 2026-05-25 on new token)

| Endpoint | Access | Use case |
|---|---|---|
| `POST /v3/search/companies` | ✅ **WORKS** | Full company search + lookalike (use this, not preview) |
| `POST /v3/search/companies/preview` | ❌ 403 | Preview is still gated; use `/v3/search/companies` directly |
| `POST /v2/lookup/companies` | ✅ YES | Brand metadata enrichment by domain |
| `POST /v2/lookup/people` | ✅ YES (often empty) | Person enrichment by LinkedIn handle |
| `POST /v3/search/people` | ✅ Likely (PeopleFiltersV3 schema confirmed) | People search w/ lookalike + firmographics |

**Token:** `api_juM4dZ_M6UoYZ7cbA03v28Ji9ReYyHZMzqmA3v5` (env var `OCEAN_KEY`, also on VPS at `~/brain/.env`).

**Cost:** 1 credit per company returned.

## Auth

`apiToken` query parameter (NOT a header):
```
POST https://api.ocean.io/v2/lookup/companies?apiToken=<OCEAN_KEY>
```

## What you get from a company lookup

```json
{
  "domain": "curvycouture.com",
  "name": "Curvy Couture Intimates",
  "companySize": "2-10",
  "revenue": "0-1M",
  "yearFounded": 2012,
  "countries": ["gb", "us"],
  "primaryCountry": "us",
  "ecommerce": null,
  "industries": ["E-Commerce", "Retail", "Lingerie", "Fashion", "Consumer Goods"],
  "industryCategories": ["Commerce and Shopping", "Clothing and Apparel", "Consumer Goods", "Design"],
  "technologies": ["Google Tag Manager", "Snowplow Analytics", "VWO", "AdRoll", "Shopify"]
}
```

## Where to use it in the pipeline

### Use case 1 — Niche reclassification (HIGH VALUE)

Ocean.io's `industries` array contains rich semantic tags like "Lingerie",
"Maternity", "Childrenswear", "Plus Size", "Sustainable Fashion". Compare:

| Brand | My regex tag | Ocean.io industries |
|---|---|---|
| curvycouture.com | `innerwear` (via "couture" + "intimates") | `["Lingerie","Retail","Fashion"]` ← cleaner |
| eastessence.com | `modest` | `["Fashion","Retail","Lifestyle"]` ← misses "modest" but confirms apparel |
| magnaready.com | `adaptive` | `["Retail","Fashion","Manufacturing"]` ← misses "adaptive" |

**Strategy**: Use Ocean.io as a SECONDARY signal:
- If Ocean.io industries include a niche keyword we missed → boost confidence tier
- If Ocean.io industries indicate NON-niche (e.g. "Cosmetics", "Food") → demote
- If Ocean.io confirms our regex → keep current niche

### Use case 2 — /collections.json fallback

When `/collections.json` blocks (the 3,635 brands with no_data in the Ayna run),
use Ocean.io's industries + technologies arrays for niche detection.

Map: `"Lingerie"` → niche=innerwear, `"Childrenswear"` → kidswear,
`"Maternity"` → maternity, `"Modest Fashion"` → modest, etc.

### Use case 3 — Brand metadata enrichment

For brands missing revenue/headcount data in Storeleads, Ocean.io can fill in:
- `companySize` (e.g. "11-50")
- `revenue` (e.g. "1-10M")
- `yearFounded`
- `technologies` (tech stack)

## Batching

Lookup endpoint accepts an array of domains. Test batch size — likely 100-500
per call. Add backoff on 429.

```python
POST /v2/lookup/companies
Body: { "domains": ["popilush.com", "curvycouture.com", ...] }
```

## Cost

Ocean.io charges per credit per company looked up. Confirm pricing on the
account before running on 8,000+ domains. Typically 1 credit per company.

## Script

`scripts/29_ocean_enrich.py` — takes a list of domains, calls v2/lookup/companies
in batches, maps Ocean.io industries to niche tags, writes enriched output.

## v3 Search — full schema (CompaniesFiltersV3)

All filters confirmed working on the new token:

| Filter | Shape | Example |
|---|---|---|
| `lookalikeDomains` | array | `["cursor.com","lovable.dev","bolt.new"]` → 44K lookalikes |
| `includeDomains` / `excludeDomains` | array | — |
| `industries` | `{"industries":[...], "mode":"anyOf|allOf"}` | `{"industries":["Beauty"],"mode":"anyOf"}` |
| `industryCategories` | `IndustryCategoriesFilter` | — |
| `primaryLocations` | `{"includeCountries":[...], "includeRegions":[...]}` | ISO-3166 alpha-2: `["us","gb","ca","au"]` |
| `otherLocations` | same | any country presence |
| `companySizes` | array | `["2-10","11-50"]` |
| `revenues` | array | `["1-10M","10-50M"]` |
| `employeeCountLinkedin` | `{"from":N,"to":M}` | `{"from":1,"to":25}` |
| `employeeCountOcean` | `{"from":N,"to":M}` | — |
| `yearFounded` | `{"from":YYYY,"to":YYYY}` | — |
| `technologies` | `{"apps":{"anyOf":[...]}, "categories":{"anyOf":[...]}}` | Use Ocean's exact app names (fetch via `/v2/data-fields`) |
| `keywords` | `{"anyOf":[...],"allOf":[...],"noneOf":[...]}` | — |
| `minRelevance` | `"A" | "B" | "C"` | lookalike relevance threshold |
| `socialMedias`, `webTraffic`, `fundingRound`, `headcountGrowth` | — | advanced |

### People (PeopleFiltersV3)

- `lookalikeLinkedinHandles: [...]`
- `includeLinkedinHandles` / `excludeLinkedinHandles`
- `countries: ["us"]` (note: array of country codes, NOT a LocationsFilter object like for companies)
- `seniorities: [...]`
- `jobTitleKeywords: {...}`
- `currentJobDescription` / `allJobDescriptions`
- `regions`, `states`, `cities` (+ excludes)
- `departments`
- `connections: {"from":N,"to":M}`
- `followers: {"from":N,"to":M}`

### Pagination

Response contains `searchAfter` (opaque cursor). Pass back as `searchAfter` in next request. Each response also returns `total`.

## Example: Campaign A vibe-coding lookalike

```python
POST https://api.ocean.io/v3/search/companies?apiToken=<OCEAN_KEY>
{
  "size": 100,
  "companiesFilters": {
    "lookalikeDomains": ["cursor.com","lovable.dev","bolt.new","windsurf.com","v0.dev","anthropic.com"],
    "primaryLocations": {"includeCountries": ["us","gb","ca","au"]},
    "employeeCountLinkedin": {"from": 1, "to": 25},
    "minRelevance": "A"
  }
}
```
Expected: ~5K-10K high-fit vibe-coding-adjacent companies after geo+headcount filter. Each pulled costs 1 credit.

## History
- **2026-05-21:** old token (`api_b75MFh_...`) only allowed v2 lookup; v3 search/lookalike returned 403.
- **2026-05-25:** new token (`api_juM4dZ_M6UoYZ...`) unlocked v3 search. Confirmed: industry+revenue filter returned 4,252; lookalike with `[cursor.com, lovable.dev, bolt.new]` returned 44,074 matches.
