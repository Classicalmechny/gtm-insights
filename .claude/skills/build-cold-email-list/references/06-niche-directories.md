# Reference 06 — Niche Directory Scraping

## When to Use
Many B2B verticals have a dominant public directory that's a better
ground-truth source than any general database:

| Vertical | Directory | URL |
|----------|-----------|-----|
| Real estate agents | Realtor.com / Zillow Premier Agent | realtor.com/realestateagents |
| B2B agencies | Clutch.co | clutch.co |
| Shopify e-com stores | StoreLeads-style listings, builtwith.com/Shopify-stores | builtwith.com |
| Restaurants | Yelp / Google Maps (use Existing DB) | — |
| Doctors / clinics | Healthgrades, Zocdoc | healthgrades.com |
| Lawyers | Avvo, Martindale | avvo.com |
| Dentists | 1-800-DENTIST, ADA finder | — |
| Gyms / fitness | MindBody-listed studios | — |
| Hotels | TripAdvisor / Booking partners | — |
| Plumbers / contractors | HomeAdvisor / Angi | angi.com |
| E-com brands by tech | builtwith.com / wappalyzer.com | — |
| Auto dealers | Cars.com dealer directory | — |
| Universities | IPEDS public dataset | nces.ed.gov |
| Podcasts | Listen Notes API | listennotes.com |
| Newsletters | Substack discover | substack.com |

## Discovery Heuristic
If you can't find a directory in the table above for the ICP's vertical:

1. Web-search: `<vertical> directory site:` `top <vertical> in <region>`
   `<vertical> association members`.
2. Look for sites with paginated listings, structured cards per entity,
   stable URL patterns.
3. Prefer directories with filters (city, size, rating) that align with
   ICP geo/firmo dimensions.
4. **If no public directory exists, fall back to general sources.**

## Scraping Approach (Firecrawl)

Firecrawl handles JS-rendered pages, retries, and rate limits. Two modes:

### Mode A — Crawl Mode
Best when the directory has a known root + paginated structure.
```python
firecrawl.crawl_url(
    "https://www.clutch.co/agencies/digital",
    params={
        "limit": 500,
        "scrapeOptions": {
            "formats": ["markdown", "html", "links"],
            "onlyMainContent": True
        },
        "allowBackwardLinks": False,
        "maxDepth": 2
    }
)
```

### Mode B — Scrape + Custom Pagination
Best when you need explicit per-page URLs (e.g. `?page=1, 2, 3`).
```python
for page in range(1, 51):
    r = firecrawl.scrape_url(
        f"https://example.com/directory?page={page}",
        params={"formats": ["markdown", "html"]}
    )
    # parse cards from r.markdown / r.html
```

## Extraction
Two paths:

1. **Structured extractor (preferred):** Firecrawl supports a schema-
   based `extract` action. Pass a JSON schema of fields you want
   (company_name, website, city, phone, etc.) and it auto-extracts.
2. **Custom regex / BS4 parse:** when extractor fails, fall back to
   `scripts/firecrawl_scrape.py`'s parse helpers.

## Output Columns (raw/<directory>.csv)

Minimum columns:
```
source                = "<directory_slug>"  e.g. "clutch", "realtor_com"
external_id           = unique id from directory if available, else URL hash
company_name          (required)
company_domain        (extracted from listing or by Firecrawl-following the listed website link — be resilient if missing)
company_linkedin_url  (optional)
company_industry      (default to directory's vertical if not on page)
country / state / city
phone                 (some directories include this)
listing_url           (canonical link to the directory entry — useful for AI variable enrichment context)
raw_html              (optional, only when downstream parsing might need it)
```

If the directory exposes individual people (e.g. realtor.com listings
have agent names), capture them too:
```
first_name, last_name, full_name, title, linkedin_url
```

## Cost Notes
- Firecrawl charges per page scraped. 1000 pages ≈ $10–20.
- Crawl mode is usually 2–3x cheaper than per-page scrapes.

## Common Pitfalls

- **Directories with login walls** — skip unless we have credentials.
- **JS-only sites** — Firecrawl handles these, but slow. Cache pages by
  URL hash so retries don't re-charge.
- **Anti-bot 403** — back off; Firecrawl auto-rotates IPs, but some
  sites (LinkedIn-style) actively block. Use BlitzAPI instead for those.
- **Directory data is stale** — always re-verify domains via DNS/MX
  before emailing.

## Script
`scripts/firecrawl_scrape.py` — generic wrapper. The skill writes a
small per-directory adapter script when invoking, since each directory
has a unique URL pattern and field layout. Save adapters under
`scripts/directories/<slug>.py` if they'll be reused.
