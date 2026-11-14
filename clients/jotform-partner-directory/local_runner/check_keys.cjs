/* ============================================================================
 * check_keys.cjs — verify every API key this pipeline needs is present & working.
 *
 *   node check_keys.cjs
 *
 * Reads ../.env. Does a live connectivity test per key:
 *   - MillionVerifier: GET /api/v3/credits            (FREE, no credit consumed)
 *   - DeepInfra:       GET /v1/openai/models           (FREE)
 *   - BlitzAPI:        POST domain-to-linkedin jotform.com (~1 credit)
 * ==========================================================================*/
'use strict';

const fs = require('fs');
const path = require('path');
const https = require('https');
const { URL } = require('url');

function loadEnv() {
  const p = path.join(__dirname, '..', '.env');
  const K = {};
  if (fs.existsSync(p)) {
    for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith('#') || !t.includes('=')) continue;
      const i = t.indexOf('=');
      K[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
  }
  for (const k of Object.keys(process.env)) if (k.startsWith('BLITZ') || k.startsWith('MILLION') || k.startsWith('DEEPINFRA')) K[k] = process.env[k];
  return K;
}

function httpJson(rawUrl, opts = {}) {
  const { method = 'GET', headers = {}, body = null, timeout = 30000 } = opts;
  return new Promise((resolve) => {
    let u;
    try { u = new URL(rawUrl); } catch (e) { return resolve({ ok: false, status: 0, json: null, text: 'bad url' }); }
    const payload = body == null ? null : JSON.stringify(body);
    const h = Object.assign({}, headers);
    if (payload != null) { h['Content-Type'] = 'application/json'; h['Content-Length'] = Buffer.byteLength(payload); }
    const req = https.request({ hostname: u.hostname, path: u.pathname + u.search, method, headers: h, timeout }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => { let json = null; try { json = data ? JSON.parse(data) : null; } catch (_) {} resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, json, text: data }); });
    });
    req.on('error', (e) => resolve({ ok: false, status: 0, json: null, text: String(e) }));
    req.on('timeout', () => req.destroy(new Error('timeout')));
    if (payload != null) req.write(payload);
    req.end();
  });
}

const REQUIRED = ['BLITZAPI_KEY', 'MILLIONVERIFIER_KEY', 'DEEPINFRA_KEY'];

(async () => {
  const K = loadEnv();
  console.log('\n=== Jotform pipeline — API key check ===\n');
  const results = [];

  for (const name of REQUIRED) {
    if (!(K[name] && K[name].length > 6)) results.push({ tool: name, present: 'NO', live: 'skipped', detail: 'missing/empty in .env' });
  }

  if (K.MILLIONVERIFIER_KEY && K.MILLIONVERIFIER_KEY.length > 6) {
    const r = await httpJson(`https://api.millionverifier.com/api/v3/credits?api=${encodeURIComponent(K.MILLIONVERIFIER_KEY)}`);
    const credits = r.json && (r.json.credits ?? r.json.credit);
    const ok = r.ok && r.json && r.json.error == null && credits != null;
    results.push({ tool: 'MILLIONVERIFIER_KEY', present: 'YES', live: ok ? 'OK' : 'FAIL', detail: ok ? `credits=${credits}` : `status=${r.status} ${(r.text || '').slice(0, 120)}` });
  }

  if (K.DEEPINFRA_KEY && K.DEEPINFRA_KEY.length > 6) {
    const r = await httpJson('https://api.deepinfra.com/v1/openai/models', { headers: { Authorization: `Bearer ${K.DEEPINFRA_KEY}` } });
    const ok = r.status === 200;
    results.push({ tool: 'DEEPINFRA_KEY', present: 'YES', live: ok ? 'OK' : 'FAIL', detail: ok ? 'models endpoint reachable' : `status=${r.status} ${(r.text || '').slice(0, 120)}` });
  }

  if (K.BLITZAPI_KEY && K.BLITZAPI_KEY.length > 6) {
    const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/domain-to-linkedin', {
      method: 'POST', headers: { 'x-api-key': K.BLITZAPI_KEY }, body: { domain: 'jotform.com' },
    });
    const ok = r.status === 200 && r.json != null;
    results.push({ tool: 'BLITZAPI_KEY', present: 'YES', live: ok ? 'OK' : 'FAIL', detail: ok ? `found=${!!r.json.found} li=${r.json.company_linkedin_url || '-'}` : `status=${r.status} ${(r.text || '').slice(0, 120)}` });
  }

  const pad = (s, n) => String(s).padEnd(n);
  console.log(pad('TOOL', 24), pad('PRESENT', 9), pad('LIVE', 6), 'DETAIL');
  console.log('-'.repeat(80));
  for (const r of results) console.log(pad(r.tool, 24), pad(r.present, 9), pad(r.live, 6), r.detail);
  const allOk = results.length === REQUIRED.length && results.every((r) => r.live === 'OK');
  console.log('\n' + (allOk ? '✅ ALL KEYS PRESENT & WORKING — ready to run the pipeline.' : '❌ One or more keys missing/failing — fix .env and re-run.'));
  process.exit(allOk ? 0 : 1);
})();
