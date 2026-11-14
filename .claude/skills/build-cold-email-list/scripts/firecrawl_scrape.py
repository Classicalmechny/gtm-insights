#!/usr/bin/env python3
"""
Firecrawl scraping helper.

Two reusable entry points:

  scrape_url(url)            - scrape one page, return markdown+html+links
  crawl_site(root, limit)    - crawl a site / directory and yield pages

Used by:
  - Niche directory scraping (custom adapters under scripts/directories/)
  - AI variable enrichment to fetch company homepages for prompt context

Caching:
  All fetched pages are cached on disk at ~/.cache/firecrawl/<sha1>.json
  so repeated lookups don't re-charge.

Docs: https://docs.firecrawl.dev
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from _common import arg, get_key, log_event, make_session, stable_hash

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
CACHE_DIR = Path.home() / ".cache" / "firecrawl"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(url: str) -> Path:
    return CACHE_DIR / f"{stable_hash(url, 16)}.json"


def scrape_url(url: str, formats=("markdown",), only_main: bool = True,
               timeout_ms: int = 20000, force_refresh: bool = False,
               max_429_retries: int = 5) -> dict:
    """Scrape a single URL. Returns the Firecrawl response payload."""
    cache = _cache_path(url)
    if cache.exists() and not force_refresh:
        try:
            return json.loads(cache.read_text())
        except Exception:
            pass

    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('FIRECRAWL_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": list(formats),
        "onlyMainContent": only_main,
        "timeout": timeout_ms,
    }
    for attempt in range(max_429_retries + 1):
        r = session.post(FIRECRAWL_BASE + "/scrape", json=payload,
                         headers=headers, timeout=timeout_ms / 1000 + 30)
        if r.status_code == 429:
            time.sleep(min(60, 2 ** attempt))
            continue
        if r.status_code >= 400:
            return {"error": r.text[:500], "status": r.status_code}
        body = r.json()
        cache.write_text(json.dumps(body, ensure_ascii=False))
        return body
    return {"error": "rate_limited_max_retries", "status": 429}


def crawl_site(root: str, limit: int = 500, formats=("markdown", "links"),
               only_main: bool = True, max_depth: int = 2) -> dict:
    """Start an async crawl job; poll to completion; return the bundled pages."""
    session = make_session()
    headers = {
        "Authorization": f"Bearer {get_key('FIRECRAWL_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": root,
        "limit": limit,
        "scrapeOptions": {
            "formats": list(formats),
            "onlyMainContent": only_main,
        },
        "maxDepth": max_depth,
        "allowBackwardLinks": False,
    }
    r = session.post(FIRECRAWL_BASE + "/crawl", json=payload, headers=headers, timeout=60)
    if r.status_code >= 400:
        return {"error": r.text[:500], "status": r.status_code}
    job = r.json()
    job_id = job.get("id") or job.get("jobId")
    if not job_id:
        return job

    # Poll job.
    while True:
        sr = session.get(f"{FIRECRAWL_BASE}/crawl/{job_id}", headers=headers, timeout=30)
        if sr.status_code >= 400:
            return {"error": sr.text[:500], "status": sr.status_code}
        st = sr.json()
        status = (st.get("status") or "").lower()
        if status in ("completed", "complete", "success"):
            return st
        if status in ("failed", "cancelled", "error"):
            return st
        time.sleep(5)


def main() -> None:
    """CLI entry. Either:
       --url <url>                     # one-off scrape
       --crawl <root> --limit 500      # crawl
       --run-id <id> (optional)        # also log to run.log
    """
    run_id = arg("run-id", None)
    url = arg("url", None)
    crawl_root = arg("crawl", None)
    limit = int(arg("limit", "500"))
    out = arg("out", None)

    if url:
        result = scrape_url(url)
    elif crawl_root:
        result = crawl_site(crawl_root, limit=limit)
    else:
        raise SystemExit("Provide --url or --crawl")

    if out:
        Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"Wrote {out}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])

    if run_id:
        log_event(run_id, "firecrawl.cli",
                  url=url, crawl=crawl_root, limit=limit, ok="error" not in result)


if __name__ == "__main__":
    main()
