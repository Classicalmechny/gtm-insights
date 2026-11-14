---
name: connect-spaceship-to-inboxkit
description: >
  Connect every domain in a Spaceship account to an InboxKit workspace by
  (1) adding the domain to InboxKit (or reading existing assignment),
  (2) reading the Cloudflare nameserver pair that InboxKit issues per domain,
  (3) writing those nameservers back to Spaceship as a custom nameserver set,
  (4) asking InboxKit to verify nameserver propagation.
  Use whenever the user says "connect spaceship domains to inboxkit", "point my
  spaceship domains at inboxkit", "move NS to inboxkit", or wants every Spaceship
  domain pointing at the InboxKit Cloudflare zone the workspace owns.
triggers:
  - connect spaceship to inboxkit
  - point spaceship domains at inboxkit
  - inboxkit nameservers
  - move nameservers to inboxkit
  - spaceship inboxkit migration
tools:
  - Bash
  - Write
  - WebFetch
---

# Connect Spaceship Domains to InboxKit (Validated)

## Overview
This is a 4-call pipeline. Two APIs, four endpoints, no UI. Validated end-to-end
on 2026-05-12 against a 55-domain Spaceship account and the InboxKit `Ayna (DFY)`
workspace — all 55 Spaceship NS writes returned 200; InboxKit confirmed 22/55
propagated within the first minute (rest async on TLD/resolver TTL).

## Inputs required
- Spaceship `X-Api-Key` and `X-Api-Secret` (account-scoped)
- InboxKit API key (JWT, sent as `Authorization: Bearer ...`)
- Name of the destination InboxKit workspace (e.g. `Ayna (DFY)`)

## Critical gotchas (read first)
1. **Cloudflare WAF blocks default Python UA on Spaceship.** `urllib`'s
   `Python-urllib/3.x` UA triggers Error 1010. Set `User-Agent: curl/8.7.1`
   (any normal UA works). `curl` works out of the box; Python does not.
2. **InboxKit workspace can already contain the domain.** `POST
   /v1/api/domains/nameservers` returns `409 "Domain(s) already connected to
   your workspace"` and includes the existing NS pair in `result[].nameservers`.
   Treat 409 as success — read the NS pair from the response.
3. **`list-domains` shows the source of truth.** If the workspace lists
   `total > 0` with NS pairs already assigned, you do not need to call the
   create endpoint; just read NS from the list response.
4. **Propagation is async.** Spaceship returns 200 on the NS write but the TLD
   registry push + resolver TTLs take minutes to hours. `.com` typically
   converges in <5 min, `.info` often 30+ min. Check propagation in batches;
   do not block on it.
5. **The InboxKit base path is `/v1/api/...`** (note: there is both `/v1/` and
   `/v1/api/`). All domain endpoints live under `/v1/api/`.

## Endpoints (validated 2026-05-12)

### Spaceship
- `GET https://spaceship.dev/api/v1/domains?take=100&skip=0&orderBy=name`
  Headers: `X-Api-Key`, `X-Api-Secret`.
  Returns `{ items: [{ name, nameservers:{provider, hosts:[...]}, ... }], total }`.
- `PUT https://spaceship.dev/api/v1/domains/{domain}/nameservers`
  Headers: `X-Api-Key`, `X-Api-Secret`, `Content-Type: application/json`,
  **`User-Agent: curl/8.7.1`** (mandatory if calling from Python).
  Body: `{"provider":"custom","hosts":["ns1.cloudflare.com","ns2.cloudflare.com"]}`
  Returns 200 with the updated NS record. Idempotent.

### InboxKit (base `https://api.inboxkit.com`)
- `GET /v1/api/workspaces/list`
  Headers: `Authorization: Bearer <jwt>`.
  Returns `{ workspaces: [{ uid, name, domains, ... }] }`. Use `uid` as
  `X-Workspace-Id` for every other call.
- `POST /v1/api/domains/list`
  Headers: `Authorization`, `X-Workspace-Id`, `Content-Type: application/json`.
  Body: `{"page":1,"limit":200}`. Returns `{ domains: [{ name, nameservers, status,
  nameserver_match_status }], total }`. **The NS pair InboxKit expects on Spaceship
  is the `nameservers` field on each item.**
- `POST /v1/api/domains/nameservers`
  Headers: `Authorization`, `X-Workspace-Id`.
  Body: `{"domains":["example.com"], "mask_forwarding": false}`.
  201: `{ result:[{ domain, nameservers:[ns1,ns2], uid }] }`.
  409: same shape — the workspace already has it; read NS from `result[].nameservers`.
