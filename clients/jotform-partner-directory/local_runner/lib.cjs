/* ============================================================================
 * Jotform Partner Directory → Verified Lead List — pipeline library.
 *
 * Single source of truth for config + helpers. CommonJS, uses require('https')
 * so it runs under plain Node. Helpers (httpJson/pMap/normalizers/writeCsv)
 * are adapted from clients/qset/.../local_runner/lib.cjs.
 * ==========================================================================*/
'use strict';

const https = require('https');
const http = require('http');
const { URL } = require('url');
const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// 0. CONFIG
// ---------------------------------------------------------------------------
const JOTFORM_BASE = 'https://www.jotform.com';
const DIRECTORY_PATH = '/partnership/partner-directory/';
const TOTAL_PAGES = 11; // confirmed via recon; Stage 1 stops early on an empty page anyway
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

const BLITZ = 'https://api.blitz-api.ai';
const DEEPINFRA = 'https://api.deepinfra.com/v1/openai';
const DEEPINFRA_MODEL = 'openai/gpt-oss-20b';
const LINKEDIN_BULK_HOST = 'realtime-linkedin-bulk-data.p.rapidapi.com'; // Stage 3b recovery (key from .mcp.json/.env)

// ICP decision-maker buckets. One DM kept per bucket. Bucket D only runs for
// large "Carahsoft-type" resellers (tier Elite/Gold OR >=50 employees).
const EXCL_T = ['assistant', 'intern', 'former', 'ex-', 'advisor', 'board member', 'board', 'consultant', 'freelance'];
const ICP_BUCKETS = [
  { key: 'A', name: 'Owner / Top management', largeOnly: false,
    titles: ['Founder', 'Co-Founder', 'Cofounder', 'Owner', 'CEO', 'Chief Executive Officer', 'Managing Director', 'Managing Partner', 'Principal', 'President', 'Director'] },
  { key: 'B', name: 'Partnerships / BD', largeOnly: false,
    titles: ['Head of Partnerships', 'Partnerships Manager', 'Partner Manager', 'Head of Business Development', 'VP Business Development', 'VP of Business Development', 'Strategic Alliances Manager', 'Channel Manager', 'Head of Growth'] },
  { key: 'C', name: 'Delivery / Technical', largeOnly: false,
    titles: ['COO', 'Chief Operating Officer', 'Head of Operations', 'Operations Manager', 'Head of Delivery', 'Head of Client Services', 'Client Services Director', 'Solutions Architect', 'Head of Automation', 'Automation Lead', 'CTO', 'Chief Technology Officer', 'Technical Director', 'Implementation Lead'] },
  { key: 'D', name: 'Sales / Procurement (large resellers)', largeOnly: true,
    titles: ['VP Sales', 'VP of Sales', 'Sales Director', 'Director of Sales', 'Vendor Manager', 'Alliance Manager', 'Vendor Alliance Manager', 'Procurement Lead', 'Procurement Manager', 'Head of Procurement'] },
];
const EMP_FINDER_LEVELS = ['C-Team', 'VP', 'Director', 'Head'];
const LARGE_TIERS = new Set(['elite', 'gold']);
const LARGE_EMP_FLOOR = 50;

// ---------------------------------------------------------------------------
// 1. HELPERS (adapted from QSET lib.cjs)
// ---------------------------------------------------------------------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** HTTP. Returns {ok,status,json,text}. Retry on 429/5xx/network w/ backoff. */
async function httpJson(rawUrl, opts = {}) {
  const { method = 'GET', headers = {}, body = null, timeout = 60000, retries = 4 } = opts;
  let attempt = 0, lastErr = null;
  while (attempt <= retries) {
    try {
      const result = await new Promise((resolve, reject) => {
        const u = new URL(rawUrl);
        const payload = body == null ? null : (typeof body === 'string' ? body : JSON.stringify(body));
        const h = Object.assign({}, headers);
        if (payload != null && !h['Content-Type']) h['Content-Type'] = 'application/json';
        if (payload != null) h['Content-Length'] = Buffer.byteLength(payload);
        const req = https.request(
          { hostname: u.hostname, path: u.pathname + u.search, method, headers: h, timeout },
          (res) => {
            let data = '';
            res.on('data', (c) => (data += c));
            res.on('end', () => {
              let json = null;
              try { json = data ? JSON.parse(data) : null; } catch (_) {}
              resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, json, text: data });
            });
          }
        );
        req.on('error', reject);
        req.on('timeout', () => req.destroy(new Error('timeout')));
        if (payload != null) req.write(payload);
        req.end();
      });
      if (result.status === 429 || result.status >= 500) {
        if (attempt === retries) return result;
        await sleep(Math.min(1000 * 2 ** attempt, 10000));
        attempt++; continue;
      }
      return result;
    } catch (e) {
      lastErr = e;
      if (attempt === retries) return { ok: false, status: 0, json: null, text: String(e) };
      await sleep(Math.min(1000 * 2 ** attempt, 10000));
      attempt++;
    }
  }
  return { ok: false, status: 0, json: null, text: String(lastErr) };
}

