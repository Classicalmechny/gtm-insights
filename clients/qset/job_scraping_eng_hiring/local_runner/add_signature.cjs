/* Append the QSET signature to the end of every sequence step (every variant)
 * of all 5 regional campaigns. Idempotent — skips steps that already have it.
 *   node add_signature.cjs
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

const SIGNATURE = '<div><br></div><div>{{sendingAccountName}} </div><div>Partnerships {{RANDOM | @QSET | - QSET}}</div>';

const CAMPAIGNS = {
  US: '1417b6e0-f82a-429e-92c7-d0b37c18b424',
  CA: '3d5ec0c1-efb9-4e2e-a132-68c18d9180c9',
  UK: '0f00b9cc-69df-48e3-a823-8639f57e217b',
  EMEA: '5083f478-3eca-465f-90b9-1c70fd96c5d0',
  AU: '8978f440-5156-493a-a99a-8651f4e29eef',
};

async function jget(url) { const r = await fetch(url, { headers: H }); return { ok: r.ok, status: r.status, json: await r.json().catch(() => null) }; }
async function jpatch(url, body) { const r = await fetch(url, { method: 'PATCH', headers: H, body: JSON.stringify(body) }); return { ok: r.ok, status: r.status, text: r.ok ? '' : await r.text().catch(() => '') }; }

(async () => {
  for (const [reg, id] of Object.entries(CAMPAIGNS)) {
    const r = await jget(BASE + '/api/v2/campaigns/' + id);
    const seqs = (r.json && r.json.sequences) || [];
    let added = 0, skipped = 0;
    for (const seq of seqs) for (const step of (seq.steps || [])) for (const v of (step.variants || [])) {
      if ((v.body || '').includes('Partnerships {{RANDOM')) { skipped++; continue; }
      v.body = (v.body || '') + SIGNATURE;
      added++;
    }
    const up = await jpatch(BASE + '/api/v2/campaigns/' + id, { sequences: seqs });
    console.log(reg.padEnd(5), up.ok ? `OK (variants signed: ${added}, already-had: ${skipped})` : `FAIL ${up.status} ${(up.text || '').slice(0, 150)}`);
  }
  console.log('\nDONE');
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
