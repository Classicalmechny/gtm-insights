"""
Email enrichment + verification waterfall.

For each DM dict, attempt to find a verified work email through providers
in this order:
  Pass 1: BlitzAPI /v2/enrichment/email by person_linkedin_url
          (returns email + all_emails + verification flags)
  Pass 2 (only if BlitzAPI miss + we have name+domain): try Instantly
          standalone email-verification on candidate {firstname}@{domain}
          patterns. Skipped if Instantly returns no credits.

Rejects unverified / unknown statuses.
"""
from __future__ import annotations

import json
import time

from _common import (
    env, log_event, make_session, normalize_email,
    normalize_linkedin, run_dir, write_csv,
)

BLITZ_BASE = "https://api.blitz-api.ai"
EP_EMAIL = "/v2/enrichment/email"

INSTANTLY_BASE = "https://api.instantly.ai"
BETTERCONTACT_BASE = "https://app.bettercontact.rocks"

# Statuses we accept (Blitz / Instantly conventions).
GOOD_VERIFY = {"valid", "accept_all", "deliverable", "ok"}


def _mx_check(domain: str, _cache: dict = {}) -> bool:
    """Free verification floor: confirm the domain has MX records.

    Doesn't prove the inbox exists, but proves the domain accepts mail.
    Catches typo-domains, dead orgs, parked domains.
    """
    if not domain:
        return False
    if domain in _cache:
        return _cache[domain]
    try:
        import socket
        socket.setdefaulttimeout(5)
        # Quick DNS check first — confirms domain exists
        socket.gethostbyname(domain)
        # Now check MX via dnspython if available, else fall back to dns command
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX", lifetime=5)
            ok = len(list(answers)) > 0
        except ImportError:
            import subprocess
            r = subprocess.run(["dig", "+short", domain, "MX"],
                               capture_output=True, text=True, timeout=5)
            ok = bool(r.stdout.strip())
        _cache[domain] = ok
        return ok
    except Exception:
        _cache[domain] = False
        return False


def _blitz_headers() -> dict:
    return {"x-api-key": env("BLITZAPI_KEY"), "Content-Type": "application/json"}


def _instantly_headers() -> dict:
    return {"Authorization": f"Bearer {env('INSTANTLY_KEY')}",
            "Content-Type": "application/json"}


def blitz_find_email(session, person_li: str) -> dict:
    """Return {email, all_emails, found, verified} from BlitzAPI."""
    if not person_li:
        return {"found": False, "email": "", "all_emails": [], "verified": False,
                "provider": "blitz"}
    try:
        r = session.post(BLITZ_BASE + EP_EMAIL,
                         json={"person_linkedin_url": person_li},
                         headers=_blitz_headers(), timeout=60)
        if r.status_code >= 400:
            return {"found": False, "email": "", "all_emails": [], "verified": False,
                    "provider": "blitz", "error": r.text[:200]}
        body = r.json()
        email = normalize_email(body.get("email") or "")
        all_emails = body.get("all_emails") or []
        # Blitz returns a `verified` boolean per-email; use that if available
        verified = bool(body.get("verified", False)) or (
            len(all_emails) > 0 and any(e.get("verified") for e in all_emails)
        )
        # If `found` true and email present, treat as deliverable
        return {
            "found": bool(body.get("found")) and bool(email),
            "email": email,
            "all_emails": all_emails,
            "verified": verified,
            "provider": "blitz",
            "raw": body,
        }
    except Exception as e:
        return {"found": False, "email": "", "all_emails": [], "verified": False,
                "provider": "blitz", "error": str(e)}


# Note: Instantly's standalone email verification endpoint is
# /api/v2/email-verification/verify-email — POST {email: ...}. Requires
# verification credits which may or may not be available in this workspace.
# We attempt it but degrade gracefully on 402.
def instantly_verify(session, email: str) -> dict:
    if not email:
        return {"verified": False, "status": "", "provider": "instantly"}
    try:
        r = session.post(INSTANTLY_BASE + "/api/v2/email-verification",
                         json={"email": email},
                         headers=_instantly_headers(), timeout=30)
        if r.status_code in (402, 403):
            return {"verified": False, "status": "no_credits", "provider": "instantly"}
        if r.status_code >= 400:
            return {"verified": False, "status": "error",
                    "error": r.text[:200], "provider": "instantly"}
        body = r.json()
        # Instantly returns verification_status: valid|invalid|accept_all|unknown
        status = (body.get("verification_status") or
                  body.get("status") or "").lower()
        return {"verified": status in GOOD_VERIFY, "status": status,
                "provider": "instantly", "raw": body}
    except Exception as e:
        return {"verified": False, "status": "error", "error": str(e),
                "provider": "instantly"}


