/* Assign the full QSET mailbox pool to all 5 regional campaigns and activate them.
 *   node assign_and_launch.cjs           # assign + activate
 *   node assign_and_launch.cjs --dry     # assign only, do NOT activate
 */
'use strict';
const fs = require('fs');
const path = require('path');

function loadEnv() {
  const p = path.join(__dirname, '..', '.env'); const K = {};
  for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const t = line.trim(); if (!t || t.startsWith('#') || !t.includes('=')) continue;
    const i = t.indexOf('='); K[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return K;
}
const K = loadEnv();
const BASE = 'https://api.instantly.ai';
const H = { Authorization: 'Bearer ' + K.INSTANTLY_KEY, 'Content-Type': 'application/json' };
const DRY = process.argv.includes('--dry');

const CAMPAIGNS = {
  US: '12130179-48a5-41cc-a20c-136f14a87dfe',
  CA: '40cb1709-dc25-4f87-b49d-1c050aaf0289',
  UK: '4c3ffdda-c612-409c-a4f4-fa6e3f0ff8a8',
  EMEA: '6819585d-eeec-4c7f-9586-f81e748daed3',
  AU: 'cecf84e1-57dc-426a-a19a-592f2f9cf791',
};

async function jget(url) { const r = await fetch(url, { headers: H }); return { ok: r.ok, status: r.status, json: await r.json().catch(() => null) }; }
async function jsend(method, url, body) { const r = await fetch(url, { method, headers: H, body: body ? JSON.stringify(body) : undefined }); return { ok: r.ok, status: r.status, json: await r.json().catch(() => null), text: r.ok ? '' : await r.text().catch(() => '') }; }

(async () => {
  // 1. paginate ALL sending accounts
  const emails = []; let cursor = null;
  for (let i = 0; i < 50; i++) {
    const url = BASE + '/api/v2/accounts?limit=100' + (cursor ? '&starting_after=' + encodeURIComponent(cursor) : '');
    const r = await jget(url);
    const items = (r.json && (r.json.items || r.json.data)) || [];
    for (const a of items) { if (a.email && (a.status === 1 || a.status === undefined)) emails.push(a.email.toLowerCase()); }
    cursor = r.json && (r.json.next_starting_after || r.json.next_cursor);
    if (!cursor || items.length < 100) break;
  }
  const pool = [...new Set(emails)];
  console.log('Mailbox pool: ' + pool.length + ' active accounts');

  // 2. assign pool + (optionally) activate each campaign
  const results = {};
  for (const [reg, id] of Object.entries(CAMPAIGNS)) {
    const patch = await jsend('PATCH', BASE + '/api/v2/campaigns/' + id, { email_list: pool });
    let activated = 'skipped(dry)';
    if (!DRY) {
      let act = await jsend('POST', BASE + '/api/v2/campaigns/' + id + '/activate', {});
      if (!act.ok) act = await jsend('PATCH', BASE + '/api/v2/campaigns/' + id, { status: 1 }); // fallback
      activated = act.ok ? 'ACTIVE' : ('FAILED ' + act.status + ' ' + (act.text || '').slice(0, 120));
    }
    results[reg] = { id, assign: patch.ok ? 'ok(' + pool.length + ')' : ('FAIL ' + patch.status + ' ' + (patch.text || '').slice(0, 120)), activate: activated };
    console.log(reg.padEnd(5), JSON.stringify(results[reg]));
  }

  // 3. verify final status
  console.log('\n--- verify ---');
  for (const [reg, id] of Object.entries(CAMPAIGNS)) {
    const r = await jget(BASE + '/api/v2/campaigns/' + id);
    const c = r.json || {};
    console.log(reg.padEnd(5), 'status=' + c.status + ' (1=active)', 'mailboxes=' + ((c.email_list || []).length));
  }
  console.log('\nDONE' + (DRY ? ' (dry — not activated)' : ''));
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
