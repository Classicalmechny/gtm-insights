"""
Shared utilities for the build-cold-email-list skill.

Loaded by every script in this folder. Centralises:
  - API key loading (env first, hardcoded fallback)
  - HTTP session with retries
  - Run-directory layout helpers
  - JSON / CSV I/O
  - Domain / LinkedIn / name normalisation
  - run.log writer
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse as _up
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.stderr.write(
        "ERROR: `requests` is required. Install via `pip install requests`.\n"
    )
    raise

# ---------------------------------------------------------------------------
# API keys (env first, hardcoded fallback so the skill is self-contained)
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "BLITZAPI_KEY":   "blitz_mkbWaJvTNLHs525Aegh4W9gt",
    "BETTERCONTACTS": "d1694d3b44010ee6ec43",
    "FIRECRAWL_KEY":  "Fc-485dfe05cfe64a2685123ead2719f604",
    "DEEPINFRA_KEY":  "wOaRky1fcun3LBqaVTzA6zU4IQ6Y7FSF",
    "INSTANTLY_KEY":  "NDViMDQxNmEtZDhiNC00MmY5LWJjOTYtOTlhNzU4YTVmMTBhOk93YW5XVmJFQlJCTw==",
    # OCEAN_KEY intentionally NOT defaulted — must be supplied via env (e.g. `export OCEAN_KEY=...`).
    # The new v3-unlocked token rotates and must not be committed.
}


def get_key(name: str) -> str:
    val = os.environ.get(name)
    if val:
        return val.strip()
    if name in _DEFAULTS:
        return _DEFAULTS[name]
    raise RuntimeError(f"Missing API key: {name}")


# ---------------------------------------------------------------------------
# HTTP session with retry on 429 / 5xx
# ---------------------------------------------------------------------------

def make_session(total_retries: int = 5, backoff: float = 1.0) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# ---------------------------------------------------------------------------
# Run directory layout
# ---------------------------------------------------------------------------

def run_dir(run_id: str) -> Path:
    p = Path("output") / run_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "raw").mkdir(exist_ok=True)
    (p / "checkpoints").mkdir(exist_ok=True)
    return p


def log_event(run_id: str, step: str, **fields: Any) -> None:
    p = run_dir(run_id) / "run.log"
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"ts": ts, "step": step, **fields}
    with p.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# JSON / CSV helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_csv(path: Path, rows: Iterable[Dict[str, Any]], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    n = 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if new_file:
            w.writeheader()
        for row in rows:
            w.writerow(row)
            n += 1
    return n


def read_csv(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Checkpoint helpers (resumable scripts)
# ---------------------------------------------------------------------------

def checkpoint_path(run_id: str, name: str) -> Path:
    return run_dir(run_id) / "checkpoints" / f"{name}.json"


def load_checkpoint(run_id: str, name: str, default: Any = None) -> Any:
    p = checkpoint_path(run_id, name)
    if p.exists():
        try:
            return load_json(p)
        except Exception:
            return default
    return default


def save_checkpoint(run_id: str, name: str, data: Any) -> None:
    write_json(checkpoint_path(run_id, name), data)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_LINKEDIN_TRACK_PARAMS = {"trk", "lipi", "originalSubdomain"}


def normalize_domain(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    if s.startswith("www."):
        s = s[4:]
    s = s.split("/", 1)[0]
    s = s.split("?", 1)[0]
    s = s.rstrip(".")
    return s


def normalize_linkedin(url: Optional[str]) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    parsed = _up.urlparse(url)
    host = parsed.netloc.lower()
    # collapse country subdomains: de.linkedin.com -> linkedin.com
    if host.endswith("linkedin.com"):
        host = "linkedin.com"
    path = parsed.path.rstrip("/")
    # strip tracking params
    q = [
        (k, v) for k, v in _up.parse_qsl(parsed.query)
        if k not in _LINKEDIN_TRACK_PARAMS
    ]
    qs = ("?" + _up.urlencode(q)) if q else ""
    return f"https://{host}{path}{qs}".lower()


def normalize_name(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"[^\w\s'-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.title()


def normalize_email(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.strip().lower()


def slugify(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:max_len].strip("_")


def stable_hash(s: str, length: int = 12) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Country normalisation (small lookup, expand as needed)
# ---------------------------------------------------------------------------

_COUNTRY_FIX = {
    "us": "United States", "usa": "United States", "u.s.": "United States",
    "u.s.a.": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "uae": "United Arab Emirates",
    "ksa": "Saudi Arabia",
    "nl": "Netherlands", "the netherlands": "Netherlands", "holland": "Netherlands",
    "deutschland": "Germany",
    "es": "Spain", "españa": "Spain",
    "fr": "France",
    "ca": "Canada",
    "au": "Australia",
    "nz": "New Zealand",
    "in": "India",
    "sg": "Singapore",
    "br": "Brazil", "brasil": "Brazil",
}


def normalize_country(s: Optional[str]) -> str:
    if not s:
        return ""
    key = s.strip().lower()
    return _COUNTRY_FIX.get(key, s.strip().title())


# ---------------------------------------------------------------------------
# CLI arg helper
# ---------------------------------------------------------------------------

def arg(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Tiny CLI parser: --name=value or --name value."""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == f"--{name}" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
    if required:
        raise SystemExit(f"Missing required arg --{name}")
    return default


# ---------------------------------------------------------------------------
# Polling helper
# ---------------------------------------------------------------------------

def poll(fn, interval: float = 30.0, timeout: float = 60 * 60, label: str = "job") -> Any:
    """Call fn() until it returns truthy (the "done" payload). Returns that payload."""
    start = time.time()
    while True:
        result = fn()
        if result:
            return result
        elapsed = time.time() - start
        if elapsed > timeout:
            raise TimeoutError(f"{label} timed out after {elapsed:.0f}s")
        time.sleep(interval)
