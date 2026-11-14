#!/usr/bin/env python3
"""
Deepinfra AI Variable Enrichment (GPTOSS 20B).

Two modes:

  mode=sample   - run all variable prompts on N sample leads and write
                  ai_samples.md for user review. No further work until
                  user approves.

  mode=full     - run all variable prompts across the full verified.csv,
                  write enriched.csv (= verified.csv + variable columns).
                  Uses concurrency. Progress persisted to
                  ai_progress.jsonl so re-runs resume from last index.

Variable spec format (JSON file):
  {
    "variables": [
      {
        "name": "icebreaker",
        "prompt": "Write a 1-sentence cold-email icebreaker for {first_name}, {title} at {company_name} ({company_domain}). Company homepage context: {company_homepage_text}",
        "max_tokens": 120,
        "needs_web": true,
        "fallback": "Reaching out because {company_name} fits a pattern we see across {company_industry} teams."
      },
      ...
    ]
  }

Usage:
  python deepinfra_ai_enrich.py --run-id <id> --mode sample
        --spec output/<run>/ai_spec.json [--n 5]

  python deepinfra_ai_enrich.py --run-id <id> --mode full
        --spec output/<run>/ai_spec.json
        [--concurrency 8]
"""
from __future__ import annotations

import concurrent.futures as _cf
import csv
import json
import re
import threading
import time
from pathlib import Path

from _common import (
    arg, get_key, log_event, make_session, run_dir, stable_hash,
)
import firecrawl_scrape  # local import for web context

# requests.Session is NOT thread-safe — use one per worker thread.
_tls = threading.local()


def _thread_session():
    sess = getattr(_tls, "session", None)
    if sess is None:
        sess = make_session()
        _tls.session = sess
    return sess

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = (
    "You write concise cold-email personalization variables. "
    "Output ONLY the variable value — no preamble, no quotes, no markdown, "
    "no commentary, no 'As an AI'."
)

REFUSAL_MARKERS = [
    "i cannot", "i can't", "as an ai", "i am unable", "i'm unable",
    "i don't have", "i do not have",
]


def call_model(session, prompt: str, max_tokens: int = 200,
               temperature: float = 0.4) -> str:
    headers = {
        "Authorization": f"Bearer {get_key('DEEPINFRA_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    for attempt in range(4):
        r = session.post(DEEPINFRA_BASE + "/chat/completions",
                         json=payload, headers=headers, timeout=60)
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 400:
            return ""
        body = r.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except Exception:
            return ""
        return _clean(text)
    return ""


def _clean(s: str) -> str:
    s = s.strip()
    # strip wrapping quotes
    if len(s) >= 2 and s[0] in '"\'' and s[-1] == s[0]:
        s = s[1:-1].strip()
    # collapse internal whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # filter obvious refusals
    if any(m in s.lower() for m in REFUSAL_MARKERS):
        return ""
    return s


def fill_template(template: str, lead: dict, web_ctx: dict) -> str:
    """Resolve {placeholders} against lead row and web_ctx."""
    merged = dict(lead)
    merged.setdefault("company_homepage_text", web_ctx.get("homepage_markdown", ""))
    merged.setdefault("linkedin_about", web_ctx.get("linkedin_about", ""))
    def repl(m):
        key = m.group(1)
        return str(merged.get(key, "") or "")[:2000]  # cap each var
    return re.sub(r"\{(\w+)\}", repl, template)


def maybe_fetch_web_context(lead: dict, needs_web: bool, run_id: str) -> dict:
    """Pre-scrape the company homepage when at least one var needs web context."""
    if not needs_web:
        return {}
    domain = (lead.get("company_domain") or "").strip()
    if not domain:
        return {}
    cache_dir = run_dir(run_id) / "web_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f"{stable_hash(domain, 16)}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    result = firecrawl_scrape.scrape_url(f"https://{domain}", formats=("markdown",))
    homepage_md = ""
    try:
        homepage_md = result.get("data", {}).get("markdown") or result.get("markdown") or ""
    except Exception:
        homepage_md = ""
    payload = {
        "homepage_markdown": homepage_md[:6000],
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False))
    return payload


def process_lead(lead: dict, variables: list[dict], run_id: str) -> dict:
    # Always grab the thread-local session so this is safe to call from a
    # ThreadPoolExecutor (requests.Session isn't thread-safe).
    sess = _thread_session()
    needs_web = any(v.get("needs_web") for v in variables)
    web_ctx = maybe_fetch_web_context(lead, needs_web, run_id)

    out = dict(lead)
    for var in variables:
        prompt = fill_template(var["prompt"], lead, web_ctx)
        text = call_model(sess, prompt, max_tokens=var.get("max_tokens", 200))
        if not text:
            fallback = var.get("fallback") or ""
            text = fill_template(fallback, lead, web_ctx)
        out[var["name"]] = text
    return out


# ---------------------------------------------------------------------------
# Sample mode
# ---------------------------------------------------------------------------

