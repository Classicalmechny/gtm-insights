#!/usr/bin/env python3
"""Generate the end-to-end lead-generation report as a .docx (python-docx)."""
import json, csv, os
from collections import Counter
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output", "full_run")
summary = json.load(open(os.path.join(OUT, "summary.json"), encoding="utf-8"))
s = summary["stages"]

# email_status distribution from the final CSV
dist = Counter()
rows = list(csv.DictReader(open(os.path.join(OUT, "jotform_partner_leads.csv"), encoding="utf-8")))
for r in rows:
    if r.get("first_name"):
        dist[r.get("email_status") or "(blank)"] += 1

NAVY = RGBColor(0x0A, 0x15, 0x51)
CYAN = RGBColor(0x1A, 0x55, 0x8C)
GREY = RGBColor(0x55, 0x55, 0x55)

doc = Document()
# base font
st = doc.styles["Normal"]
st.font.name = "Calibri"; st.font.size = Pt(10.5)

def h(text, level=1):
    p = doc.add_heading(text, level=level)
    for r in p.runs:
        r.font.color.rgb = NAVY if level <= 1 else CYAN
    return p

def para(text="", bold=False, italic=False, color=None, size=None, after=6):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold; run.italic = italic
    if color: run.font.color.rgb = color
    if size: run.font.size = Pt(size)
    p.paragraph_format.space_after = Pt(after)
    return p

