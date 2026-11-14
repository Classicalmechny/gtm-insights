#!/usr/bin/env python3
"""
Stage 2 — Collection-based niche verification.

For each Storeleads brand (matched + unmatched, in-band), fetches
  https://DOMAIN/collections.json?limit=250
which every Shopify store exposes publicly. Classifies niche from
collection titles. Falls back to:
  fallback 1: HTML scrape of /collections page
  fallback 2: BlitzAPI company enrichment (uses Storeleads linkedin_url)
  fallback 3: Instantly Supersearch company enrichment (TODO)

Outputs:
  output/<run_id>/raw/storeleads_verified.csv   — final tagged TAM (passes)
  output/<run_id>/raw/storeleads_dropped.csv    — brands dropped (non-apparel / dead store)
  output/<run_id>/checkpoints/collections_probe.json — resumable

CLI:
  python 03_collections_enrich.py --limit 500          # process first N brands
  python 03_collections_enrich.py                       # process all
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

RUN_ID = "2026-05-21_ayna_niche_fashion"
RD = Path("output") / RUN_ID
RAW = RD / "raw"
CKPT = RD / "checkpoints"
CKPT.mkdir(parents=True, exist_ok=True)
CHECKPOINT_FILE = CKPT / "collections_probe.json"

VERIFIED_OUT = RAW / "storeleads_verified.csv"
DROPPED_OUT = RAW / "storeleads_dropped.csv"

# --- Niche taxonomy (final, applied to collection titles + handles) -----------
NICHE_PATTERNS = {
    "kidswear":     r"(?:^|[^a-z])(kids?|kidz|kids[\s-]?wear|childrens?(wear)?|baby(wear)?|babies|toddler|infant|tween|boys?|girls?|youth|newborn|onesie|romper)\b",
    "innerwear":    r"\b(lingerie|underwear|innerwear|bras|bralette|panty|panties|knicker|brassiere|shapewear|sleepwear|loungewear|pajamas?|nightgown|nightie|nightwear|intimates?|robe|chemise|boy[\s-]?shorts|thong|teddy|babydoll|corset|garter)\b",
    "plus_size":    r"\b(plus[\s-]?size|plus[\s-]?sized|curvy|curve\b|fuller[\s-]?figure|extended[\s-]?siz|14\+|16\+|18\+|xxl|3xl|4xl|5xl)\b",
    "inclusive":    r"\b(size[\s-]?inclusive|all[\s-]?bodies|every[\s-]?body|body[\s-]?positive|body[\s-]?neutral|inclusive[\s-]?sizing|gender[\s-]?neutral|non[\s-]?binary)\b",
    "maternity":    r"\b(maternity|pregnan(t|cy)|nursing|breastfeed(ing)?|bump|postpartum|babywearing|mom[\s-]?to[\s-]?be)\b",
    "modest":       r"\b(modest|hijab|abaya|kaftan|jilbab|burqa|tznius|tzniut|niqab|islamic|muslim|orthodox|christian[\s-]?fashion|sharia|halal[\s-]?fashion)\b",
    "adaptive":     r"\b(adaptive|disabili|wheelchair|sensory|magnetic[\s-]?closure|seated[\s-]?wear|easy[\s-]?dress)\b",
    "athleisure":   r"\b(athleisure|activewear|active[\s-]?wear|yoga[\s-]?wear|workout|gym[\s-]?wear|fitness[\s-]?wear|performance[\s-]?wear|leggings|sports?[\s-]?bra|run(ning)?[\s-]?wear)\b",
}

# Apparel keywords — used to compute apparel-focus score
APPAREL_KEYWORDS = {
    "top", "tops", "shirt", "shirts", "tee", "tees", "blouse", "blouses",
    "tank", "tanks", "sweater", "sweaters", "hoodie", "hoodies", "sweatshirt",
    "jacket", "jackets", "coat", "coats", "outerwear",
    "dress", "dresses", "gown", "gowns", "skirt", "skirts",
    "pant", "pants", "trouser", "trousers", "legging", "leggings", "jean", "jeans",
    "short", "shorts", "jumpsuit", "jumpsuits", "romper", "rompers",
    "bra", "bras", "bralette", "underwear", "panty", "panties", "lingerie",
    "swim", "swimwear", "swimsuit", "bikini", "bikinis", "monokini",
    "loungewear", "sleepwear", "pajama", "pajamas", "robe", "robes",
    "bodysuit", "bodysuits", "playsuit", "onesie", "onesies",
    "athletic", "activewear", "athleisure", "tracksuit",
    "scarf", "scarves", "kaftan", "abaya", "hijab", "dupatta",
    "blazer", "cardigan", "vest", "kimono", "two-piece", "set", "sets",
    "matching set", "knitwear", "denim", "outfit", "outfits",
    "clothing", "apparel", "wear", "wears", "fashion",
}

# External brand names (multi-brand retailer signal — non-exhaustive starter list)
EXTERNAL_BRANDS = {
    # Lingerie multi-brand
    "panache", "fantasie", "parfait", "elomi", "freya", "chantelle",
    "wacoal", "spanx", "calvin klein", "tommy hilfiger",
    # General apparel
    "abercrombie", "aeropostale", "banana republic", "ann taylor", "loft",
    "gap", "old navy", "nike", "adidas", "puma", "under armour",
    "the north face", "patagonia", "columbia",
    "lululemon", "athleta", "fabletics", "free people",
    "anthropologie", "j crew", "j.crew", "madewell", "everlane",
    "ralph lauren", "polo", "hugo boss", "armani", "michael kors",
    "kate spade", "tory burch", "coach", "vera bradley",
    # Kids
    "carters", "carter's", "oshkosh", "gymboree", "hanna andersson",
    "tea collection", "kid", "primary",
    # Surfwear (Sun Diego case)
    "vissla", "vuori", "rhythm", "roark", "billabong", "quiksilver", "rip curl",
    "salty crew", "rvca", "volcom", "hurley",
    # Disney/character merch
    "disney", "marvel", "star wars", "warner bros",
}

# --- HTTP helpers ----------------------------------------------------------
UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
]

def headers():
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "application/json,text/javascript,*/*;q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

def fetch_collections(domain):
    """Try domain, then www.domain. Returns list of collection dicts or None."""
    candidates = [domain]
    if not domain.startswith("www."):
        candidates.append("www." + domain)
    for host in candidates:
        url = f"https://{host}/collections.json?limit=250"
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=20, headers=headers())
                if r.status_code == 200:
                    try:
                        return r.json().get("collections", [])
                    except Exception:
                        break
                if r.status_code in (429, 503, 502, 520, 521, 522, 524):
                    time.sleep((2 ** attempt) + random.random())
                    continue
                break
            except requests.RequestException:
                time.sleep(2 ** attempt)
    return None

# --- BlitzAPI company enrichment fallback ---------------------------------
BLITZ_KEY = os.environ.get("BLITZAPI_KEY", "REDACTED_BLITZAPI_KEY")
def blitz_company_enrich(linkedin_url):
    if not linkedin_url: return None
    try:
        r = requests.post(
            "https://api.blitz-api.ai/v2/enrichment/company",
            json={"company_linkedin_url": linkedin_url},
            headers={
                "x-api-key": BLITZ_KEY,
                "Authorization": f"Bearer {BLITZ_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None

# --- Classification --------------------------------------------------------

ADULT_GENERAL_PATTERNS = [
    r"\b(men|mens|men's|menswear|man|guys)\b",
    r"\b(women|womens|women's|womenswear|woman|ladies|lady|miss|misses)\b",
]
ADULT_GENERAL_RX = [re.compile(p, re.IGNORECASE) for p in ADULT_GENERAL_PATTERNS]

NON_APPAREL_TERMS = {
    "jewelry", "necklace", "necklaces", "bracelet", "bracelets", "ring", "rings",
    "earring", "earrings", "pendant", "pendants", "anklet", "anklets",
    "amber", "gemstone", "diamond", "pearl", "pearls",
    "furniture", "sofa", "chair", "table", "bed", "crib", "nursery decor",
    "rug", "rugs", "pillow", "pillows", "blanket", "blankets", "throw",
    "home decor", "home", "kitchen", "cookware", "candle", "candles",
    "mug", "mugs", "drinkware", "tumbler", "tumblers", "bottle", "bottles",
    "art print", "art prints", "sticker", "stickers", "poster", "posters",
    "stroller", "strollers", "car seat", "car seats", "high chair",
    "goggle", "goggles", "swim mask",
    "supplement", "vitamin", "skincare", "cosmetic", "makeup",
    "food", "snack", "candy",
    "boards", "skateboard", "skateboards", "surfboard", "surfboards",
    "wetsuit", "wetsuits",  # adjacent but not fashion
}


def classify(collections, fallback_text="", merchant_name="", domain=""):
    """
    Intensity-based niche detection.
    A niche is only assigned if either:
      (a) It hits >= max(2, 10% of total collections), OR
      (b) The merchant_name or domain itself matches the niche keyword AND >=1 collection matches
    """
    if collections is None:
        # Fallback text mode (BlitzAPI enrich) — STRICT: require multiple keyword hits
        # AND that the niche keyword appears in the merchant name or domain.
        text = (fallback_text or "").lower()
        name_blob = (merchant_name + " " + domain).lower()
        hits = []
        for k, p in NICHE_PATTERNS.items():
            text_hits = len(re.findall(p, text, re.IGNORECASE))
            name_hit = bool(re.search(p, name_blob, re.IGNORECASE))
            # Require either domain/name match, or 2+ keyword hits in description
            if name_hit or text_hits >= 2:
                hits.append(k)
        return {
            "source_of_truth": "none",
            "niches": hits,
            "primary_niche": hits[0] if hits else "",
            "niche_hit_counts": {k: 0 for k in NICHE_PATTERNS},
            "apparel_score": 0.0,
            "n_apparel": 0,
            "n_non_apparel": 0,
            "is_apparel": False,
            "external_brand_hits": 0,
            "is_multi_brand_retailer": False,
            "n_collections": 0,
            "sample_titles": [],
        }

    titles = [(c.get("title", "") or "").strip() for c in collections]
    handles = [(c.get("handle", "") or "").strip() for c in collections]
    n = len(titles)

    # Per-niche intensity
    niche_hit_counts = {}
    for k, p in NICHE_PATTERNS.items():
        count = 0
        for t, h in zip(titles, handles):
            blob = (t + " " + h).lower()
            if re.search(p, blob, re.IGNORECASE):
                count += 1
        niche_hit_counts[k] = count

    # Adult-general count (Men's / Women's / etc. collections)
    n_adult_general = 0
    for t, h in zip(titles, handles):
        blob = (t + " " + h).lower()
        if any(rx.search(blob) for rx in ADULT_GENERAL_RX):
            n_adult_general += 1

    threshold = max(3, int(round(n * 0.10)))  # >=10% AND >=3 absolute hits

    confirmed = []
    for k, count in niche_hit_counts.items():
        if count < threshold:
            continue
        # Competitive check: niche-specific must outnumber pure adult-general,
        # OR niche keyword appears in the brand's merchant_name/domain.
        name_blob = (merchant_name + " " + domain).lower()
        name_match = bool(re.search(NICHE_PATTERNS[k], name_blob, re.IGNORECASE))
        if count >= n_adult_general or name_match:
            confirmed.append(k)

    # Bonus: if merchant_name or domain strongly matches a niche AND >=2 collection hits
    name_text = (merchant_name + " " + domain).lower()
    for k, pat in NICHE_PATTERNS.items():
        if re.search(pat, name_text, re.IGNORECASE) and niche_hit_counts.get(k, 0) >= 2:
            if k not in confirmed:
                confirmed.append(k)

    # Apparel + non-apparel counting
    n_apparel = 0
    n_non_apparel = 0
    for t in titles:
        tl = t.lower()
        if any(kw in tl for kw in APPAREL_KEYWORDS):
            n_apparel += 1
        if any(kw in tl for kw in NON_APPAREL_TERMS):
            n_non_apparel += 1
    apparel_score = (n_apparel / n) if n else 0.0
    non_apparel_score = (n_non_apparel / n) if n else 0.0

    # External brand match (multi-brand retailer signal)
    external_hits = 0
    for t in titles:
        tl = t.lower().strip()
        for brand in EXTERNAL_BRANDS:
            if brand in tl:
                external_hits += 1
                break

    # Stricter is_apparel: require minimum 4 apparel-keyword collections AND apparel > non-apparel
    is_apparel = (n_apparel >= 4) and (n_apparel > n_non_apparel)

    return {
        "source_of_truth": "collections.json",
        "niches": confirmed,
        "primary_niche": primary_pick(confirmed, niche_hit_counts),
        "niche_hit_counts": niche_hit_counts,
        "n_adult_general": n_adult_general,
        "apparel_score": round(apparel_score, 3),
        "n_apparel": n_apparel,
        "n_non_apparel": n_non_apparel,
        "is_apparel": is_apparel,
        "external_brand_hits": external_hits,
        "is_multi_brand_retailer": external_hits >= 3,
        "n_collections": n,
        "sample_titles": titles[:10],
    }


def primary_pick(confirmed, counts):
    """Choose the niche with the highest collection hit count among confirmed."""
    if not confirmed:
        return ""
    # Use priority as tiebreak when counts equal
    return max(confirmed, key=lambda k: (counts.get(k, 0), -NICHE_PRIORITY.index(k) if k in NICHE_PRIORITY else 0))

# --- Niche priority for choosing primary ----------------------------------
NICHE_PRIORITY = [
    "modest", "adaptive", "maternity", "plus_size", "inclusive",
    "kidswear", "innerwear", "athleisure",
]
def primary(niches):
    for k in NICHE_PRIORITY:
        if k in niches:
            return k
    return niches[0] if niches else ""

# --- Main ------------------------------------------------------------------
INPUT_CSVS = [RAW / "storeleads.csv", RAW / "storeleads_unmatched.csv"]

def load_input():
    rows = []
    for p in INPUT_CSVS:
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    return rows

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except Exception:
            return {"done_domains": []}
    return {"done_domains": []}

def save_checkpoint(state):
    CHECKPOINT_FILE.write_text(json.dumps(state))

def main():
    limit = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--limit" and i + 2 <= len(sys.argv[1:]):
            limit = int(sys.argv[i+2])
        elif a.startswith("--limit="):
            limit = int(a.split("=",1)[1])

    rows = load_input()
    # dedupe by domain, keep first
    seen = set()
    dedup = []
    for r in rows:
        d = r.get("company_domain","")
        if not d or d in seen: continue
        seen.add(d); dedup.append(r)
    rows = dedup
    print(f"Loaded {len(rows):,} unique in-band brands")

    state = load_checkpoint()
    done = set(state.get("done_domains", []))
    queue = [r for r in rows if r["company_domain"] not in done]
    if limit:
        queue = queue[:limit]
    print(f"Queue to process: {len(queue):,} (skipping {len(done):,} already done)")

    fields = list(rows[0].keys()) + [
        "verification_source",
        "niches_detected",
        "primary_niche_verified",
        "niche_intensity_json",
        "apparel_score",
        "n_apparel",
        "n_non_apparel",
        "is_apparel",
        "external_brand_hits",
        "is_multi_brand_retailer",
        "n_collections",
        "sample_collection_titles",
    ]
    # Open output files
    verified_exists = VERIFIED_OUT.exists()
    dropped_exists = DROPPED_OUT.exists()
    fv = VERIFIED_OUT.open("a" if verified_exists else "w", newline="", encoding="utf-8")
    fd = DROPPED_OUT.open("a" if dropped_exists else "w", newline="", encoding="utf-8")
    wv = csv.DictWriter(fv, fieldnames=fields, extrasaction="ignore")
    wd = csv.DictWriter(fd, fieldnames=fields, extrasaction="ignore")
    if not verified_exists: wv.writeheader()
    if not dropped_exists: wd.writeheader()

    stats = {"verified": 0, "dropped_non_apparel": 0, "dropped_no_niche": 0,
             "dropped_empty": 0, "fallback_blitz": 0, "fallback_none": 0,
             "processed": 0}

    def worker(row):
        domain = row["company_domain"]
        merchant_name = row.get("company_name", "")
        # Try /collections.json
        collections = fetch_collections(domain)
        cls = classify(collections, fallback_text="", merchant_name=merchant_name, domain=domain)
        if cls["source_of_truth"] == "none":
            # Fallback to BlitzAPI company enrich
            ln = row.get("company_linkedin_url") or ""
            blitz = blitz_company_enrich(ln) if ln else None
            if blitz and blitz.get("found"):
                c = blitz.get("company", {})
                spec = c.get("specialties")
                if isinstance(spec, list): spec = " ".join(str(x) for x in spec)
                spec = str(spec or "")
                fb_text = " | ".join([
                    str(c.get("name","") or ""),
                    str(c.get("about","") or ""),
                    str(c.get("industry","") or ""),
                    spec,
                ])
                cls = classify(None, fallback_text=fb_text, merchant_name=merchant_name, domain=domain)
                cls["source_of_truth"] = "blitz_enrich"
        return row, cls

    processed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=15) as ex:
        futures = [ex.submit(worker, r) for r in queue]
        for fut in as_completed(futures):
            row, cls = fut.result()
            processed += 1
            stats["processed"] = processed
            out_row = dict(row)
            out_row.update({
                "verification_source": cls.get("source_of_truth",""),
                "niches_detected": "|".join(cls.get("niches", [])),
                "primary_niche_verified": cls.get("primary_niche",""),
                "niche_intensity_json": json.dumps(cls.get("niche_hit_counts", {})),
                "apparel_score": cls.get("apparel_score",""),
                "n_apparel": cls.get("n_apparel", 0),
                "n_non_apparel": cls.get("n_non_apparel", 0),
                "is_apparel": "yes" if cls.get("is_apparel") else "no",
                "external_brand_hits": cls.get("external_brand_hits",0),
                "is_multi_brand_retailer": "yes" if cls.get("is_multi_brand_retailer") else "no",
                "n_collections": cls.get("n_collections",0),
                "sample_collection_titles": " | ".join(cls.get("sample_titles", [])[:10]),
            })
            # Decision
            if cls["source_of_truth"] == "none":
                stats["fallback_none"] += 1
                wd.writerow({**out_row, "verification_source":"none"})
            elif cls.get("source_of_truth") == "blitz_enrich":
                stats["fallback_blitz"] += 1
                if cls.get("niches"):
                    wv.writerow(out_row); stats["verified"] += 1
                else:
                    wd.writerow(out_row); stats["dropped_no_niche"] += 1
            else:
                if not cls.get("niches"):
                    wd.writerow(out_row); stats["dropped_no_niche"] += 1
                elif not cls.get("is_apparel"):
                    wd.writerow(out_row); stats["dropped_non_apparel"] += 1
                elif cls.get("n_collections", 0) <= 1:
                    wd.writerow(out_row); stats["dropped_empty"] += 1
                else:
                    wv.writerow(out_row); stats["verified"] += 1

            done.add(row["company_domain"])
            if processed % 50 == 0:
                save_checkpoint({"done_domains": sorted(done)})
                fv.flush(); fd.flush()
                rate = processed / max(time.time()-t0,1)
                eta = (len(queue)-processed)/rate if rate>0 else 0
                print(f"[{processed:>5}/{len(queue)}] verified={stats['verified']} "
                      f"dropped={stats['dropped_no_niche']+stats['dropped_non_apparel']+stats['dropped_empty']} "
                      f"blitz_fb={stats['fallback_blitz']} no_data={stats['fallback_none']} "
                      f"@ {rate:.1f}/s, eta {eta/60:.1f}m")

    save_checkpoint({"done_domains": sorted(done)})
    fv.close(); fd.close()
    print("\n=== Final stats ===")
    for k, v in stats.items():
        print(f"  {k:25s} {v}")
    print(f"\nVerified -> {VERIFIED_OUT}")
    print(f"Dropped  -> {DROPPED_OUT}")

if __name__ == "__main__":
    main()