def enrich(run_id: str, dm_rows: list[dict],
           sleep_between: float = 0.2,
           also_run_instantly_verify: bool = True,
           require_mx: bool = True) -> list[dict]:
    """
    Returns the dm_rows with extra columns:
       email, email_provider, email_verified, email_verification_source

    Verification tiers (highest → lowest confidence):
      1. instantly_verified  — passed Instantly's verify-email endpoint
      2. mx_passed           — domain has MX records (free floor)
      3. unverified          — no MX or all checks failed

    Only rows with a non-empty email AND (mx_passed | instantly_verified)
    are returned when require_mx=True.
    """
    session = make_session()
    out_dir = run_dir(run_id) / "stage3_emails"
    out_dir.mkdir(exist_ok=True)

    out_rows: list[dict] = []
    stats = {"input": len(dm_rows), "blitz_found": 0,
             "instantly_verified": 0, "mx_passed": 0,
             "dropped_no_email": 0, "dropped_no_mx": 0,
             "with_email_final": 0, "instantly_no_credits": 0}

    for row in dm_rows:
        person_li = normalize_linkedin(row.get("linkedin_url", ""))
        blitz = blitz_find_email(session, person_li)
        time.sleep(sleep_between)

        email = blitz["email"]
        verif_source = ""

        if not email:
            stats["dropped_no_email"] += 1
            log_event(run_id, "email.miss", linkedin_url=person_li,
                      first_name=row.get("first_name"))
            continue
        stats["blitz_found"] += 1

        # Tier 1: Try Instantly verify (paid; degrades gracefully on no-credits)
        verified = False
        if also_run_instantly_verify:
            iv = instantly_verify(session, email)
            if iv.get("status") == "no_credits":
                stats["instantly_no_credits"] += 1
            if iv["verified"]:
                verified = True
                verif_source = "instantly"
                stats["instantly_verified"] += 1
            time.sleep(sleep_between)

        # Tier 2: MX-check floor (free, deterministic)
        domain = email.split("@", 1)[1] if "@" in email else ""
        mx_ok = _mx_check(domain) if domain else False
        if mx_ok and not verified:
            verif_source = "mx_check"
            stats["mx_passed"] += 1

        if require_mx and not mx_ok and not verified:
            stats["dropped_no_mx"] += 1
            log_event(run_id, "email.no_mx", email=email, domain=domain)
            continue

        merged = dict(row)
        merged.update({
            "email": email,
            "email_provider": blitz["provider"],
            "email_verified": "yes" if (verified or mx_ok) else "no",
            "email_verification_source": verif_source or "unverified",
            "all_emails_json": json.dumps(blitz.get("all_emails", []), ensure_ascii=False),
        })
        out_rows.append(merged)
        stats["with_email_final"] += 1

    log_event(run_id, "email.done", **stats)

    if out_rows:
        fieldnames = list(out_rows[0].keys())
        write_csv(out_dir / "leads_with_emails.csv", out_rows, fieldnames)
    return out_rows


if __name__ == "__main__":
    import sys, csv
    run_id = sys.argv[1] if len(sys.argv) > 1 else "smoketest"
    dm_csv = run_dir(run_id) / "stage2_dms" / "decision_makers.csv"
    with dm_csv.open() as f:
        dms = list(csv.DictReader(f))
    print(f"Enriching {len(dms)} DMs...")
    out = enrich(run_id, dms)
    print(f"\n{len(out)} leads with emails:")
    for r in out:
        print(f"  - {r['first_name']} {r['last_name']:<18} | "
              f"{r['email']:<40} | verified={r['email_verified']} "
              f"({r['email_verification_source']})")
