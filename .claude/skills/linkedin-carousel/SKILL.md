---
name: linkedin-carousel
description: Build a multi-slide LinkedIn document-post carousel as a 1080x1350 PDF with the brand's pink + navy style. Use when the user says "draft a carousel", "make a LinkedIn carousel", "build a doc post", "turn this into a carousel", or asks for slides on a topic. Produces 6-9 slides, renders locally via HTML + Playwright, no external SaaS.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# linkedin-carousel skill

You build LinkedIn document-post carousels. The brand style is loaded from `brand.json`. Templates live in `templates/`. Render with `scripts/render.py`. Output goes to `output/<topic-slug>/carousel.pdf`.

## When this skill runs

Triggers:
- "Draft a carousel on [topic]"
- "Make a LinkedIn carousel about [topic]"
- "Build a doc post on [topic]"
- "Turn this post into a carousel"
- "Iterate slide N" / "swap the cover" / "redo slide 4"

If the user only gives a topic with no outline, ask for the outline before building. Do not guess the structure.

If the user says "infographic" instead of "carousel" — STOP. That's the `linkedin-infographic` skill, not this one.

## Workflow (follow exactly)

1. **Confirm the spec.** Take topic + outline. Write `output/<topic-slug>/spec.json`. Show it in chat. If user says "go", render. If they say "change X", update spec first.

2. **Render.** Run from the skill folder:
   ```bash
   python3 scripts/render.py output/<topic-slug>/spec.json
   ```
   Flags: `--slides 3,5` for partial re-render, `--preview` for half-res, `--no-pdf` for PNGs only.

3. **Deliver.** Use `present_files` on the PDF. If running through Telegram channel, send via channel reply tool with: "Carousel ready. N slides. Reply with edits."

4. **Iterate slide-by-slide.** When user says "redo slide 4 with X", edit ONLY that slide entry in `spec.json`, then re-render with `--slides 4`. Re-stitch the PDF. Never regenerate the whole carousel for a single-slide change.

## Brand identity (read brand.json every render)

- **Pink (`accent`)**: `#FF1F5A` — CTAs, number badges, ONE word in headline
- **Deep navy (`dark`)**: `#0A1532` — dark slide bg, primary text on light slides
- **Light gradient**: `#E8F0FB → #F4F8FC` — light slide bg
- **Muted**: `#7C8AA8` — page numbers, secondary text
- **Display font**: Archivo Black (or Anton fallback)
- **Body font**: Inter
- **Mono**: JetBrains Mono — handle, page counter, section labels

Never hardcode the handle. Read from `brand.json["handle"]`.

## Template catalog (8 types in templates/)

1. **`cover`** — Slide 1 only. 110px headline, one word in pink box, photo bottom.
2. **`intro`** — Light bg. Section pill + headline + numbered list of items.
3. **`section_dark`** — Dark navy + grid overlay. Pill + headline + 2-4 cards + pink pill CTA.
4. **`section_light`** — Same as section_dark but light bg with white-filled cards.
5. **`stat_grid`** — 2x2 grid of huge stat boxes.
6. **`terminal`** — Tool card + dark terminal block with traffic-light dots.
7. **`lead_magnet`** — Offer slide before the close. Benefits box + install line.
8. **`cta_close`** — Final slide. "Comment 'KEYWORD'" with keyword in pink box.

Don't invent a 9th template. Restructure content to fit one of these.

## The 4 carousel formats

**Format 1 — Step-by-step guide (8 slides):**
cover → intro → section_dark → section_light → section_dark → section_light → stat_grid OR lead_magnet → cta_close

**Format 2 — Tool stack (7 slides):**
cover → intro → section_dark → terminal → section_light → lead_magnet → cta_close

**Format 3 — Lead magnet giveaway (6 slides):**
cover → stat_grid → intro → section_light → lead_magnet → cta_close

**Format 4 — Mini-framework (8 slides):**
cover → intro → section_dark/light alternating × 5 → cta_close

## Slide copy rules (this is what makes carousels feel like the brand, not generic AI)

**Headlines.** ONE sentence. Period at end. ONE word in pink (the punch word).
- ✅ "The cold email engine."
- ✅ "The skill that improves the other 9."
- ❌ "Discover the power of cold email"
- ❌ "Unlock your potential with skills"

**Subheads.** ONE short line. Specific.
- ✅ "4 skills. Zero ICP to campaigns live in Bison."
- ❌ "Learn how to build effective cold email campaigns."

