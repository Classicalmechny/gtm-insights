# Reference 02 — Source Routing Decision Tree

## Goal
Pick the cheapest combination of sources that maximally covers the ICP. Do
NOT use all sources by default — each costs money or time.

## Source Capabilities Matrix

| Source | Returns | Has Email? | Cost | Speed | Best For |
|--------|---------|------------|------|-------|----------|
| **Existing GitHub DB** | Companies (sometimes people) | ❌ | Free | Instant | SaaS / startups (Crunchbase) OR US local biz (Google Maps) |
| **Instantly Supersearch** | People + verified emails | ✅ | $$ (cheap per lead) | Slow (5–30 min poll) | Default for most B2B — single-pass leads+emails |
| **BlitzAPI people search** | People (LinkedIn) | ❌ (separate enrich) | $ per credit | Fast | Niche titles, LinkedIn-findable personas |
| **BlitzAPI company search** | Companies (LinkedIn) | n/a | $ per credit | Fast | When you need to filter companies first then find DMs |
| **Ocean.io** | Lookalike companies | n/a | $$ per credit | Medium | User has ≥3 seed customer domains |
| **Niche directories** | Companies (sometimes people) | Sometimes | $ (Firecrawl credits) | Slow (per-page scrape) | Vertical-specific: realtors, agencies, doctors, e-comm |
| **BlitzAPI employee finder** | Decision makers at given companies | ❌ | $ per credit | Medium | Always pairs with any company-only source |

## Routing Rules (apply in order)

### Rule 1 — Default Backbone
For 95% of B2B ICPs, start with:
- **Instantly Supersearch** — handles people sourcing + email enrichment + verification in one pipeline. Highest signal-to-cost ratio.

### Rule 2 — Add Coverage Layer
Add ONE secondary source for coverage:

| If ICP has... | Add this source |
|---------------|-----------------|
| Seed customer domains | Ocean.io (lookalikes) |
| Highly specific LinkedIn title | BlitzAPI people search |
| Industry with public directory | Niche directory scrape |
| Crunchbase-listable business (SaaS / startup) | Existing DB (Crunchbase subset) |
| US local services | Existing DB (Google Maps subset) |
| Companies first, then DMs | BlitzAPI company search → employee finder |

### Rule 3 — Skip Instantly If
- ICP is hyper-niche (<500 worldwide) — Instantly's database is broad but
  shallow. Better to scrape a directory + use BlitzAPI for DMs.
- Persona doesn't exist on standard B2B databases (e.g. solo
  practitioners, indie hackers, very local services) — go directory + DM
  enrichment instead.

### Rule 4 — Always Run In Parallel
Once the plan is set, launch ALL chosen sources concurrently. Don't
serialize — Instantly polling alone takes 5–30 min, no reason to wait.

## Examples

### Example A: "Founders of US B2B SaaS, 2–50 employees, seed/Series A"
Plan:
- Instantly Supersearch (default) — titles: Founder, CEO, Co-Founder
- Existing GitHub DB (Crunchbase) — funded SaaS, US, 2–50 emp
- Merge & dedupe.
Skip: Ocean (no seeds), BlitzAPI people (Instantly covers), Niche
directories (no obvious one).

### Example B: "Heads of Marketing at e-commerce stores doing $1M–$10M GMV, US"
Plan:
- Niche directory: Shopify store directories + StoreLeads-style scrape
  (Firecrawl)
- BlitzAPI employee finder against scraped store domains
- Instantly Supersearch parallel pass (for any well-known e-comm brands)
- Merge & dedupe.

### Example C: "Real estate agents in Texas with active listings"
Plan:
- Niche directory: realtor.com / Zillow agent scrape (Firecrawl)
- BlitzAPI find-work-email for each scraped agent
- Skip Instantly (poor coverage of individual agents).

### Example D: "B2B agency owners in EU, agencies under 20 people"
Plan:
- Niche directory: Clutch (Firecrawl) — filter EU, size
- BlitzAPI employee finder for owner/founder at each agency
- Instantly Supersearch parallel pass for agency-type LinkedIn titles
- Merge & dedupe.

### Example E: "Existing customer is acme.com, ride.io, juno.app — find lookalikes"
Plan:
- Ocean.io lookalikes from these 3 seeds
- BlitzAPI employee finder against returned companies (persona = ICP titles)
- Instantly Supersearch parallel for the same persona+industry
- Merge & dedupe.

## Output: source_plan.json

```json
{
  "sources": [
    {
      "name": "instantly_supersearch",
      "config": { "... per-source config ..." },
      "expected_yield": 1500,
      "expected_cost_estimate_usd": 30
    },
    {
      "name": "ocean_lookalike",
      "config": { "seeds": ["acme.com", "ride.io", "juno.app"], "limit": 500 },
      "expected_yield": 500,
      "expected_cost_estimate_usd": 50
    }
  ],
  "needs_dm_finding": ["ocean_lookalike"],
  "estimated_total_cost_usd": 80,
  "estimated_wall_time_min": 25
}
```

Always show the plan to the user before executing. If estimated cost is
above $100, get explicit approval first.
