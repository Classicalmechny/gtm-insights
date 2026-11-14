/* ============================================================================
 * Cidroy TAM scrape — BlitzAPI people search -> LLM ICP classify -> email
 *                      enrich -> MillionVerifier -> CSV
 *
 *   node run.cjs --smoke 100        # smoke: ~100 VERIFIED leads end-to-end
 *   node run.cjs --full             # full run to --target verified (default 17000)
 *   node run.cjs --full --target 17000 --run-id cidroy_full
 *
 * ICP: PRODUCT-tech companies (services/consulting/staffing/nonprofit removed by
 *      an LLM classifier), 1-50 employees, US + Canada, decision-makers
 *      (CEO/CTO/Founder/Co-Founder/Owner + any C-suite). Verify: MillionVerifier
 *      v3, keep result=="ok" only.
 *
 * Compulsory output fields (row dropped if any missing): email, first_name,
 * company_name. All other columns ride along free.
 *
 * FULLY RESUMABLE: every stage streams progress to disk under output/<run_id>/.
 * Re-running the same command continues from the last checkpoint (safe for the
 * multi-hour VPS run). Keys load from a .env in the SAME folder as this file
 * (VPS-friendly) or the repo root.
 * ==========================================================================*/
'use strict';

const https = require('https');
const path = require('path');
const fs = require('fs');
const { URL } = require('url');

const BLITZ = 'https://api.blitz-api.ai';
const DEEPINFRA = 'https://api.deepinfra.com/v1/openai/chat/completions';
const DEEPINFRA_MODEL = 'deepseek-ai/DeepSeek-V4-Flash';
const CLASSIFY_CONCURRENCY = 25; // conservative throttle (Deepinfra exposes no rate-limit header; 429s auto-backoff)

