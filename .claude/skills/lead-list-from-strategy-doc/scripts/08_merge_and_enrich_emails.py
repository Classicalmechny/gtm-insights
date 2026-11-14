#!/usr/bin/env python3
"""
Stage 5 — Merge all sources + Email enrichment waterfall.

Inputs:
  raw/storeleads_verified.csv  — 1287 verified niche brands (no people)
  raw/decision_makers.csv      — 362 people from BlitzAPI (no email)
  raw/instantly.csv            — 223 leads with verified email + brand domain

Steps:
  1. Verify each Instantly lead's company via /collections.json (Stage 2 logic).
     Only keep leads whose company is Shopify + matches a niche.
  2. Build merged people.csv (Storeleads DMs + Instantly leads), each joined
     with brand context (niche, drop cadence, multi-brand flag, etc.)
  3. Email enrichment for Storeleads DMs (no email yet):
     a. BlitzAPI find-work-email
     b. Instantly verify (bulk)
  4. Output: verified.csv with email-valid people + brand context.
"""
import csv, json, os, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import random

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
VERIFIED = RD / "raw" / "storeleads_verified.csv"
DMS = RD / "raw" / "decision_makers.csv"
INSTANTLY = RD / "raw" / "instantly.csv"
PEOPLE_OUT = RD / "people_merged.csv"
EMAILS_PRE = RD / "people_with_blitz_emails.csv"
FINAL = RD / "verified.csv"

BLITZ_KEY = "REDACTED_BLITZAPI_KEY"
INSTANTLY_KEY = "REDACTED_INSTANTLY_KEY"
BLITZ_H = {"x-api-key": BLITZ_KEY, "Authorization": f"Bearer {BLITZ_KEY}", "Content-Type": "application/json"}
INST_H = {"Authorization": f"Bearer {INSTANTLY_KEY}", "Content-Type": "application/json"}

# Reuse niche classification from Stage 2
import importlib.util
spec = importlib.util.spec_from_file_location("stage2", "scripts/03_collections_enrich.py")
stage2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage2)


def load_csv(p):
    if not p.exists(): return []
    return list(csv.DictReader(p.open(encoding="utf-8")))


def normalize_domain(s):
    if not s: return ""
    s = s.strip().lower()
    if "://" in s: s = s.split("://", 1)[1]
    if s.startswith("www."): s = s[4:]
    return s.split("/", 1)[0].split("?", 1)[0].rstrip(".")


def verify_instantly_companies(instantly_leads, storeleads_index):
    """For each unique domain in Instantly leads NOT already in Storeleads, hit /collections.json."""
    needs_verify = {}
    for l in instantly_leads:
        d = normalize_domain(l["company_domain"])
        if not d or d in storeleads_index:
            continue
        needs_verify[d] = l.get("company_name", "")

    print(f"Verifying {len(needs_verify)} new Instantly companies via /collections.json…")
    verified_extra = {}
    def worker(d):
        cols = stage2.fetch_collections(d)
        cls = stage2.classify(cols, fallback_text="", merchant_name=needs_verify[d], domain=d)
        return d, cls

    with ThreadPoolExecutor(max_workers=10) as ex:
        for fut in as_completed([ex.submit(worker, d) for d in needs_verify]):
            d, cls = fut.result()
            if cls["source_of_truth"] == "collections.json" and cls.get("niches") and cls.get("is_apparel"):
                verified_extra[d] = cls
    print(f"  → {len(verified_extra)} Instantly companies passed Stage 2 verification")
    return verified_extra


