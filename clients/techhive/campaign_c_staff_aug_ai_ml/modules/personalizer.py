"""
AI personalization.

For Campaign C (staff aug HERO copy), the critical custom variable is
`tech_skills` — the tech stack the company is hiring for, extracted from
the job description. The full set we populate:

  role_being_hired   — normalized role title (deterministic from job_title)
  tech_skills        — comma-joined top tech skills from job_description (Deepinfra)
  company_description — 1-line summary from Firecrawl scrape (Deepinfra)
  usecase            — one-sentence "what they're trying to build" (Deepinfra)
  fallback_role      — generic "AI Engineer" fallback if extraction empty

We minimize cost by:
  (a) trying deterministic extraction first (role from job title)
  (b) batching Deepinfra calls per row (1 LLM call → all 3 inferred vars)
  (c) using gptoss-20b which is dirt cheap (~$0.0005 per call)
  (d) only Firecrawl-scraping when we don't already have enough context
"""
from __future__ import annotations

import json
import re
import time

import requests

from _common import env, log_event, make_session, run_dir, write_csv

DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
DEEPINFRA_MODEL = "openai/gpt-oss-20b"  # cheap, fast

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"


# ----------------------------------------------------------------------
# Deterministic role normalizer
# ----------------------------------------------------------------------
_ROLE_PATTERNS = [
    (r"\b(senior|sr|staff|principal|lead)?\s*(machine learning|ml)\s+engineer", "ML Engineer"),
    (r"\b(senior|sr|staff|principal|lead)?\s*(deep learning|dl)\s+engineer", "Deep Learning Engineer"),
    (r"\b(senior|sr|staff|principal|lead)?\s*(natural language processing|nlp)\s+engineer", "NLP Engineer"),
    (r"\b(senior|sr|staff|principal|lead)?\s*(computer vision|cv)\s+engineer", "Computer Vision Engineer"),
    (r"\b(senior|sr|staff|principal|lead)?\s*(ai|artificial intelligence)\s+research\s+engineer", "AI Research Engineer"),
    (r"\b(senior|sr|staff|principal|lead)?\s*applied\s+ai\s+engineer", "Applied AI Engineer"),
    (r"\b(senior|sr|staff|principal|lead)?\s*(ai|artificial intelligence)\s+engineer", "AI Engineer"),
    (r"\bgenai\b", "GenAI Engineer"),
    (r"\bllm\b", "LLM Engineer"),
]


def normalize_role(job_title: str) -> str:
    t = (job_title or "").lower()
    for pattern, label in _ROLE_PATTERNS:
        if re.search(pattern, t):
            return label
    # Default: strip seniority/parens, keep first 4 words
    words = re.sub(r"[([].*?[)\]]", "", job_title or "").split()
    return " ".join(words[:4]).strip() or "AI/ML Engineer"


