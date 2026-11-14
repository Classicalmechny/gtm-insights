#!/usr/bin/env python3
"""Add emails to blitz_ny_local_300.csv.

Stage A: scrape each company website for published emails (info@ etc).
Stage B: BlitzAPI employee-finder -> best decision maker -> find work email.
Stage C: verify every candidate via MillionVerifier.
Stage D: merge -> blitz_ny_local_300_with_emails.csv

Checkpointed per stage (stage_*.json) — safe to re-run.
"""
import csv, html, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
IN_CSV = os.path.join(HERE, "blitz_ny_local_300.csv")
OUT_CSV = os.path.join(HERE, "blitz_ny_local_300_with_emails.csv")

def _env_key(prefix):
    with open(os.path.join(HERE, "..", "..", ".env"), encoding="utf-8") as f:
        for line in f:
            if line.lower().startswith(prefix.lower()):
                return line.split(":", 1)[1].strip()
    raise SystemExit(f"key not found in .env: {prefix}")

BLITZ_KEY = _env_key("blitzapi key")
MV_KEY = _env_key("millionverifier api")
BLITZ = "https://api.blitz-api.ai"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# obfuscated: info [at] domain [dot] com
OBF_RE = re.compile(
    r"([a-zA-Z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\s@\s)\s*([a-zA-Z0-9.-]+)\s*(?:\[dot\]|\(dot\))\s*([a-zA-Z]{2,})",
    re.I)
JUNK_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "sentry.wixpress.com",
                "domain.com", "email.com", "yourdomain.com", "godaddy.com",
                "squarespace.com", "yoursite.com", "company.com", "mysite.com")
JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TITLE_RANK = ["owner", "founder", "co-founder", "ceo", "president", "principal",
              "partner", "managing", "director", "manager"]

ckpt_lock = Lock()

def load_ckpt(name):
    p = os.path.join(HERE, f"stage_{name}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_ckpt(name, data):
    p = os.path.join(HERE, f"stage_{name}.json")
    with ckpt_lock:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)

def clean_emails(text, prefer_domain=None):
    found = set(m.group(0) for m in EMAIL_RE.finditer(text))
    for m in OBF_RE.finditer(text):
        found.add(f"{m.group(1)}@{m.group(2)}.{m.group(3)}")
    out = []
    for e in found:
        e = e.strip().strip(".").lower()
        if any(e.endswith(x) for x in JUNK_EXT):
            continue
        dom = e.split("@", 1)[1]
        if dom in JUNK_DOMAINS or "sentry" in dom or "wix" in dom:
            continue
        if re.match(r"^[0-9a-f]{16,}@", e):  # hashed/tracking addresses
            continue
        out.append(e)
    # prefer same-domain, then common providers, then rest
    def rank(e):
        dom = e.split("@", 1)[1]
        local = e.split("@", 1)[0]
        r = 2
        if prefer_domain and dom == prefer_domain:
            r = 0
        elif dom in ("gmail.com", "yahoo.com", "aol.com", "outlook.com", "hotmail.com", "icloud.com"):
            r = 1
        bonus = 0 if any(k in local for k in ("info", "contact", "hello", "office", "book", "sales", "hi")) else 0.5
        return (r, bonus, len(e))
    return sorted(set(out), key=rank)

# ---------------- Stage A: website scrape ----------------

def fetch(url, timeout=15):
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        if r.status_code < 400 and "text" in r.headers.get("Content-Type", "text"):
            return r.text or ""
    except Exception:
        pass
    return ""

def scrape_domain(domain):
    pages = []
    base = None
    for scheme in ("https://", "http://"):
        h = fetch(scheme + domain)
        if h:
            base = scheme + domain
            pages.append(h)
            break
    if base:
        # find contact-ish links on homepage, plus standard paths
        paths = {"/contact", "/contact-us", "/contactus", "/about", "/about-us"}
        for m in re.finditer(r'href=["\']([^"\']+)["\']', pages[0], re.I):
            href = m.group(1)
            if re.search(r"contact|about|reservation|book", href, re.I) and len(href) < 120:
                if href.startswith("/"):
                    paths.add(href)
                elif domain in href:
                    paths.add("/" + href.split(domain, 1)[1].lstrip("/"))
        for p in list(paths)[:6]:
            h = fetch(base + p)
            if h:
                pages.append(h)
    text = html.unescape(" ".join(pages))
    # also catch mailto: with url-encoding
    text = text.replace("%40", "@")
    return clean_emails(text, prefer_domain=domain)

def stage_a(rows):
    ck = load_ckpt("website")
    todo = [r for r in rows if r["domain"] and r["domain"] not in ck]
    print(f"[A] scraping {len(todo)} domains ({len(ck)} cached)")
    done = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(scrape_domain, r["domain"]): r["domain"] for r in todo}
        for fut in as_completed(futs):
            dom = futs[fut]
            try:
                ck[dom] = fut.result()
            except Exception as e:
                ck[dom] = []
            done += 1
            if done % 25 == 0:
                save_ckpt("website", ck)
                print(f"[A] {done}/{len(todo)}")
    save_ckpt("website", ck)
    hits = sum(1 for v in ck.values() if v)
    print(f"[A] done — {hits}/{len(ck)} domains yielded emails")
    return ck

# ---------------- Stage B: BlitzAPI decision makers ----------------

def blitz_post(path, payload, timeout=90):
    for attempt in range(4):
        try:
            r = requests.post(BLITZ + path, json=payload,
                              headers={"x-api-key": BLITZ_KEY}, timeout=timeout)
        except Exception:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 400:
            return {"_error": f"{r.status_code}: {r.text[:200]}"}
        try:
            return r.json()
        except Exception:
            return {"_error": "bad json"}
    return {"_error": "retries exhausted"}

