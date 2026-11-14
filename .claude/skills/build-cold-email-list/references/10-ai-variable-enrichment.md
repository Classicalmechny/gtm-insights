# Reference 10 — AI Variable Enrichment

## When to Run
ONLY if the user explicitly asked for AI personalization variables. Never
run by default — it's expensive and useless without a clear prompt.

## Sample-First Approval (Mandatory)

**The single most important rule.** Always run prompts on 5 sample leads
first. Show the user. Get approval. Only then run across the full list.

This saves 95%+ of cost on bad prompts and avoids garbage variables.

## Inputs Needed From User

For each variable:
- **Variable name** (snake_case, e.g. `icebreaker`, `custom_angle`, `fit_score`)
- **Prompt** — with placeholders like `{first_name}`, `{title}`,
  `{company_name}`, `{company_domain}`, `{linkedin_url}`,
  `{company_description}`, `{company_homepage_text}`, etc.
- **Output type** — short string / sentence / paragraph / number / category
- **Fallback** — what to write if the model fails or returns empty
- **Needs web context?** — if yes, we'll Firecrawl-scrape the company
  homepage and/or LinkedIn before running.

## Provider: Deepinfra (GPTOSS 20B)

Endpoint: `https://api.deepinfra.com/v1/openai/chat/completions`
Header: `Authorization: Bearer {DEEPINFRA_KEY}`
Model: `openai/gpt-oss-20b` (verify exact model slug via
`https://api.deepinfra.com/v1/models` at runtime)

Why GPTOSS 20B:
- Cheap (~$0.05 per 1M tokens at writing time).
- Fast.
- Good enough for templated cold-email personalization.

Payload:
```json
{
  "model": "openai/gpt-oss-20b",
  "messages": [
    {"role": "system", "content": "You write concise cold-email personalization variables. Output ONLY the variable value — no preamble, no quotes, no markdown."},
    {"role": "user", "content": "<resolved prompt with placeholders filled>"}
  ],
  "temperature": 0.4,
  "max_tokens": 200
}
```

System prompt forces no-preamble output. Always strip whitespace and
opening/closing quotes from the response.

## Web Context (Firecrawl)

For prompts that reference `{company_homepage_text}` or
`{linkedin_about}`, pre-scrape ONCE per lead and cache to disk:

```
./output/<run_id>/web_cache/<domain>.json
{ "homepage_markdown": "...", "fetched_at": "..." }
```

Firecrawl call:
```python
firecrawl.scrape_url(f"https://{company_domain}", params={
    "formats": ["markdown"],
    "onlyMainContent": True,
    "timeout": 20000
})
```

Cache hits skip re-scrape on subsequent variables for the same lead.

## Sample Preview Format

After running on 5 samples, write `ai_samples.md`:

```markdown
# Sample AI Variable Preview — <run_id>

## Variables
- icebreaker
- custom_angle

## Lead 1: Jane Doe, CEO, Acme Inc (acme.com)
**icebreaker:** Saw Acme just launched the v3 dashboard — the move from polling to webhooks must have been a relief for your customers.
**custom_angle:** Acme's recent positioning around "compliance-grade analytics" overlaps closely with the pain we solve for fintech ops teams.

## Lead 2: ...
...

---
Approve? Reply "yes" to run across all 847 verified leads.
Edit a prompt? Reply with the new prompt for the variable.
```

Then WAIT for explicit user approval. If user edits a prompt, re-run
samples and show again.

## Full Run

After approval:
1. Iterate over `verified.csv`.
2. For each lead, for each variable:
   - Resolve prompt placeholders against the lead's data + web cache.
   - Call Deepinfra.
   - Strip + sanitize output.
   - On failure (empty, 429 after retries, or refused), use the
     declared fallback.
3. Run with concurrency (default 8 concurrent requests, configurable).
4. Persist progress to `./output/<run_id>/ai_progress.jsonl` after every
   lead — resumable on crash.
5. Write `enriched.csv` (= `verified.csv` + one column per variable).

## Fallback Strategy

Recommended defaults:
- `icebreaker` → `"Reaching out because {company_name} fits a pattern we see across {industry} teams."` (templated, not AI-generated)
- `custom_angle` → empty string
- `fit_score` → `"medium"` (when score model fails)

For each variable, the user CAN override the fallback in intake.

## Cost Notes

- GPTOSS 20B on Deepinfra: ~$0.05 / 1M tokens.
- Typical icebreaker prompt: ~500 input + 100 output = ~$0.00003 per lead.
- 1000 leads × 3 variables ≈ $0.09 total. Cheap.
- Firecrawl pre-scrape dominates cost: ~$0.01 per page × N companies.

## Failure Modes

- **Model returns garbage** ("As an AI...", refusals) → strip common
  refusal phrases, fall back to declared fallback.
- **Rate limits** → exponential backoff up to 60s, then declared fallback.
- **Firecrawl returns empty homepage** → prompt with company name + domain
  only; some variables degrade quality but never break.

## Script
`scripts/deepinfra_ai_enrich.py` — full pipeline: takes `verified.csv` +
variable spec JSON, runs samples or full mode based on flag, writes
either `ai_samples.md` or `enriched.csv`.
