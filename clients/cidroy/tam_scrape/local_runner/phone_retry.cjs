/* ============================================================================
 * Phone RETRY — for leads still missing a phone, try QuickEnrich's
 * name + company search (company_url + first_name + last_name), which resolves
 * people whose exact LinkedIn URL didn't match. Merges any new phones back into
 * Cidroy_leads_FINAL_12k_with_phone.csv. Checkpointed + resumable.
 *   node phone_retry.cjs
 * ==========================================================================*/
'use strict';
const fs = require('fs');
const path = require('path');
const { httpJson, pMap } = require('./run.cjs');

const CLIENT_DIR = path.join(__dirname, '..');
const CSV = path.join(CLIENT_DIR, 'Cidroy_leads_FINAL_12k_with_phone.csv');
const CKPT = path.join(CLIENT_DIR, 'output', 'full', 'phone_retry.jsonl');
const SUMMARY = path.join(CLIENT_DIR, 'output', 'full', 'phone_retry_summary.json');

function loadKeys2() {
  const cands = [path.join(__dirname, '.env'), path.join(process.cwd(), '.env'), path.join(__dirname, '..', '.env'), path.join(__dirname, '..', '..', '..', '..', '.env')];
  const p = cands.find((c) => { try { return fs.existsSync(c); } catch (_) { return false; } });
  const K = { QUICKENRICH_KEY: '' };
  if (p) for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const t = line.trim(); if (!t || t.startsWith('#')) continue;
    const i = t.search(/[:=]/); if (i < 0) continue;
    if (t.slice(0, i).toLowerCase().includes('quickenrich')) K.QUICKENRICH_KEY = t.slice(i + 1).trim();
  }
  return K;
}
function parseCsv(text) {
  const rows = []; let field = '', row = [], inQ = false, i = 0;
  while (i < text.length) { const c = text[i];
    if (inQ) { if (c === '"') { if (text[i + 1] === '"') { field += '"'; i += 2; continue; } inQ = false; i++; continue; } field += c; i++; continue; }
    if (c === '"') { inQ = true; i++; continue; }
    if (c === ',') { row.push(field); field = ''; i++; continue; }
    if (c === '\r') { i++; continue; }
    if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
    field += c; i++; }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}
function writeCsv(file, header, rows) {
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [header.map(esc).join(',')];
  for (const r of rows) lines.push(header.map((h) => esc(r[h])).join(','));
  fs.writeFileSync(file, lines.join('\n'));
}
const normPhone = (p) => { if (!p) return ''; const d = String(p).replace(/[^\d]/g, ''); if (!d) return ''; if (d.length === 10) return '+1' + d; if (d.length === 11 && d[0] === '1') return '+' + d; return '+' + d; };
const appendJsonl = (f, o) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.appendFileSync(f, JSON.stringify(o) + '\n'); };
const readJsonl = (f) => !fs.existsSync(f) ? [] : fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(Boolean);
const key = (l) => (l.linkedin_url || (l.first_name + '|' + l.last_name + '|' + l.company_domain)).toLowerCase();

async function qeNameCompany(K, l) {
  const co = /^https?:\/\//.test(l.company_domain) ? l.company_domain : 'https://' + l.company_domain;
  const q = 'company_url=' + encodeURIComponent(co) + '&first_name=' + encodeURIComponent(l.first_name) + '&last_name=' + encodeURIComponent(l.last_name);
  const r = await httpJson('https://app.quickenrich.io/api/employees/search?' + q, { method: 'GET', headers: { Authorization: 'Bearer ' + K.QUICKENRICH_KEY, Accept: 'application/json' }, timeout: 30000, retries: 3 });
  const data = (r.json || {}).data || {}, meta = (r.json || {}).meta || {};
  return { status: r.status, phone: normPhone(data.employee_phone || ''), remaining: meta.remaining_credits };
}

(async () => {
  const K = loadKeys2();
  if (!K.QUICKENRICH_KEY) { console.error('no QE key'); process.exit(1); }
  const rows = parseCsv(fs.readFileSync(CSV, 'utf8'));
  const header = rows[0];
  const leads = rows.slice(1).filter((r) => r.length >= header.length - 1).map((r) => { const o = {}; header.forEach((h, k) => { o[h] = r[k] != null ? r[k] : ''; }); return o; });

  const eligible = leads.filter((l) => !(l.phone_number || '').trim() && (l.first_name || '').trim() && (l.last_name || '').trim() && (l.company_domain || '').trim());
  const prior = readJsonl(CKPT);
  const done = new Set(prior.map((e) => e.k));
  const foundMap = {}; for (const e of prior) if (e.phone) foundMap[e.k] = e.phone;
  const todo = eligible.filter((l) => !done.has(key(l)));
  const st = { eligible: eligible.length, todo: todo.length, calls: 0, found: Object.keys(foundMap).length, remaining: null };
  console.log(`retry-eligible: ${eligible.length} | cached: ${eligible.length - todo.length} | to do: ${todo.length}`);

  await pMap(todo, async (l) => {
    const r = await qeNameCompany(K, l);
    st.calls++; if (r.remaining != null) st.remaining = r.remaining;
    appendJsonl(CKPT, { k: key(l), phone: r.phone, status: r.status });
    if (r.phone) { st.found++; foundMap[key(l)] = r.phone; }
    if (st.calls % 300 === 0) console.log(`retry ${st.calls}/${todo.length} | new phones ${st.found}`);
  }, 6);

  // merge back
  let added = 0;
  for (const l of leads) { const p = foundMap[key(l)]; if (p && !(l.phone_number || '').trim()) { l.phone_number = p; l.phone_source = 'quickenrich_namecompany'; added++; } }
  writeCsv(CSV, header, leads);
  const total = leads.filter((l) => (l.phone_number || '').trim()).length;
  const summary = { retry_eligible: eligible.length, retry_calls: st.calls, new_phones_added: added, total_with_phone_now: total, new_fill_rate: +(total / leads.length).toFixed(3), quickenrich_credits_remaining: st.remaining, csv: CSV };
  fs.writeFileSync(SUMMARY, JSON.stringify(summary, null, 2));
  console.log('\n=== RETRY DONE ===\n' + JSON.stringify(summary, null, 2));
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