/** GET an HTML page with a browser UA, following redirects. Returns {ok,status,text}. */
function fetchHtml(url, maxRedirects = 4) {
  return new Promise((resolve) => {
    const go = (u, n) => {
      let parsed;
      try { parsed = new URL(u); } catch (e) { return resolve({ ok: false, status: 0, text: '' }); }
      const mod = parsed.protocol === 'http:' ? http : https;
      const req = mod.request(
        { hostname: parsed.hostname, path: (parsed.pathname || '/') + parsed.search, method: 'GET', headers: { 'User-Agent': UA, Accept: 'text/html,application/xhtml+xml' }, timeout: 30000 },
        (res) => {
          if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && n > 0) {
            res.resume();
            let next; try { next = new URL(res.headers.location, u).toString(); } catch (_) { return resolve({ ok: false, status: res.statusCode, text: '' }); }
            return go(next, n - 1);
          }
          let data = '';
          res.on('data', (c) => (data += c));
          res.on('end', () => resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, text: data }));
        }
      );
      req.on('error', () => resolve({ ok: false, status: 0, text: '' }));
      req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0, text: '' }); });
      req.end();
    };
    go(url, maxRedirects);
  });
}

/** Bounded-concurrency map. Per-item errors resolve to null; pool keeps draining. */
async function pMap(items, mapper, concurrency = 5) {
  const out = new Array(items.length);
  let i = 0;
  const workers = new Array(Math.min(concurrency, items.length || 1)).fill(0).map(async () => {
    while (i < items.length) {
      const idx = i++;
      try { out[idx] = await mapper(items[idx], idx); }
      catch (e) { out[idx] = null; }
    }
  });
  await Promise.all(workers);
  return out;
}

const normDomain = (s) => {
  if (!s) return '';
  s = String(s).trim().toLowerCase();
  if (s.includes('://')) s = s.split('://')[1];
  if (s.startsWith('www.')) s = s.slice(4);
  return s.split('/')[0].split('?')[0].replace(/\.$/, '');
};
const normLi = (s) => {
  if (!s) return '';
  s = String(s).trim();
  if (!/^https?:\/\//.test(s)) s = 'https://' + s;
  try {
    const u = new URL(s);
    let host = u.hostname.toLowerCase();
    if (host.endsWith('linkedin.com')) host = 'linkedin.com';
    return ('https://' + host + u.pathname.replace(/\/$/, '')).toLowerCase();
  } catch (_) { return s.toLowerCase(); }
};
const normEmail = (s) => (s || '').toString().trim().toLowerCase();

/** Minimal CSV reader (handles quoted fields, embedded commas/newlines/"" escapes). */
function readCsv(file) {
  const text = fs.readFileSync(file, 'utf8');
  const rows = [];
  let i = 0, field = '', row = [], inQ = false;
  while (i < text.length) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i += 2; continue; } inQ = false; i++; continue; }
      field += ch; i++; continue;
    }
    if (ch === '"') { inQ = true; i++; continue; }
    if (ch === ',') { row.push(field); field = ''; i++; continue; }
    if (ch === '\r') { i++; continue; }
    if (ch === '\n') { row.push(field); field = ''; rows.push(row); row = []; i++; continue; }
    field += ch; i++;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  if (!rows.length) return [];
  const header = rows[0];
  return rows.slice(1)
    .filter((r) => !(r.length === 1 && r[0] === ''))
    .map((r) => { const o = {}; header.forEach((h, idx) => (o[h] = r[idx] == null ? '' : r[idx])); return o; });
}

/** CSV writer — dynamic columns from row keys unless `cols` given. */
function writeCsv(file, rows, cols = null) {
  if (!rows.length) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, ''); return 0; }
  const columns = cols || [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [columns.join(',')];
  for (const r of rows) lines.push(columns.map((c) => esc(r[c])).join(','));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, lines.join('\n'));
  return rows.length;
}

