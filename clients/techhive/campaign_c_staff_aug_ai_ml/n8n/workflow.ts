/**
 * Deployed n8n workflow: zRIGcUQcB2TBMSAS (v7 — high-volume + parallel + retry)
 * URL: https://n8n.intentledsales.com/workflow/zRIGcUQcB2TBMSAS
 *
 * Trigger: every Monday 09:00 (n8n instance TZ)
 *
 * VALIDATED in actual n8n browser execution `176644` on 2026-05-25 at 14:24:
 *   - Total wall time: 10m 2s
 *   - Stage 5 result: input=13, uploaded=10, skipped_in_campaign=3, failed=0
 *   - 10 new ICP-fit leads added to the campaign (sizes 1-10 / 11-50, US/CA HQ)
 *
 * Pipeline (one Code node per stage; each uses Node `https` since n8n's
 * sandbox lacks global fetch):
 *   Stage 1   JSearch — 8 AI/ML roles x US+CA x 10 pages = up to 1600 jobs,
 *             concurrency 8, 429/5xx retry with exponential backoff to 10s
 *   Stage 1b  ICP filter — BlitzAPI domain->LI + company enrich (concurrency
 *             10), drop companies outside headcount 1-10/11-50, US/CA HQ,
 *             excluded-industry list (regulated/mega-corp/agency competitor)
 *   Stage 2   DM finder — BlitzAPI Waterfall ICP (concurrency 8), fallback
 *             Employee Finder
 *   Stage 3   Email — BlitzAPI find-work-email + free MX-check verification
 *             floor via Google DoH (Instantly verify endpoint attempted
 *             first, degrades on 402/403 'no_credits')
 *   Stage 4   Personalize — Deepinfra GPT-OSS-20B extracts tech_skills,
 *             company_description, usecase from the job description
 *             (concurrency 6)
 *   Stage 5   Upload — fetch existing campaign leads (dedupe), then push
 *             new leads to Instantly campaign with custom_variables for
 *             email template placeholders + ICP audit fields
 *
 * Re-deploy by running:
 *   mcp__n8n-mcp__update_workflow({ workflowId: 'zRIGcUQcB2TBMSAS', code: <this file's contents> })
 *
 * Followed by mcp__n8n-mcp__publish_workflow({ workflowId: 'zRIGcUQcB2TBMSAS' }).
 */
import { workflow, node, trigger, sticky } from '@n8n/workflow-sdk';

const INSTANTLY_KEY = 'YmI0OWE1YTktNDNjMC00ZDMwLWFlMjctMGIzMmJlMTRkNmQ2OnNtUkFKQmR2SXJrdg==';
const INSTANTLY_CAMPAIGN_ID = 'dfd51d7d-f85f-4ab5-8f4b-8e9d0d507267';
const RAPIDAPI_KEY = '8367fed8c8msha05fce04361f804p115903jsn7677774c7e88';
const BLITZAPI_KEY = 'blitz_mkbWaJvTNLHs525Aegh4W9gt';
const DEEPINFRA_KEY = 'wOaRky1fcun3LBqaVTzA6zU4IQ6Y7FSF';

const HELPERS = `
const https = require('https');
const { URL: URLClass } = require('url');
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function _rawHttp(url, opts) {
  opts = opts || {};
  const method = opts.method || 'GET';
  const headers = opts.headers || {};
  const bodyStr = opts.body != null ? (typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body)) : null;
  const u = new URLClass(url);
  const reqOpts = { method, hostname: u.hostname, port: u.port || 443, path: u.pathname + u.search, headers: Object.assign({}, headers, bodyStr ? { 'Content-Length': Buffer.byteLength(bodyStr) } : {}), timeout: 30000 };
  return new Promise((resolve) => {
    const req = https.request(reqOpts, (res) => {
      let data = '';
      res.on('data', (c) => { data += c; });
      res.on('end', () => { let parsed = null; try { parsed = JSON.parse(data); } catch (e) {} resolve({ ok: res.statusCode < 400, status: res.statusCode, json: parsed, text: data, headers: res.headers }); });
    });
    req.on('error', () => resolve({ ok: false, status: 0, json: null, text: '' }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0, json: null, text: '' }); });
    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}
async function httpJson(url, opts, maxRetries) {
  if (maxRetries == null) maxRetries = 3;
  let delay = 1000;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const r = await _rawHttp(url, opts);
    if (r.status === 429 || r.status >= 500 || r.status === 0) {
      if (attempt === maxRetries) return r;
      const retryAfter = r.headers && r.headers['retry-after'] ? Math.max(1000, parseInt(r.headers['retry-after']) * 1000) : delay;
      await sleep(retryAfter);
      delay = Math.min(delay * 2, 10000);
      continue;
    }
    return r;
  }
  return { ok: false, status: 0, json: null, text: '' };
}
async function pMap(items, concurrency, fn) {
  const results = new Array(items.length);
  let idx = 0;
  const N = Math.min(concurrency, items.length);
  const workers = [];
  for (let w = 0; w < N; w++) {
    workers.push((async () => {
      while (true) {
        const i = idx++;
        if (i >= items.length) return;
        try { results[i] = await fn(items[i], i); } catch (e) { results[i] = null; }
      }
    })());
  }
  await Promise.all(workers);
  return results;
}
`;

