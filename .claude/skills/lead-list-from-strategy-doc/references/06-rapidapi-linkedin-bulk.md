# Reference 06 — RapidAPI Realtime LinkedIn Bulk Data (added 2026-05-25)

## What it is

RapidAPI Hub product `realtime-linkedin-bulk-data.p.rapidapi.com` (publisher `letscrape-6bRBa3QguO5`). Pay-as-you-go REST API for LinkedIn data — profiles, posts, post engagements (reactions + comments + reposts), companies, employees, search. No LinkedIn account / cookies needed.

## Why it earns a slot in the pipeline

The vibe-coding Campaign A pipeline (Trigify → Blitz → Instantly) hit two recurring blockers that this API solves:

1. **Trigify returns obfuscated `ACoAA…` LinkedIn URNs** for post likers / commenters. BlitzAPI cannot resolve these. We previously had to call Trigify's `enrich_profile` per URN, which is rate-limited and slow. This API resolves URN → clean `linkedin.com/in/<vanity>` in bulk.
2. **No company-employee endpoint outside Blitz/Apollo.** When Apollo lacks coverage on a long-tail brand (common for niche DTC), Blitz's employee finder is the only option and it's expensive. This API offers a cheaper second source.

## Auth

| Header | Value |
|---|---|
| `x-rapidapi-host` | `realtime-linkedin-bulk-data.p.rapidapi.com` |
| `x-rapidapi-key` | `$RAPIDAPI_KEY` (env var; not committed) |

Local key lives in user's MCP config (`~/.claude.json` under `rapidapi-linkedin-bulk-scraper`). VPS key lives in `~/brain/.env` as `RAPIDAPI_KEY`.

## How to call it

### Option A — MCP (preferred, verified 2026-05-25)

The `mcp-remote` bridge to `https://mcp.rapidapi.com` exposes every endpoint as a typed MCP tool. After install (one-time, already done), 37 tools surface as `mcp__rapidapi-linkedin-bulk__*` (VPS) or `mcp__rapidapi-linkedin-bulk-scraper__*` (local).

**Verified tool inventory (37 tools):**

| Category | Tools |
|---|---|
| Person | `Person_Data` (by URL), `Person_Data_using_URN` (by `ACoAA…` URN — resolves Trigify obfuscation), `Person_Skills`, `Person_Updates`, `Person_Comments_from_recent_Activity`, `Person_data_with_open_to_work_falg` *(sic)*, `Profiles`, `Similar_Profiles` |
| Company | `Company_Data`, `Company_Employee`, `Company_Employee_Count`, `Company_Posts_BETA`, `Company_Updates`, `Company_jobs`, `Companies` |
| Post | `Post`, `Post_reactions__Reactions_on_a_postupdate_`, `Post_comments_Comments_on_a_postupdate`, `Post_Reposts__Reposts_of_a_postupdate_` |
| Search | `Search_people_With_Filters`, `Search_posts`, `Search_Posts_With_Filters`, `search_company_with_filters`, `Search_jobs` |
| School / job | `School_Alumini_Count` *(sic)*, `Job_Details` |
| Suggestion (autocomplete) | `Suggestion_Company`, `Suggestion_Company_Size`, `Suggestion_Function`, `Suggestion_Geourns`, `Suggestion_Industry`, `Suggestion_Language`, `Suggestion_Location`, `Suggestion_School`, `Suggestion_Service_Category`, `Suggestion_person` |
| Utility | `Calculate` |

**Verified call (2026-05-25):** `Person_Data` with `{"link": "https://www.linkedin.com/in/williamhgates"}` returned `{"success":true,"status":200,"data":{"urn":"…","firstName":"Bill","lastName":"Gates","headline":"Chair, Gates Foundation…","industry":"Philanthropy",…}}`.

**Key params:** `link` (full LinkedIn URL) is the standard for `Person_Data` / `Company_Data` / post tools. `Person_Data_using_URN` takes a URN like `ACoAAA8BYqEBCGLg_vT_ca6mMEqkpp9nVffJ3hc` — use this to resolve Trigify obfuscated identifiers without first scraping the page.

**Local install (already wired):**
```
claude mcp add -s user "rapidapi-linkedin-bulk-scraper" -- npx -y mcp-remote https://mcp.rapidapi.com \
  --header "x-api-host: realtime-linkedin-bulk-data.p.rapidapi.com" \
  --header "x-api-key: $RAPIDAPI_KEY"
```