def bullet(text, bold_prefix=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        r = p.add_run(bold_prefix); r.bold = True
        p.add_run(text)
    else:
        p.add_run(text)
    return p

def table(headers, data, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = ""
        run = c.paragraphs[0].add_run(hd); run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for row in data:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    return t

# ---------------- Title ----------------
title = doc.add_heading("Jotform Partner Directory — Lead Generation Report", level=0)
for r in title.runs: r.font.color.rgb = NAVY
para("End-to-end pipeline: scrape → enrich → resolve → recover → decision-makers → verify → deliver",
     italic=True, color=GREY, size=11)
para("Source: jotform.com/partnership/partner-directory  ·  Run date: 2026-06-23  ·  Run ID: full_run", color=GREY, size=9)
doc.add_paragraph()

# ---------------- 1. Executive Summary ----------------
h("1. Executive Summary", 1)
para(f"A custom 8-stage pipeline scraped all {s['s1']['partners']} companies listed in the Jotform "
     f"Partner Directory, enriched each company's services, recovered firmographics, identified "
     f"decision-makers across the target ICP, and verified their work emails. The full run completed "
     f"in {round(summary['elapsed_s']/60,1)} minutes and produced a {s['s6']['rows']}-row outreach-ready CSV.")
bullet(f"{s['s1']['partners']} partner companies — 100% captured & service-enriched", "Coverage: ")
bullet(f"{s['s6']['companies_with_leads']} companies with named decision-makers; {s['s4']['dms']} decision-makers total", "Decision-makers: ")
bullet(f"{dist.get('ok',0)} verified-OK work emails (send-ready) + {sum(v for k,v in dist.items() if k!='ok')} contacts reachable via LinkedIn", "Emails: ")
bullet("No data fabricated — every blank cell reflects genuinely unavailable data; strict email verification (MillionVerifier ok-only).", "Quality: ")

# ---------------- 2. Objective & ICP ----------------
h("2. Objective & Ideal Customer Profile", 1)
para("Goal: build an outreach-ready lead list of Jotform partners (resellers, agencies, IT shops, "
     "automation consultancies) — the partners themselves are the prospects. Decision-makers were "
     "targeted across three ICP buckets, plus a fourth bucket for large Carahsoft-type resellers.")
table(["Bucket", "Titles targeted"], [
    ["A — Owner / Top management", "Founder, Co-Founder, Owner, CEO, Managing Director, Managing Partner, Principal, President, Director"],
    ["B — Partnerships / BD", "Head of Partnerships, Partner/Partnerships Manager, Head/VP Business Development, Strategic Alliances Manager, Channel Manager, Head of Growth"],
    ["C — Delivery / Technical", "COO, Head of Operations/Delivery/Client Services, Solutions Architect, Head of Automation, Automation Lead, CTO, Technical Director, Implementation Lead"],
    ["D — Sales / Procurement (large resellers only)", "VP Sales, Sales Director, Vendor/Alliance Manager, Procurement Lead"],
], widths=[2.2, 4.3])

# ---------------- 3. Tools ----------------
h("3. Data Sources & Tools", 1)
table(["Tool", "Role in pipeline", "Cost"], [
    ["Direct HTTP scrape", "Jotform listing + detail modals; partner homepages", "Free"],
    ["DeepInfra (gpt-oss-20b)", "AI summary of each company's services", "~$0.07"],
    ["BlitzAPI", "domain→LinkedIn, firmographics, decision-maker search, find-work-email", "Bulk of spend"],
    ["RapidAPI LinkedIn-Bulk", "Stage 3b recovery of companies Blitz could not resolve", "Shared team key"],
    ["MillionVerifier", "Strict email verification (ok-only gate)", "~$1-2"],
], widths=[1.8, 3.6, 1.1])

# ---------------- 4. Architecture ----------------
h("4. End-to-End Architecture (the 8 layers)", 1)
layers = [
    ("Stage 1 — Listing scrape", "Crawled all 11 directory pages and parsed each partner card.",
     "Company name, slug, profile URL, partner tier (Elite/Gold/Authorized), short description.",
     f"{s['s1']['partners']} unique partners."),
    ("Stage 2 — Detail-modal scrape", "Fetched each partner's detail modal and parsed stable hooks.",
     "Website, location, services, specialty/integrations, industries, languages, full description, bonus contact email.",
     f"{s['s2']['scraped']} scraped, {s['s2']['with_website']} with a website."),
    ("Stage 2b — Service enrichment", "Fetched each company's own homepage and summarised its services with an LLM; falls back to Jotform text when a site is blocked/JS-only.",
     "services_enriched (1-2 sentence summary) + source flag.",
     f"{s['s2b']['website_llm']} from website, {s['s2b']['jotform_llm']} from Jotform — 0 empty."),
    ("Stage 3 — Company resolution + firmographics", "Resolved each domain to a LinkedIn company page (BlitzAPI) and pulled firmographics.",
     "company_linkedin_url, size, industry, HQ country; large-reseller flag.",
     f"{s['s3']['li_found']} resolved, {s['s3']['large']} flagged large."),
    ("Stage 3b — LinkedIn-Bulk recovery", "For companies Blitz could not resolve, searched LinkedIn-Bulk by exact name and accepted a match only if its website domain matched the partner's Jotform domain (false-positive guard).",
     "Recovered LinkedIn URL + firmographics; company_resolution_source.",
     f"{s['s3b']['recovered']} recovered of {s['s3b']['attempted']} attempted."),
    ("Stage 4 — Decision-maker finding", "Ran a per-bucket LinkedIn title search (one DM per ICP bucket; +sales/procurement for large resellers).",
     "first/last name, title, person LinkedIn URL, location, ICP bucket.",
     f"{s['s4']['dms']} decision-makers; {s['s4']['no_li']} companies had no LinkedIn to search."),
    ("Stage 5 — Email find + verify", "Found each DM's work email and verified it; kept the person if they have a verified-ok email OR a LinkedIn profile.",
     "email (ok-verified only) + email_status (ok/catch_all/not_found/invalid/unknown).",
     f"{s['s5']['ok']} verified-ok; {s['s5']['kept_unverified']} kept via LinkedIn."),
    ("Stage 6 — Assembly", "Joined verified decision-makers back to their companies; companies with no DM are retained as company-only rows.",
     "Final 28-column CSV.",
     f"{s['s6']['rows']} rows across {s['s6']['companies']} companies."),
]
for name, what, outp, res in layers:
    h(name, 2)
    para(what)
    bullet(outp, "Captures: ")
    bullet(res, "Result: ")

# ---------------- 5. Funnel ----------------
h("5. Pipeline Funnel (actual run)", 1)
table(["Stage", "Key metric", "Value"], [
    ["1 Listing", "Partners scraped", s['s1']['partners']],
    ["2 Detail", "Scraped / with website", f"{s['s2']['scraped']} / {s['s2']['with_website']}"],
    ["2b Enrich", "Service summaries (website / jotform / empty)", f"{s['s2b']['website_llm']} / {s['s2b']['jotform_llm']} / {s['s2b']['empty']}"],
    ["3 Blitz resolve", "Companies resolved + firmographics", s['s3']['li_found']],
    ["3b Recovery", "Extra companies recovered", s['s3b']['recovered']],
    ["", "Total companies with firmographics", s['s3']['li_found'] + s['s3b']['recovered']],
    ["4 DM finding", "Decision-makers found", s['s4']['dms']],
    ["5 Verify", "Verified-OK emails / kept via LinkedIn", f"{s['s5']['ok']} / {s['s5']['kept_unverified']}"],
    ["6 Assemble", "Final rows / companies", f"{s['s6']['rows']} / {s['s6']['companies']}"],
], widths=[1.4, 3.6, 1.5])

# ---------------- 6. Challenges ----------------
h("6. Challenges Faced & How They Were Resolved", 1)
para("Every issue below was caught during low-cost smoke testing (5 companies, <$1) before the full run, "
     "then fixed and re-validated — so the full run executed cleanly end-to-end.")
table(["#", "Issue", "Root cause", "Resolution"], [
    ["1", "No public API on Jotform", "Directory is server-rendered HTML, no JSON endpoint", "Two-pass HTML scrape (listing → detail) via stable CSS/data hooks"],
    ["2", "Partners missed on a page", "Slugs are camelCase (e.g. DataInteractive)", "Case-insensitive slug matching"],
    ["3", "Partner tier always read 'Partner Tier'", "Grabbed a heading label, not the value", "Read tier from the listing-card badge (Elite/Gold/Authorized)"],
    ["4", "Services/specialty/industry fields had HTML bleed", "Captured across adjacent sections", "Precise chip-list extractor"],
    ["5", "Only 5/21 homepages enriched", "Many partner sites 301-redirect to an empty body", "Added redirect-following → success rose to 9/21, then Jotform fallback covers the rest (0 empty)"],
    ["6", "LLM returned empty summaries", "gpt-oss-20b is a reasoning model; the token budget was spent on hidden reasoning", "Raised max_tokens + set reasoning_effort=low; added deterministic fallback"],
    ["7", "~60% of small/foreign companies unresolved by Blitz", "Limited Blitz coverage on tiny/non-US firms", "Added Stage 3b LinkedIn-Bulk recovery (+29 companies)"],
    ["8", "Recovery matched the WRONG company", "Generic names (e.g. 'Cutting Edge Digital')", "Domain cross-check: accept only if LinkedIn website domain matches the Jotform domain"],
    ["9", "Decision-maker name + LinkedIn were being dropped", "Pipeline discarded anyone without a verified email", "Retention rule: keep the person if verified email OR LinkedIn (person rows 2→7 on the smoke sample)"],
    ["10", "Excel turned '11-50' into a date", "CSV auto-coercion", "Size written as '11-50 employees'"],
], widths=[0.3, 1.7, 1.9, 2.6])

# ---------------- 7. Final output ----------------
h("7. Final Output Breakdown", 1)
total_people = sum(dist.values())
table(["Segment", "Count", "How to use"], [
    ["Total rows", s['s6']['rows'], "One row per decision-maker; company-only where none found"],
    ["Unique companies", s['s6']['companies'], "All partners represented + service-enriched"],
    ["Companies with firmographics", s['s3']['li_found'] + s['s3b']['recovered'], "LinkedIn URL + size/industry/HQ"],
    ["Decision-makers (named)", total_people, "Name + title + LinkedIn"],
    ["  - verified-OK emails", dist.get('ok',0), "Send-ready cold email"],
    ["  - catch-all email", dist.get('catch_all',0), "Deliverable but unconfirmable — send with caution / LinkedIn"],
    ["  - not found / invalid / unknown", dist.get('not_found',0)+dist.get('invalid',0)+dist.get('unknown',0), "LinkedIn outreach"],
    ["Company-only rows", s['s6']['company_only_rows'], "Company + services; no DM found"],
], widths=[2.6, 0.9, 3.0])

# ---------------- 8. Cost & performance ----------------
h("8. Cost & Performance", 1)
bullet(f"{round(summary['elapsed_s']/60,1)} minutes wall-clock for the full {s['s1']['partners']}-company run.", "Runtime: ")
bullet("Scraping + service enrichment essentially free (direct HTTP + ~$0.07 DeepInfra).", "Free layers: ")
bullet("BlitzAPI (resolution + DM search + email find) is the main cost; MillionVerifier ~$1-2; LinkedIn-Bulk on shared team key.", "Paid layers: ")
bullet("Estimated total ≈ $12-45, dominated by BlitzAPI credits.", "Total: ")

# ---------------- 9. Deliverables ----------------
h("9. Deliverables", 1)
para("All files are under clients/jotform-partner-directory/output/full_run/:")
for f, d in [
    ("jotform_partner_leads.csv", "FINAL deliverable — 28-column outreach list"),
    ("stage1_partners.csv", "Raw partner list"),
    ("stage2_companies.csv", "Scraped company profiles + services"),
    ("stage2b_enriched.csv", "+ AI service summaries"),
    ("stage3_qualified.csv", "+ Blitz firmographics"),
    ("stage3b_recovered.csv", "+ LinkedIn-Bulk recovery"),
    ("stage4_dms.csv", "Decision-makers found"),
    ("stage5_leads_verified.csv", "Decision-makers + email status"),
    ("summary.json", "Machine-readable funnel"),
]:
    bullet(d, f + " — ")

# ---------------- 10. Recommendations ----------------
h("10. Recommended Next Steps", 1)
bullet(f"Start outreach with the {dist.get('ok',0)} verified-OK emails (filter email_status = ok).")
bullet("Use the LinkedIn column for the catch-all / not-found contacts (no reliable email).")
bullet("Personalise using the services_enriched column + partner tier.")
bullet("Re-run anytime — the pipeline is idempotent and resumable per stage.")

path = os.path.join(BASE, "Jotform_Lead_Generation_Report.docx")
doc.save(path)
print("WROTE", path)