const STAGE_1_CODE = HELPERS + `
const RAPIDAPI_KEY = '${RAPIDAPI_KEY}';
const ROLES = ['Machine Learning Engineer','ML Engineer','Deep Learning Engineer','NLP Engineer','Computer Vision Engineer','AI Research Engineer','Applied AI Engineer','AI Engineer'];
const COUNTRIES = ['US', 'CA'];
const PAGES_PER_ROLE = 10;
const CONCURRENCY = 8;
const EXCLUDE = new Set(['google','alphabet','meta','facebook','amazon','aws','apple','microsoft','azure','openai','anthropic','nvidia','intel','ibm','oracle','salesforce','tesla','spacex','netflix','uber','lyft','airbnb','stripe','shopify','snowflake','databricks','palantir','twitter','x corp','linkedin','tiktok','bytedance','deepmind','github','gitlab','robert half','kforce','teksystems','insight global','randstad','hays','experis','adecco','michael page','deloitte','accenture','cognizant','infosys','tata consultancy','tcs','wipro','capgemini','mindtree','jobot','lensa','jobleads','ladders','ziprecruiter','talent.com','diversity recruiter','joblist','dice','glassdoor','indeed','monster','simplyhired','workable','greenhouse']);
const isExcluded = (name) => { const n = (name || '').toLowerCase(); for (const k of EXCLUDE) if (n.includes(k)) return true; return false; };
const cleanDomain = (s) => { if (!s) return ''; s = s.toLowerCase().trim(); if (s.includes('://')) s = s.split('://')[1]; if (s.startsWith('www.')) s = s.slice(4); return s.split('/')[0].split('?')[0].replace(/\\.+$/, ''); };
const jobs = [];
for (const role of ROLES) for (const country of COUNTRIES) for (let page = 1; page <= PAGES_PER_ROLE; page++) jobs.push({ role, country, page });
let stats = { queries_total: jobs.length, queries_ok: 0, queries_failed: 0, raw_jobs: 0 };
const pageResults = await pMap(jobs, CONCURRENCY, async (j) => {
  const u = 'https://jsearch.p.rapidapi.com/search?query=' + encodeURIComponent(j.role + ' in ' + j.country) + '&page=' + j.page + '&num_pages=1&country=' + j.country.toLowerCase() + '&date_posted=week&employment_types=FULLTIME';
  const r = await httpJson(u, { headers: { 'x-rapidapi-host': 'jsearch.p.rapidapi.com', 'x-rapidapi-key': RAPIDAPI_KEY }});
  if (!r.ok || !r.json) { stats.queries_failed++; return []; }
  stats.queries_ok++;
  return (r.json.data || []).map(d => Object.assign({}, d, { _role_query: j.role }));
});
let rawJobs = [];
for (const arr of pageResults) if (Array.isArray(arr)) rawJobs.push(...arr);
stats.raw_jobs = rawJobs.length;
const perCompany = new Map();
const roleCounts = new Map();
for (const j of rawJobs) {
  const name = (j.employer_name || '').trim();
  if (!name || isExcluded(name)) continue;
  const domain = cleanDomain(j.employer_website || '');
  if (!domain) continue;
  const key = domain;
  if (!roleCounts.has(key)) roleCounts.set(key, new Set());
  roleCounts.get(key).add(j._role_query);
  const existing = perCompany.get(key);
  const fresh = { employer_name: name, employer_website: domain, employer_linkedin: (j.employer_linkedin || '').trim(), employer_logo: (j.employer_logo || '').trim(), job_title: (j.job_title || '').trim(), job_id: (j.job_id || '').trim(), job_apply_link: (j.job_apply_link || '').trim(), job_posted_at: (j.job_posted_at_datetime_utc || '').trim(), job_city: (j.job_city || '').trim(), job_state: (j.job_state || '').trim(), job_country: (j.job_country || '').trim(), job_description_snippet: (j.job_description || '').slice(0, 400), job_role_query: j._role_query };
  if (!existing || (fresh.job_posted_at > existing.job_posted_at)) perCompany.set(key, fresh);
}
const rows = [];
for (const [key, row] of perCompany.entries()) rows.push(Object.assign({}, row, { job_count_for_company: roleCounts.get(key).size, all_roles_seen: [...roleCounts.get(key)].sort().join('|') }));
rows.sort((a, b) => b.job_count_for_company - a.job_count_for_company);
stats.unique_companies = rows.length;
console.log('STAGE_1 stats:', JSON.stringify(stats));
return rows.map(r => ({ json: r }));
`;