**VPS (brain runtime, already wired):** Registered in `/home/ubuntu/brain/.claude/mcp-servers.json` as `rapidapi-linkedin-bulk`.

### Option B — Direct HTTPS (scripts, n8n, batch loops)

```bash
curl "https://realtime-linkedin-bulk-data.p.rapidapi.com/<endpoint>?<params>" \
  -H "x-rapidapi-host: realtime-linkedin-bulk-data.p.rapidapi.com" \
  -H "x-rapidapi-key: $RAPIDAPI_KEY"
```

⚠️ **Direct HTTPS paths are NOT 1:1 with the MCP tool names.** Probing `/Person_Data`, `/person_data`, `/profile`, `/profiles` etc. all returned `{"message":"Endpoint '/X' does not exist"}`. The MCP bridge translates tool names to actual API paths via the RapidAPI catalog under the hood. To use direct HTTPS, copy the exact path + param shape from the RapidAPI playground for each endpoint you need:
https://rapidapi.com/letscrape-6bRBa3QguO5/api/realtime-linkedin-bulk-data

**For most pipeline use cases, prefer the MCP path** — it works out of the box and is what brain VPS already has wired.

## Use cases in this skill

### Use case 1 — Resolve obfuscated URNs (Trigify follow-up)

Trigify's `get_post_engagements_linkedin` and `discover_creators` return URNs like `ACoAACgVTAYBmAEcvD...`. Pipe each URN into RapidAPI's profile-resolve endpoint → get clean `linkedin.com/in/<vanity>` + name + headline + current company. Then BlitzAPI can find the work email.

### Use case 2 — Engagement scraping (post URL → likers + commenters)

Given a competitor or influencer post URL, pull the full reactor + commenter list. Combined with Trigify's `create_linkedin_posts_search` (which surfaces relevant posts), this becomes an end-to-end "keyword-targeted intent signal → engagement scrape → ICP filter → email" loop.

### Use case 3 — Company employee finder (Apollo fallback)

Given a company LinkedIn URL (from Ocean.io discovery, manual research, or a Storeleads `linkedin_url` field), pull the employee list and filter by title/seniority. Use when Apollo lacks coverage.

### Use case 4 — Bulk profile enrichment (firmographics layer)

Cheaper per-row than Apollo when you only need basic firmographics (current company, current title, location, headline). Useful for ICP scoring before spending Blitz credits on email enrichment.

### Use case 5 — Company page details

For brands where Ocean.io `industries`/`technologies` is sparse, pull the LinkedIn company page directly to get `headcount`, `industry`, `specialties`, `headquarters`, `founded`.

## Pipeline pattern

```
Trigify create_linkedin_posts_search  → relevant posts (with obfuscated URNs)
   ↓
RapidAPI post-engagement endpoint     → full liker + commenter URN list
   ↓
RapidAPI profile-resolve endpoint     → clean linkedin.com/in/<vanity> + firmographics
   ↓
ICP filter (title, seniority, company)  → in-ICP shortlist
   ↓
BlitzAPI find-work-email              → verified work emails
   ↓
Instantly /api/v2/leads/add           → loaded into campaign
```

This replaces the prior loop where Trigify's slow per-URN `enrich_profile` was the bottleneck.

## Where this fits vs. other LinkedIn data sources

| Source | Best for | Avoid for |
|---|---|---|
| **Trigify MCP** | Live monitoring + keyword/profile alerts | Bulk one-shot enrichment (rate-limited per workspace) |
| **RapidAPI LinkedIn Bulk** | Bulk profile / post-engagement / employee scrape + URN resolution | Live monitoring (no push) |
| **BlitzAPI** | Cheap work-email find from clean LinkedIn URL | Anything that requires resolving URNs first |
| **Apollo** | US firmographic depth + pre-verified emails | UK/EU coverage; long-tail brands |
| **Ocean.io v3** | Top-of-funnel company discovery (lookalike + filter) | Person-level emails |

## Cost & rate limits

- RapidAPI metered per-call. Track usage at https://rapidapi.com/developer/dashboard.
- Subscribe to a paid tier before bulk loops — free tier 429s aggressively.
- For runs >1000 calls, batch and add 0.3-1s sleep between requests; respect 429 backoff.

## History

- **2026-05-25:** Added to user MCP config (`rapidapi-linkedin-bulk-scraper`), brain VPS `.env` (`RAPIDAPI_KEY`), and brain MCP config (`rapidapi-linkedin-bulk`). Indexed in `~/brain/memory/MEMORY.md` and `~/brain/memory/tools/rapidapi_linkedin_bulk.md`.
