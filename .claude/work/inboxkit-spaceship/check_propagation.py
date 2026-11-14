import json, urllib.request, urllib.error

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY5NmZhZTIyMGIwNTM2NGFmODM1NjRiYyIsInR5cGUiOiJhcGkiLCJyb3RhdGlvbiI6IjI3NGQzZDNhLTc2MzktNGJhYi04YzllLTI2ODBmZDRhNjMyYyIsImlhdCI6MTc2ODkyNjc1NH0.b9P4mw0fz3Qtb0fyCcp0giNijhjP9UruXemyXGGKGMg"
WS = "db7672d4-ddbb-4f36-b92e-2d800ac3fd39"

plan = json.load(open("update_plan.json"))
domains = [p["domain"] for p in plan]

body = json.dumps({"domains": domains}).encode()
req = urllib.request.Request(
    "https://api.inboxkit.com/v1/api/domains/nameservers/check-propagation",
    data=body, method="POST",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "X-Workspace-Id": WS,
        "Content-Type": "application/json",
        "User-Agent": "curl/8.7.1",
    },
)
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
except urllib.error.HTTPError as e:
    print("HTTPError", e.code, e.read().decode())
    raise SystemExit(1)

json.dump(resp, open("propagation_result.json","w"), indent=2)
print("error=", resp.get("error"), "message=", resp.get("message"))
res = resp.get("result", [])
prop_yes = [r for r in res if r.get("propagated")]
prop_no  = [r for r in res if not r.get("propagated")]
print(f"Domains checked: {len(res)}")
print(f"Propagated: {len(prop_yes)}")
print(f"Not yet propagated: {len(prop_no)}")
for r in prop_no[:60]:
    print(" -", r.get("name"), r.get("status"), "propagated=", r.get("propagated"))