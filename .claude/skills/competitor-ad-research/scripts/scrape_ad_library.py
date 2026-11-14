#!/usr/bin/env python3
"""
Scrape every ad for an advertiser from Meta Ad Library and save to metadata.json.

USAGE
  Step 1 — call this script's helper functions FROM the orchestrator (Claude)
  via Playwright MCP. This file is the canonical source of the DOM-extraction
  JavaScript snippet — copy/paste the JS body of `EXTRACT_JS` below into a
  browser_evaluate call after navigating to the ad library URL.

  Step 2 — pass the returned ad list to `write_metadata()` to persist it.

The reason this isn't a one-shot CLI: Meta Ad Library is JS-rendered behind a
login wall for non-EU geos. Running headless without an authenticated session
gets blocked. Letting Claude drive Playwright (which inherits the user's
logged-in profile on the host) is the reliable path.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

# -----------------------------------------------------------------------------
# 1. URL builder
# -----------------------------------------------------------------------------
def ad_library_url(query: str) -> str:
    """Build the Meta Ad Library URL sorted by total impressions desc."""
    return (
        "https://www.facebook.com/ads/library/"
        f"?active_status=all&ad_type=all&country=ALL"
        f"&q={quote_plus(query)}"
        f"&search_type=keyword_unordered&media_type=all"
        f"&sort_data[mode]=total_impressions&sort_data[direction]=desc"
    )

# -----------------------------------------------------------------------------
# 2. The JS snippet to paste into a browser_evaluate() call.
#    Scroll first (see SCROLL_JS), then run EXTRACT_JS.
# -----------------------------------------------------------------------------
SCROLL_JS = r"""
async () => {
  for (let i = 0; i < 8; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise(r => setTimeout(r, 1200));
  }
  return { scrolled: true, height: document.body.scrollHeight };
}
"""

EXTRACT_JS = r"""
() => {
  const ads = [];
  const all = Array.from(document.querySelectorAll('div, span'));
  const seen = new Set();
  for (const el of all) {
    const txt = el.innerText || '';
    const m = txt.match(/Library ID: (\d+)/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    let p = el;
    let depth = 0;
    while (p && depth < 12) {
      const t = p.innerText || '';
      const idsInCard = (t.match(/Library ID: \d+/g) || []).length;
      if ((t.includes('Started running') || t.includes(' - ')) && idsInCard === 1) {
        const video = p.querySelector('video');
        const startMatch = t.match(/Started running on ([^\n]+)/);
        const rangeMatch = t.match(/(\d{1,2} \w+ \d{4} - \d{1,2} \w+ \d{4})/);
        const status = t.startsWith('Inactive') ? 'Inactive' : 'Active';
        const sponsoredIdx = t.indexOf('Sponsored\n');
        let body = '';
        if (sponsoredIdx >= 0) {
          body = t.slice(sponsoredIdx + 10).split('\n0:00 /')[0];
        }
        const variantMatch = t.match(/(\d+) ads use this creative/);
        ads.push({
          library_id: id,
          status,
          started_running: startMatch ? startMatch[1].trim() : null,
          date_range: rangeMatch ? rangeMatch[1] : null,
          video_url: video ? (video.src || video.currentSrc) : null,
          video_poster: video ? video.poster : null,
          video_duration: video ? video.duration : null,
          body_text: body.slice(0, 1500),
          variant_count: variantMatch ? parseInt(variantMatch[1]) : 1
        });
        seen.add(id);
        break;
      }
      p = p.parentElement;
      depth++;
    }
  }
  return { count: ads.length, ads };
}
"""

# -----------------------------------------------------------------------------
# 3. Persist results to metadata.json
# -----------------------------------------------------------------------------
def write_metadata(workdir: Path, advertiser: str, query: str, raw_ads: list[dict],
                   reference_url: str | None = None) -> Path:
    """Normalize raw scraped ads → metadata.json with rank order preserved."""
    workdir.mkdir(parents=True, exist_ok=True)

    def normalize_date(s: str | None) -> str | None:
        if not s:
            return None
        # "24 Apr 2026" → "2026-04-24"
        import datetime
        try:
            return datetime.datetime.strptime(s.strip(), "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            return s

    ads = []
    for i, a in enumerate(raw_ads, start=1):
        start_date = end_date = None
        if a.get("date_range"):
            parts = a["date_range"].split(" - ")
            if len(parts) == 2:
                start_date = normalize_date(parts[0])
                end_date = normalize_date(parts[1])
        elif a.get("started_running"):
            start_date = normalize_date(a["started_running"])

        ads.append({
            "rank": i,
            "library_id": a["library_id"],
            "status": a["status"],
            "start_date": start_date,
            "end_date": end_date,
            "duration_sec": round(a.get("video_duration") or 0, 1),
            "variant_count": a.get("variant_count", 1),
            "body_text": (a.get("body_text") or "").strip(),
            "video_url": a.get("video_url"),
            "video_poster": a.get("video_poster"),
        })

    out = {
        "advertiser": advertiser,
        "query": query,
        "reference_url": reference_url,
        "ad_library_query_url": ad_library_url(query),
        "captured_at": __import__("datetime").date.today().isoformat(),
        "total_ads_in_library": len(ads),
        "ads_with_video": sum(1 for a in ads if a["video_url"]),
        "ads": ads,
    }
    target = workdir / "metadata.json"
    target.write_text(json.dumps(out, indent=2))
    return target


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: scrape_ad_library.py <workdir> <advertiser-name> [reference_url]")
        print("       (then paste the ads list as JSON on stdin)")
        sys.exit(1)
    workdir = Path(sys.argv[1])
    advertiser = sys.argv[2]
    ref = sys.argv[3] if len(sys.argv) > 3 else None
    raw = json.load(sys.stdin)
    if isinstance(raw, dict) and "ads" in raw:
        raw = raw["ads"]
    path = write_metadata(workdir, advertiser, advertiser, raw, ref)
    print(f"wrote {path}")
