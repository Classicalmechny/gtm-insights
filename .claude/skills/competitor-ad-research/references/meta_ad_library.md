# Meta Ad Library — scraping notes

The Ad Library is React-rendered behind progressive scroll, lazy-loading
ads as the user scrolls. It is not protected by auth for read access in
the keyword-search flow we use, but rate limits kick in if you hammer it.

## URL parameters that matter

| Param | Required value | Why |
|---|---|---|
| `active_status` | `all` | Returns active + inactive (paused) ads. Inactive history is where you learn what the brand abandoned. |
| `ad_type` | `all` | Don't filter to political-only or housing-only. |
| `country` | `ALL` | One scrape catches every geo the brand targets. |
| `q` | URL-encoded query | Try the personal handle first, then the company name as fallback. |
| `search_type` | `keyword_unordered` | More forgiving than exact-match. |
| `media_type` | `all` | Static and carousel ads are signal too. |
| `sort_data[mode]` | `total_impressions` | Highest-spend ads bubble to top. This is the closest public proxy for ROAS. |
| `sort_data[direction]` | `desc` | Descending impressions. |

A correct URL looks like:

```
https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL&q=BRAND&search_type=keyword_unordered&media_type=all&sort_data[mode]=total_impressions&sort_data[direction]=desc
```

## What each ad card contains in the DOM

Every ad card is a `div` that contains:
- A status header: `Active` or `Inactive`
- `Library ID: <numeric>` — unique per ad asset
- Either `Started running on DD Mon YYYY` (active) or `DD Mon YYYY - DD Mon YYYY` (paused)
- "Platforms" footer
- A `Sponsored\n` line followed by the ad's primary text (the caption)
- A `<video>` element with `src` and `poster` attributes
- A duration line like `0:00 / 1:13`
- A CTA strip: domain + button text (e.g. "INSTAGRAM.COM Visit Instagram profile")
- Optional `"N ads use this creative and text"` line when one creative is
  reused across multiple ad sets — count this as variants, not separate ads.

The scrape strategy: scroll 8x with 1.2s delay, then walk the DOM, find every
element with `innerText` matching `Library ID: \d+`, walk up to find the
ancestor that ALSO contains either `Started running` or a date range, and
that ancestor is the card. See `scripts/scrape_ad_library.py` for the exact JS.

## Video URLs are short-lived

`<video src>` is a signed Meta CDN URL with a `oe=` query param that
contains the expiry timestamp. They typically live ~24h. Download the
videos in the same session as the scrape — don't store the URLs and try
to fetch tomorrow.

If a URL expires mid-pipeline, re-scrape that one ad card to refresh.

## Impression numbers and EU transparency

Outside the EU political-ads transparency framework, Meta does NOT publish
per-ad impression numbers. But the `sort_data[mode]=total_impressions`
parameter still works — Meta sorts on internal signal and returns ads in
that order, you just can't see the actual number. Don't quote impression
counts in reports unless they're visible in the UI.

For EU political ads, the card includes a "EU transparency" badge and an
impression range becomes visible inside the "See ad details" expansion.

## Caveats

- **No advertiser-specific feed.** You must search by keyword; Meta has no
  `/advertiser/<page_id>` endpoint. If a brand has a generic name, prefer
  the personal handle as the query.
- **Multiple pages may share a name.** When two Pages have the same name,
  the library returns ads from both. Filter post-scrape by checking the
  `<a href>` of the "See ad details" link if needed.
- **Carousel/static ads have no `<video>`.** Their `video_url` will be
  null — skip them in the transcription step, but keep them in metadata
  so the final report can mention them as "Static creatives" alongside
  the active set.
