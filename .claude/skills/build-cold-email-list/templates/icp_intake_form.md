# ICP Intake Form

> Copy/paste this back to the user as a reverse-prompt OR fill in
> directly from the conversation.

```yaml
run_id: <fill>                  # YYYY-MM-DD_HHMM_<3-word-slug>
target_count: 1000

persona:
  titles: []                    # e.g. ["Founder", "Co-Founder", "CEO"]
  seniority: []                 # ["c_suite", "owner", "founder", "vp", "director", "manager"]
  departments: []               # ["executive", "marketing", "sales", "engineering", ...]
  title_exclusions: []          # ["Assistant", "Intern", "Former", ...]
  dms_per_company: 3            # cap when running DM finding

firmographics:
  industries: []                # LinkedIn taxonomy preferred
  industries_exclude: []
  employee_count_min:
  employee_count_max:
  revenue_min:
  revenue_max:
  founded_year_min:
  founded_year_max:
  tech_stack_includes: []
  tech_stack_excludes: []
  funding_stages: []            # ["seed", "series_a", "series_b", ...]

geographics:
  countries: []                 # full names: "United States", "United Kingdom"
  regions: []
  cities: []
  exclude_countries: []

seed_domains: []                # if user has aspirational/customer accounts

exclusions:
  competitor_domains: []
  customer_domains: []
  blocklist_domains: []

ai_variables:
  enabled: false
  variables:
    # - name: icebreaker
    #   prompt: "Write a 1-sentence icebreaker for {first_name} at {company_name}..."
    #   max_tokens: 120
    #   needs_web: true
    #   fallback: "Reaching out because {company_name} fits a pattern we see across {company_industry} teams."

delivery:
  format: csv
  columns_extra: []
```
