---
name: linkedin-infographic
description: Build a single-page LinkedIn infographic as a tall PNG + PDF, strictly styled per the IntentLedSales brand identity (single cyan accent on dark, Plus Jakarta Sans + Inter + Playfair Display). The IntentLedSales brand NAME and LOGO are never used — personal photo only. Use when the user says "make an infographic", "build a comparison chart", "create a visual breakdown", or "design a one-pager". Default canvas is 1080×1350 (LinkedIn portrait), width fixed, height auto-grows for tall content.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# linkedin-infographic skill

Build single-page infographics for LinkedIn. **Brand-strict**: the IntentLedSales Brand Identity Guide v1.0 is the only allowed visual system. Single cyan accent (`#22D3EE`) on a near-black background. No multi-color section palettes, no random hue rotations, no decorative scripts beyond Playfair Display.

## When this skill runs

Triggers:
- "Make an infographic on [topic]"
- "Build a comparison chart between X, Y, Z"
- "Create a visual breakdown of [topic]"
- "Design a one-pager about [topic]"
- "Turn this into an infographic"

If the user says "carousel" instead of "infographic" — STOP. That's the `linkedin-carousel` skill.

If the request is ambiguous, ask: "Carousel (multi-slide PDF) or infographic (single tall image)?"

## Workflow

1. **Pick the template** based on content shape:
   - Comparing 2–4 items side by side → `comparison_grid`
   - 50–100+ tips broken into N themed sections → `master_grid`
   - N numbered strategies/predictions/principles → `strategy_cards`
   - Single-topic deep dive with 3–5 stacked sections → `deep_dive`

2. **Confirm the spec.** Write `output/<topic-slug>/spec.json`. Show in chat. If user says "go", render.

3. **Render** from the skill folder:
   ```bash
   python3 scripts/render.py output/<topic-slug>/spec.json
   ```
   Flags: `--width N` / `--height N` (defaults 1080×1350 from `brand.json`), `--no-pdf` for PNG only.

4. **Run the mandatory reviewer.** Spawn an Agent (general-purpose subagent) with the contents of `REVIEWER.md` as the prompt, plus the absolute path to the rendered PNG, the spec.json, and brand.json. The reviewer returns a JSON verdict.

   **You MUST NOT show the user the output until the reviewer returns `verdict: "pass"`.** This is non-negotiable. The reviewer is fresh-eyes by design — its job is to catch what you missed.

   If `verdict: "fail"`:
   - Read each `issue.fix` in the JSON.
   - Apply the fix to the named file.
   - Re-render.
   - Re-run the reviewer.
   - Repeat until pass — or, after 3 review cycles, surface the remaining issues to the user and ask for guidance instead of looping forever.

   If `verdict: "pass"` with `minor` issues only: deliver, but mention the minor issues so the user can decide whether to iterate.

5. **Deliver.** Show the PNG (and PDF) path to the user with a one-line summary of what changed.

6. **Iterate.** Infographics are single-page — no partial render. Edit `spec.json` and re-run from step 3.

## Visual language — brand-strict

These tokens come from `_shared/assets/IntentLedSales_Brand_Assets.pdf`. Do not invent values.

**Surfaces**
- `bg`: `#0A0A0F` (page background)
- `surface`: `#111118` (inset surface inside cards)
- `card`: `#1A1A24` (primary card)
- Borders: `rgba(255,255,255,0.05)` subtle, `rgba(255,255,255,0.10)` hover

**Text**
- Primary `#FFFFFF`, secondary `#D1D5DB`, muted `#6B7280`, dim `#4B5563`

**Accent — single, used sparingly**
- `#22D3EE` cyan only. No red/green/yellow/orange/purple/pink/blue/teal/magenta variants exist in this skill.
- Use cyan for: section pills, key value highlights in the title, stat values, takeaway italic lines, the bottom CTA border, primary buttons.
- Do NOT colorize 9 different sections with 9 different hues. Every section card looks the same. Differentiation comes from content, layout, and typography — not color.

