/* Remove catch-all (accept_all) leads from all QSET + TechHive campaigns.
 * Catch-all leads were tagged payload.email_risk === 'accept_all' at upload.
 *   node remove_catchall.cjs --dry    # count only
 *   node remove_catchall.cjs          # delete them
 */
'use strict';
const fs = require('fs');
const path = require('path');
const DRY = process.argv.includes('--dry');
const BASE = 'https://api.instantly.ai';

function keyFrom(envPath) {
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const t = line.trim(); if (t.startsWith('INSTANTLY_KEY=')) return t.slice('INSTANTLY_KEY='.length).trim();
  }
  throw new Error('no INSTANTLY_KEY in ' + envPath);
}

const WORKSPACES = [
  { name: 'QSET', envPath: path.join(__dirname, '..', '.env'),
    campaigns: ['1417b6e0-f82a-429e-92c7-d0b37c18b424','3d5ec0c1-efb9-4e2e-a132-68c18d9180c9','0f00b9cc-69df-48e3-a823-8639f57e217b','5083f478-3eca-465f-90b9-1c70fd96c5d0','8978f440-5156-493a-a99a-8651f4e29eef'] },
  { name: 'TechHive', envPath: path.join(__dirname, '..', '..', '..', 'techhive', 'job_scraping_eng_hiring', '.env'),
    campaigns: ['12130179-48a5-41cc-a20c-136f14a87dfe','40cb1709-dc25-4f87-b49d-1c050aaf0289','4c3ffdda-c612-409c-a4f4-fa6e3f0ff8a8','6819585d-eeec-4c7f-9586-f81e748daed3','cecf84e1-57dc-426a-a19a-592f2f9cf791'] },
];

async function jpost(H, ep, body) { const r = await fetch(BASE + ep, { method: 'POST', headers: H, body: JSON.stringify(body) }); return { ok: r.ok, status: r.status, json: await r.json().catch(() => null) }; }
async function jdelete(H, ep) { const r = await fetch(BASE + ep, { method: 'DELETE', headers: { Authorization: H.Authorization } }); return { ok: r.ok, status: r.status, text: r.ok ? '' : await r.text().catch(() => '') }; }

function isCatchAll(l) {
  const p = l.payload || {};
  const risk = (p.email_risk || l.email_risk || '').toLowerCase();
  return risk === 'accept_all';
}

(async () => {
  let grandTotal = 0, grandDeleted = 0;
  for (const ws of WORKSPACES) {
    const H = { Authorization: 'Bearer ' + keyFrom(ws.envPath), 'Content-Type': 'application/json' };
    console.log(`\n=== ${ws.name} ===`);
    for (const cid of ws.campaigns) {
      // collect catch-all lead ids (paginate)
      const ids = []; let total = 0, cursor = null;
      for (let i = 0; i < 500; i++) {
        const body = { campaign: cid, limit: 100 }; if (cursor) body.starting_after = cursor;
        const r = await jpost(H, '/api/v2/leads/list', body);
        const items = (r.json && (r.json.items || r.json.data)) || [];
        if (!items.length) break;
        total += items.length;
        for (const l of items) if (isCatchAll(l) && l.id) ids.push(l.id);
        cursor = r.json && (r.json.next_starting_after || r.json.next_cursor);
        if (!cursor || items.length < 100) break;
      }
      let del = 0, fail = 0;
      if (!DRY) {
        for (const id of ids) {
          const d = await jdelete(H, '/api/v2/leads/' + id);
          if (d.ok) del++; else { fail++; if (fail <= 2) console.log('   delete fail', id, d.status, d.text.slice(0, 80)); }
        }
      }
      grandTotal += total; grandDeleted += del;
      console.log(`  ${cid}  total=${total}  catch_all=${ids.length}` + (DRY ? '  (dry)' : `  deleted=${del}  failed=${fail}`));
    }
  }
  console.log(`\n${DRY ? 'WOULD DELETE' : 'DELETED'} catch_all leads. Total leads scanned: ${grandTotal}` + (DRY ? '' : `, deleted: ${grandDeleted}`));
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