**Card body.** Max 2 lines. Specific tools, specific numbers.
- ✅ "ICP + offer + messaging angles from transcripts"
- ✅ "9-gate launch checklist → Bison or Instantly"
- ❌ "AI-powered ideation for sales messaging"

**Pink pill CTA at bottom of detail slides.** All caps. ONE sentence. Period. 3-7 words. It's a slogan, not a description.
- "THIS BUCKET PRINTS THE PIPELINE."
- "MY STACK GETS BETTER WHILE I SLEEP."
- "EVERY PAGE I RUN, I TEST. PERIOD."

**Forbidden words (break the voice instantly):**
unlock, elevate, transform, embrace, supercharge, harness, journey, dive, deep, magic, game changer, reshape, foundation, navigate, empower, leverage, holistic, picture, architect, embark, fuel, evolve, pioneer, testament, enrich, multifaceted, meticulously, intersection, hurdle, bustling, realm, depict, demystify, beacon, unleash, paramount, paradigm.

**Required: every detail slide must have a topic-specific number.**
"24 hypotheses ready" / "847 contacts synced in 3.2s" / "9-gate launch checklist."

## Layout pixel rules (baked into templates — adjust by these increments, don't redesign)

- Frame: 1080×1350 portrait. Padding 80px H, 70px T/B.
- Header (top): handle left + page counter right. Both 22px JetBrains Mono. 12px pink dot before handle.
- Section pill: pink bg, 8px radius, white mono number. Followed by uppercase mono label, letter-spacing 0.12em.
- Headline: 88px Archivo Black, line-height 1.02, letter-spacing -0.02em. Max 3 lines.
- Subhead: 32px Inter 500.
- Cards: 22px padding, 18px radius, 18px gap. Card title 30px Inter 700. Body 24px Inter 400.
- Number badge: 64px min-width, pink bg at 0.15 alpha, mono 26px.
- Pink pill CTA: 30px Inter 800, 30/40 padding, 999px radius, 8px outer pink glow.

## Spec.json structure

```json
{
  "topic_slug": "claude-code-skills-agency",
  "carousel_title": "10 Claude Code skills running my $600K/mo agency",
  "slides": [
    {
      "slide_number": 1,
      "template": "cover",
      "headline_pre": "10 Claude Code Skills",
      "headline_highlight": "Running My $600K/mo",
      "headline_post": "Agency",
      "use_photo": true
    },
    {
      "slide_number": 3,
      "template": "section_dark",
      "section_pill_number": "01",
      "section_pill_label": "COLD PIPELINE",
      "headline": "The cold email engine.",
      "subhead": "4 skills. Zero ICP to campaigns live in Bison.",
      "cards": [
        {"number": "01", "title": "Cold Email Strategy", "body": "ICP + offer + messaging angles from transcripts"}
      ],
      "cta": "THIS BUCKET PRINTS THE PIPELINE."
    }
  ]
}
```

Full reference: `examples/carousel_spec.json`.

## Iteration patterns (handle without asking)

- **"Make slide 3 pop more"** → switch template `section_light` → `section_dark`, OR add a `cta` line.
- **"Cover is weak"** → strengthen the metric in `headline_highlight`. Most concrete number on the slide.
- **"This feels generic"** → replace adjective phrases with tool names + numbers.
- **"Make CTA stronger"** → rewrite the pink pill as a slogan with a period. 3-7 words.
- **"Slide N is too long"** → cap card bodies at 2 lines, OR split into two slides.

## Self-anneal clause (Nick's pattern)

If a render step fails or the user asks for the same edit repeatedly, fix the underlying issue AND update this `SKILL.md` with the fix so it sticks. Examples:
- If a template silently truncates text → fix the template AND note the max char count in this file
- If `--slides` partial render breaks PDF stitching → fix the script AND document the working pattern here
- If the user keeps asking for "the takeaway line shorter" → tighten the rule above (e.g., "5 words max" instead of "3-7 words")

## What this skill does NOT do

- Does not write the LinkedIn caption — user writes their own
- Does not post to LinkedIn — separate skill
- Does not generate cover photos from scratch — use existing assets in `_shared/assets/` or pass image path in spec

## Asset checklist (one-time setup before first render)

Drop into `_shared/assets/` (sibling to this skill folder):
- `photo-cover.png` — headshot for cover slide, ~1080px tall, transparent PNG preferred
- `photo-close.png` — headshot for CTA close slide
- `cover-bg.png` — optional abstract dark background

Edit `brand.json` in this folder to set your handle.
