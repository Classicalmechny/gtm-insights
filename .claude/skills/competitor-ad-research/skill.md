---
name: competitor-ad-research
description: >
  Given a reference Instagram/Facebook/TikTok ad URL or a brand/advertiser
  name, identify the advertiser, pull their full active+inactive ad set from
  the Meta Ad Library (sorted by total impressions, which is the public proxy
  for spend/ROI), download every video creative, transcribe each one with
  faster-whisper, and produce an analyst-style report grouping ads into
  "creative families" with hooks, structures, CTAs, and the long-running
  winners highlighted. Use whenever the user says "research competitor ads",
  "transcribe these ads", "find other ads this brand is running",
  "what ads is X running", or supplies a Meta/IG ad URL and asks for analysis.
triggers:
  - competitor ad research
  - research competitor ads
  - transcribe competitor ads
  - transcribe these ads
  - find other ads this brand is running
  - what ads is [brand] running
  - meta ad library
  - facebook ad library
  - ad library research
  - long-running ads
  - high-ROI ads from
tools:
  - Read
  - Write
  - Edit
  - Bash
  - WebFetch
  - mcp__playwright__browser_navigate
  - mcp__playwright__browser_evaluate
  - mcp__playwright__browser_snapshot
  - mcp__playwright__browser_wait_for
  - Agent
---

# Competitor Ad Research — Skill

## Purpose

Given a reference ad (Instagram/Facebook reel URL, an advertiser handle, or a
brand name), produce a structured competitive-ad research report:

