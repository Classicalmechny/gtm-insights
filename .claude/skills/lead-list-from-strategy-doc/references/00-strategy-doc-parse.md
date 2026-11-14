# Reference 00 — Strategy Doc Parse + ICP Extraction

## Read the doc

| URL type | Tool |
|----------|------|
| Google Doc (docs.google.com/document/...) | `mcp__claude_ai_Google_Drive__read_file_content` with fileId from URL |
| Google Drive PDF | `mcp__claude_ai_Google_Drive__download_file_content` + Read with `pages` |
| Notion / Coda / web URL | `WebFetch` |
| Pasted text | parse directly |

For Google Doc URLs of form `https://docs.google.com/document/d/<FILE_ID>/edit?...`, extract `<FILE_ID>`.

## Extract fields → icp.json

Map brief sections to slots:

| Brief section | icp.json slot |
|---|---|
| Geography lever | `geographics.countries` |
| Revenue band | `firmographics.revenue_band_annual_usd.{min,max}` |
| Headcount | `firmographics.employee_count_{min,max}` |
| Storefront platform | `firmographics.tech_stack_includes` |
| Categories / niches | `company.categories_niche` |
| Industry tags | `firmographics.industries` |
| Persona titles | `persona.titles` |
| Title exclusions | `persona.title_exclusions` |
| DM cap | `persona.dm_cap_per_company` |
| Compulsory filters | `compulsory_filters` |
| Personalization vars | `personalization_variables` |
| Campaign portfolio | `campaigns` (list of {id, name, audience}) |

## Reverse-prompt ambiguous fields

Single consolidated prompt, multi-choice where possible. Common ambiguities in fashion/DTC briefs:

1. **Storefront platform** — "Shopify only" / "Shopify + BigCommerce + WooCommerce" / "Any DTC"
2. **Revenue band tightness** — "Strict" / "±20% (looser)" / "Top-of-band only"
3. **Multi-brand retailers** — "Drop" / "Keep with flag" / "Keep equally"
4. **Flat-lay-only brands** — "Drop" / "Keep" (often kept — most photoshoot tools handle both)
5. **DM cap per company** — 1 / 2 / 3 / unlimited
6. **Sample size for validation loop** — 10 / 20 / 30

Write final ICP to `output/<run_id>/icp.json`. Show user a one-screen confirmation table and wait for "approved" before continuing.

## run_id format
`YYYY-MM-DD_<client_slug>_<campaign_slug>` (e.g. `2026-05-21_ayna_niche_fashion`).
