#!/usr/bin/env python3
"""
Stage 7 — Generate sample personalization preview (5 leads, one per campaign).

For now, personalization variables are largely DETERMINISTIC (extracted from
data we already have):
  {{first_name}}   = from row
  {{company_name}} = from row
  {{category}}     = category_label from segmentation step
  {{storefront_url}} = storefront_url from segmentation step
  {{drop_cadence}}  = 'high' or 'standard' (used in Campaign 4 only)

NO AI is needed for these — they're all in the data. So this script just
generates a preview of how each campaign email will render, picking
5 sample leads spread across campaigns + niches.

Writes: output/<run>/personalization_sample.md
"""
import csv, json, random
from pathlib import Path

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
SRC = RD / "campaigns" / "all_segmented.csv"
OUT = RD / "personalization_sample.md"

# Email templates from the strategy doc (Variant A only for preview)
TEMPLATES = {
    "1_free_sample": ("sample on a {{company_name}} piece",
        "{{first_name}}, We do AI on-model imagery for DTC fashion brands. "
        "$10-20 per SKU vs $200-1,000 from a studio. 3,000+ brands using us. "
        "Rather than describe it, happy to pull a piece off {{company_name}} "
        "and generate a sample on one of our models. Takes about 2 minutes "
        "on our side. Want me to send one over? Yash"),
    "2_cost_per_sku": ("{{category}} shoot costs",
        "{{first_name}}, How much is {{company_name}} paying per SKU for "
        "on-model photography right now? If it's between $200 and $1,000, "
        "that's the studio standard. We do the same thing for $10-20 per "
        "SKU. Fashion-specific AI, real garments, brand-approved model "
        "libraries you own. Mind if I share more on how the math shakes "
        "out for a full drop? Yash"),
    "3_representation": ("every body type, every drop",
        "{{first_name}}, Saw {{company_name}}'s sizing range. The hard "
        "part with inclusive sizing isn't pricing the SKUs - it's "
        "shooting every body type on every drop without going broke. "
        "We build per-brand model libraries that cover XS-4XL, every "
        "skin tone, every body shape. You approve the models once; they're "
        "yours across every future drop at $10-20 per SKU. Mind if I send "
        "a sample on one of {{company_name}}'s pieces? Yash"),
    "4_drop_velocity": ("drop turnaround",
        "{{first_name}}, Noticed {{company_name}} ships drops on a quick "
        "cadence. The 2-6 week agency turnaround usually doesn't fit that "
        "rhythm. We turn around catalog-ready on-model imagery in hours to "
        "days. Same brand-approved models on every drop. $10-20 per SKU. "
        "Mind if I share more on how brands at your cadence are using "
        "us? Yash"),
}

def render(template: str, row: dict) -> str:
    return (template
        .replace("{{first_name}}",   row["first_name"])
        .replace("{{company_name}}", row["company_name"])
        .replace("{{category}}",     row["category_label"])
        .replace("{{storefront_url}}", row["storefront_url"]))

def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    # Filter to rows with full info
    rows = [r for r in rows if r["first_name"] and r["company_name"] and r["primary_niche"]]
    random.seed(42)
    random.shuffle(rows)

    sample = []
    seen_campaigns = set()
    for r in rows:
        camps = r["campaigns_csv"].split("|")
        for c in camps:
            if c not in seen_campaigns and c in TEMPLATES:
                sample.append((c, r))
                seen_campaigns.add(c)
                break
        if len(sample) >= len(TEMPLATES): break

    # Pad with niche-diverse samples
    while len(sample) < 8:
        r = random.choice(rows)
        if (r["company_domain"], r["campaigns_csv"]) not in {(s["company_domain"], s["campaigns_csv"]) for c,s in sample}:
            camps = r["campaigns_csv"].split("|")
            if camps and camps[0] in TEMPLATES:
                sample.append((camps[0], r))

    md = ["# Personalization Preview — 5 sample renders\n",
          "Variables used: `{{first_name}}`, `{{company_name}}`, `{{category}}`, `{{storefront_url}}`\n",
          "All are derived directly from the data (no AI inference required for these).\n\n"]
    for camp, r in sample[:6]:
        subj_t, body_t = TEMPLATES[camp]
        subj = render(subj_t, r)
        body = render(body_t, r)
        md.append(f"---\n\n## Campaign: **{camp}**")
        md.append(f"**Lead:** {r['first_name']} {r['last_name']} ({r['title']}) — {r['company_name']} ({r['company_domain']})")
        md.append(f"**Niche:** `{r['primary_niche']}` → `{{category}} = {r['category_label']}`")
        md.append(f"**Drop cadence:** {r['drop_cadence']}")
        md.append(f"\n**Subject:** {subj}\n")
        md.append(f"**Body:**\n\n{body}\n")
    OUT.write_text("\n".join(md))
    print(f"Wrote sample → {OUT}")

if __name__ == "__main__":
    main()