// ---------------------------------------------------------------------------
// 2. HTML PARSING UTILS (regex-based, dependency-free)
// ---------------------------------------------------------------------------
function decodeEntities(s) {
  return (s || '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#0?39;|&apos;|&#x27;/g, "'")
    .replace(/&nbsp;/g, ' ').replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n))
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
}
function stripTags(html) {
  return decodeEntities(
    String(html || '')
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<svg[\s\S]*?<\/svg>/gi, ' ')
      .replace(/<[^>]+>/g, ' ')
  ).replace(/\s+/g, ' ').trim();
}

/** Inner text of the FIRST element whose class contains `cls` (up to its close tag). */
function classText(html, cls) {
  const re = new RegExp('<(\\w+)[^>]*class="[^"]*\\b' + cls + '\\b[^"]*"[^>]*>', 'i');
  const m = re.exec(html);
  if (!m) return '';
  const tag = m[1];
  const start = m.index + m[0].length;
  const close = html.indexOf('</' + tag, start);
  const chunk = close >= 0 ? html.slice(start, close) : html.slice(start, start + 600);
  return stripTags(chunk);
}

/** List-ish field: capture from `cls` element up to the next jf-modal-- marker (cap 1500). */
function classListText(html, cls) {
  const re = new RegExp('class="[^"]*\\b' + cls + '\\b[^"]*"[^>]*>', 'i');
  const m = re.exec(html);
  if (!m) return '';
  const start = m.index + m[0].length;
  let rest = html.slice(start);
  const nextMarker = rest.search(/jf-modal--/);
  let chunk = nextMarker >= 0 ? rest.slice(0, nextMarker) : rest.slice(0, 1500);
  let text = stripTags(chunk).replace(/\bShow (more|less)\b/gi, '').trim();
  return text;
}

/** Chip list inside the `flex flex-wrap ... <cls>` container — joins inner <span> texts.
 *  Used for jf-modal--services / --speciality / --industries / --languages. */
function modalChips(html, cls) {
  const re = new RegExp('class="[^"]*\\b' + cls + '\\b[^"]*"[^>]*>', 'i');
  const m = re.exec(html);
  if (!m) return '';
  const start = m.index + m[0].length;
  const close = html.indexOf('</div>', start);
  const inner = close >= 0 ? html.slice(start, close) : html.slice(start, start + 1500);
  const spans = [];
  let sm; const sre = /<span[^>]*>([\s\S]*?)<\/span>/gi;
  while ((sm = sre.exec(inner))) { const t = stripTags(sm[1]); if (t) spans.push(t); }
  const vals = (spans.length ? spans : [stripTags(inner)]).map((s) => s.trim()).filter(Boolean);
  return [...new Set(vals)].join(' | ');
}

/** href of the <a> tag that carries data-jfa="VAL" (attr order-agnostic). */
function hrefForDataJfa(html, val) {
  const re = new RegExp('<a\\b[^>]*data-jfa="' + val + '"[^>]*>', 'i');
  const m = re.exec(html);
  if (!m) return '';
  const hm = /href="([^"]+)"/i.exec(m[0]);
  return hm ? decodeEntities(hm[1]).trim() : '';
}

/** All values of an attribute across the doc. */
function allAttr(html, re) {
  const out = [];
  let m;
  const g = new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g');
  while ((m = g.exec(html))) out.push(m[1]);
  return out;
}

// ---------------------------------------------------------------------------
// 3. ICP helpers
// ---------------------------------------------------------------------------
const lc = (s) => (s || '').toString().toLowerCase();
function isLargeReseller(tier, employees) {
  return LARGE_TIERS.has(lc(tier).trim()) || (Number(employees) || 0) >= LARGE_EMP_FLOOR;
}
/** Classify a job title into the highest-priority ICP bucket key, or '' if none. */
function classifyBucket(title, isLarge) {
  const t = lc(title);
  for (const b of ICP_BUCKETS) {
    if (b.largeOnly && !isLarge) continue;
    if (b.titles.some((kw) => t.includes(lc(kw)))) return b.key;
  }
  return '';
}

// ---------------------------------------------------------------------------
// 3b. LinkedIn-Bulk recovery (RapidAPI direct HTTP — key from .env/.mcp.json)
// ---------------------------------------------------------------------------
const liHeaders = (K) => ({ 'x-rapidapi-key': K.RAPIDAPI_KEY, 'x-rapidapi-host': LINKEDIN_BULK_HOST });

