/* ============================================================================
 * Phone enrichment — QuickEnrich (all leads, all geos) + BlitzAPI (US backstop).
 * Reads Cidroy_leads_FINAL_12k.csv, adds phone_number + phone_source columns,
 * writes Cidroy_leads_FINAL_12k_with_phone.csv. All rows preserved.
 * Checkpointed + resumable (output/full/phone_results.jsonl).
 *
 *   node phone_enrich.cjs [--probe]     # --probe = pre-flight only (2 calls)
 * ==========================================================================*/
'use strict';
const fs = require('fs');
const path = require('path');
const R = require('./run.cjs');
const { httpJson, pMap } = R;

const CLIENT_DIR = path.join(__dirname, '..');
const INPUT = path.join(CLIENT_DIR, 'Cidroy_leads_FINAL_12k.csv');
const OUTPUT = path.join(CLIENT_DIR, 'Cidroy_leads_FINAL_12k_with_phone.csv');
const CKPT = path.join(CLIENT_DIR, 'output', 'full', 'phone_results.jsonl');
const SUMMARY = path.join(CLIENT_DIR, 'output', 'full', 'phone_summary.json');

// ---- keys (BlitzAPI + QuickEnrich) from repo-root .env -------------------
function loadKeys2() {
  const cands = [path.join(__dirname, '.env'), path.join(process.cwd(), '.env'),
    path.join(__dirname, '..', '.env'), path.join(__dirname, '..', '..', '..', '..', '.env')];
  const p = cands.find((c) => { try { return fs.existsSync(c); } catch (_) { return false; } });
  const K = { BLITZAPI_KEY: '', QUICKENRICH_KEY: '', _env: p || '(none)' };
  if (p) for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const t = line.trim(); if (!t || t.startsWith('#')) continue;
    const i = t.search(/[:=]/); if (i < 0) continue;
    const label = t.slice(0, i).toLowerCase(), val = t.slice(i + 1).trim();
    if (label.includes('quickenrich')) K.QUICKENRICH_KEY = val;
    else if (label.includes('blitz')) K.BLITZAPI_KEY = val;
  }
  return K;
}

// ---- RFC-4180 CSV parse (titles contain commas) --------------------------
function parseCsv(text) {
  const rows = []; let field = '', row = [], inQ = false, i = 0;
  while (i < text.length) {
    const c = text[i];
    if (inQ) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i += 2; continue; } inQ = false; i++; continue; }
      field += c; i++; continue;
    }
    if (c === '"') { inQ = true; i++; continue; }
    if (c === ',') { row.push(field); field = ''; i++; continue; }
    if (c === '\r') { i++; continue; }
    if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
    field += c; i++;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}
function writeCsv(file, header, rows) {
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [header.map(esc).join(',')];
  for (const r of rows) lines.push(header.map((h) => esc(r[h])).join(','));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, lines.join('\n'));
}

const normPhone = (p) => {
  if (!p) return '';
  const d = String(p).replace(/[^\d]/g, '');
  if (!d) return '';
  if (d.length === 10) return '+1' + d;
  if (d.length === 11 && d[0] === '1') return '+' + d;
  return '+' + d;
};
const appendJsonl = (f, o) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.appendFileSync(f, JSON.stringify(o) + '\n'); };
function readJsonl(f) { if (!fs.existsSync(f)) return []; return fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(Boolean); }
const liKey = (s) => (s || '').toString().trim().toLowerCase().replace(/\/+$/, '');

// ---- enrichers -----------------------------------------------------------
async function qeEnrich(K, url) {
  const u = 'https://app.quickenrich.io/api/employees/search?linkedin_url=' + encodeURIComponent(url);
  const r = await httpJson(u, { method: 'GET', headers: { Authorization: 'Bearer ' + K.QUICKENRICH_KEY, Accept: 'application/json' }, timeout: 30000, retries: 3 });
  const data = (r.json || {}).data || {};
  const meta = (r.json || {}).meta || {};
  return { status: r.status, phone: normPhone(data.employee_phone || ''), remaining: meta.remaining_credits };
}
async function blitzPhone(K, url) {
  const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/phone', { method: 'POST', headers: { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' }, body: { person_linkedin_url: url }, timeout: 30000, retries: 3 });
  return { status: r.status, phone: normPhone((r.json || {}).phone || '') };
}