# ----------------------------------------------------------------------
# Deepinfra LLM
# ----------------------------------------------------------------------
def _call_deepinfra(session, system: str, user: str,
                    max_tokens: int = 400, temperature: float = 0.3) -> str:
    headers = {"Authorization": f"Bearer {env('DEEPINFRA_KEY')}",
               "Content-Type": "application/json"}
    payload = {
        "model": DEEPINFRA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = session.post(DEEPINFRA_URL, json=payload, headers=headers, timeout=60)
    if r.status_code >= 400:
        return ""
    body = r.json()
    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return ""


def _firecrawl_scrape(session, url: str) -> str:
    """Scrape a URL → return markdown (truncated)."""
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    headers = {"Authorization": f"Bearer {env('FIRECRAWL_KEY')}",
               "Content-Type": "application/json"}
    try:
        r = session.post(FIRECRAWL_URL,
                         json={"url": url, "formats": ["markdown"],
                               "onlyMainContent": True, "waitFor": 0},
                         headers=headers, timeout=45)
        if r.status_code >= 400:
            return ""
        body = r.json()
        md = (body.get("data") or {}).get("markdown") or ""
        return md[:3500]  # cap
    except Exception:
        return ""


# ----------------------------------------------------------------------
# Extraction prompts
# ----------------------------------------------------------------------
EXTRACT_SYSTEM = """You are an analyst extracting structured info for B2B sales personalization.
Always reply with strict JSON only — no commentary, no markdown fence.
Be specific. If a field can't be determined, use null."""

EXTRACT_USER_TEMPLATE = """Company: {company_name}
Website: {company_website}
Hiring for role: {job_title}

Job description snippet:
\"\"\"
{job_description}
\"\"\"

{website_block}

Return JSON with these keys:
- tech_skills: a short string listing the 2-4 most important technical skills/tools the role requires (comma-separated, e.g. "PyTorch, LLMs, Python"). Pull these from the job description.
- company_description: a single short sentence describing what the company actually builds or does, in plain language (no marketing speak). Max 14 words.
- usecase: a single sentence describing the product/feature/system the new hire will work on. Max 18 words. Use specific nouns, not generic ones."""


def _extract_for_row(session, row: dict) -> dict:
    """Run LLM extraction, return three variables.

    Falls back gracefully if Deepinfra fails.
    """
    company_name = row.get("company_name", "")
    company_website = row.get("company_domain", "")
    job_title = row.get("job_title_hiring", "")
    job_desc = row.get("job_description_snippet", "")

    # Skip Firecrawl in smoke-test mode (just use job description)
    # Production: enable scrape if job_desc is too thin
    website_md = ""
    if len(job_desc) < 150 and company_website:
        website_md = _firecrawl_scrape(session, company_website)
    website_block = (f"\nHomepage content (truncated):\n{website_md}\n"
                     if website_md else "")

    user = EXTRACT_USER_TEMPLATE.format(
        company_name=company_name,
        company_website=company_website,
        job_title=job_title,
        job_description=job_desc[:1200],
        website_block=website_block,
    )
    raw = _call_deepinfra(session, EXTRACT_SYSTEM, user)
    if not raw:
        return {}

    # Robust JSON extract (model sometimes wraps in code fence)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def personalize(run_id: str, leads: list[dict],
                sleep_between: float = 0.2) -> list[dict]:
    session = make_session()
    out_dir = run_dir(run_id) / "stage4_personalized"
    out_dir.mkdir(exist_ok=True)

    out: list[dict] = []
    stats = {"input": len(leads), "with_tech": 0, "with_usecase": 0,
             "extraction_failed": 0}

    for row in leads:
        merged = dict(row)
        role = normalize_role(row.get("job_title_hiring", ""))
        merged["role_being_hired"] = role
        merged["fallback_role"] = "AI Engineer"

        extract = _extract_for_row(session, row)
        if not extract:
            stats["extraction_failed"] += 1
            merged["tech_skills"] = "Python, LLMs, modern ML stack"
            merged["company_description"] = ""
            merged["usecase"] = ""
        else:
            ts = (extract.get("tech_skills") or "").strip()
            cd = (extract.get("company_description") or "").strip()
            uc = (extract.get("usecase") or "").strip()
            merged["tech_skills"] = ts or "Python, LLMs, modern ML stack"
            merged["company_description"] = cd
            merged["usecase"] = uc
            if ts:
                stats["with_tech"] += 1
            if uc:
                stats["with_usecase"] += 1

        out.append(merged)
        time.sleep(sleep_between)

    log_event(run_id, "personalize.done", **stats)
    if out:
        fieldnames = list(out[0].keys())
        write_csv(out_dir / "leads_personalized.csv", out, fieldnames)
    return out


if __name__ == "__main__":
    import sys, csv
    run_id = sys.argv[1] if len(sys.argv) > 1 else "smoketest"
    src = run_dir(run_id) / "stage3_emails" / "leads_with_emails.csv"
    with src.open() as f:
        leads = list(csv.DictReader(f))
    print(f"Personalizing {len(leads)} leads...")
    out = personalize(run_id, leads)
    for r in out:
        print(f"\n{r['first_name']} {r['last_name']} @ {r['company_name']}")
        print(f"  role_being_hired : {r['role_being_hired']}")
        print(f"  tech_skills      : {r['tech_skills']}")
        print(f"  usecase          : {r.get('usecase','')}")
        print(f"  company_descr    : {r.get('company_description','')}")
