#!/usr/bin/env python3
"""Print BlitzAPI account/key status (credits, plan, limits)."""
import json, os
import requests

env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
key = os.environ.get("BLITZAPI_KEY", "")
if not key:
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.lower().startswith("blitzapi key"):
                key = line.split(":", 1)[1].strip()

r = requests.get("https://api.blitz-api.ai/v2/account/key-info",
                 headers={"x-api-key": key}, timeout=30)
print(r.status_code)
print(json.dumps(r.json(), indent=2))