def main():
    storeleads = load_csv(VERIFIED)
    dms = load_csv(DMS)
    instantly = load_csv(INSTANTLY)
    print(f"Loaded: storeleads={len(storeleads)}, dms={len(dms)}, instantly={len(instantly)}")

    # Build storeleads index: domain -> brand row
    sl_idx = {r["company_domain"]: r for r in storeleads}

    # Verify Instantly companies (those not in Storeleads) via Stage 2 logic
    extra = verify_instantly_companies(instantly, sl_idx)

    # Build merged people CSV
    fields = [
        "source","first_name","last_name","full_name","title","linkedin_url",
        "email","email_verification_status",
        "company_name","company_domain","company_linkedin_url","company_website",
        "primary_niche","all_niches","is_multi_brand_retailer",
        "monthly_revenue_usd","plan","products_created_30","products_created_90",
        "high_cadence","most_recent_product_title","most_recent_product_image_url",
        "most_recent_product_url","instagram_url","tiktok_url",
        "city","state","country","email_source",
    ]
    f = PEOPLE_OUT.open("w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()

    n_dms = 0; n_inst = 0
    # Storeleads DMs (need email enrichment)
    for dm in dms:
        d = normalize_domain(dm["sourced_from_domain"] or dm["company_domain"])
        brand = sl_idx.get(d, {})
        row = {
            "source": "storeleads+blitz_dm",
            "first_name": dm["first_name"],
            "last_name": dm["last_name"],
            "full_name": dm["full_name"],
            "title": dm["title"],
            "linkedin_url": dm["linkedin_url"],
            "email": "",
            "email_verification_status": "",
            "company_name": brand.get("company_name") or dm["company_name"],
            "company_domain": d,
            "company_linkedin_url": brand.get("company_linkedin_url") or dm["company_linkedin_url"],
            "company_website": brand.get("company_website",""),
            "primary_niche": brand.get("primary_niche_verified",""),
            "all_niches": brand.get("niches_detected",""),
            "is_multi_brand_retailer": brand.get("is_multi_brand_retailer","no"),
            "monthly_revenue_usd": brand.get("estimated_monthly_sales_usd",""),
            "plan": brand.get("plan",""),
            "products_created_30": brand.get("products_created_30","0"),
            "products_created_90": brand.get("products_created_90","0"),
            "high_cadence": brand.get("high_cadence","no"),
            "most_recent_product_title": brand.get("most_recent_product_title",""),
            "most_recent_product_image_url": brand.get("most_recent_product_image_url",""),
            "most_recent_product_url": brand.get("most_recent_product_url",""),
            "instagram_url": brand.get("instagram_url",""),
            "tiktok_url": brand.get("tiktok_url",""),
            "city": brand.get("city","") or dm["city"],
            "state": brand.get("state","") or dm["state"],
            "country": brand.get("country","") or dm["country"],
            "email_source": "",
        }
        w.writerow(row); n_dms += 1

    # Instantly leads (already have emails)
    for l in instantly:
        d = normalize_domain(l["company_domain"])
        brand = sl_idx.get(d, {})
        extra_cls = extra.get(d) if d not in sl_idx else None
        if d not in sl_idx and not extra_cls:
            continue  # not Shopify or not niche — drop
        primary = brand.get("primary_niche_verified") or (
            stage2.primary_pick(extra_cls["niches"], extra_cls["niche_hit_counts"]) if extra_cls else ""
        )
        all_niches = brand.get("niches_detected") or (
            "|".join(extra_cls["niches"]) if extra_cls else ""
        )
        row = {
            "source": "instantly_supersearch",
            "first_name": l["first_name"],
            "last_name": l["last_name"],
            "full_name": l["full_name"],
            "title": l["title"],
            "linkedin_url": l["linkedin_url"],
            "email": l["email"],
            "email_verification_status": l["email_verification_status"],
            "company_name": brand.get("company_name") or l["company_name"],
            "company_domain": d,
            "company_linkedin_url": brand.get("company_linkedin_url") or l["company_linkedin_url"],
            "company_website": brand.get("company_website",""),
            "primary_niche": primary,
            "all_niches": all_niches,
            "is_multi_brand_retailer": brand.get("is_multi_brand_retailer","no"),
            "monthly_revenue_usd": brand.get("estimated_monthly_sales_usd",""),
            "plan": brand.get("plan",""),
            "products_created_30": brand.get("products_created_30","0"),
            "products_created_90": brand.get("products_created_90","0"),
            "high_cadence": brand.get("high_cadence","no"),
            "most_recent_product_title": brand.get("most_recent_product_title",""),
            "most_recent_product_image_url": brand.get("most_recent_product_image_url",""),
            "most_recent_product_url": brand.get("most_recent_product_url",""),
            "instagram_url": brand.get("instagram_url",""),
            "tiktok_url": brand.get("tiktok_url",""),
            "city": brand.get("city","") or l["city"],
            "state": brand.get("state","") or l["state"],
            "country": brand.get("country","") or l["country"],
            "email_source": "instantly_supersearch_verified",
        }
        w.writerow(row); n_inst += 1
    f.close()
    print(f"Wrote merged: {n_dms} DMs + {n_inst} Instantly leads = {n_dms+n_inst} → {PEOPLE_OUT}")

    # =====================================================
    # Step 3: Email enrichment for DMs without email
    # =====================================================
    print("\nRunning BlitzAPI find-work-email for DMs missing email…")
    people = load_csv(PEOPLE_OUT)
    need_email = [p for p in people if not p["email"]]
    have_email = [p for p in people if p["email"]]
    print(f"  Have email: {len(have_email)}, need email: {len(need_email)}")

    def find_email(p):
        payload = {
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "company_domain": p["company_domain"],
        }
        if p["linkedin_url"]:
            payload["linkedin_url"] = p["linkedin_url"]
        try:
            r = requests.post("https://api.blitz-api.ai/people/find-work-email",
                              json=payload, headers=BLITZ_H, timeout=30)
            if r.status_code == 200:
                body = r.json()
                return body.get("email") or body.get("work_email") or ""
        except Exception:
            return ""
        return ""

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(find_email, p): p for p in need_email}
        n_found = 0
        for i, fut in enumerate(as_completed(futures), 1):
            p = futures[fut]
            email = fut.result()
            if email:
                p["email"] = email.lower()
                p["email_source"] = "blitz_find_work_email"
                n_found += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(need_email)}] emails found so far: {n_found}")
    print(f"  Total Blitz emails found: {n_found}/{len(need_email)}")

    # Write the people with blitz emails (for Pass 3 verification)
    fpath = EMAILS_PRE
    with fpath.open("w", newline="", encoding="utf-8") as f2:
        w2 = csv.DictWriter(f2, fieldnames=fields, extrasaction="ignore")
        w2.writeheader()
        for p in people:
            w2.writerow(p)
    print(f"  Wrote intermediate → {fpath}")

    # =====================================================
    # Step 4: Verify Blitz-found emails via Instantly bulk
    # =====================================================
    # For now, simple verification: query Instantly per-email
    print("\nVerifying Blitz-found emails via Instantly…")
    to_verify = [p for p in people if p["email_source"] == "blitz_find_work_email"]
    def verify_email(p):
        try:
            r = requests.post("https://api.instantly.ai/api/v2/email-verification",
                              json={"email": p["email"]}, headers=INST_H, timeout=20)
            if r.status_code == 200:
                body = r.json()
                return (body.get("verification_status") or body.get("status") or "").lower()
        except Exception:
            return "unverified"
        return "unverified"

    n_verified = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(verify_email, p): p for p in to_verify}
        for i, fut in enumerate(as_completed(futures), 1):
            p = futures[fut]
            p["email_verification_status"] = fut.result()
            if p["email_verification_status"] in ("valid","accept_all"):
                n_verified += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(to_verify)}] valid so far: {n_verified}")
    print(f"  Verified: {n_verified}/{len(to_verify)}")

    # =====================================================
    # Final: drop emails not valid/accept_all
    # =====================================================
    final = [p for p in people if p["email"] and p["email_verification_status"] in ("valid","accept_all")]
    print(f"\nFinal verified people: {len(final)}")

    with FINAL.open("w", newline="", encoding="utf-8") as f3:
        w3 = csv.DictWriter(f3, fieldnames=fields, extrasaction="ignore")
        w3.writeheader()
        for p in final:
            w3.writerow(p)
    print(f"Wrote → {FINAL}")


if __name__ == "__main__":
    main()
