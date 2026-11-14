"""
Shared helpers. Each module imports from here.

The same primitive functions exist (renamed) inside the n8n Code nodes
so the workflow stays portable.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.parse as _up
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ------------------------------------------------------------------
# .env loader (no python-dotenv dep)
# ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env_file()


def env(name: str, required: bool = True, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None and required:
        raise RuntimeError(f"Missing env var: {name}")
    return v or ""


# ------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------
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


# ------------------------------------------------------------------
# Run dir + logging
# ------------------------------------------------------------------
def run_dir(run_id: str) -> Path:
    p = ROOT / "output" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_event(run_id: str, step: str, **fields: Any) -> None:
    p = run_dir(run_id) / "run.log"
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"ts": ts, "step": step, **fields}
    with p.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ------------------------------------------------------------------
# JSON / CSV
# ------------------------------------------------------------------
def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------
# Normalization
# ------------------------------------------------------------------
def normalize_domain(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    if s.startswith("www."):
        s = s[4:]
    s = s.split("/", 1)[0].split("?", 1)[0].rstrip(".")
    return s


_LI_TRACK = {"trk", "lipi", "originalSubdomain"}


def normalize_linkedin(url: Optional[str]) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    parsed = _up.urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("linkedin.com"):
        host = "linkedin.com"
    path = parsed.path.rstrip("/")
    q = [(k, v) for k, v in _up.parse_qsl(parsed.query) if k not in _LI_TRACK]
    qs = ("?" + _up.urlencode(q)) if q else ""
    return f"https://{host}{path}{qs}".lower()


def normalize_email(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def slugify(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:max_len].strip("_")


def today_run_id(tag: str = "techhive_camp_c") -> str:
    return _dt.date.today().strftime("%Y-%m-%d") + "_" + tag
