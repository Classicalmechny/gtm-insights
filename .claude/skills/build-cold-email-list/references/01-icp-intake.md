# Reference 01 — ICP Intake

## Goal
Capture a complete, structured ICP before spending a single token on lookup.

## Canonical ICP Schema (`icp.json`)

```json
{
  "run_id": "2026-05-14_1330_us_saas_founders",
  "target_count": 1000,
  "persona": {
    "titles": ["Founder", "Co-Founder", "CEO"],
    "seniority": ["c_suite", "owner", "founder"],
    "departments": ["executive"],
    "title_exclusions": ["Assistant", "Intern", "Former"]
  },
  "firmographics": {
    "industries": ["Software", "Computer Software", "SaaS"],
    "industries_exclude": ["Government", "Non-Profit"],
    "employee_count_min": 2,
    "employee_count_max": 50,
    "revenue_min": null,
    "revenue_max": null,
    "founded_year_min": 2018,
    "founded_year_max": null,
    "tech_stack_includes": [],
    "tech_stack_excludes": [],
    "funding_stages": ["seed", "series_a"]
  },
  "geographics": {
    "countries": ["United States"],
    "regions": [],
    "cities": [],
    "exclude_countries": []
  },
  "seed_domains": [],
  "exclusions": {
    "competitor_domains": [],
    "customer_domains": [],
    "blocklist_domains": []
  },
  "ai_variables": {
    "enabled": false,
    "variables": []
  },
  "delivery": {
    "format": "csv",
    "columns_extra": []
  }
}
```

## Intake Questions (Reverse Prompt)

Fire all questions in ONE message to the user. Only ask about fields the
user didn't already fill in. Examples:

1. **Persona** — what job titles? (e.g. "Founder, Co-Founder, CEO" or
   "Head of Marketing, VP Marketing, CMO"). Also: any seniority filter?
2. **Industry** — list of industries (LinkedIn taxonomy preferred) or a
   free-text description we'll translate into BlitzAPI / Instantly
   industry codes.
3. **Geo** — countries / states / cities (be as specific as helpful).
4. **Company size** — employee count range. (Default ranges: 1–10 SMB,
   11–50 small, 51–200 mid, 201–1000 large, 1000+ enterprise.)
5. **Target count** — how many verified leads do you want? (Default 1000.
   Below 100 the cost-per-lead becomes high. Above 5000 we'll batch.)
6. **Seed domains** (optional) — any existing customer or aspirational
   accounts you want us to find lookalikes of? (Triggers Ocean.io path.)
7. **Exclusions** — competitors? existing customers? specific domains to
   blocklist? (Upload list or paste comma-separated.)
8. **AI variables** — do you want personalization variables (icebreaker,
   custom angle, fit score)? If yes, list them and the angle for each.

## Disambiguation Rules

- "Decision maker" alone is too vague — push for specific titles.
- "SMB" → confirm employee range (10–200 vs 1–50 etc).
- "US-based" → default to United States only; ask if Canada / LATAM are OK.
- "B2B SaaS" → confirm whether to include B2B agencies / IT services or strict pure-play SaaS.
- "Founders of agencies" → ask agency type (marketing, dev, design, recruiting, BPO, etc).

## Stop Conditions

- If estimated TAM < 50 worldwide given the filters, warn the user and
  propose loosening one dimension.
- If user can't articulate a persona at all (just "anyone who might
  need X"), refuse to proceed and ask for a clearer persona — vague
  ICPs always produce bad lists.

## Confirmation Format

Reply back with a compact table:

```
| Field          | Value                                |
|----------------|--------------------------------------|
| Titles         | Founder, Co-Founder, CEO             |
| Industries     | SaaS, Computer Software              |
| Geo            | United States                        |
| Employees      | 2–50                                 |
| Funding        | Seed, Series A                       |
| Target Count   | 1000                                 |
| AI Variables   | icebreaker, custom_angle             |
| Exclusions     | 3 competitor domains                 |
```

Then: "Proceed? (yes / edit X)".