def title_of(person):
    exps = person.get("experiences") or []
    for e in exps:
        if e.get("is_current") or not e.get("end_date"):
            t = e.get("title") or e.get("position") or ""
            if t:
                return t
    return person.get("headline") or ""

def pick_person(results):
    def rank(p):
        t = (title_of(p) or "").lower()
        for i, kw in enumerate(TITLE_RANK):
            if kw in t:
                return i
        return len(TITLE_RANK)
    ranked = sorted(results, key=rank)
    return ranked[0] if ranked else None

def dm_for_company(li_url):
    body = blitz_post("/v2/search/employee-finder",
                      {"company_linkedin_url": li_url, "country_code": ["US"],
                       "max_results": 5, "page": 1})
    results = body.get("results") or []
    if not results:
        return {"error": body.get("_error", "no results")}
    p = pick_person(results)
    person = {
        "first_name": p.get("first_name") or "",
        "last_name": p.get("last_name") or "",
        "title": title_of(p),
        "linkedin_url": p.get("linkedin_url") or "",
    }
    if person["linkedin_url"]:
        eb = blitz_post("/v2/enrichment/email", {"person_linkedin_url": person["linkedin_url"]})
        person["email"] = (eb.get("email") or "").lower() if eb.get("found") else ""
    else:
        person["email"] = ""
    return person

def stage_b(rows):
    ck = load_ckpt("blitz_dm")
    todo = [r for r in rows if r["linkedin_url"] and r["linkedin_url"] not in ck]
    print(f"[B] finding DMs for {len(todo)} companies ({len(ck)} cached)")
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:  # 5 RPS account cap, 2 calls/company
        futs = {ex.submit(dm_for_company, r["linkedin_url"]): r["linkedin_url"] for r in todo}
        for fut in as_completed(futs):
            li = futs[fut]
            try:
                ck[li] = fut.result()
            except Exception as e:
                ck[li] = {"error": str(e)[:200]}
            done += 1
            if done % 20 == 0:
                save_ckpt("blitz_dm", ck)
                print(f"[B] {done}/{len(todo)}")
    save_ckpt("blitz_dm", ck)
    hits = sum(1 for v in ck.values() if v.get("email"))
    print(f"[B] done — {hits}/{len(ck)} companies yielded a DM email")
    return ck

# ---------------- Stage C: MillionVerifier ----------------

def mv_verify(email):
    for attempt in range(3):
        try:
            r = requests.get("https://api.millionverifier.com/api/v3/",
                             params={"api": MV_KEY, "email": email, "timeout": 20},
                             timeout=35)
            j = r.json()
            res = j.get("result") or j.get("quality") or "unknown"
            if res == "error":
                time.sleep(2)
                continue
            return res
        except Exception:
            time.sleep(2)
    return "unknown"

def stage_c(candidates):
    ck = load_ckpt("verify")
    todo = sorted(set(candidates) - set(ck))
    print(f"[C] verifying {len(todo)} emails ({len(ck)} cached)")
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(mv_verify, e): e for e in todo}
        for fut in as_completed(futs):
            e = futs[fut]
            ck[e] = fut.result()
            done += 1
            if done % 25 == 0:
                save_ckpt("verify", ck)
                print(f"[C] {done}/{len(todo)}")
    save_ckpt("verify", ck)
    return ck

# ---------------- Stage D: merge ----------------

STATUS_RANK = {"ok": 0, "catch_all": 1, "unknown": 2}

def best_email(options, verdicts):
    """options: list of (email, source, contact) — pick verified-ok first, personal over generic."""
    scored = []
    for email, source, contact in options:
        v = verdicts.get(email, "unknown")
        if v in ("invalid", "disposable"):
            continue
        src_rank = 0 if source == "blitz_dm" else 1
        scored.append((STATUS_RANK.get(v, 2), src_rank, email, source, v, contact))
    if not scored:
        return None
    scored.sort()
    _, _, email, source, v, contact = scored[0]
    return email, source, v, contact

def main():
    with open(IN_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    web = stage_a(rows)
    dm = stage_b(rows)

    candidates = set()
    for r in rows:
        for e in (web.get(r["domain"]) or [])[:2]:
            candidates.add(e)
        p = dm.get(r["linkedin_url"]) or {}
        if p.get("email"):
            candidates.add(p["email"])
    verdicts = stage_c(candidates)

    out_fields = list(rows[0].keys()) + [
        "email", "email_status", "email_source",
        "contact_first_name", "contact_last_name", "contact_title", "contact_linkedin_url",
    ]
    n_email = n_ok = 0
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            options = []
            p = dm.get(r["linkedin_url"]) or {}
            if p.get("email"):
                options.append((p["email"], "blitz_dm", p))
            for e in (web.get(r["domain"]) or [])[:2]:
                options.append((e, "website", None))
            pick = best_email(options, verdicts)
            row = dict(r)
            if pick:
                email, source, v, contact = pick
                row.update({"email": email, "email_status": v, "email_source": source})
                if contact:
                    row.update({
                        "contact_first_name": contact.get("first_name", ""),
                        "contact_last_name": contact.get("last_name", ""),
                        "contact_title": contact.get("title", ""),
                        "contact_linkedin_url": contact.get("linkedin_url", ""),
                    })
                n_email += 1
                if v == "ok":
                    n_ok += 1
            w.writerow(row)
    print(f"[D] done — {n_email}/{len(rows)} rows have an email, {n_ok} verified 'ok'")
    print(f"OUT: {OUT_CSV}")

if __name__ == "__main__":
    main()
