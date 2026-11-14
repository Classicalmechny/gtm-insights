#!/usr/bin/env python3
"""Thin Zapmail API wrapper.

Auth: x-auth-zapmail header (get from Dashboard -> Settings -> Integrations -> API).
Set env var ZAPMAIL_API_KEY before importing.

Rate limits (per Zapmail docs):
  - 5 req/sec, 20 req/min general
  - 10 req per 30min for domain search
  - 3 reexports per mailbox per week
"""
import json
import os
import subprocess
import time
from typing import Any, Optional

BASE = "https://api.zapmail.ai/api"


class ZapmailClient:
    def __init__(self, api_key: Optional[str] = None, workspace_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ZAPMAIL_API_KEY")
        if not self.api_key:
            raise RuntimeError("set ZAPMAIL_API_KEY env var or pass api_key=")
        self.workspace_key = workspace_key
        self._last_call = 0.0

    def _throttle(self):
        delta = time.time() - self._last_call
        if delta < 0.25:
            time.sleep(0.25 - delta)
        self._last_call = time.time()

    def call(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        self._throttle()
        url = f"{BASE}{path}"
        args = [
            "curl", "-sS", "-X", method, url,
            "-H", f"x-auth-zapmail: {self.api_key}",
            "-H", "Content-Type: application/json",
        ]
        if self.workspace_key:
            args += ["-H", f"x-workspace-key: {self.workspace_key}"]
        if body is not None:
            args += ["-d", json.dumps(body)]
        raw = subprocess.check_output(args, timeout=60)
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw.decode("utf-8", errors="replace")}

    # --- Sanity check ---
    def whoami(self):
        # Try a few common endpoints to verify auth
        for path in ("/v2/workspaces", "/v2/user", "/v2/me", "/v2/domains?limit=1"):
            r = self.call("GET", path)
            print(f"GET {path} -> {json.dumps(r, indent=2)[:400]}")
            print("---")
