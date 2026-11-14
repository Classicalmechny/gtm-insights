/* Upload an existing stage4 CSV to Instantly (ensureCampaign + stage5Upload).
 * Avoids re-spending Blitz credits when only Stage 5 needs a retry.
 *   node upload_only.cjs ../output/<run>/stage4_personalized.csv [--no-upload-check]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const S = require('./stages.cjs');

function loadEnv() {
  const p = path.join(__dirname, '..', '.env'); const K = {};
  for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const t = line.trim(); if (!t || t.startsWith('#') || !t.includes('=')) continue;
    const i = t.indexOf('='); K[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return K;
}
function parseCsv(file) {
  const text = fs.readFileSync(file, 'utf8');
  const rows = []; let i = 0, field = '', row = [], inQ = false;
  const pushF = () => { row.push(field); field = ''; };
  const pushR = () => { rows.push(row); row = []; };
  while (i < text.length) {
    const ch = text[i];
    if (inQ) { if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i += 2; continue; } inQ = false; i++; continue; } field += ch; i++; continue; }
    if (ch === '"') { inQ = true; i++; continue; }
    if (ch === ',') { pushF(); i++; continue; }
    if (ch === '\r') { i++; continue; }
    if (ch === '\n') { pushF(); pushR(); i++; continue; }
    field += ch; i++;
  }
  if (field.length || row.length) { pushF(); pushR(); }
  const header = rows.shift();
  return rows.filter((r) => r.length > 1).map((r) => Object.fromEntries(header.map((h, idx) => [h, r[idx]])));
}

(async () => {
  const K = loadEnv();
  const csv = process.argv[2];
  const leads = parseCsv(path.resolve(csv));
  // coerce numeric-ish fields
  for (const l of leads) l.job_count = Number(l.job_count || 1) || 1;
  const log = (s, d) => console.log(`[${s}]`, JSON.stringify(d));
  console.log(`Uploading ${leads.length} leads from ${csv} (routed by region)`);
  const result = await S.uploadByRegion(K, leads, log);
  console.log('\nRESULT', JSON.stringify(result, null, 2));
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
