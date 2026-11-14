# Competitor Ad Research — {{ADVERTISER}}

**Captured:** {{DATE}}
**Reference URL:** {{REFERENCE_URL}}
**Advertiser:** {{ADVERTISER_HANDLE}} — {{ONE_LINE_DESCRIPTION_OF_BRAND}}
**Live Ad Library:** [link]({{AD_LIBRARY_QUERY_URL}})

---

## TL;DR

Three sentences max. Who they are, what they sell, and the single most
important pattern in their ad mix (the hook? the funnel pivot? the ICP focus?).

---

## Ad Library Overview

| Metric | Value |
|---|---|
| Total ads in library | {{N}} |
| Video creatives | {{N}} |
| Image / static creatives | {{N}} |
| Currently active | {{N}} |
| Inactive historical | {{N}} |
| Earliest ad in library | {{DATE}} |
| Most recent launch | {{DATE}} |
| Sorted by | `total_impressions desc` |

---

## Strategic Pattern (if there is one)

If the library tells a story — a pivot, an era boundary, a vertical
expansion — name it here in a 2x4 table. Examples:

- "DM-bait long-form era → click-CTA short-form era"
- "Single-funnel for 6 months, then split into B2B and B2C"
- "Stopped naming clients in Q1 after a testimonial got contested"

Skip this section if no clear pattern exists — don't manufacture one.

---

## Creative Families

Cluster ads by **angle** (not by caption — captions often duplicate across
families). Aim for 3–10 families. For each:

### Family X — short descriptive name

| Library ID | Sec | Hook angle |
|---|---|---|
| `xxx` | NN | One-line hook + proof + CTA |

Then a paragraph or two on:
- The 5–8 second opening hook structure
- What proof is used (named clients, dollar amounts, follower counts,
  press, third-party validation, founder credentials)
- The CTA mechanism (DM keyword, click link, profile visit, form fill)
- What makes this family distinct from the others

---

## Long-Running Winners

List ads that have been active >30 days, sorted by impression rank. These
are the survivors of Meta's learning phase. For each, one line on why it
likely works.

---

## What They Abandoned

Inactive families. For each, hypothesize why it was paused (creative
fatigue, CTA mismatch, wrong audience, replaced by a refresh, or
straightforward underperformance).

---

## Strategic Takeaways

5–8 bullets the user can act on. Examples:

1. What pattern from this brand the user could adapt to their own offer.
2. What gap in the competitor's mix the user could fill.
3. What the competitor is NOT testing (vertical-specific ads,
   testimonial-driven creatives, retargeting-specific creative, etc.).
4. Surprising finding that goes against conventional ad-creative wisdom.
5. Risk the competitor seems to be taking (or hedging).

---

## Appendix — Where the Raw Data Lives

- `metadata.json`
- `videos/<library_id>.mp4`
- `audio/<library_id>.wav`
- `transcripts/<library_id>.txt`
- `pipeline.log`

Note that whisper transliteration of proper nouns is imperfect —
cross-reference against the source video when quoting specific names.