const STAGE_1B_CODE = HELPERS + `
const BLITZ = '${BLITZAPI_KEY}';
const CONCURRENCY = 10;
const ALLOWED = new Set(['1-10', '11-50']);
const ALLOWED_HQ = new Set(['US', 'CA']);
const EXCLUDE_INDUSTRY = ['banking','financial services','insurance','investment management','investment banking','credit cards','wealth management','government','public administration','defense','military','higher education','primary/secondary education','hospitals & health care','pharmaceutical','biotechnology','utilities','oil & gas','mining','telecommunications','airlines'];
const isExcludedIndustry = (i) => { const s = (i || '').toLowerCase(); return EXCLUDE_INDUSTRY.some(k => s.includes(k)); };
const cleanLi = (u) => { if (!u) return ''; let s = u.toLowerCase().trim(); if (!s.startsWith('http')) s = 'https://' + s; return s.replace(/\\/$/, ''); };
const headers = { 'x-api-key': BLITZ, 'Content-Type': 'application/json' };
async function domainToLi(domain) { if (!domain) return ''; const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/domain-to-linkedin', { method: 'POST', headers, body: { domain } }); if (!r.ok || !r.json) return ''; return r.json.found ? cleanLi(r.json.company_linkedin_url || '') : ''; }
async function enrichCompany(li) { if (!li) return null; const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/company', { method: 'POST', headers, body: { company_linkedin_url: li } }); if (!r.ok || !r.json || !r.json.found) return null; return r.json.company || r.json; }
const input = $input.all().map(i => i.json);
let stats = { input: input.length, qualified: 0, no_li: 0, no_enrich: 0, size_excluded: 0, industry_excluded: 0, hq_excluded: 0 };
const enrichedAll = await pMap(input, CONCURRENCY, async (c) => {
  let li = cleanLi(c.employer_linkedin || '');
  if (!li && c.employer_website) li = await domainToLi(c.employer_website);
  if (!li) { stats.no_li++; return null; }
  const enriched = await enrichCompany(li);
  if (!enriched) { stats.no_enrich++; return null; }
  return { c, li, enriched };
});
const out = [];
for (const r of enrichedAll) {
  if (!r) continue;
  const { c, li, enriched } = r;
  const size = (enriched.size || '').trim();
  const industry = (enriched.industry || '').trim();
  const empLi = enriched.employees_on_linkedin || 0;
  const hq = enriched.hq || {};
  const hqCountry = (hq.country_code || '').toUpperCase();
  if (!ALLOWED.has(size)) { stats.size_excluded++; continue; }
  if (isExcludedIndustry(industry)) { stats.industry_excluded++; continue; }
  if (hqCountry && !ALLOWED_HQ.has(hqCountry)) { stats.hq_excluded++; continue; }
  if (empLi && empLi > 60) { stats.size_excluded++; continue; }
  out.push(Object.assign({}, c, { company_linkedin_url: li, company_size_bucket: size, company_industry: industry, company_employees_on_linkedin: empLi, company_hq_country: hqCountry, company_hq_city: hq.city || '', company_founded_year: enriched.founded_year, company_about: (enriched.about || '').slice(0, 500) }));
  stats.qualified++;
}
console.log('STAGE_1B stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_2_CODE = HELPERS + `
const BLITZ = '${BLITZAPI_KEY}';
const CONCURRENCY = 8;
const headers = { 'x-api-key': BLITZ, 'Content-Type': 'application/json' };
const CASCADE = [
  { include_title: ['Founder','Co-Founder','CEO','Chief Executive Officer','President & Founder'], exclude_title: ['assistant','intern','former','ex-','advisor'], location: ['NORTH_AMERICA'], include_headline_search: false },
  { include_title: ['CTO','Chief Technology Officer','VP Engineering','VP of Engineering','Head of Engineering'], exclude_title: ['assistant','intern','former','ex-'], location: ['NORTH_AMERICA'], include_headline_search: false },
  { include_title: ['Head of AI','Head of Machine Learning','Head of Data','VP AI','VP Machine Learning','VP Data','Director of Engineering','Director of AI','Director of Machine Learning'], exclude_title: ['assistant','intern','former','ex-'], location: ['NORTH_AMERICA'], include_headline_search: false }
];
const cleanLi = (u) => { if (!u) return ''; let s = u.toLowerCase().trim(); if (!s.startsWith('http')) s = 'https://' + s; return s.replace(/\\/$/, ''); };
async function waterfall(li) { const r = await httpJson('https://api.blitz-api.ai/v2/search/waterfall-icp-keyword', { method: 'POST', headers, body: { company_linkedin_url: li, cascade: CASCADE, max_results: 1 } }); if (!r.ok || !r.json) return []; return r.json.results || []; }
async function employeeFinder(li) { const r = await httpJson('https://api.blitz-api.ai/v2/search/employee-finder', { method: 'POST', headers, body: { company_linkedin_url: li, job_level: ['C-Team','VP','Director'], max_results: 1, page: 1 } }); if (!r.ok || !r.json) return []; return r.json.results || []; }
const personFromWaterfall = (res) => { const p = res.person || {}; const exp = (p.experiences || [{}])[0]; return { first_name: (p.first_name || '').trim(), last_name: (p.last_name || '').trim(), title: (exp.job_title || p.headline || '').trim(), headline: (p.headline || '').trim(), linkedin_url: cleanLi(p.linkedin_url || ''), person_country: (p.location || {}).country_code || '', person_city: (p.location || {}).city || '', blitz_icp_rank: res.ranking, blitz_icp_layer: res.icp }; };
const personFromEf = (res) => { const exp = (res.experiences || [{}])[0]; return { first_name: (res.first_name || '').trim(), last_name: (res.last_name || '').trim(), title: (exp.job_title || res.headline || '').trim(), headline: (res.headline || '').trim(), linkedin_url: cleanLi(res.linkedin_url || ''), person_country: (res.location || {}).country_code || '', person_city: (res.location || {}).city || '', blitz_icp_rank: null, blitz_icp_layer: null }; };
const input = $input.all().map(i => i.json);
let stats = { input: input.length, waterfall_hits: 0, fallback_hits: 0, no_dm: 0 };
const dmResults = await pMap(input, CONCURRENCY, async (c) => {
  const li = cleanLi(c.company_linkedin_url || c.employer_linkedin || '');
  if (!li) return null;
  let results = await waterfall(li);
  let dmSource = 'waterfall';
  if (!results.length) { results = await employeeFinder(li); dmSource = 'employee_finder'; }
  if (!results.length) { stats.no_dm++; return null; }
  if (dmSource === 'waterfall') stats.waterfall_hits++; else stats.fallback_hits++;
  const p = dmSource === 'waterfall' ? personFromWaterfall(results[0]) : personFromEf(results[0]);
  if (!p.first_name || !p.last_name) { stats.no_dm++; return null; }
  return { c, li, p, dmSource };
});
const out = [];
for (const r of dmResults) {
  if (!r) continue;
  const { c, li, p, dmSource } = r;
  out.push(Object.assign({}, p, { company_name: c.employer_name || '', company_domain: c.employer_website || '', company_linkedin_url: li, company_size_bucket: c.company_size_bucket || '', company_industry: c.company_industry || '', company_employees_on_linkedin: c.company_employees_on_linkedin || '', company_hq_country: c.company_hq_country || '', company_hq_city: c.company_hq_city || '', company_about: c.company_about || '', job_title_hiring: c.job_title || '', job_id: c.job_id || '', job_apply_link: c.job_apply_link || '', job_posted_at: c.job_posted_at || '', job_city: c.job_city || '', job_state: c.job_state || '', job_country: c.job_country || '', job_description_snippet: c.job_description_snippet || '', job_role_query: c.job_role_query || '', job_count_for_company: c.job_count_for_company || 1, all_roles_seen: c.all_roles_seen || '', dm_source: dmSource }));
}
console.log('STAGE_2 stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_3_CODE = HELPERS + `
const BLITZ = '${BLITZAPI_KEY}';
const INSTANTLY = '${INSTANTLY_KEY}';
const CONCURRENCY = 8;
const headers = { 'x-api-key': BLITZ, 'Content-Type': 'application/json' };
async function blitzEmail(li) { if (!li) return { found: false, email: '', all_emails: [] }; const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/email', { method: 'POST', headers, body: { person_linkedin_url: li } }); if (!r.ok || !r.json) return { found: false, email: '', all_emails: [] }; return { found: !!r.json.found && !!r.json.email, email: (r.json.email || '').toLowerCase(), all_emails: r.json.all_emails || [] }; }
const mxCache = new Map();
async function mxCheck(domain) { if (!domain) return false; if (mxCache.has(domain)) return mxCache.get(domain); const r = await httpJson('https://dns.google/resolve?name=' + encodeURIComponent(domain) + '&type=MX'); if (!r.ok || !r.json) { mxCache.set(domain, false); return false; } const ok = (r.json.Answer || []).some(a => a.type === 15); mxCache.set(domain, ok); return ok; }
async function instantlyVerify(email) { const r = await httpJson('https://api.instantly.ai/api/v2/email-verification', { method: 'POST', headers: { Authorization: 'Bearer ' + INSTANTLY, 'Content-Type': 'application/json' }, body: { email } }); if (r.status === 402 || r.status === 403) return { verified: false, status: 'no_credits' }; if (!r.ok || !r.json) return { verified: false, status: 'error' }; const status = (r.json.verification_status || r.json.status || '').toLowerCase(); return { verified: ['valid','accept_all','deliverable','ok'].includes(status), status }; }
const input = $input.all().map(i => i.json);
let stats = { input: input.length, blitz_found: 0, instantly_verified: 0, mx_passed: 0, no_email: 0, no_mx: 0, with_email_final: 0, instantly_no_credits: 0 };
const results = await pMap(input, CONCURRENCY, async (row) => {
  const li = (row.linkedin_url || '').toLowerCase();
  const blitz = await blitzEmail(li);
  if (!blitz.email) { stats.no_email++; return null; }
  stats.blitz_found++;
  let verified = false; let source = '';
  const iv = await instantlyVerify(blitz.email);
  if (iv.status === 'no_credits') stats.instantly_no_credits++;
  if (iv.verified) { verified = true; source = 'instantly'; stats.instantly_verified++; }
  const domain = blitz.email.split('@')[1] || '';
  const mxOk = await mxCheck(domain);
  if (mxOk && !verified) { source = 'mx_check'; stats.mx_passed++; }
  if (!mxOk && !verified) { stats.no_mx++; return null; }
  return Object.assign({}, row, { email: blitz.email, email_provider: 'blitz', email_verified: (verified || mxOk) ? 'yes' : 'no', email_verification_source: source || 'unverified' });
});
const out = results.filter(x => x);
stats.with_email_final = out.length;
console.log('STAGE_3 stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_4_CODE = HELPERS + `
const DEEPINFRA = '${DEEPINFRA_KEY}';
const CONCURRENCY = 6;
const ROLE_PATTERNS = [[/(senior|sr|staff|principal|lead)?\\s*(machine learning|ml)\\s+engineer/i, 'ML Engineer'], [/(senior|sr|staff|principal|lead)?\\s*(deep learning|dl)\\s+engineer/i, 'Deep Learning Engineer'], [/(senior|sr|staff|principal|lead)?\\s*(natural language processing|nlp)\\s+engineer/i, 'NLP Engineer'], [/(senior|sr|staff|principal|lead)?\\s*(computer vision|cv)\\s+engineer/i, 'Computer Vision Engineer'], [/(senior|sr|staff|principal|lead)?\\s*(ai|artificial intelligence)\\s+research\\s+engineer/i, 'AI Research Engineer'], [/(senior|sr|staff|principal|lead)?\\s*applied\\s+ai\\s+engineer/i, 'Applied AI Engineer'], [/(senior|sr|staff|principal|lead)?\\s*(ai|artificial intelligence)\\s+engineer/i, 'AI Engineer']];
const normalizeRole = (t) => { for (const pair of ROLE_PATTERNS) { if (pair[0].test(t || '')) return pair[1]; } const words = (t || '').replace(/[(\\[].*?[)\\]]/g, '').split(/\\s+/).slice(0, 4); return words.join(' ').trim() || 'AI/ML Engineer'; };
async function llm(systemMsg, userMsg) { const r = await httpJson('https://api.deepinfra.com/v1/openai/chat/completions', { method: 'POST', headers: { Authorization: 'Bearer ' + DEEPINFRA, 'Content-Type': 'application/json' }, body: { model: 'openai/gpt-oss-20b', messages: [{ role: 'system', content: systemMsg }, { role: 'user', content: userMsg }], max_tokens: 400, temperature: 0.3 } }); if (!r.ok || !r.json) return ''; return (((r.json.choices || [])[0] || {}).message || {}).content || ''; }
const SYSTEM = "You are an analyst extracting structured info for B2B sales personalization. Always reply with strict JSON only - no commentary, no markdown fence. Be specific. If a field can't be determined, use null.";
const input = $input.all().map(i => i.json);
let stats = { input: input.length, llm_success: 0, llm_parse_failed: 0 };
const results = await pMap(input, CONCURRENCY, async (row) => {
  const merged = Object.assign({}, row);
  merged.role_being_hired = normalizeRole(row.job_title_hiring || '');
  merged.fallback_role = 'AI Engineer';
  const user = 'Company: ' + (row.company_name || '') + '\\nWebsite: ' + (row.company_domain || '') + '\\nHiring for role: ' + (row.job_title_hiring || '') + '\\n\\nJob description snippet:\\n"""\\n' + (row.job_description_snippet || '').slice(0, 1200) + '\\n"""\\n\\nReturn JSON with these keys:\\n- tech_skills: a short string listing the 2-4 most important technical skills/tools the role requires (comma-separated, e.g. "PyTorch, LLMs, Python"). Pull these from the job description.\\n- company_description: a single short sentence describing what the company actually builds or does, in plain language (no marketing speak). Max 14 words.\\n- usecase: a single sentence describing the product/feature/system the new hire will work on. Max 18 words. Use specific nouns, not generic ones.';
  const raw = await llm(SYSTEM, user);
  let parsed = null;
  const m = raw.match(/\\{[\\s\\S]*\\}/);
  if (m) { try { parsed = JSON.parse(m[0]); stats.llm_success++; } catch (e) { stats.llm_parse_failed++; } } else { stats.llm_parse_failed++; }
  merged.tech_skills = (parsed && parsed.tech_skills) || 'Python, LLMs, modern ML stack';
  merged.company_description = (parsed && parsed.company_description) || '';
  merged.usecase = (parsed && parsed.usecase) || '';
  return merged;
});
console.log('STAGE_4 stats:', JSON.stringify(stats));
return results.map(r => ({ json: r }));
`;

const STAGE_5_CODE = HELPERS + `
const INSTANTLY = '${INSTANTLY_KEY}';
const CAMPAIGN = '${INSTANTLY_CAMPAIGN_ID}';
const H = { Authorization: 'Bearer ' + INSTANTLY, 'Content-Type': 'application/json' };
async function fetchExisting() {
  const set = new Set();
  let cursor = null;
  for (let i = 0; i < 200; i++) {
    const body = { campaign: CAMPAIGN, limit: 100 };
    if (cursor) body.starting_after = cursor;
    const r = await httpJson('https://api.instantly.ai/api/v2/leads/list', { method: 'POST', headers: H, body });
    if (!r.ok || !r.json) break;
    const items = r.json.items || r.json.data || r.json.leads || [];
    if (!items.length) break;
    for (const l of items) if (l.email) set.add(l.email.toLowerCase().trim());
    cursor = r.json.next_starting_after || r.json.next_cursor;
    if (!cursor || items.length < 100) break;
  }
  return set;
}
async function uploadOne(lead) {
  const payload = { campaign: CAMPAIGN, email: lead.email, first_name: lead.first_name || '', last_name: lead.last_name || '', company_name: lead.company_name || '', website: lead.company_domain || '', skip_if_in_workspace: false, skip_if_in_campaign: true, verify_leads_on_import: false, custom_variables: { role_being_hired: lead.role_being_hired || 'AI Engineer', tech_skills: lead.tech_skills || 'Python, ML stack', usecase: lead.usecase || '', company_description: lead.company_description || '', job_apply_link: lead.job_apply_link || '', job_city: lead.job_city || '', job_title_hiring: lead.job_title_hiring || '', linkedin_url: lead.linkedin_url || '', person_title: lead.title || '', icp_size_bucket: lead.company_size_bucket || '', icp_industry: lead.company_industry || '', icp_hq_country: lead.company_hq_country || '', icp_employees_li: String(lead.company_employees_on_linkedin || '') } };
  const r = await httpJson('https://api.instantly.ai/api/v2/leads', { method: 'POST', headers: H, body: payload });
  if (!r.ok) return { ok: false, error: (r.text || '').slice(0, 300) };
  return { ok: true, body: r.json };
}
const input = $input.all().map(i => i.json);
let stats = { input: input.length, uploaded: 0, skipped_in_campaign: 0, failed: 0 };
const existing = await fetchExisting();
stats.existing_in_campaign = existing.size;
const uploadResults = await pMap(input, 4, async (lead) => {
  const e = (lead.email || '').toLowerCase().trim();
  if (!e) return { skip: true };
  if (existing.has(e)) return { dup: true };
  const res = await uploadOne(lead);
  if (res.ok) { existing.add(e); return { uploaded: true }; }
  return { failed: true, email: e, error: res.error };
});
for (const r of uploadResults) {
  if (!r) continue;
  if (r.uploaded) stats.uploaded++;
  else if (r.dup) stats.skipped_in_campaign++;
  else if (r.failed || r.skip) stats.failed++;
}
stats.campaign = CAMPAIGN;
stats.timestamp = new Date().toISOString();
console.log('STAGE_5 stats:', JSON.stringify(stats));
return [{ json: stats }];
`;

const mondayTrigger = trigger({
  type: 'n8n-nodes-base.scheduleTrigger',
  version: 1.3,
  config: { name: 'Every Monday 09:00', parameters: { rule: { interval: [{ field: 'weeks', weeksInterval: 1, triggerAtDay: [1], triggerAtHour: 9, triggerAtMinute: 0 }] } }, position: [240, 400] },
  output: [{ runStartedAt: '2026-06-01T09:00:00Z' }],
});

const stage1 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 1 - JSearch (10pg parallel x8)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_1_CODE }, position: [540, 400] }, output: [{ employer_name: 'Sample', employer_website: 'sample.com', job_title: 'AI Engineer' }] });
const stage1b = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 1b - ICP Filter (parallel x10)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_1B_CODE }, position: [840, 400] }, output: [{ employer_name: 'Sample', company_size_bucket: '11-50' }] });
const stage2 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 2 - DM Finder (parallel x8)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_2_CODE }, position: [1140, 400] }, output: [{ first_name: 'Sample', last_name: 'Founder' }] });
const stage3 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 3 - Email + MX (parallel x8)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_3_CODE }, position: [1440, 400] }, output: [{ first_name: 'Sample', email: 'founder@sample.com' }] });
const stage4 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 4 - Personalize (parallel x6)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_4_CODE }, position: [1740, 400] }, output: [{ first_name: 'Sample', tech_skills: 'PyTorch' }] });
const stage5 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 5 - Instantly Upload (parallel x4)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_5_CODE }, position: [2040, 400] }, output: [{ uploaded: 10, skipped_in_campaign: 3, failed: 0, campaign: INSTANTLY_CAMPAIGN_ID }] });
const note = sticky({ config: { name: 'Pipeline v7 high-volume', parameters: { content: 'TechHive Campaign C v7 — Monday 9am. PAID RapidAPI key (50K/mo, 10 req/sec). JSearch 8 roles x US+CA x 10 pages = 160 queries at concurrency 8. NO caps. Blitz parallel x10/8. VALIDATED 2026-05-25 exec #176644: 10m 2s, +10 ICP-fit leads uploaded.', height: 200, width: 460 }, position: [240, 80] } });

export default workflow('techhive-campaign-c-staff-aug', 'TechHive - Campaign C - Staff Aug (AI/ML hires US+CA)')
  .add(note)
  .add(mondayTrigger)
  .to(stage1)
  .to(stage1b)
  .to(stage2)
  .to(stage3)
  .to(stage4)
  .to(stage5);