// ---------------------------------------------------------------------------
// ICP CONFIG
// ---------------------------------------------------------------------------
const CFG = {
  titleInclude: [
    'CEO', 'Chief Executive Officer', 'Founder', 'Co-Founder', 'Cofounder',
    'Owner', 'President', 'CTO', 'Chief Technology Officer',
    'COO', 'Chief Operating Officer', 'CPO', 'Chief Product Officer',
    'CIO', 'Chief Information Officer',
    'VP Engineering', 'VP of Engineering', 'Head of Engineering',
    'VP Product', 'VP of Product', 'Head of Product',
  ],
  titleExclude: ['Assistant', 'Intern', 'Former', 'Fractional', 'Advisor', 'Freelance', 'Aspiring', 'Student', 'Retired'],
  countries: ['US', 'CA'], // North America only (per user)
  employeeRange: ['1-10', '11-50'], // per brief: 1-50 employees
  // PRODUCT-tech only. Deliberately EXCLUDES the services buckets that imported
  // Cidroy's competitors: 'IT Services and IT Consulting', 'Information Technology
  // and Services', 'IT System Custom Software Development' (dev agencies), and
  // 'Internet Publishing' (content/media/nonprofits).
  industryInclude: [
    'Software Development', 'Technology; Information and Internet', 'Computer Software', 'Internet',
    'Computer Networking', 'Computer and Network Security', 'Data Infrastructure and Analytics',
    'Data Security Software Products', 'Mobile Computing Software Products', 'Embedded Software Products',
    'Internet Marketplace Platforms', 'Computer Games', 'Mobile Games', 'Mobile Gaming Apps',
    'Blockchain Services', 'Business Intelligence Platforms', 'Desktop Computing Software Products',
  ],
  industryExclude: ['Staffing and Recruiting', 'Outsourcing and Offshoring Consulting', 'Outsourcing/Offshoring'],
  nameExclude: ['Stealth', 'Self-Employed', 'Self Employed', 'Freelance', 'Confidential', 'Independent Consultant',
    'Positivity', 'Remote Work', 'Jobgether', 'Psychology Today', 'The Cyber Security Hub', 'Loker',
    'Various', 'Private', 'Undisclosed', 'Not Disclosed', 'Personal', 'Homemaker'],
  headlineExclude: [/open to work/i, /#opentowork/i, /\baspiring\b/i, /\bstudent\b/i, /seeking (a |new |next |my )/i, /looking for (a |my |new |next )/i],
  companyExclude: [/^stealth/i, /stealth (startup|mode|company)/i, /^self[- ]employed/i, /^freelance/i,
    /staffing/i, /\brecruit/i, /workforce solution/i, /executive search/i, /professional search/i,
    /\btalent\b/i, /\bheadhunt/i, /women in (cyber|tech)/i, /blacks in tech/i, /\bwicys\b/i,
    /\bsearch (group|partners|consult|advisor)/i,
    /\bconsult/i, /consultancy/i, /\bagency\b/i, /\bstudio\b/i, /managed services/i, /outsourc/i,
    /nearshore/i, /offshore/i, /augmentation/i, /\bfoundation\b/i, /\bsociety\b/i, /\bassociation\b/i,
    /\bacademy\b/i, /bootcamp/i, /ministr/i, /non[- ]?profit/i, /\bcouncil\b/i,
    /solutions\s+(inc|llc|group|corp)/i, /business solutions/i],
  titleExcludeRe: /recruit|staffing|talent acquisition|executive search|search consultant|headhunt|founder in residence|\bin residence\b|chief of staff|founder'?s office|ceo'?s office/i,
};

// LLM classifier prompt — the lever that removes services/nonprofit/staffing
// companies that self-tag as "Software Development" on LinkedIn.
const CLASSIFY_PROMPT = (name, domain) =>
  `You classify companies for a B2B outbound list. The seller provides OUTSOURCED software engineering + product execution to companies that build their OWN tech product.\n\n` +
  `KEEP if the company builds and operates its OWN software/tech product or platform — in ANY industry (SaaS, AI, fintech, health-tech, e-commerce with own tech, developer tools, games, crypto/web3, hardware+software). If a product/app/platform IS the business, KEEP.\n\n` +
  `DROP only if the company's core business is selling PEOPLE or SERVICES instead of a product: IT-services / software consulting / dev agency / systems integrator / staff-augmentation; staffing / recruiting / talent or freelance marketplace; OR it is a nonprofit / community / association / religious org / government / media-content / education-courses / a solo individual.\n\n` +
  `When unsure, KEEP.\n\n` +
  `Company: "${name}"${domain ? ` (website: ${domain})` : ''}\n` +
  `Reply with ONLY one word: KEEP or DROP.`;

// BlitzAPI caps a single cursor-search at 50,000 results. To exceed that we run
// one search per title-group (distinct slices of the TAM), deduping across all.
const TITLE_GROUPS = [
  ['CEO', 'Chief Executive Officer', 'Founder', 'Co-Founder', 'Cofounder', 'Owner', 'President'],
  ['CTO', 'Chief Technology Officer', 'CIO', 'Chief Information Officer', 'VP Engineering', 'VP of Engineering', 'Head of Engineering'],
  ['COO', 'Chief Operating Officer', 'CPO', 'Chief Product Officer', 'VP Product', 'VP of Product', 'Head of Product'],
  // Broader C-suite (per brief: "any C-suite") — adds distinct decision-makers to reach volume.
  ['CISO', 'Chief Information Security Officer', 'CDO', 'Chief Data Officer', 'CFO', 'Chief Financial Officer', 'CMO', 'Chief Marketing Officer', 'CRO', 'Chief Revenue Officer', 'Managing Director', 'Managing Partner'],
  // Tech VP / Head / Director layer.
  ['VP Technology', 'VP of Technology', 'Head of Technology', 'VP Software', 'Head of Software', 'Director of Engineering', 'Director of Product', 'Director of Technology', 'VP Data', 'Head of Data', 'VP Infrastructure', 'Head of Infrastructure', 'Head of Platform'],
];

// ---------------------------------------------------------------------------
// KEYS + HTTP + HELPERS
// ---------------------------------------------------------------------------
function loadKeys() {
  const candidates = [
    path.join(__dirname, '.env'),                                   // VPS: same folder as run.cjs
    path.join(process.cwd(), '.env'),                               // cwd
    path.join(__dirname, '..', '.env'),                             // client dir
    path.join(__dirname, '..', '..', '..', '..', '.env'),           // repo root
  ];
  const p = candidates.find((c) => { try { return fs.existsSync(c); } catch (_) { return false; } });
  const K = { BLITZAPI_KEY: '', MILLIONVERIFIER_KEY: '', DEEPINFRA_KEY: '' };
  if (p) {
    for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const ci = t.indexOf(':'), ei = t.indexOf('=');
      const idx = ci >= 0 && (ei < 0 || ci < ei) ? ci : ei;
      if (idx < 0) continue;
      const label = t.slice(0, idx).toLowerCase();
      const value = t.slice(idx + 1).trim();
      if (label.includes('millionverifier')) K.MILLIONVERIFIER_KEY = value;
      else if (label.includes('blitz')) K.BLITZAPI_KEY = value;
      else if (label.includes('deepinfra')) K.DEEPINFRA_KEY = value;
    }
  }
  if (process.env.BLITZAPI_KEY) K.BLITZAPI_KEY = process.env.BLITZAPI_KEY;
  if (process.env.MILLIONVERIFIER_KEY) K.MILLIONVERIFIER_KEY = process.env.MILLIONVERIFIER_KEY;
  if (process.env.DEEPINFRA_KEY) K.DEEPINFRA_KEY = process.env.DEEPINFRA_KEY;
  K._envPath = p || '(none)';
  return K;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function titleIsDM(rawTitle) {
  const t = (rawTitle || '').toLowerCase();
  if (!t) return false;
  const isVP = /\bvice[\s-]*president\b|\bvp\b|\bs\.?vp\b|\be\.?vp\b|\bavp\b/.test(t);
  const csuite = /\bfounder\b|co[\s-]?founder|\bowner\b|\bceo\b|\bcto\b|\bcoo\b|\bcpo\b|\bcio\b|\bcmo\b|\bcfo\b|\bciso\b|\bcdo\b|\bcao\b|\bcro\b|\bcxo\b|chief\s+[a-z]+\s+officer|chief\s+(executive|technology|technical|operating|product|information|financial|data|marketing|security|revenue|innovation|digital|people)\b|managing\s+(director|partner|member)/.test(t);
  if (csuite) return true;
  if (/\bpresident\b/.test(t) && !isVP) return true;
  const leader = /\b(vice[\s-]*president|vp|svp|evp|avp|head|director|dir)\b/.test(t);
  const techFn = /engineering|technolog|\btech\b|\bproduct\b|software|platform|infrastructure|\bdata\b|devops|\bcloud\b|information technology|\bit\b|machine\s*learning|\bai\b|\bml\b|cyber|\bsecurity\b|\br&d\b/.test(t);
  return leader && techFn;
}

async function httpJson(rawUrl, opts = {}) {
  const { method = 'GET', headers = {}, body = null, timeout = 60000, retries = 5 } = opts;
  let attempt = 0;
  while (attempt <= retries) {
    const result = await new Promise((resolve) => {
      const u = new URL(rawUrl);
      const payload = body == null ? null : (typeof body === 'string' ? body : JSON.stringify(body));
      const h = Object.assign({}, headers);
      if (payload != null && !h['Content-Type']) h['Content-Type'] = 'application/json';
      if (payload != null) h['Content-Length'] = Buffer.byteLength(payload);
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
    if ((result.status === 429 || result.status >= 500) && attempt < retries) { await sleep(Math.min(1000 * 2 ** attempt, 10000)); attempt++; continue; }
    return result;
  }
  return { ok: false, status: 0, json: null, text: 'retries exhausted' };
}

async function pMap(items, mapper, concurrency = 5) {
  const out = new Array(items.length);
  let i = 0;
  const workers = new Array(Math.min(concurrency, items.length || 1)).fill(0).map(async () => {
    while (i < items.length) { const idx = i++; try { out[idx] = await mapper(items[idx], idx); } catch (e) { out[idx] = null; } }
  });
  await Promise.all(workers);
  return out;
}

function liKey(s) {
  if (!s) return '';
  let v = String(s).trim();
  for (let n = 0; n < 4; n++) { try { const d = decodeURIComponent(v); if (d === v) break; v = d; } catch (_) { break; } }
  v = v.toLowerCase().replace(/\/+$/, '');
  const m = v.match(/linkedin\.com\/in\/([^/?#]+)/);
  return m ? m[1] : v;
}
const normEmail = (s) => (s || '').toString().trim().toLowerCase();
const normDomain = (s) => {
  if (!s) return '';
  s = String(s).trim().toLowerCase();
  if (s.includes('://')) s = s.split('://')[1];
  if (s.startsWith('www.')) s = s.slice(4);
  return s.split('/')[0].split('?')[0].replace(/\.$/, '');
};
const companyKey = (p) => (p.company_linkedin_url || p.company_domain || p.company_name || '').toString().trim().toLowerCase();

function currentExp(p) {
  const exps = Array.isArray(p.experiences) ? p.experiences : [];
  return exps.find((e) => e && e.job_is_current) || exps[0] || {};
}

// ---------------------------------------------------------------------------
// disk helpers (checkpoint / resume)
// ---------------------------------------------------------------------------
const ensureDir = (d) => fs.mkdirSync(d, { recursive: true });
function appendJsonl(file, obj) { fs.appendFileSync(file, JSON.stringify(obj) + '\n'); }
function readJsonl(file) {
  if (!fs.existsSync(file)) return [];
  return fs.readFileSync(file, 'utf8').split('\n').filter(Boolean)
    .map((l) => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(Boolean);
}
function readJson(file, dflt) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return dflt; } }
function writeJson(file, obj) { ensureDir(path.dirname(file)); fs.writeFileSync(file, JSON.stringify(obj)); }

// ---------------------------------------------------------------------------
// CSV
// ---------------------------------------------------------------------------
const CSV_COLS = ['email', 'first_name', 'last_name', 'full_name', 'title', 'company_name',
  'company_domain', 'company_linkedin_url', 'linkedin_url', 'country', 'state', 'city',
  'email_verification_status', 'source'];
function writeCsv(file, rows, cols) {
  const c = cols || (rows.length ? [...new Set(rows.flatMap((r) => Object.keys(r)))] : []);
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [c.join(',')];
  for (const r of rows) lines.push(c.map((k) => esc(r[k])).join(','));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, lines.join('\n'));
  return rows.length;
}

// ---------------------------------------------------------------------------
// STAGE 1 — SOURCE (people search, cursor pagination, dedup, resumable)
// ---------------------------------------------------------------------------
function searchBody(cursor, pageSize, titleInclude) {
  const b = {
    people: {
      job_title: { include: titleInclude || CFG.titleInclude, exclude: CFG.titleExclude },
      location: { country_code: CFG.countries },
    },
    company: {
      employee_range: CFG.employeeRange,
      industry: { include: CFG.industryInclude, exclude: CFG.industryExclude },
      name: { exclude: CFG.nameExclude },
    },
    max_results: pageSize,
  };
  if (cursor) b.cursor = cursor;
  return b;
}

async function stageSource(K, targetCandidates, outDir, log) {
  const H = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const rawFile = path.join(outDir, 'raw_people.jsonl');
  const ckptFile = path.join(outDir, 'source_ckpt.json');
  ensureDir(outDir);

  const people = readJsonl(rawFile);
  const seen = new Set(people.map((p) => p._key));
  const ckpt = readJson(ckptFile, { groupIdx: 0, cursor: null, done: false });
  const stats = { pages: 0, raw: 0, dup: 0, noise: 0, title_reject: 0, kept: people.length, resumed: people.length, total_results: 0, search_calls: 0, groups_done: ckpt.groupIdx };
  if (ckpt.done || people.length >= targetCandidates) { log('STAGE1_source.resume', { have: people.length, done: ckpt.done }); return { people, stats }; }

  outer:
  for (let gi = ckpt.groupIdx; gi < TITLE_GROUPS.length; gi++) {
    let cursor = gi === ckpt.groupIdx ? ckpt.cursor : null;
    log('source.group', { group: gi + 1, of: TITLE_GROUPS.length, kept_so_far: people.length });
    while (people.length < targetCandidates) {
      const r = await httpJson(`${BLITZ}/v2/search/people`, { method: 'POST', headers: H, body: searchBody(cursor, 50, TITLE_GROUPS[gi]) });
      stats.search_calls++;
      if (!r.ok) { log('source.err', { group: gi + 1, status: r.status, body: (r.text || '').slice(0, 200) }); break; }
      stats.pages++;
      if (r.json && r.json.total_results != null) stats.total_results = r.json.total_results;
      const rows = (r.json && (r.json.results || r.json.people || r.json.data)) || [];
      if (!rows.length) break;
      for (const p of rows) {
        stats.raw++;
        const key = liKey(p.linkedin_url) || ((p.full_name || '') + '|' + (currentExp(p).company_name || '')).toLowerCase();
        if (!key || seen.has(key)) { stats.dup++; continue; }
        seen.add(key);
        const exp = currentExp(p);
        const headline = p.headline || '';
        const company = (exp.company_name || '').trim();
        const title = (exp.job_title || '').trim();
        if (CFG.headlineExclude.some((re) => re.test(headline)) || CFG.companyExclude.some((re) => re.test(company))) { stats.noise++; continue; }
        if (!titleIsDM(title) || CFG.titleExcludeRe.test(title)) { stats.title_reject++; continue; }
        const person = {
          _key: key,
          first_name: (p.first_name || '').trim(),
          last_name: (p.last_name || '').trim(),
          full_name: (p.full_name || '').trim(),
          title,
          company_name: company,
          company_domain: normDomain(exp.company_domain || ''),
          company_linkedin_url: (exp.company_linkedin_url || '').trim(),
          linkedin_url: (p.linkedin_url || '').trim(),
          country: (p.location && p.location.country_code) || '',
          state: (p.location && p.location.state_code) || '',
          city: (p.location && p.location.city) || '',
          headline,
        };
        appendJsonl(rawFile, person);
        people.push(person);
        stats.kept++;
      }
      cursor = (r.json && r.json.cursor) || null;
      writeJson(ckptFile, { groupIdx: gi, cursor, done: false });
      if (stats.pages % 20 === 0) log('source.progress', { kept: people.length, target: targetCandidates, group: gi + 1, pages: stats.pages });
      if (!cursor) break; // this title-group exhausted → next group
      if (stats.search_calls >= 12000) { log('source.backstop', { search_calls: stats.search_calls }); break outer; }
      await sleep(220);
    }
    if (people.length >= targetCandidates) { writeJson(ckptFile, { groupIdx: gi, cursor, done: false }); break; }
    stats.groups_done = gi + 1;
  }
  if (people.length < targetCandidates) writeJson(ckptFile, { groupIdx: TITLE_GROUPS.length, cursor: null, done: true });
  log('STAGE1_source', stats);
  return { people, stats };
}

// ---------------------------------------------------------------------------
// STAGE 1b — LLM ICP CLASSIFY (product-tech vs services/nonprofit), resumable
// ---------------------------------------------------------------------------
async function classifyCompany(K, name, domain) {
  if (!K.DEEPINFRA_KEY) return 'keep';
  const r = await httpJson(DEEPINFRA, {
    method: 'POST',
    headers: { Authorization: `Bearer ${K.DEEPINFRA_KEY}`, 'Content-Type': 'application/json' },
    body: { model: DEEPINFRA_MODEL, messages: [{ role: 'user', content: CLASSIFY_PROMPT(name, domain) }], max_tokens: 64, temperature: 0 },
    timeout: 45000,
  });
  const txt = ((((r.json || {}).choices || [])[0] || {}).message || {}).content || '';
  const low = txt.toLowerCase();
  const d = low.lastIndexOf('drop'), k = low.lastIndexOf('keep');
  if (d > k) return 'drop';
  return 'keep'; // default keep on ambiguous / error — never lose a real lead
}

async function deepinfraAlive(K) {
  if (!K.DEEPINFRA_KEY) return false;
  const r = await httpJson(DEEPINFRA, {
    method: 'POST', headers: { Authorization: `Bearer ${K.DEEPINFRA_KEY}`, 'Content-Type': 'application/json' },
    body: { model: DEEPINFRA_MODEL, messages: [{ role: 'user', content: 'Reply with the single word OK.' }], max_tokens: 400, temperature: 0 }, timeout: 30000, retries: 1,
  });
  return r.ok && /\S/.test(((((r.json || {}).choices || [])[0] || {}).message || {}).content || '');
}

async function stageClassify(K, people, outDir, log) {
  const cacheFile = path.join(outDir, 'classify_cache.json');
  const cache = readJson(cacheFile, {});
  const uniq = new Map();
  for (const p of people) { const ck = companyKey(p); if (ck && !uniq.has(ck)) uniq.set(ck, { ck, name: p.company_name, domain: p.company_domain }); }
  const todo = [...uniq.values()].filter((c) => !(c.ck in cache));
  const stats = { companies: uniq.size, to_classify: todo.length, cached: uniq.size - todo.length, keep: 0, drop: 0, people_in: people.length, people_kept: 0, skipped: false };
  const skipAllKept = () => { stats.skipped = true; stats.keep = uniq.size; stats.people_kept = people.length; return { kept: people, stats }; };
  if (!K.DEEPINFRA_KEY) { log('STAGE1b_classify.skip', { reason: 'no DEEPINFRA_KEY', kept_all: people.length }); return skipAllKept(); }
  // Probe once — if Deepinfra is down / out of credits (402), skip the whole
  // stage (keep all) instead of wasting a dead call on every company. Clean the
  // list later with classify_cleanup.cjs once credits are topped up.
  if (todo.length && !(await deepinfraAlive(K))) {
    log('STAGE1b_classify.skip', { reason: 'deepinfra unavailable (402/err) — run classifier cleanup later', kept_all: people.length });
    return skipAllKept();
  }

  let done = 0;
  await pMap(todo, async (c) => {
    cache[c.ck] = await classifyCompany(K, c.name, c.domain);
    if (++done % 200 === 0) { writeJson(cacheFile, cache); log('classify.progress', { done, total: todo.length }); }
  }, CLASSIFY_CONCURRENCY);
  writeJson(cacheFile, cache);

  for (const c of uniq.values()) { if (cache[c.ck] === 'drop') stats.drop++; else stats.keep++; }
  const kept = people.filter((p) => cache[companyKey(p)] !== 'drop');
  stats.people_kept = kept.length;
  log('STAGE1b_classify', stats);
  return { kept, stats };
}

// ---------------------------------------------------------------------------
// STAGE 2 — EMAIL ENRICHMENT (Blitz), resumable
// ---------------------------------------------------------------------------
async function stageEmail(K, people, outDir, log) {
  const H = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const outFile = path.join(outDir, 'email_results.jsonl');
  const prior = readJsonl(outFile);
  const doneKeys = new Set(prior.map((x) => x._key));
  const withEmail = prior.filter((x) => x.email);
  const todo = people.filter((p) => !doneKeys.has(p._key));
  const stats = { input: people.length, resumed: prior.length, found: withEmail.length, not_found: prior.length - withEmail.length, email_calls: 0 };

  await pMap(todo, async (row) => {
    if (!row.linkedin_url) { appendJsonl(outFile, { _key: row._key, email: '' }); stats.not_found++; return; }
    const r = await httpJson(`${BLITZ}/v2/enrichment/email`, { method: 'POST', headers: H, body: { person_linkedin_url: row.linkedin_url } });
    stats.email_calls++;
    const j = r.json || {};
    const email = normEmail(j.email || (j.all_emails && j.all_emails[0] && j.all_emails[0].email) || '');
    if (!email) { appendJsonl(outFile, { _key: row._key, email: '' }); stats.not_found++; return; }
    const eDomain = (j.all_emails && j.all_emails[0] && j.all_emails[0].email_domain) || email.split('@')[1] || '';
    const eCoLi = (j.all_emails && j.all_emails[0] && j.all_emails[0].company_linkedin_url) || '';
    const enriched = Object.assign({}, row, { email, company_domain: row.company_domain || normDomain(eDomain), company_linkedin_url: row.company_linkedin_url || eCoLi });
    appendJsonl(outFile, enriched);
    withEmail.push(enriched);
    stats.found++;
  }, 6);
  log('STAGE2_email', stats);
  return { withEmail, stats };
}

// ---------------------------------------------------------------------------
// STAGE 3 — VERIFY (MillionVerifier v3, keep "ok" only), resumable
// ---------------------------------------------------------------------------
async function millionVerify(K, email) {
  const r = await httpJson(`https://api.millionverifier.com/api/v3/?api=${K.MILLIONVERIFIER_KEY}&email=${encodeURIComponent(email)}&timeout=15`);
  if (!r.ok || !r.json) return { ok: false, status: 'error' };
  const res = (r.json.result || '').toLowerCase();
  return { ok: res === 'ok', status: res };
}
async function stageVerify(K, leads, outDir, log) {
  const outFile = path.join(outDir, 'verify_results.jsonl');
  const prior = readJsonl(outFile);
  const doneEmails = new Set(prior.map((x) => x.email));
  const verified = prior.filter((x) => x.email_verification_status === 'ok');
  const todo = leads.filter((l) => !doneEmails.has(l.email));
  const stats = { input: leads.length, resumed: prior.length, ok: verified.length, catch_all: 0, invalid: 0, unknown: 0, disposable: 0, error: 0, mv_calls: 0 };

  await pMap(todo, async (row) => {
    const v = await millionVerify(K, row.email);
    stats.mv_calls++;
    stats[v.status] = (stats[v.status] || 0) + 1;
    const rec = Object.assign({}, row, { email_verification_status: v.status, source: 'blitz_people_search' });
    appendJsonl(outFile, rec);
    if (v.ok) verified.push(rec);
  }, 15);
  log('STAGE3_verify', stats);
  return { verified, stats };
}

// ---------------------------------------------------------------------------
// STAGE 4 — EXPORT (enforce compulsory fields, dedup, write CSV)
// ---------------------------------------------------------------------------
function stageExport(verified, outDir, log) {
  const seen = new Set();
  const rows = [];
  const stats = { input: verified.length, dropped_missing: 0, dropped_dup: 0, final: 0 };
  for (const r of verified) {
    if (!r.email || !r.first_name || !r.company_name) { stats.dropped_missing++; continue; }
    if (seen.has(r.email)) { stats.dropped_dup++; continue; }
    seen.add(r.email);
    rows.push(r);
  }
  stats.final = rows.length;
  const file = path.join(outDir, 'final.csv');
  writeCsv(file, rows, CSV_COLS);
  log('STAGE4_export', stats);
  return { rows, stats, file };
}

// ---------------------------------------------------------------------------
// MAIN
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const val = (f, d) => { const i = argv.indexOf(f); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };

module.exports = { CFG, titleIsDM, loadKeys, httpJson, pMap, liKey, normEmail, normDomain, companyKey, currentExp, searchBody, classifyCompany, stageSource, stageClassify, stageEmail, stageVerify, stageExport, millionVerify, writeCsv, CSV_COLS };

async function main() {
  const K = loadKeys();
  if (!K.BLITZAPI_KEY || !K.MILLIONVERIFIER_KEY) { console.error('Missing keys (blitz/millionverifier). Put a .env next to run.cjs.'); process.exit(1); }
  const smoke = has('--smoke');
  const smokeN = Number(val('--smoke', '100')) || 100;
  const target = Number(val('--target', '17000'));
  // STABLE run_id so re-running the same command RESUMES from checkpoints.
  const runId = val('--run-id', smoke ? 'smoke' : 'full');
  const outDir = path.join(__dirname, '..', 'output', runId);
  ensureDir(outDir);
  // Net yield after the LLM classifier (~0.33 pre-classify * ~0.7 keep-rate ~= 0.22).
  const YIELD_GUESS = Number(val('--yield', '0.22'));
  const wantVerified = smoke ? smokeN : target;
  const candidates = Number(val('--candidates', String(Math.ceil(wantVerified / YIELD_GUESS))));

  const log = (step, data) => console.log(`${new Date().toISOString()} [${step}]`, JSON.stringify(data));
  console.log(`\n=== Cidroy TAM scrape — run ${runId} (${smoke ? 'SMOKE ' + smokeN : 'FULL target ' + target}) ===`);
  console.log(`env: ${K._envPath} | deepinfra: ${K.DEEPINFRA_KEY ? 'on' : 'OFF'} | source target: ${candidates} candidates`);
  const t0 = Date.now();

  const s1 = await stageSource(K, candidates, outDir, log);
  const sC = await stageClassify(K, s1.people, outDir, log);
  const s2 = await stageEmail(K, sC.kept, outDir, log);
  const s3 = await stageVerify(K, s2.withEmail, outDir, log);
  const s4 = stageExport(s3.verified, outDir, log);

  const summary = {
    run_id: runId, mode: smoke ? 'smoke' : 'full', elapsed_s: Math.round((Date.now() - t0) / 1000),
    tam_total_results: s1.stats.total_results,
    funnel: { sourced: s1.people.length, after_classify: sC.stats.people_kept, with_email: s2.stats.found, verified_ok: s4.stats.final },
    classify: { companies: sC.stats.companies, kept: sC.stats.keep, dropped: sC.stats.drop },
    rates: {
      classify_keep_rate: sC.stats.companies ? +(sC.stats.keep / sC.stats.companies).toFixed(3) : 0,
      email_find_rate: s2.stats.input ? +(s2.stats.found / s2.stats.input).toFixed(3) : 0,
      mv_ok_rate: s3.stats.input ? +(s3.stats.ok / s3.stats.input).toFixed(3) : 0,
      net_sourced_to_verified: s1.people.length ? +(s4.stats.final / s1.people.length).toFixed(3) : 0,
    },
    billed_calls: { search: s1.stats.search_calls, classify: sC.stats.to_classify, email_enrich: s2.stats.email_calls, million_verifier: s3.stats.mv_calls },
    verify_breakdown: { ok: s3.stats.ok, catch_all: s3.stats.catch_all, invalid: s3.stats.invalid, unknown: s3.stats.unknown, disposable: s3.stats.disposable, error: s3.stats.error },
    output_csv: s4.file,
  };
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log('\n=== SUMMARY ===');
  console.log(JSON.stringify(summary, null, 2));
  console.log(`\nFinal CSV → ${s4.file}`);
}

if (require.main === module) {
  main().catch((e) => { console.error('FATAL', e); process.exit(1); });
}
