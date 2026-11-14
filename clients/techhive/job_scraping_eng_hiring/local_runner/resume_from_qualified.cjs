/* Resume from a cached stage1b_qualified.csv → run Stage 2-5 only.
 * Reuses the expensive Blitz firmographic-filter work; re-runs DM finding at a
 * higher per-company count to add more decision-makers, then uploads by region.
 *   node resume_from_qualified.cjs ../output/<run>/stage1b_qualified.csv [perCompany]
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
function writeCsv(file, rows) {
  if (!rows.length) return 0;
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n'));
  return rows.length;
}

(async () => {
  const K = loadEnv();
  const csv = path.resolve(process.argv[2]);
  const perCompany = Number(process.argv[3] || 3) || 3;
  const qualified = parseCsv(csv);
  const outDir = path.join(path.dirname(csv), '..', 'resume_' + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, ''));
  const log = (s, d) => console.log(\`[\${s}]\`, JSON.stringify(d));
  console.log(\`Resume from \${qualified.length} qualified companies, perCompany=\${perCompany}\`);

  // Pre-create all region campaigns (incl. AU + EMEA) so they exist even empty.
  await S.ensureAllRegionCampaigns(K, log);

  const s2 = await S.stage2Dms(K, qualified, { perCompany }, log);
  writeCsv(path.join(outDir, 'stage2_dms.csv'), s2.dms);
  const s3 = await S.stage3Emails(K, s2.dms, log);
  writeCsv(path.join(outDir, 'stage3_leads_verified.csv'), s3.leads);
  const s4 = S.stage4Personalize(s3.leads, log);
  writeCsv(path.join(outDir, 'stage4_personalized.csv'), s4.leads);
  const s5 = await S.uploadByRegion(K, s4.leads, log);

  const summary = { qualified_in: qualified.length, perCompany, decision_makers: s2.stats.dms, verified_leads: s3.stats.kept, upload: s5 };
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log('\n=== RESUME SUMMARY ===\n' + JSON.stringify(summary, null, 2));
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
