# RapidAPI JSearch — Job Board Scraper (added 2026-05-25)

**Host:** `jsearch.p.rapidapi.com` (publisher `letscrape-6bRBa3QguO5`)
**Auth:** `$RAPIDAPI_KEY` (same key as `rapidapi-linkedin-bulk`; one quota covers both)
**MCP:** `rapidapi-jsearch` (wired in `~/brain/.claude/mcp-servers.json`)
**Verified working 2026-05-25.**

## Why it's in the brain toolkit

Job postings are a **buying-signal goldmine** for outbound:

- Company hiring SDR/AE = budget for outbound infra (Instantly, Smartlead, lead-gen)
- Company hiring "Head of Growth" / "VP Marketing" = appointment-set window opens
- Company hiring multiple developers = scaling = needs sales-eng tools
- Job posts list hiring managers by name + LinkedIn = decision-maker enrichment

Also enables candidate-side workflows: candidates who just posted "actively looking" are open to recruiter outreach.

## MCP tools (5 total, verified)

| Tool | Use |
|---|---|
| `Job_Search` | Query by keyword + location, returns 10-100 jobs/page with company, title, description, apply URL, posted-at |
| `Job_Search_V2` | Extended filters (employment_types, date_posted, remote_jobs_only, salary_range) |
| `Job_Details` | Fetch full job by `job_id` from search results |
| `Job_Salary` | Salary estimate for `job_title` + `location` |
| `Company_Job_Salary` | Salary estimate for a specific company + role |

## Direct HTTPS (script-friendly)

```bash
curl "https://jsearch.p.rapidapi.com/search?query=SDR+in+San+Francisco&num_pages=1" \
  -H "x-rapidapi-host: jsearch.p.rapidapi.com" \
  -H "x-rapidapi-key: $RAPIDAPI_KEY"
```

**Verified params (Job_Search):**
- `query` — keyword + optional "in <city>" syntax (e.g., `"SDR in San Francisco"`)
- `page` — 1-indexed (default 1)
- `num_pages` — pages to fetch per call (default 1, max 20)
- `country` — `us`, `gb`, `ca`, `au`, etc. (default `us`)
- `date_posted` — `all`, `today`, `3days`, `week`, `month`
- `employment_types` — comma-separated: `FULLTIME,PARTTIME,CONTRACTOR,INTERN`
- `remote_jobs_only` — `true`/`false`
- `job_titles` — filter to exact titles (semicolon-separated)

## Response shape

```json
{
  "status": "OK",
  "request_id": "...",
  "data": [
    {
      "job_id": "OBzK7Tf2qmAydZWYAAAAAA==",
      "job_title": "Software Engineer 4",
      "employer_name": "Software Technology",
      "employer_website": null,
      "job_publisher": "Monster",
      "job_employment_type": "Full-time",
      "job_apply_link": "https://...",
      "apply_options": [{"apply_link": "...", "publisher": "Monster"}],
      "job_description": "...",
      "job_city": "...",
      "job_state": "...",
      "job_country": "...",
      "job_posted_at_datetime_utc": "...",
      "job_min_salary": 90000,
      "job_max_salary": 140000,
      "job_salary_currency": "USD",
      "job_highlights": {"Qualifications": [...], "Responsibilities": [...]}
    }
  ]
}
```

## Use cases in the lead-gen pipeline

### 1. Hiring-signal prospecting (best ROI)
Query `"<persona> in <country>"` → extract `employer_name` + `employer_website` → cross-reference with Ocean.io for firmographics → drop into BlitzAPI for email enrichment. Result: companies with active budget for tools that support that persona.

### 2. Decision-maker discovery via job posts
Many job descriptions include "reports to <Name>, <Title>" or list hiring manager. Parse with regex + LLM to extract DM name → BlitzAPI find-work-email.

### 3. Title taxonomy research
Run `Job_Search` for each ICP company → aggregate `job_title` distribution → discover the exact titles that ICP uses (e.g., "Manager, Performance Marketing" vs "Performance Marketing Manager"). Refines outbound persona filters.

### 4. Salary-anchored personalization
For prospects in roles your service impacts, fetch `Job_Salary` for their role+city → use as personalization variable: "noticed San Francisco AEs in your stack typically clear $180K — our infra typically pays back in 6-8 weeks".

### 5. Hiring velocity tracking
Schedule weekly `Job_Search` runs per company → graph job count over time → companies with accelerating hiring = expansion stage = best-fit for many B2B services.

## Cost

Same RapidAPI key budget as `rapidapi-linkedin-bulk`. Monitor at https://rapidapi.com/developer/dashboard.

## History
- **2026-05-25**: Added MCP `rapidapi-jsearch` (VPS + local). Skill `job-board-scraping` created. Indexed here.