1. The full list of ads the brand is running (active + recently inactive).
2. Sorted by **total impressions** (Meta's public proxy for spend/ROI).
3. Long-running creatives highlighted (these are the proven scalers).
4. Every video creative downloaded and transcribed.
5. Grouped into "creative families" (same script, different cutdowns).
6. Per-family analysis: hook, problem framing, proof, CTA, length, age.

This is a competitive-intelligence tool, not a copy-paste tool. The deliverable
is **analytical** (patterns, structures, what's working) rather than just a
dump of transcripts.

---

## Inputs

The user gives ONE of:
- A reference Instagram post/reel URL (e.g. `https://instagram.com/p/XXXX/` or
  `/reel/XXXX/`) — common case.
- A Facebook ad URL or Meta Ad Library URL.
- A brand or advertiser name directly (e.g. "Moksh Vasant", "Meteoric").

If only a URL is given, step 1 below resolves it to a brand name.

---

## When to Use vs. NOT Use

**Use when:**
- User pastes a competitor's ad URL and asks "what else are they running?"
- User wants to reverse-engineer a competitor's funnel by reading every script.
- User is preparing a launch and wants to map the existing landscape.

**Do NOT use when:**
- User wants ads for their *own* brand (use `campaign-optimization` etc.).
- User wants organic content research (this skill is ads-only).
- The competitor's region restricts public ad library disclosure (i.e. ads
  outside the EU political-ads scope have no impression numbers, only running
  dates — sort by recency instead).

---

## Step-by-Step Process

### Step 1 — Resolve the URL to an advertiser

If the input is an Instagram `/p/` or `/reel/` URL, navigate Playwright to it
and read the `meta[property="og:description"]` tag (visible even on the
"Page couldn't load" wall). The `og:description` reliably contains the
handle in the form `X likes, Y comments - HANDLE on DATE: "caption"`.

If the input is a `/share/...` Facebook link or an ad URL with `id=...`,
extract the page name from the document title or the `meta[og:title]` tag.

Pull two things from the caption when possible:
- The personal handle (`moksh.vasant`)
- The company / brand mentioned in the script ("founder of Meteoric")

Use both as search queries in step 2 — Meta Ad Library is matched on the
advertiser's Facebook Page name, which is sometimes the personal handle and
sometimes the company name.

### Step 2 — Pull the full ad library

Navigate Playwright to:

```
https://www.facebook.com/ads/library/
  ?active_status=all
  &ad_type=all
  &country=ALL
  &q=<URL-ENCODED QUERY>
  &search_type=keyword_unordered
  &media_type=all
  &sort_data[mode]=total_impressions
  &sort_data[direction]=desc
```

Key URL params:
- `active_status=all` → returns both currently-running and inactive ads
  (inactive = the brand's historical ad set, which is gold for "what worked")
- `country=ALL` → all geos
- `sort_data[mode]=total_impressions&direction=desc` → IMPORTANT. By default
  Meta returns chronologically; we want impressions desc so the first ads in
  the DOM are the highest-spend / highest-ROI ones.
- `media_type=all` → don't filter to videos only at this stage; image and
  carousel ads are also signal even if we won't transcribe them.

Scroll the page 6-8 times with a ~1.2s delay between scrolls to lazy-load
every ad card. See `scripts/scrape_ad_library.py` for the full extraction
function.

For each card, capture:
- `library_id` (the Meta-assigned ID, unique per ad)
- `status` ("Active" / "Inactive")
- `start_date` and optional `end_date`
- `video_url` (CDN URL from the `<video>` element; **temporary signed URL,
  download promptly**)
- `duration_sec`
- `body_text` (the ad's primary text caption)
- `variant_count` (when Meta says "N ads use this creative and text")
- `cta` (the button label — "Send message", "Learn more", "Apply Now", etc.)

Save to `metadata.json` in the working directory.

### Step 3 — Pick the creatives to transcribe

Don't transcribe everything blindly. Cluster ads by body text — many ads
share the same caption + script with slightly different durations (these are
cutdowns of the same creative). For each "creative family":

- Always transcribe the **longest** variant (it's the source script).
- Transcribe the shortest active variant too (you'll see what the brand
  chose to keep when forced to cut down — that's the proven hook).
- Skip near-duplicates of the same length.
- For inactive historical ads, transcribe at least one per family — these
  show what the brand abandoned vs. evolved.

A "long-running" or "high-ROI" ad is one that meets any of:
- Currently active AND `start_date` is >30 days ago (still scaling means
  ROAS is holding).
- Top-N by impressions in the sorted result set.
- Same exact creative re-launched as a new library_id within 60 days of an
  earlier creative being paused (the brand reset learning on a proven asset).

### Step 4 — Download videos and transcribe

Run `scripts/transcribe_pipeline.py <working_dir>`. It:

1. Reads `metadata.json`.
2. Downloads each `video_url` to `videos/<library_id>.mp4` in parallel
   (6 workers, 60s timeout). Meta CDN URLs are short-lived — fail fast
   and re-scrape if expired.
3. Extracts mono 16kHz WAV with ffmpeg.
4. Loads `faster-whisper` with the `base.en` model (CPU int8, ~150MB,
   auto-downloads on first run).
5. Transcribes each clip with timestamps. Writes `transcripts/<library_id>.txt`.

Toolchain required (install once, see `references/setup.md`):
- `ffmpeg` (brew)
- `yt-dlp` (brew, for fallback Instagram organic links)
- Python 3.9+ and `pip install --user faster-whisper`

No API keys needed — entirely local.

### Step 5 — Write the analyst report

Use the template at `templates/report_template.md`. Sections:

1. **TL;DR** — three sentences: who the advertiser is, what their main
   pitch is, what the winning creative pattern is.
2. **Ad Library overview** — total ads, active vs inactive count, date
   range, link to the live ad library URL.
3. **Creative families** — one section per family. For each:
   - Hook (first 5 seconds)
   - Problem framing (what pain they call out)
   - Proof points (stats, social proof, names dropped)
   - CTA mechanism (DM keyword, link click, profile visit)
   - Script structure (which beats, in what order)
   - Length spread (shortest cutdown → source)
   - Why this likely works (or didn't)
4. **Long-running winners** — the specific library IDs running >30 days.
5. **What they abandoned** — inactive families, with hypotheses.
6. **Strategic takeaways for the user** — patterns the user can adapt,
   gaps the competitor isn't filling.
7. **Appendix: full transcripts** — concatenated, with library IDs.

Save the report to the working directory as `report.md`. Read it back to the
user as a chat summary (top of report only — appendix stays on disk).

---

## Working Directory Convention

Everything for a given research run goes under:

```
.cache/competitor-ad-research/<advertiser-slug>/
├── metadata.json          # scraped ad library data
├── videos/                # downloaded mp4s
├── audio/                 # extracted wavs
├── transcripts/           # per-ad-id txt files
├── pipeline.log           # download + transcribe log
└── report.md              # the deliverable
```

Use the advertiser handle (e.g. `moksh-vasant`) as the slug. If the same
brand is researched again later, the directory's presence lets you cache
metadata and re-fetch only what's changed.

---

## Edge Cases

- **Instagram URL returns "Page couldn't load"**: that's expected when not
  logged in. The `og:` meta tags are still rendered into the HTML — read
  them via `browser_evaluate`, do not rely on rendered DOM text.
- **No ads found in library**: try search variants — the personal handle,
  the company name, and the company domain without TLD. If still nothing,
  the advertiser may run only via Instagram boosted posts under a different
  Facebook Page, or may run no Meta ads at all.
- **Many ads with identical body text**: cluster on the first 100 chars of
  `body_text`. Different videos can share the same caption. Treat them as
  one family for analysis but transcribe each unique video.
- **Video URL returns 410 / expired**: the Meta CDN signs URLs with a
  ~24h TTL. Re-scrape that ad card to refresh the URL, then re-download.
- **Region without impression data**: outside the EU political-ads
  framework, Meta doesn't publish impressions. The Ad Library sort still
  works (Meta uses internal signal) but you can't quote impression numbers
  in the report.
- **Image / carousel ads**: no audio to transcribe. Capture the headline +
  caption only and list them in the report as "Static creatives".
- **Reel URL is organic, not an ad**: the URL identifies the brand, but the
  reel itself may not be in the ad library. That's fine — the goal is to
  find what IS in the ad library for that brand.

---

## Quality Bar (Definition of Done)

- [ ] Every ad in the library is in `metadata.json` with status, dates,
      duration, body text, and video URL.
- [ ] Every video creative is downloaded and transcribed.
- [ ] Each transcript has segment-level timestamps (`[mm:ss] text`).
- [ ] The report groups ads into creative families, not a flat list.
- [ ] Long-running winners are explicitly called out by library ID.
- [ ] The report ends with strategic takeaways the user can act on.
- [ ] If anything failed (expired URL, blocked region, etc.) it's flagged
      in the report, not silently dropped.
