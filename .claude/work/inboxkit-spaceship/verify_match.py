import json

sp = json.load(open("spaceship_p1_after.json"))
ink = json.load(open("inboxkit_ayna_all.json"))
ink_map = {x["name"]: sorted(x.get("nameservers", [])) for x in ink["domains"]}

mismatch = []
items = sp["items"]
for it in items:
    sp_ns = sorted(it.get("nameservers", {}).get("hosts", []))
    tgt = ink_map.get(it["name"], [])
    prov = it.get("nameservers", {}).get("provider")
    if sp_ns != tgt:
        mismatch.append((it["name"], prov, sp_ns, tgt))

print(f"Total Spaceship domains: {len(items)}")
print(f"Mismatched after update: {len(mismatch)}")
for m in mismatch:
    print(" MISMATCH", m)
if not mismatch:
    print("ALL MATCH")