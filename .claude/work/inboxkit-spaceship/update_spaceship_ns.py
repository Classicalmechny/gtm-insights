import json, urllib.request, urllib.error, time, sys

KEY = "gNOLlN0g8C6n5tYJwWvh"
SEC = "nC4aSGAUSP3EnipRkXcPSpdZScDw1Zp9WNQxZ3V5O7RrVcuc69kIqJ9RRucfOPqN"

plan = json.load(open("update_plan.json"))
results = []
total = len(plan)
for i, item in enumerate(plan, 1):
    d = item["domain"]
    target = item["target"]
    body = json.dumps({"provider": "custom", "hosts": target}).encode()
    req = urllib.request.Request(
        f"https://spaceship.dev/api/v1/domains/{d}/nameservers",
        data=body, method="PUT",
        headers={
            "X-Api-Key": KEY,
            "X-Api-Secret": SEC,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/8.7.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.status
            resp = r.read().decode()
    except urllib.error.HTTPError as e:
        code = e.code
        resp = e.read().decode()
    except Exception as e:
        code = -1
        resp = str(e)
    ok = code in (200, 204)
    status = "OK" if ok else resp[:200]
    print(f"[{i:2d}/{total}] {d:<28} -> {code} {status}")
    results.append({"domain": d, "code": code, "ok": ok, "response": resp, "target": target})
    sys.stdout.flush()
    time.sleep(0.2)

json.dump(results, open("spaceship_update_results.json", "w"), indent=2)
ok_count = sum(1 for r in results if r["ok"])
fail = [r for r in results if not r["ok"]]
print(f"\nOK: {ok_count}/{len(results)}")
print(f"Failed: {len(fail)}")
for f in fail[:10]:
    print(" ", f["domain"], f["code"], f["response"][:200])