- `POST /v1/api/domains/nameservers/check-propagation`
  Body: `{"domains":["example.com", ...]}`.
  Returns `{ result:[{ name, status, propagated:boolean }] }`. `status: active`
  + `propagated: true` is the green state.

## Step-by-Step Process

1. **Pick workspace.** `GET /v1/api/workspaces/list`, match by name (e.g.
   `Ayna (DFY)`). Store `uid` as `WS`.
2. **Inventory Spaceship.** `GET /v1/domains?take=100&skip=0`. Page through if
   `total > 100`. Build `spaceship_map = {name: {provider, hosts}}`.
3. **Inventory InboxKit workspace.** `POST /v1/api/domains/list` with
   `limit: 200` (page through if `total > 200`). Build
   `inboxkit_map = {name: nameservers}`.
4. **Reconcile.** For each Spaceship domain:
   - If in `inboxkit_map` → use that NS pair.
   - Else → `POST /v1/api/domains/nameservers` with `{domains:[name]}`. Read
     NS from `result[0].nameservers`. Treat HTTP 409 as success.
5. **Build update plan.** For each domain, compare current Spaceship hosts
   (sorted) vs InboxKit-issued NS pair (sorted). If equal, skip. If not, queue.
6. **Push to Spaceship.** For each queued domain, `PUT
   /v1/domains/{domain}/nameservers` with `{"provider":"custom","hosts":[ns1,ns2]}`.
   Use `User-Agent: curl/8.7.1`. ~5/sec is safe (Spaceship rate-limits silently
   if you push faster).
7. **Trigger propagation check.** `POST /v1/api/domains/nameservers/check-propagation`
   with all domains at once (batches of ~100 if very large).
8. **Re-check after ~15 min** for stragglers. Status flips from `not_connected`
   → `active` when InboxKit's CF zone sees the NS delegation.

## Templates / Examples

### Set Spaceship NS (Python, with the UA fix)
```python
import urllib.request, json
req = urllib.request.Request(
    f"https://spaceship.dev/api/v1/domains/{domain}/nameservers",
    data=json.dumps({"provider":"custom","hosts":[ns1, ns2]}).encode(),
    method="PUT",
    headers={
        "X-Api-Key": SP_KEY,
        "X-Api-Secret": SP_SECRET,
        "Content-Type": "application/json",
        "User-Agent": "curl/8.7.1",   # <-- mandatory, else CF WAF returns 1010/403
    },
)
urllib.request.urlopen(req, timeout=30).read()
```

### Add domain to InboxKit + read NS
```python
body = json.dumps({"domains":[domain],"mask_forwarding":False}).encode()
req = urllib.request.Request(
    "https://api.inboxkit.com/v1/api/domains/nameservers",
    data=body, method="POST",
    headers={
        "Authorization": f"Bearer {INK_TOKEN}",
        "X-Workspace-Id": WS,
        "Content-Type": "application/json",
    },
)
try:
    resp = json.loads(urllib.request.urlopen(req).read())
except urllib.error.HTTPError as e:
    # 409 == already connected — body still includes result[].nameservers
    resp = json.loads(e.read())
ns_pair = resp["result"][0]["nameservers"]
```

## Edge Cases
- **Spaceship NS already match InboxKit NS.** Skip the PUT — it is a no-op write
  with the same payload, but skipping keeps logs clean and avoids resetting any
  Spaceship-side `updatedAt`.
- **Domain registered at Spaceship but `lifecycleStatus != "registered"`.** Filter
  these out — you cannot change NS on a domain in `pendingTransfer` etc.
- **More than 100 Spaceship domains.** Page using `skip`. `take` max is 100.
- **More than 200 InboxKit domains.** Use `page` parameter on `/v1/api/domains/list`.
- **Workspace name collides** (multiple workspaces same name in `list-workspaces`).
  Disambiguate by `created_at`, `domains` count, or ask the user.
- **CF Error 1010 / 403 from Spaceship.** Always a UA problem. Send a real UA.
- **CF Error 1015.** You are rate-limited. Slow to <1 req/sec.
- **InboxKit returns NS that look like Cloudflare anycast pairs already on
  the domain.** They are different zones. Compare strings, not provider — the
  pair `a.ns.cloudflare.com / b.ns.cloudflare.com` will differ between zones
  even though both are CF.

## Definition of Done
- For every Spaceship domain, `spaceship.dev/api/v1/domains` returns
  `nameservers.hosts == inboxkit_workspace.nameservers` for that domain.
- `POST /v1/api/domains/nameservers/check-propagation` returns `propagated: true`
  for every domain (allow up to 24h after the Spaceship PUT for slow TLDs).
- The InboxKit workspace shows each domain in `status: active` /
  `nameserver_match_status: matched`.
