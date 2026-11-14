---
name: job-board-scraping
description: >
  Scrape live job postings from 20+ job boards (LinkedIn, Indeed, Glassdoor,
  ZipRecruiter, Monster, etc.) via the RapidAPI JSearch MCP. Use cases:
  hiring-signal prospecting (companies actively hiring → buying signal),
  decision-maker discovery via job post bylines, title taxonomy research,
  salary benchmarking for personalization, hiring-velocity tracking, and
  candidate-side recruiter outreach. Trigger on phrases like "find
  companies hiring X", "who's hiring", "salary benchmark for X",
  "job postings for X persona", or "hiring signals in Y industry".
triggers:
  - find companies hiring
  - companies actively hiring
  - hiring signals
  - job postings for
  - find jobs matching
  - salary benchmark for
  - decision maker via job post
  - hiring velocity
  - who is hiring
  - candidates open to work in
tools:
  - mcp__rapidapi-jsearch__Job_Search
  - mcp__rapidapi-jsearch__Job_Search_V2
  - mcp__rapidapi-jsearch__Job_Details
  - mcp__rapidapi-jsearch__Job_Salary
  - mcp__rapidapi-jsearch__Company_Job_Salary
  - Bash
  - Read
  - Write
  - WebFetch
---

# Job Board Scraping — Skill

## Purpose

Convert public job-posting data from JSearch (RapidAPI aggregator over 20+ job boards) into outbound-ready lead signals.

The core insight: **a company posting a job is a stronger buying signal than a company appearing in a static firmographic database.** Posting = budget approved, ICP confirmed, decision-maker identifiable.

## When to use this skill

| User intent | Use this skill |
|---|---|
| "Find me 500 companies hiring AEs right now" | ✅ Primary |
| "Who's hiring data engineers in NYC?" | ✅ Primary |
| "What do companies actually call my persona?" (title research) | ✅ Primary |
| "Salary range for SDR in Austin?" | ✅ Primary |
| "Track hiring velocity for [list of competitors]" | ✅ Primary |
| "Find candidates currently job-hunting for recruiter outreach" | ✅ Secondary |
| Build TAM from scratch with no buying signal needed | ❌ Use `lead-list-from-strategy-doc` instead |

## Setup (one-time, already done for `anirudhgupta1177`)

MCP `rapidapi-jsearch` is wired both locally (`~/.claude.json`) and on the brain VPS (`~/brain/.claude/mcp-servers.json`). The shared `RAPIDAPI_KEY` covers JSearch + LinkedIn Bulk on the same quota.

For team members: clone this repo and Claude Code will load the project-scoped MCPs from `.mcp.json` automatically (approve on first prompt).

## The 5 MCP tools

| Tool | Returns | Best for |
|---|---|---|
| `Job_Search` | List of jobs (10/page default) for keyword + location | Bulk discovery |
| `Job_Search_V2` | Same + filters (employment_type, date_posted, remote_only, salary_range) | Targeted discovery |
| `Job_Details` | Full job detail by `job_id` | Hiring-manager extraction, full description scan |
| `Job_Salary` | Salary band for a role + location | Personalization variables |
| `Company_Job_Salary` | Salary band for role at a specific company | Account-level enrichment |

## Standard pipeline — hiring-signal prospecting

```
1. Define query
   query = "<persona-role> in <country/city>"
   filters = {date_posted:"week", employment_types:"FULLTIME"}

2. Paginate
   Loop pages 1..N until response.data is empty or N=20.
   Sleep 0.3s between pages.

3. Extract company facets
   For each job: collect (employer_name, employer_website, job_city, job_country,
   job_id, job_posted_at_datetime_utc, job_min_salary, job_max_salary)

4. Dedupe by (employer_name, job_city)

5. Enrich (per company)
   Pass employer_website to Ocean.io v2 lookup → industries + companySize + revenue
   Pass company to BlitzAPI company search → company_linkedin_url → employee finder
   for the ICP DM title (CEO/VP/Director matching persona)

6. Email find
   Per DM: BlitzAPI find-work-email by LinkedIn URL
   Fall back to Instantly Supersearch verify

7. Output
   companies_hiring_<persona>.csv with columns:
     employer_name, employer_website, job_city, job_posted_at, job_title,
     dm_name, dm_title, dm_linkedin_url, dm_email,
     hiring_signal_recency_days, ocean_industry, ocean_revenue
```

## Example queries

| Goal | Query | Filters |
|---|---|---|
| Companies hiring outbound SDRs (US, fresh) | `"Sales Development Representative"` | `date_posted:week, country:us` |
| AI startups hiring senior engineers | `"Senior Machine Learning Engineer"` | `employment_types:FULLTIME, date_posted:week` |
| E-commerce brands hiring growth roles | `"Head of Growth e-commerce"` | `country:us` |
| Remote-only DevRel positions | `"Developer Relations"` | `remote_jobs_only:true` |
| Hiring trend per competitor | `"<exact company> engineer"` | `date_posted:month` (run weekly, graph counts) |

## Sample call (MCP)

```python
# Via the MCP tool — claude code will auto-format the call
mcp__rapidapi-jsearch__Job_Search(
    query="VP of Marketing in San Francisco",
    num_pages=3,
    date_posted="week",
    country="us"
)
```

## Sample call (direct HTTPS for scripts)

```python
import os, requests
r = requests.get(
    "https://jsearch.p.rapidapi.com/search",
    params={"query": "VP of Marketing in San Francisco", "num_pages": 3, "date_posted": "week"},
    headers={
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
        "x-rapidapi-key": os.environ["RAPIDAPI_KEY"],
    },
    timeout=30,
)
jobs = r.json()["data"]
```

## Cost / rate limits

- Charged per request via RapidAPI Hub. Same quota as `rapidapi-linkedin-bulk`.
- Default tier: ~10K req/month. Bulk loops > 1K req should add `time.sleep(0.5)` and respect 429 backoff.
- Monitor: https://rapidapi.com/developer/dashboard

## Pairings

| Stack pair | Why |
|---|---|
| JSearch → Ocean.io v2 lookup | Hiring company → firmographics in one call |
| JSearch → BlitzAPI employee finder | Hiring company → DM identification |
| JSearch → Trigify LinkedIn post search | Cross-reference: company posting jobs + posting on LinkedIn = active growth signal |
| JSearch → RapidAPI LinkedIn Bulk Profile | Job description mentions hiring-manager name → resolve to LinkedIn profile + URN |

## References

- VPS tool doc: `~/brain/memory/tools/rapidapi_jsearch.md`
- API playground: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
- See `references/01-jsearch-api.md` for full param reference + response schema
