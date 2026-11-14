#!/usr/bin/env python3
"""Step 3: upload Elizabeth's profile photo to all 150 newly-created mailboxes.

Per Zapmail docs (Update Mailbox API), the `profilePicture` field accepts a URL
or a path string. We host the photo once (publicly accessible URL or upload via
form), then PUT in batches against /v2/mailboxes.

Requires:
  - assets/elizabeth.png present on disk
  - ELIZABETH_PHOTO_URL env var pointing to a public URL hosting that photo
    (e.g. a Cloudflare R2 / S3 / Github raw / Imgur link). Zapmail's
    `profilePicture` field is documented as URL-or-path; URL is the safe bet.
"""
import csv
import json
import os
import sys

from zapmail_client import ZapmailClient

DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_URL = os.environ.get("ELIZABETH_PHOTO_URL")
PHOTO_PATH = os.path.join(DIR, "assets", "elizabeth.png")


def list_mailboxes(c: ZapmailClient):
    r = c.call("GET", "/v2/mailboxes?limit=500")
    items = []
    if isinstance(r, dict):
        for k in ("data", "mailboxes", "items", "results"):
            if isinstance(r.get(k), list):
                items = r[k]
                break
    elif isinstance(r, list):
        items = r
    return items


def main():
    if not PHOTO_URL and not os.path.exists(PHOTO_PATH):
        print(f"ERROR: need either ELIZABETH_PHOTO_URL env var OR {PHOTO_PATH} on disk")
        sys.exit(1)
    photo_value = PHOTO_URL or PHOTO_PATH

    with open(os.path.join(DIR, "domains.txt")) as f:
        target_domains = {ln.strip().lower() for ln in f
                          if ln.strip() and not ln.startswith("#")}

    c = ZapmailClient()
    mboxes = list_mailboxes(c)
    target = [m for m in mboxes
              if (m.get("domainName") or "").lower() in target_domains]
    print(f"Total mailboxes in workspace: {len(mboxes)}")
    print(f"Mailboxes matching the 50 new .co domains: {len(target)}")

    BATCH = 25
    results = []
    for i in range(0, len(target), BATCH):
        chunk = target[i:i + BATCH]
        body = {
            "mailboxData": [
                {
                    "mailboxId": m.get("id") or m.get("mailboxId"),
                    "profilePicture": photo_value,
                }
                for m in chunk
            ]
        }
        r = c.call("PUT", "/v2/mailboxes", body)
        ok = bool(r.get("ok") or r.get("success") or r.get("data"))
        print(f"batch {i//BATCH + 1} ({len(chunk)} mailboxes): {'OK' if ok else 'ERR'}")
        results.append({"batch": i // BATCH + 1, "count": len(chunk), "ok": ok, "response": json.dumps(r)[:500]})

    out = os.path.join(DIR, "photo_results.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\nTrace: {out}")


if __name__ == "__main__":
    main()