**Typography**
- Headings: Plus Jakarta Sans (700 / 800)
- Body: Inter (400 / 500 / 600)
- Editorial accent (italic takeaways, stat sublabels in display): Playfair Display
- Do not introduce other fonts (no Caveat, no JetBrains Mono outside numeric counters, no Archivo).

**Title styling**
- Plus Jakarta Sans 700, 56px, letter-spacing -0.025em
- Highlighted word(s) → cyan via `class="accent"`. No other highlight colors.

## Template catalog (4 types)

### `comparison_grid` — N-column comparison
Use for "X vs Y vs Z". Header tag → centered title → N column headers (logo + name + meta) → optional "When to use" pills → attribute rows → bottom takeaway.

### `master_grid` — N sections of M tips
Use for "100 tips", "30 frameworks". Title left + profile pill right → 2-column outer grid of sections → each section has a cyan-tinted header bar + 2-column inner grid of tips (number + title + caption).

### `strategy_cards` — Numbered strategies
Use for "N strategies", "N principles", "N predictions", "N updates". Profile pill top-center → big title with one accent word → optional subtitle + author → optional 3-card stat row → 2-col grid of cards, each with `LABEL N` pill, title, body, optional points, italic takeaway → bottom CTA card.

### `deep_dive` — Stacked sectioned analysis
Use for single-topic deep dive ("Why X is worth $YB"). Title left + subtitle + profile pill right → 3–5 stacked section cards → each has a section pill, body / two-col split / callouts / embedded image → final centered tagline.

## Stat row colors — brand only

All stat cards use the same cyan accent. Differentiation comes from the **value text** and arrows, not the card border.
- `arrow: "↑"` for upward movement, `"↓"` for downward — the symbol carries direction; the color stays cyan.
- Do not assign `color: red`, `color: green`, etc. The schema no longer accepts those values.

## Copy rules

**Section titles.** 4–8 words, declarative.
- ✅ "Cold email in a silo is dead"
- ✅ "The signal is the new list"
- ❌ "Effective Cold Email Marketing Strategies for B2B"

**Card body.** 1–2 sentences max. Cite numbers.
- ✅ "Clay hit $3.1B valuation / $100M ARR selling relevance, not tokens."
- ❌ "Clay has built an impressive valuation through innovative GTM technology."

**Italic takeaway lines (Playfair italic, cyan).** ONE sharp line.
- ✅ "The list is the bottleneck. The signal is the leverage."
- ✅ "Before two humans talk, their AIs already have."

**Forbidden words** (also used by carousel skill): unlock, elevate, transform, embrace, harness, journey, dive, deep, magic, game changer, reshape, foundation, navigate, empower, leverage, holistic, architect, embark, fuel, evolve, pioneer, testament, enrich, multifaceted, paradigm.

## Spec.json structures

All `color` fields have been removed. Specs are simpler now.

### `strategy_cards`:
```json
{
  "topic_slug": "...",
  "template": "strategy_cards",
  "profile": {"photo": "../_shared/assets/Personal photo.png", "name": "...", "url": "...", "position": "top_center"},
  "title_parts": [{"text": "9 things", "highlight": false}, {"text": "broke", "highlight": true}],
  "subtitle": "...",
  "author": "...",
  "top_stats": [{"label": "...", "arrow": "↑", "value": "...", "sublabel": "..."}],
  "strategies": [
    {"label": "BREAK 1", "title": "...", "body": "...", "points": [{"title": "...", "desc": "..."}], "takeaway": "...", "full_width": false}
  ],
  "cta_repost": {"photo": "...", "headline": "...", "sub": "..."}
}
```

### `comparison_grid`:
```json
{
  "template": "comparison_grid",
  "header_tag": "AI CODING TOOLS",
  "title": "Claude Code vs Cursor vs Copilot",
  "has_when_to_use": true,
  "columns": [
    {"logo": "...", "name": "...", "meta": "...", "when_title": "...", "when_desc": "...",
     "values": {"context": {"title": "...", "desc": "..."}, "pricing": {"title": "...", "desc": "..."}}}
  ],
  "attributes": [{"key": "context", "label": "Context"}, {"key": "pricing", "label": "Pricing"}],
  "takeaway": {"title": "...", "annotation": "...for GTM engineers", "body": "...", "points": [...]}
}
```