async function liSuggestCompany(K, name) {
  if (!K.RAPIDAPI_KEY || !name) return [];
  const url = `https://${LINKEDIN_BULK_HOST}/suggestion_company?query=${encodeURIComponent(name)}`;
  const r = await httpJson(url, { headers: liHeaders(K) });
  return (r.ok && r.json && r.json.suggestions) || [];
}
async function liCompanyData(K, link) {
  if (!K.RAPIDAPI_KEY || !link) return null;
  const r = await httpJson(`https://${LINKEDIN_BULK_HOST}/company`, { method: 'POST', headers: liHeaders(K), body: { link } });
  return (r.ok && r.json && r.json.data) || null;
}

/** Strict name-match guard so we don't attach the wrong LinkedIn company. */
function nameTokensMatch(a, b) {
  const norm = (s) => (s || '').toLowerCase().replace(/&/g, ' and ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\b(inc|llc|ltd|gmbh|co|corp|corporation|company|technologies|technology|solutions|solution|consulting|services|service|group|the|cv|sti|limited|pvt|software|digital|media|agency|studio|labs|international)\b/g, ' ')
    .replace(/\s+/g, ' ').trim();
  const ta = norm(a).split(' ').filter((w) => w.length > 1);
  const tb = new Set(norm(b).split(' ').filter((w) => w.length > 1));
  if (!ta.length || !tb.size) return false;
  let inter = 0; for (const t of ta) if (tb.has(t)) inter++;
  const smaller = Math.min(ta.length, tb.size);
  return smaller <= 2 ? inter === smaller : inter / smaller >= 0.6;
}

// ---------------------------------------------------------------------------
// 4. DeepInfra LLM service summary (shape from deepinfra_ai_enrich.py)
// ---------------------------------------------------------------------------
const SYSTEM_PROMPT = 'You summarize what services a company offers, concisely and factually. Output ONLY one or two plain sentences — no preamble, no quotes, no markdown, no commentary.';

async function deepinfraSummary(K, contextText) {
  if (!K.DEEPINFRA_KEY || !contextText) return '';
  const prompt = 'Based on the following company website / profile text, summarize in 1-2 sentences the concrete services this company offers (and any platforms they specialize in). Text:\n\n' + String(contextText).slice(0, 6000);
  const headers = { Authorization: `Bearer ${K.DEEPINFRA_KEY}` };
  // gpt-oss-20b is a reasoning model: it spends tokens on hidden reasoning before
  // the visible answer, so max_tokens must be generous and reasoning_effort low,
  // else content comes back empty with finish_reason="length".
  const body = { model: DEEPINFRA_MODEL, messages: [{ role: 'system', content: SYSTEM_PROMPT }, { role: 'user', content: prompt }], temperature: 0.3, max_tokens: 400, reasoning_effort: 'low' };
  for (let attempt = 0; attempt < 5; attempt++) {
    const r = await httpJson(`${DEEPINFRA}/chat/completions`, { method: 'POST', headers, body, timeout: 60000 });
    if (r.status === 429 || r.status >= 500 || r.status === 0) { await sleep(Math.min(1000 * 2 ** attempt, 8000)); continue; }
    if (!r.ok || !r.json) return '';
    let text = '';
    try { text = r.json.choices[0].message.content || ''; } catch (_) { return ''; }
    text = text.trim().replace(/^["']|["']$/g, '').replace(/\s+/g, ' ').trim();
    if (/\b(i cannot|i can't|as an ai|i'm unable|i am unable)\b/i.test(text)) return '';
    if (text) return text;
    await sleep(500); // empty completion — brief pause then retry
  }
  return '';
}

module.exports = {
  JOTFORM_BASE, DIRECTORY_PATH, TOTAL_PAGES, UA, BLITZ, DEEPINFRA, DEEPINFRA_MODEL, LINKEDIN_BULK_HOST,
  ICP_BUCKETS, EXCL_T, EMP_FINDER_LEVELS, LARGE_TIERS, LARGE_EMP_FLOOR,
  sleep, httpJson, fetchHtml, pMap, normDomain, normLi, normEmail, writeCsv, readCsv,
  decodeEntities, stripTags, classText, classListText, modalChips, hrefForDataJfa, allAttr,
  isLargeReseller, classifyBucket, deepinfraSummary,
  liSuggestCompany, liCompanyData, nameTokensMatch,
};
