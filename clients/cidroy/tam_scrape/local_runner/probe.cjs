/* ============================================================================
 * Cidroy TAM scrape — DRY PROBE (read-shape / credit check, minimal spend).
 *
 *   node probe.cjs
 *
 * Makes exactly:
 *   1x POST /v2/search/people   (max_results 2)   -> inspect person + company shape
 *   1x POST /v2/enrichment/email (first person)   -> inspect email + email_domain shape
 *   1x GET  MillionVerifier v3   (found email)     -> inspect verify result
 *
 * Prints raw JSON for each so we can build the real pipeline against actual
 * field names. Surfaces 401/402 (auth / insufficient credits) immediately.
 * ==========================================================================*/
'use strict';

const https = require('https');
const path = require('path');
const fs = require('fs');
const { URL } = require('url');

// ---- tolerant .env loader (root .env uses "Label: value" colon format) -----
function loadKeys() {
  const p = path.join(__dirname, '..', '..', '..', '..', '.env'); // repo-root .env
  const K = { BLITZAPI_KEY: '', MILLIONVERIFIER_KEY: '' };
  if (fs.existsSync(p)) {
    for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const sep = t.indexOf(':') >= 0 ? ':' : (t.indexOf('=') >= 0 ? '=' : '');
      if (!sep) continue;
      const label = t.slice(0, t.indexOf(sep)).toLowerCase();
      const value = t.slice(t.indexOf(sep) + 1).trim();
      if (label.includes('millionverifier')) K.MILLIONVERIFIER_KEY = value;
      else if (label.includes('blitz')) K.BLITZAPI_KEY = value;
    }
  }
  // process.env overrides
  if (process.env.BLITZAPI_KEY) K.BLITZAPI_KEY = process.env.BLITZAPI_KEY;
  if (process.env.MILLIONVERIFIER_KEY) K.MILLIONVERIFIER_KEY = process.env.MILLIONVERIFIER_KEY;
  return K;
}

function httpJson(rawUrl, opts = {}) {
  const { method = 'GET', headers = {}, body = null, timeout = 60000 } = opts;
  return new Promise((resolve) => {
    const u = new URL(rawUrl);
    const payload = body == null ? null : (typeof body === 'string' ? body : JSON.stringify(body));
    const h = Object.assign({}, headers);
    if (payload != null && !h['Content-Type']) h['Content-Type'] = 'application/json';
    if (payload != null) h['Content-Length'] = Buffer.byteLength(payload);
    const req = https.request({ hostname: u.hostname, path: u.pathname + u.search, method, headers: h, timeout }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        let json = null; try { json = data ? JSON.parse(data) : null; } catch (_) {}
        resolve({ status: res.statusCode, json, text: data });
      });
    });
    req.on('error', (e) => resolve({ status: 0, json: null, text: String(e) }));
    req.on('timeout', () => req.destroy(new Error('timeout')));
    if (payload != null) req.write(payload);
    req.end();
  });
}

const BLITZ = 'https://api.blitz-api.ai';

(async () => {
  const K = loadKeys();
  console.log('KEYS: blitz=%s… mv=%s…',
    (K.BLITZAPI_KEY || '(none)').slice(0, 14), (K.MILLIONVERIFIER_KEY || '(none)').slice(0, 8));
  const H = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };

  // ---- 1) people search, 2 results ----------------------------------------
  const searchBody = {
    people: {
      job_title: { include: ['CEO', 'CTO', 'Founder', 'Co-Founder', 'Owner'], exclude: ['Assistant', 'Intern', 'Former'] },
      location: { country_code: ['US', 'CA'] },
    },
    company: {
      employee_range: ['1-10', '11-50'],
      industry: { include: [
        'Software Development', 'IT Services and IT Consulting', 'Technology; Information and Internet',
        'Computer Software', 'Information Technology and Services', 'Internet',
        'Computer Networking', 'Computer and Network Security', 'Data Infrastructure and Analytics',
        'Data Security Software Products', 'IT System Custom Software Development',
        'Mobile Computing Software Products', 'Embedded Software Products', 'Internet Marketplace Platforms',
      ] },
    },
    max_results: 2,
  };
  console.log('\n=== 1) POST /v2/search/people (max_results 2) ===');
  console.log('request:', JSON.stringify(searchBody));
  const s = await httpJson(`${BLITZ}/v2/search/people`, { method: 'POST', headers: H, body: searchBody });
  console.log('status:', s.status);
  if (s.status === 422 && s.json && /industry/i.test(JSON.stringify(s.json))) {
    // Capture the full valid-industry enum so we can pick exact tech strings.
    const msg = (s.json.message || '');
    const opts = msg.split('|').map((x) => x.replace(/^[^"]*"/, '').replace(/".*$/, '').trim()).filter(Boolean);
    fs.writeFileSync(path.join(__dirname, 'industry_enum.txt'), opts.join('\n'));
    console.log('wrote industry_enum.txt with', opts.length, 'industries');
  }
  console.log('raw:', JSON.stringify(s.json, null, 2)?.slice(0, 4000) || s.text.slice(0, 2000));

  // find first person + linkedin url from whatever key the API uses
  const arr = (s.json && (s.json.results || s.json.people || s.json.data || s.json.items)) || [];
  const first = arr[0] || null;
  const li = first && (first.linkedin_url || first.linkedinUrl || (first.person && first.person.linkedin_url));
  console.log('\nfirst person linkedin_url:', li || '(none found)');
  console.log('cursor field present:', JSON.stringify({
    cursor: s.json && s.json.cursor, next_cursor: s.json && s.json.next_cursor,
    pagination: s.json && s.json.pagination,
  }));

  // ---- 2) email enrichment on first person ---------------------------------
  if (li) {
    console.log('\n=== 2) POST /v2/enrichment/email ===');
    const e = await httpJson(`${BLITZ}/v2/enrichment/email`, { method: 'POST', headers: H, body: { person_linkedin_url: li } });
    console.log('status:', e.status);
    console.log('raw:', JSON.stringify(e.json, null, 2)?.slice(0, 2000) || e.text.slice(0, 1000));

    const email = e.json && (e.json.email || (e.json.all_emails && e.json.all_emails[0] && e.json.all_emails[0].email));
    // ---- 3) MillionVerifier -------------------------------------------------
    if (email) {
      console.log('\n=== 3) GET MillionVerifier v3 (email=%s) ===', email);
      const v = await httpJson(`https://api.millionverifier.com/api/v3/?api=${K.MILLIONVERIFIER_KEY}&email=${encodeURIComponent(email)}&timeout=10`);
      console.log('status:', v.status);
      console.log('raw:', JSON.stringify(v.json, null, 2) || v.text.slice(0, 1000));
    } else {
      console.log('\n(no email found for first person — will happen for a fraction of leads)');
    }
  }
  console.log('\n=== PROBE DONE ===');
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