### `master_grid`:
```json
{
  "template": "master_grid",
  "title_parts": [{"text": "100 Tips", "highlight": true}, {"text": "to Master GTM", "highlight": false}],
  "profile": {...},
  "sections": [
    {"number": 1, "title": "ICP & Targeting",
     "tips": [{"number": 1, "title": "...", "desc": "..."}]}
  ]
}
```

### `deep_dive`:
```json
{
  "template": "deep_dive",
  "title_parts": [{"text": "WHY", "highlight": false}, {"text": "CLAY", "highlight": true}],
  "subtitle": "...",
  "profile": {...},
  "sections": [
    {"title": "The Data Marketplace", "layout": "two_col",
     "left_html": "<div>...</div>", "right_html": "<div>...</div>",
     "callouts": [{"label": "REPLACES", "text": "10–30 tools"}]}
  ],
  "final_tagline": {"question": "...", "answer": "..."}
}
```

## Iteration patterns

- **"Add a row to the comparison"** → append to `attributes[]` and add the matching `values` field on each column.
- **"Make it denser"** → add a `points` array to existing strategies, or switch from `strategy_cards` to `master_grid`.
- **"Layout looks crowded"** → check that the canvas width is 1080. Cards may need `full_width: true` on items with 3+ points.

## Self-anneal clause

If a render fails, the user reports a visual bug, or the user asks for the same edit repeatedly: fix the underlying issue AND update this `SKILL.md` so it sticks. Update the template, the script, or the rules above as needed.

## What this skill does NOT do

- Does not write the LinkedIn caption — user writes their own
- Does not post to LinkedIn — separate skill
- Does not generate diagrams or screenshots from scratch — embed via `image` field or raw `body_html` / `left_html`
- Does not use any color outside the brand palette (cyan + neutrals)
- Does not use the IntentLedSales name or logo

## Asset checklist

In `_shared/assets/`:
- `Personal photo.png` — square personal photo for the profile pill and CTA card

`brand.json` (in this folder) holds name, URL, and the brand tokens. Do not edit the `colors` block — it is the canonical brand palette. To override the canvas width or padding only, edit the `dimensions` block.

## Pre-delivery checklist

Before showing the user the output:
- [ ] Render finished without overflow warning from `render.py`
- [ ] **Reviewer subagent returned `verdict: "pass"`** (mandatory — see step 4 of Workflow)
- [ ] PNG dimensions verified: `python3 -c "from PIL import Image; print(Image.open('output/<slug>/infographic.png').size)"` → `(1080, 1350)`
- [ ] PDF generated successfully

## Reviewer system

After every render, spawn a fresh-eyes review subagent. The reviewer has no session context — it sees only the PNG and `REVIEWER.md`. It evaluates against:
1. Dimensions (must be 1080×1350)
2. Whitespace / canvas fill (no >120px dead zones, balanced padding, uniform card heights per row)
3. Image loading (no broken photo icons)
4. Brand compliance (cyan accent only, no IntentLedSales name/logo)
5. Typography (Plus Jakarta Sans + Inter + Playfair Display, nothing else)
6. Text overflow / clipping
7. Layout balance & visual hierarchy
8. Forbidden words / placeholder copy
9. Profile pill correctness

The reviewer returns a JSON verdict. **Do not deliver to the user until `verdict: "pass"`.** See `REVIEWER.md` for the full prompt and verdict schema.

How to invoke the reviewer (from the orchestrator):
```
Agent(
  description="Review rendered infographic",
  subagent_type="general-purpose",
  prompt=<contents of REVIEWER.md> + "\n\nINPUTS:\n- PNG: <abs path>\n- spec.json: <abs path>\n- brand.json: <abs path>"
)
```