def mode_sample(run_id: str, spec_path: Path, n: int) -> None:
    rd = run_dir(run_id)
    spec = json.loads(spec_path.read_text())
    variables = spec["variables"]

    # Take N samples from verified.csv. Prefer rows with good data.
    verified_path = rd / "verified.csv"
    if not verified_path.exists():
        raise SystemExit(f"verified.csv not found at {verified_path}")
    with verified_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("verified.csv is empty")

    # Sort by data completeness so samples are representative.
    def completeness(r):
        keys = ["first_name", "last_name", "title", "company_name",
                "company_domain", "company_industry"]
        return sum(1 for k in keys if (r.get(k) or "").strip())
    rows.sort(key=completeness, reverse=True)
    samples = rows[:n]

    log_event(run_id, "ai_sample.start", n=len(samples),
              variables=[v["name"] for v in variables])

    processed = [process_lead(s, variables, run_id) for s in samples]

    # Write ai_samples.md
    out_path = rd / "ai_samples.md"
    lines = [f"# Sample AI Variable Preview — {run_id}\n"]
    lines.append("## Variables\n")
    for v in variables:
        lines.append(f"- `{v['name']}`")
    lines.append("")
    for i, lead in enumerate(processed, 1):
        lines.append(
            f"## Lead {i}: {lead.get('first_name','')} {lead.get('last_name','')}, "
            f"{lead.get('title','')}, {lead.get('company_name','')} ({lead.get('company_domain','')})"
        )
        for v in variables:
            lines.append(f"**{v['name']}:** {lead.get(v['name'],'')}\n")
        lines.append("")
    lines.append("---")
    lines.append("Approve? Reply \"yes\" to run across the full verified list, "
                 "or share edits to any prompt.")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log_event(run_id, "ai_sample.done", path=str(out_path), n=len(processed))
    print(f"Sample preview → {out_path}")


# ---------------------------------------------------------------------------
# Full mode
# ---------------------------------------------------------------------------

def mode_full(run_id: str, spec_path: Path, concurrency: int) -> None:
    rd = run_dir(run_id)
    spec = json.loads(spec_path.read_text())
    variables = spec["variables"]

    verified_path = rd / "verified.csv"
    enriched_path = rd / "enriched.csv"
    progress_path = rd / "ai_progress.jsonl"

    with verified_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("verified.csv is empty")

    # Resume: skip rows already processed.
    done_ids = set()
    if progress_path.exists():
        for line in progress_path.read_text().splitlines():
            try:
                done_ids.add(json.loads(line)["row_id"])
            except Exception:
                pass

    # Add a stable row_id (email is unique post-verification)
    for r in rows:
        r["__row_id"] = r.get("email") or stable_hash(
            r.get("linkedin_url", "") + r.get("company_domain", "")
        )

    pending = [r for r in rows if r["__row_id"] not in done_ids]
    log_event(run_id, "ai_full.start", total=len(rows), pending=len(pending),
              variables=[v["name"] for v in variables])

    fieldnames = [k for k in rows[0].keys() if k != "__row_id"]
    fieldnames += [v["name"] for v in variables if v["name"] not in fieldnames]

    # Initialise enriched.csv if not present (write any already-done rows from
    # progress is non-trivial; simplest correctness: re-process if resuming).
    write_mode = "a" if enriched_path.exists() else "w"
    out_f = enriched_path.open(write_mode, newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=fieldnames, extrasaction="ignore")
    if write_mode == "w":
        writer.writeheader()

    prog_f = progress_path.open("a", encoding="utf-8")

    def worker(lead):
        try:
            return process_lead(lead, variables, run_id)
        except Exception as e:
            log_event(run_id, "ai_full.error",
                      row_id=lead.get("__row_id"), error=str(e))
            # Apply fallbacks only.
            out = dict(lead)
            for v in variables:
                out[v["name"]] = (v.get("fallback") or "")
            return out

    n = 0
    with _cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        for done in ex.map(worker, pending):
            writer.writerow({k: done.get(k, "") for k in fieldnames})
            prog_f.write(json.dumps({"row_id": done["__row_id"]}) + "\n")
            prog_f.flush()
            n += 1
            if n % 50 == 0:
                log_event(run_id, "ai_full.progress", processed=n,
                          remaining=len(pending) - n)

    out_f.close()
    prog_f.close()
    log_event(run_id, "ai_full.done", processed=n, output=str(enriched_path))
    print(f"AI enrichment → {enriched_path} ({n} rows processed)")


def main() -> None:
    run_id = arg("run-id", required=True)
    mode = arg("mode", required=True)
    spec_path = Path(arg("spec", required=True))
    if mode == "sample":
        mode_sample(run_id, spec_path, int(arg("n", "5")))
    elif mode == "full":
        mode_full(run_id, spec_path, int(arg("concurrency", "8")))
    else:
        raise SystemExit("--mode must be sample or full")


if __name__ == "__main__":
    main()