// ---- main ----------------------------------------------------------------
(async () => {
  const K = loadKeys2();
  const probeOnly = process.argv.includes('--probe');
  console.log(`env: ${K._env} | QE key: ${K.QUICKENRICH_KEY ? K.QUICKENRICH_KEY.slice(0, 8) + '…' : 'MISSING'} | Blitz: ${K.BLITZAPI_KEY ? 'set' : 'MISSING'}`);
  if (!K.QUICKENRICH_KEY) { console.error('FATAL: no QuickEnrich key'); process.exit(1); }

  // pre-flight probes on a known US lead
  const probeLi = 'https://www.linkedin.com/in/andrewyng';
  const qp = await qeEnrich(K, probeLi);
  console.log(`PROBE QuickEnrich: HTTP ${qp.status} phone=${qp.phone || '(none)'} remaining_credits=${qp.remaining}`);
  const bp = await blitzPhone(K, probeLi);
  console.log(`PROBE BlitzAPI:    HTTP ${bp.status} phone=${bp.phone || '(none)'}`);
  if (qp.status === 401 || qp.status === 402) { console.error('FATAL: QuickEnrich key/plan not active'); process.exit(1); }
  if (probeOnly) { console.log('probe-only done'); return; }

  // load CSV
  const rows = parseCsv(fs.readFileSync(INPUT, 'utf8'));
  const header = rows[0];
  const liIdx = header.indexOf('linkedin_url'), cIdx = header.indexOf('country');
  const leads = rows.slice(1).filter((r) => r.length >= header.length - 1).map((r) => {
    const o = {}; header.forEach((h, k) => { o[h] = r[k] != null ? r[k] : ''; }); return o;
  });
  console.log(`leads: ${leads.length}`);

  // resume
  const prior = readJsonl(CKPT);
  const qeDone = new Set(), blitzDone = new Set(), best = {};
  for (const e of prior) {
    const lk = liKey(e.li);
    if (e.stage === 'qe') qeDone.add(lk);
    if (e.stage === 'blitz') blitzDone.add(lk);
    if (e.phone && !best[lk]) best[lk] = { phone: e.phone, source: e.stage === 'blitz' ? 'blitz' : 'quickenrich' };
  }

  // STAGE 1 — QuickEnrich on all leads
  const s1 = leads.filter((l) => l.linkedin_url && !qeDone.has(liKey(l.linkedin_url)));
  const st = { qe_calls: 0, qe_found: 0, blitz_calls: 0, blitz_found: 0, remaining: qp.remaining };
  console.log(`STAGE1 QuickEnrich: ${s1.length} to do (${qeDone.size} cached)`);
  await pMap(s1, async (l) => {
    const r = await qeEnrich(K, l.linkedin_url);
    st.qe_calls++; if (r.remaining != null) st.remaining = r.remaining;
    appendJsonl(CKPT, { li: l.linkedin_url, stage: 'qe', phone: r.phone, status: r.status });
    if (r.phone) { st.qe_found++; const lk = liKey(l.linkedin_url); if (!best[lk]) best[lk] = { phone: r.phone, source: 'quickenrich' }; }
  }, 6);
  console.log(`STAGE1 done: ${st.qe_found}/${st.qe_calls} found | credits remaining ~${st.remaining}`);

  // STAGE 2 — BlitzAPI on US leads still missing a phone
  const s2 = leads.filter((l) => l.linkedin_url && !best[liKey(l.linkedin_url)] && (l.country || '').toUpperCase() === 'US' && !blitzDone.has(liKey(l.linkedin_url)));
  console.log(`STAGE2 BlitzAPI (US misses): ${s2.length} to do`);
  await pMap(s2, async (l) => {
    const r = await blitzPhone(K, l.linkedin_url);
    st.blitz_calls++;
    appendJsonl(CKPT, { li: l.linkedin_url, stage: 'blitz', phone: r.phone, status: r.status });
    if (r.phone) { st.blitz_found++; const lk = liKey(l.linkedin_url); if (!best[lk]) best[lk] = { phone: r.phone, source: 'blitz' }; }
  }, 5);
  console.log(`STAGE2 done: ${st.blitz_found}/${st.blitz_calls} found`);

  // EXPORT
  const outHeader = header.concat(['phone_number', 'phone_source']);
  let withPhone = 0, us = 0, ca = 0;
  for (const l of leads) {
    const b = best[liKey(l.linkedin_url)] || { phone: '', source: '' };
    l.phone_number = b.phone; l.phone_source = b.source;
    if (b.phone) { withPhone++; if ((l.country || '').toUpperCase() === 'US') us++; else if ((l.country || '').toUpperCase() === 'CA') ca++; }
  }
  writeCsv(OUTPUT, outHeader, leads);
  const summary = {
    total_leads: leads.length, with_phone: withPhone, fill_rate: +(withPhone / leads.length).toFixed(3),
    phones_us: us, phones_ca: ca,
    qe_found: st.qe_found, blitz_found: st.blitz_found, quickenrich_credits_remaining: st.remaining,
    output_csv: OUTPUT,
  };
  fs.writeFileSync(SUMMARY, JSON.stringify(summary, null, 2));
  console.log('\n=== DONE ===\n' + JSON.stringify(summary, null, 2) + '\nFINAL CSV → ' + OUTPUT);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
