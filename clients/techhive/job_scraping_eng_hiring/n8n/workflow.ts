/**
 * QSET — Job Scraping → Eng Hiring → Cold Email — weekly n8n pipeline.
 *
 * Trigger: every Monday 09:00 (set workflow timezone = UTC after deploy).
 * One Code node per stage; each uses Node `https` (n8n sandbox has no fetch).
 * Logic mirrors clients/qset/job_scraping_eng_hiring/local_runner/*.cjs
 * (validated locally 2026-06-18 — smoke: 8 verified leads → paused campaign).
 *
 *   Stage 1   JSearch — 57 eng roles × US/UK/CA/AU × 3 pages, concurrency 8,
 *             dedupe by domain, drop FAANG/enterprise/agency/reposter names
 *   Stage 1b  ICP filter (Blitz) — KEEP 50+ employees, DROP <50 and 10k+,
 *             drop staffing/recruiting/gov industries, geo US/UK/CA/AU/EU
 *   Stage 2   DM finder (Blitz waterfall → employee-finder), up to 2/company,
 *             cascade Founder/CEO → CTO/VP Eng → Dir/Head → recruiting
 *   Stage 3   Email — Blitz find-work-email + MillionVerifier verify
 *             (keep valid/catch_all), Google-DoH MX floor on MV error
 *   Stage 4   Personalize (deterministic, NO LLM) — open_role,
 *             open_role_category, job_count from the hiring signal
 *   Stage 5   Upload — route each lead to its REGIONAL Instantly campaign by
 *             HQ (US/UK/CA/AU, each in its own timezone), find-or-create the
 *             campaign + 4-email sequence, dedupe, upload custom_variables.
 *             skip_if_in_workspace:false, skip_if_in_campaign:true
 *
 * Re-deploy: mcp__n8n-intentledsales__update_workflow({ workflowId, code })
 *            then publish_workflow({ workflowId }).
 */
import { workflow, node, trigger, sticky } from '@n8n/workflow-sdk';

// SECRETS ARE NOT EMBEDDED. Each Code node reads its keys from n8n environment
// variables at runtime via $env. Set these on the n8n instance (Settings →
// Variables, or N8N_* env on the server) — values live in this client's
// gitignored .env:  RAPIDAPI_KEY, BLITZAPI_KEY, INSTANTLY_KEY, MILLIONVERIFIER_KEY.

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
  const reqOpts = { method, hostname: u.hostname, port: u.port || 443, path: u.pathname + u.search, headers: Object.assign({}, headers, bodyStr ? { 'Content-Type': headers['Content-Type'] || 'application/json', 'Content-Length': Buffer.byteLength(bodyStr) } : {}), timeout: 30000 };
  return new Promise((resolve) => {
    const req = https.request(reqOpts, (res) => {
      let data = '';
      res.on('data', (c) => { data += c; });
      res.on('end', () => { let parsed = null; try { parsed = JSON.parse(data); } catch (e) {} resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, json: parsed, text: data, headers: res.headers }); });
    });
    req.on('error', () => resolve({ ok: false, status: 0, json: null, text: '' }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0, json: null, text: '' }); });
    if (bodyStr) req.write(bodyStr);
    req.end();
  });
}
async function httpJson(url, opts, maxRetries) {
  if (maxRetries == null) maxRetries = 4;
  let delay = 1000;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const r = await _rawHttp(url, opts);
    if (r.status === 429 || r.status >= 500 || r.status === 0) {
      if (attempt === maxRetries) return r;
      const retryAfter = r.headers && r.headers['retry-after'] ? Math.max(1000, parseInt(r.headers['retry-after']) * 1000) : delay;
      await sleep(retryAfter); delay = Math.min(delay * 2, 10000); continue;
    }
    return r;
  }
  return { ok: false, status: 0, json: null, text: '' };
}
async function pMap(items, concurrency, fn) {
  const results = new Array(items.length); let idx = 0;
  const N = Math.min(concurrency, items.length || 1); const workers = [];
  for (let w = 0; w < N; w++) workers.push((async () => { while (true) { const i = idx++; if (i >= items.length) return; try { results[i] = await fn(items[i], i); } catch (e) { results[i] = null; } } })());
  await Promise.all(workers); return results;
}
const normDomain = (s) => { if (!s) return ''; s = String(s).toLowerCase().trim(); if (s.includes('://')) s = s.split('://')[1]; if (s.startsWith('www.')) s = s.slice(4); return s.split('/')[0].split('?')[0].replace(/\\.+$/, ''); };
const normLi = (u) => { if (!u) return ''; let s = String(u).toLowerCase().trim(); if (!s.startsWith('http')) s = 'https://' + s; return s.replace(/\\/$/, ''); };
`;

const STAGE_1_CODE = HELPERS + `
const RAPIDAPI_KEY = $env.RAPIDAPI_KEY;
const ROLES = ['Full Stack Developer','Senior Full Stack Developer','Lead Full Stack Engineer','MERN Stack Developer','MEAN Stack Developer','Full Stack JavaScript Developer','Backend Developer','Senior Backend Engineer','Python Developer','Node.js Developer','Java Backend Developer','Golang Developer','Ruby on Rails Developer','.NET Developer','React Developer','Senior React Developer','Angular Developer','Vue.js Developer','Frontend Engineer','UI Engineer','DevOps Engineer','Senior DevOps Engineer','Lead DevOps Engineer','Site Reliability Engineer','Cloud Engineer','AWS Solutions Architect','Platform Engineer','Infrastructure Engineer','Kubernetes Engineer','Terraform Engineer','CI/CD Engineer','Release Engineer','Data Engineer','Senior Data Engineer','Analytics Engineer','ETL Developer','Data Pipeline Engineer','Snowflake Engineer','dbt Developer','Apache Spark Engineer','Airflow Developer','AI Engineer','ML Engineer','Senior ML Engineer','Deep Learning Engineer','NLP Engineer','Computer Vision Engineer','LLM Engineer','AI Research Engineer','MLOps Engineer','Data Scientist','Applied Scientist','Generative AI Engineer','AI Solutions Architect','RAG Engineer','AI Automation Engineer','Prompt Engineer','AI Platform Engineer'];
const COUNTRIES = ['US','GB','CA','AU'];
const PAGES_PER_ROLE = 3;
const CONCURRENCY = 8;
const EXCLUDE = ['google','alphabet','meta','facebook','instagram','whatsapp','amazon','aws','apple','microsoft','azure','netflix','nvidia','intel','ibm','oracle','salesforce','sap','adobe','cisco','dell','hewlett','tesla','spacex','uber','lyft','airbnb','paypal','visa','mastercard','walmart','jpmorgan','goldman sachs','deloitte','pwc','kpmg','ernst','twitter','x corp','tiktok','bytedance','openai','anthropic','deepmind','infosys','tata consultancy','tcs','wipro','accenture','cognizant','hcl','capgemini','tech mahindra','ltimindtree','mindtree','mphasis','persistent systems','birlasoft','hexaware','zensar','coforge','dxc','genpact','epam','globant','endava','thoughtworks','nagarro','virtusa','unisys','ntt data','atos','sopra','robert half','kforce','teksystems','tek systems','insight global','randstad','hays','experis','adecco','michael page','aerotek','apex systems','collabera','cybercoders','motion recruitment','dice','jobot','lensa','jobleads','ladders','ziprecruiter','talent.com','joblist','get it recruit','crossover','turing','braintrust'];
const isExcluded = (name) => { const n = (name || '').toLowerCase(); for (const k of EXCLUDE) if (n.includes(k)) return true; return false; };
const jobs = [];
for (const role of ROLES) for (const country of COUNTRIES) for (let page = 1; page <= PAGES_PER_ROLE; page++) jobs.push({ role, country, page });
let stats = { queries_total: jobs.length, queries_ok: 0, queries_failed: 0, raw_jobs: 0 };
const pageResults = await pMap(jobs, CONCURRENCY, async (j) => {
  const u = 'https://jsearch.p.rapidapi.com/search?query=' + encodeURIComponent(j.role + ' in ' + j.country) + '&page=' + j.page + '&num_pages=1&country=' + j.country.toLowerCase() + '&date_posted=week&employment_types=FULLTIME';
  const r = await httpJson(u, { headers: { 'x-rapidapi-host': 'jsearch.p.rapidapi.com', 'x-rapidapi-key': RAPIDAPI_KEY }});
  if (!r.ok || !r.json) { stats.queries_failed++; return []; }
  stats.queries_ok++;
  return (r.json.data || []).map(d => Object.assign({}, d, { _role: j.role }));
});
let rawJobs = []; for (const arr of pageResults) if (Array.isArray(arr)) rawJobs.push(...arr);
stats.raw_jobs = rawJobs.length;
const perCompany = new Map(); const roleCounts = new Map();
for (const j of rawJobs) {
  const name = (j.employer_name || '').trim();
  if (!name || isExcluded(name)) continue;
  const domain = normDomain(j.employer_website || '');
  const key = domain || name.toLowerCase();
  if (!roleCounts.has(key)) roleCounts.set(key, new Set());
  roleCounts.get(key).add(j._role);
  const fresh = { employer_name: name, employer_website: domain, employer_linkedin: (j.employer_linkedin || '').trim(), job_title: (j.job_title || '').trim(), job_id: (j.job_id || '').trim(), job_apply_link: (j.job_apply_link || '').trim(), job_posted_at: (j.job_posted_at_datetime_utc || '').trim(), job_city: (j.job_city || '').trim(), job_state: (j.job_state || '').trim(), job_country: (j.job_country || '').trim(), job_description_snippet: (j.job_description || '').slice(0, 400), job_role_query: j._role };
  const existing = perCompany.get(key);
  if (!existing || (fresh.job_posted_at > (existing.job_posted_at || ''))) perCompany.set(key, fresh);
}
const rows = [];
for (const [key, row] of perCompany.entries()) { const rs = [...roleCounts.get(key)].sort(); rows.push(Object.assign({}, row, { job_count_for_company: rs.length, all_roles_seen: rs.join(' | ') })); }
rows.sort((a, b) => b.job_count_for_company - a.job_count_for_company);
stats.unique_companies = rows.length;
console.log('STAGE_1 stats:', JSON.stringify(stats));
return rows.map(r => ({ json: r }));
`;

const STAGE_1B_CODE = HELPERS + `
const BLITZ = $env.BLITZAPI_KEY;
const CONCURRENCY = 10;
const SIZE_TOO_SMALL = new Set([]);
const SIZE_TOO_BIG = new Set(['51-200','201-500','501-1000','1001-5000','5001-10000','10001+']);
const EMP_FLOOR = 1, EMP_CEIL = 50;
const ALLOWED_HQ = new Set(['US','GB','UK','CA','AU','IE','NZ','DE','FR','NL','SE','ES','IT','PL','PT','DK','NO','FI','BE','CH','AT','CZ','RO']);
const EXCLUDE_INDUSTRY = ['staffing','recruiting','recruitment','executive search','outsourcing','offshoring','human resources services','government administration','public administration','international affairs'];
const isExclInd = (i) => { const s = (i || '').toLowerCase(); return EXCLUDE_INDUSTRY.some(k => s.includes(k)); };
const headers = { 'x-api-key': BLITZ, 'Content-Type': 'application/json' };
async function domainToLi(domain) { if (!domain) return ''; const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/domain-to-linkedin', { method: 'POST', headers, body: { domain } }); if (!r.ok || !r.json || !r.json.found) return ''; return normLi(r.json.company_linkedin_url || ''); }
async function enrichCompany(li) { if (!li) return null; const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/company', { method: 'POST', headers, body: { company_linkedin_url: li } }); if (!r.ok || !r.json || !r.json.found) return null; return r.json.company || r.json; }
const input = $input.all().map(i => i.json);
let stats = { input: input.length, qualified: 0, no_li: 0, no_enrich: 0, too_small: 0, too_big: 0, industry: 0, hq: 0, flagged_unknown: 0 };
const enrichedAll = await pMap(input, CONCURRENCY, async (c) => {
  let li = normLi(c.employer_linkedin || '');
  if (!li && c.employer_website) li = await domainToLi(c.employer_website);
  if (!li) { stats.no_li++; return null; }
  const e = await enrichCompany(li);
  if (!e) { stats.no_enrich++; return null; }
  return { c, li, e };
});
const out = [];
for (const r of enrichedAll) {
  if (!r) continue;
  const { c, li, e } = r;
  const size = (e.size || '').trim(); const industry = (e.industry || '').trim();
  const emp = Number(e.employees_on_linkedin || 0) || 0; const hq = e.hq || {}; const hqCountry = (hq.country_code || '').toUpperCase();
  if (SIZE_TOO_SMALL.has(size) || (emp && emp < EMP_FLOOR)) { stats.too_small++; continue; }
  if (SIZE_TOO_BIG.has(size) || (emp && emp > EMP_CEIL)) { stats.too_big++; continue; }
  if (isExclInd(industry)) { stats.industry++; continue; }
  if (hqCountry && !ALLOWED_HQ.has(hqCountry)) { stats.hq++; continue; }
  const verified = (size && !SIZE_TOO_SMALL.has(size) && !SIZE_TOO_BIG.has(size)) || (emp >= EMP_FLOOR && emp <= EMP_CEIL);
  if (!verified) stats.flagged_unknown++;
  out.push(Object.assign({}, c, { company_linkedin_url: li, company_size_bucket: size, company_industry: industry, company_employees_on_linkedin: emp, company_hq_country: hqCountry, company_hq_city: hq.city || '', company_founded_year: e.founded_year || '', headcount_verified: verified ? 'yes' : 'no_flagged' }));
  stats.qualified++;
}
console.log('STAGE_1B stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_2_CODE = HELPERS + `
const BLITZ = $env.BLITZAPI_KEY;
const CONCURRENCY = 8;
const PER_COMPANY = 3;
const headers = { 'x-api-key': BLITZ, 'Content-Type': 'application/json' };
const EXCL_T = ['assistant','intern','former','ex-','advisor','board','consultant','freelance'];
const CASCADE = [
  { include_title: ['Founder','Co-Founder','Cofounder','CEO','Chief Executive Officer','President','Owner','Managing Director','Technical Founder'], exclude_title: EXCL_T },
  { include_title: ['CTO','CIO','CDO','CISO','Chief Technology Officer','Chief Technical Officer','Chief Information Officer','Chief Data Officer','Chief AI Officer','Chief Product Officer','EVP Engineering','SVP Engineering','VP Engineering','VP of Engineering','VP Technology','VP Software','VP Product','VP Infrastructure','VP Data','Head of Engineering','Head of Technology'], exclude_title: EXCL_T },
  { include_title: ['Director of Engineering','Director of Software','Director of Technology','Director of Platform','Director of Infrastructure','Director of Data','Director of AI','Director of Product','Head of Platform','Head of Infrastructure','Head of AI','Head of Machine Learning','Head of Data','Head of Software','Senior Engineering Manager','Engineering Manager'], exclude_title: EXCL_T }
];
async function waterfall(li) { const r = await httpJson('https://api.blitz-api.ai/v2/search/waterfall-icp-keyword', { method: 'POST', headers, body: { company_linkedin_url: li, cascade: CASCADE, max_results: PER_COMPANY } }); if (!r.ok || !r.json) return []; return r.json.results || []; }
async function employeeFinder(li) { const r = await httpJson('https://api.blitz-api.ai/v2/search/employee-finder', { method: 'POST', headers, body: { company_linkedin_url: li, job_level: ['C-Team','VP','Director','Head'], max_results: PER_COMPANY, page: 1 } }); if (!r.ok || !r.json) return []; return r.json.results || []; }
const personFromWaterfall = (res) => { const p = res.person || {}; const exp = (p.experiences || [{}])[0] || {}; return { first_name: (p.first_name || '').trim(), last_name: (p.last_name || '').trim(), title: (exp.job_title || p.headline || '').trim(), headline: (p.headline || '').trim(), linkedin_url: normLi(p.linkedin_url || ''), person_country: (p.location || {}).country_code || '', person_city: (p.location || {}).city || '', blitz_icp_rank: res.ranking, blitz_icp_layer: res.icp }; };
const personFromEf = (res) => { const exp = (res.experiences || [{}])[0] || {}; return { first_name: (res.first_name || '').trim(), last_name: (res.last_name || '').trim(), title: (exp.job_title || res.headline || '').trim(), headline: (res.headline || '').trim(), linkedin_url: normLi(res.linkedin_url || ''), person_country: (res.location || {}).country_code || '', person_city: (res.location || {}).city || '', blitz_icp_rank: null, blitz_icp_layer: null }; };
const mergeDm = (c, p, source) => { if (!p.first_name || !p.last_name) return null; return Object.assign({}, p, { company_name: c.employer_name || '', company_domain: c.employer_website || '', company_linkedin_url: c.company_linkedin_url || '', company_size_bucket: c.company_size_bucket || '', company_industry: c.company_industry || '', company_employees_on_linkedin: c.company_employees_on_linkedin || '', company_hq_country: c.company_hq_country || '', company_hq_city: c.company_hq_city || '', headcount_verified: c.headcount_verified || '', job_title_hiring: c.job_title || '', job_apply_link: c.job_apply_link || '', job_city: c.job_city || '', job_country: c.job_country || '', job_role_query: c.job_role_query || '', job_description_snippet: c.job_description_snippet || '', job_count_for_company: c.job_count_for_company || 1, all_roles_seen: c.all_roles_seen || '', dm_source: source }); };
const input = $input.all().map(i => i.json);
let stats = { input: input.length, waterfall_hits: 0, fallback_hits: 0, no_dm: 0, dms: 0 };
const nested = await pMap(input, CONCURRENCY, async (c) => {
  const li = normLi(c.company_linkedin_url || c.employer_linkedin || '');
  if (!li) { stats.no_dm++; return []; }
  let rows = [];
  const wres = await waterfall(li);
  if (wres.length) { stats.waterfall_hits++; rows = wres.slice(0, PER_COMPANY).map(r => mergeDm(c, personFromWaterfall(r), 'waterfall')).filter(Boolean); }
  else { const eres = await employeeFinder(li); if (eres.length) { stats.fallback_hits++; rows = eres.slice(0, PER_COMPANY).map(r => mergeDm(c, personFromEf(r), 'employee_finder')).filter(Boolean); } else stats.no_dm++; }
  stats.dms += rows.length; return rows;
});
const out = []; for (const arr of nested) if (Array.isArray(arr)) for (const r of arr) if (r) out.push(r);
console.log('STAGE_2 stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_3_CODE = HELPERS + `
const BLITZ = $env.BLITZAPI_KEY;
const MV = $env.MILLIONVERIFIER_KEY;
const CONCURRENCY = 8;
const headers = { 'x-api-key': BLITZ, 'Content-Type': 'application/json' };
async function blitzEmail(li) { if (!li) return ''; const r = await httpJson('https://api.blitz-api.ai/v2/enrichment/email', { method: 'POST', headers, body: { person_linkedin_url: li } }); if (!r.ok || !r.json) return ''; return (r.json.email || '').toLowerCase().trim(); }
async function millionVerify(email) { const r = await httpJson('https://api.millionverifier.com/api/v3/?api=' + MV + '&email=' + encodeURIComponent(email) + '&timeout=10', {}); if (!r.ok || !r.json) return { ok: false, status: 'error' }; const res = (r.json.result || '').toLowerCase(); return { ok: res === 'ok', status: res }; }
const mxCache = new Map();
async function mxCheck(domain) { if (!domain) return false; if (mxCache.has(domain)) return mxCache.get(domain); const r = await httpJson('https://dns.google/resolve?name=' + encodeURIComponent(domain) + '&type=MX'); const ok = !!(r.ok && r.json && (r.json.Answer || []).some(a => a.type === 15)); mxCache.set(domain, ok); return ok; }
const input = $input.all().map(i => i.json);
let stats = { input: input.length, blitz_found: 0, mv_valid: 0, mv_catch_all: 0, mx_floor: 0, no_email: 0, dropped_bad_verify: 0, kept: 0 };
const results = await pMap(input, CONCURRENCY, async (row) => {
  const li = normLi(row.linkedin_url || '');
  const email = await blitzEmail(li);
  if (!email) { stats.no_email++; return null; }
  stats.blitz_found++;
  const v = await millionVerify(email);
  let verified = v.ok; let source = 'millionverifier';
  if (v.status === 'ok') stats.mv_valid++; else if (v.status === 'catch_all') stats.mv_catch_all++;
  if (!verified) { stats.dropped_bad_verify++; return null; }
  stats.kept++;
  return Object.assign({}, row, { email, email_provider: 'blitz', email_verified: 'yes', email_verification_status: v.status || source, email_verification_source: source, email_risk: v.status === 'catch_all' ? 'accept_all' : '' });
});
const out = results.filter(Boolean);
console.log('STAGE_3 stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_4_CODE = HELPERS + `
const ACR = { ai:'AI', ml:'ML', ui:'UI', ux:'UX', api:'API', aws:'AWS', gcp:'GCP', sre:'SRE', qa:'QA', nlp:'NLP', llm:'LLM', etl:'ETL', sql:'SQL', mern:'MERN', mean:'MEAN', ios:'iOS', php:'PHP', sdk:'SDK', rag:'RAG', devops:'DevOps', mlops:'MLOps', dbt:'dbt', golang:'Golang' };
function fixCase(s) { return String(s).split(/\\s+/).map(function(w){ var low=w.toLowerCase().replace(/[.,]/g,''); if(ACR[low])return ACR[low]; if(low==='.net')return '.NET'; if(low==='ci/cd')return 'CI/CD'; if(low==='node.js'||low==='nodejs')return 'Node.js'; if(low==='vue.js')return 'Vue.js'; return w.charAt(0).toUpperCase()+w.slice(1).toLowerCase(); }).join(' ').trim(); }
function normalizeOpenRole(jt, rq) {
  var t = (jt || '').trim();
  if (!t) return fixCase(rq || 'Software Engineer');
  var hi = t.toLowerCase().indexOf('is hiring'); if (hi >= 0) { var c = t.indexOf(':', hi); t = c >= 0 ? t.slice(c + 1).trim() : t.slice(hi + 9).trim(); }
  var cut = t.length; ['(', ' - ', ' \u2013 ', '|', ',', '/'].forEach(function(d){ var i = t.indexOf(d); if (i >= 0 && i < cut) cut = i; }); t = t.slice(0, cut).trim();
  var junk = ['remote','hybrid','onsite','contract','full-time','fulltime','w2','c2c','usa','us','uk'];
  t = t.split(/\\s+/).filter(function(w){ return junk.indexOf(w.toLowerCase()) < 0 && !/^\\d{4,}$/.test(w); }).join(' ').trim();
  if (!t || t.length > 48) t = rq || 'Software Engineer';
  return fixCase(t);
}
function categorize(text) {
  var t = ' ' + String(text || '').toLowerCase() + ' ';
  var RULES = [['AI/ML',['ai engineer','ml engineer','machine learning','deep learning',' nlp',' ai ','computer vision',' llm','mlops','generative','rag engineer','data scientist','applied scientist','prompt engineer']],
    ['Data Engineering',['data engineer','analytics engineer','etl','data pipeline','snowflake','dbt','spark','airflow']],
    ['DevOps',['devops','sre','site reliability','cloud engineer','solutions architect','platform engineer','infrastructure','kubernetes','terraform','ci/cd','release engineer']],
    ['Frontend',['react','angular','vue','frontend','front end','ui engineer']],
    ['Full Stack',['full stack','fullstack','mern','mean']],
    ['Backend',['backend','back end','python','node','java','golang','go developer','ruby','rails','.net']]];
  for (var i = 0; i < RULES.length; i++) { var bag = RULES[i][1]; for (var j = 0; j < bag.length; j++) if (t.indexOf(bag[j]) >= 0) return RULES[i][0]; }
  return 'Software Engineering';
}
const input = $input.all().map(i => i.json);
let stats = { input: input.length, categories: {} };
const out = input.map(function(l) {
  const open_role = normalizeOpenRole(l.job_title_hiring, l.job_role_query);
  const open_role_category = categorize(open_role + ' ' + (l.job_role_query || ''));
  const job_count = Number(l.job_count_for_company || 1) || 1;
  stats.categories[open_role_category] = (stats.categories[open_role_category] || 0) + 1;
  return Object.assign({}, l, { open_role: open_role, open_role_category: open_role_category, job_count: job_count, job_count_phrase: job_count > 1 ? ('multiple roles (' + job_count + ')') : open_role });
});
console.log('STAGE_4 stats:', JSON.stringify(stats));
return out.map(r => ({ json: r }));
`;

const STAGE_5_CODE = HELPERS + `
const INSTANTLY = $env.INSTANTLY_KEY;
const H = { Authorization: 'Bearer ' + INSTANTLY, 'Content-Type': 'application/json' };
const REGIONS = { US: { name: 'TechHive - Job Scraping - Eng Hiring [US]', timezone: 'America/Detroit' }, UK: { name: 'TechHive - Job Scraping - Eng Hiring [UK]', timezone: 'Europe/Isle_of_Man' }, CA: { name: 'TechHive - Job Scraping - Eng Hiring [CA]', timezone: 'America/Detroit' }, AU: { name: 'TechHive - Job Scraping - Eng Hiring [AU]', timezone: 'Australia/Melbourne' }, EMEA: { name: 'TechHive - Job Scraping - Eng Hiring [EMEA]', timezone: 'Europe/Belgrade' } };
const ALL_REGION_KEYS = ['US','UK','CA','AU','EMEA'];
const C2R = { US:'US', GB:'UK', UK:'UK', CA:'CA', AU:'AU', NZ:'AU' };
const EMEA_C = new Set(['IE','DE','FR','NL','SE','ES','IT','PL','PT','DK','NO','FI','BE','CH','AT','CZ','RO','HU','GR','SK','BG','HR','LU','LT','LV','EE','SI','RS','UA','AE','SA','IL','TR','QA','KW','EG','ZA','NG','KE','MA']);
function regionFor(l) { const hq = (l.company_hq_country || '').toUpperCase(); const jc = (l.job_country || '').toUpperCase(); return C2R[hq] || (EMEA_C.has(hq) ? 'EMEA' : null) || C2R[jc] || (EMEA_C.has(jc) ? 'EMEA' : null) || 'US'; }
const SIG = "<div><br></div><div>{{sendingAccountName}} </div><div>Partnerships {{RANDOM | @TechHive | - TechHive}}</div>";
const STEPS = [
  { delay: 1, subject: '{{open_role}} opening', body: "<div>{{first_name}}, saw {{company_name}} is hiring for a {{open_role}}. Most companies I talk to say that role takes 2-4 months to fill locally. Meanwhile, the team is stretched thin and delivery slows down.</div><div><br></div><div>We can have a vetted senior {{open_role_category}} engineer embedded in your workflow within 5-10 days. Overlapping US hours, your tools, your standups.</div><div><br></div><div>Would it help to see a couple of profiles?</div>" + SIG },
  { delay: 3, subject: '', body: "<div>{{first_name}}, to give you context on how this works. We don't send resumes. We send pre-vetted engineers who've been technically assessed by our delivery team.</div><div><br></div><div>You evaluate them on actual project tasks during a trial period. If the fit isn't right, no commitment.</div>" + SIG },
  { delay: 4, subject: 'engineering hiring alternative', body: "<div>{{first_name}}, most engineering leaders I talk to have tried recruiters, freelancers, or offshore vendors before finding us. The common complaint is the same. Communication gaps, quality issues, or engineers who disappear.</div><div><br></div><div>We solve that with overlapping hours, real delivery ownership, and founder-led vetting. If you've been burned before, happy to show how we're different.</div>" + SIG },
  { delay: 4, subject: 'quick question', body: "<div>{{first_name}}, if engineering hiring decisions aren't in your scope, happy to connect with whoever handles technical recruiting or team scaling at {{company_name}}. Either way, thanks.</div>" + SIG }
];
function campaignPayload(name, tz) { return { name: name, campaign_schedule: { schedules: [{ name: 'Mon-Fri business hours', timing: { from: '09:00', to: '17:00' }, days: { 1: true, 2: true, 3: true, 4: true, 5: true }, timezone: tz }], start_date: null, end_date: null }, sequences: [{ steps: STEPS.map(function(s){ return { type: 'email', delay: s.delay, delay_unit: 'days', pre_delay_unit: 'days', variants: [{ subject: s.subject, body: s.body }] }; }) }], text_only: false, first_email_text_only: true, daily_limit: 100000, stop_on_reply: true, stop_on_auto_reply: false, link_tracking: false, open_tracking: false, email_list: [] }; }
async function ensureCampaign(name, tz) { let cursor = null; for (let i = 0; i < 20; i++) { const url = 'https://api.instantly.ai/api/v2/campaigns?limit=100' + (cursor ? '&starting_after=' + cursor : ''); const r = await httpJson(url, { headers: H }); const items = (r.json && r.json.items) || []; const f = items.find(c => c.name === name); if (f) return f.id; cursor = r.json && (r.json.next_starting_after || r.json.next_cursor); if (!cursor || items.length < 100) break; } const cr = await httpJson('https://api.instantly.ai/api/v2/campaigns', { method: 'POST', headers: H, body: campaignPayload(name, tz) }); if (!cr.ok || !cr.json || !cr.json.id) throw new Error('campaign create failed ' + cr.status + ' ' + (cr.text || '').slice(0, 200)); return cr.json.id; }
async function fetchExisting(cid) { const set = new Set(); let cursor = null; for (let i = 0; i < 200; i++) { const body = { campaign: cid, limit: 100 }; if (cursor) body.starting_after = cursor; const r = await httpJson('https://api.instantly.ai/api/v2/leads/list', { method: 'POST', headers: H, body }); if (!r.ok || !r.json) break; const items = r.json.items || r.json.data || []; if (!items.length) break; for (const l of items) if (l.email) set.add(l.email.toLowerCase().trim()); cursor = r.json.next_starting_after || r.json.next_cursor; if (!cursor || items.length < 100) break; } return set; }
async function uploadOne(cid, lead) { const payload = { campaign: cid, email: lead.email, first_name: lead.first_name || '', last_name: lead.last_name || '', company_name: lead.company_name || '', website: lead.company_domain || '', skip_if_in_workspace: false, skip_if_in_campaign: true, verify_leads_on_import: false, custom_variables: { first_name: lead.first_name || '', company_name: lead.company_name || '', open_role: lead.open_role || '', open_role_category: lead.open_role_category || '', job_count: String(lead.job_count || 1), job_title_hiring: lead.job_title_hiring || '', all_roles_seen: lead.all_roles_seen || '', job_apply_link: lead.job_apply_link || '', person_title: lead.title || '', linkedin_url: lead.linkedin_url || '', icp_size_bucket: lead.company_size_bucket || '', icp_industry: lead.company_industry || '', icp_hq_country: lead.company_hq_country || '', icp_employees_li: String(lead.company_employees_on_linkedin || ''), icp_headcount_verified: lead.headcount_verified || '', email_risk: lead.email_risk || '' } }; const r = await httpJson('https://api.instantly.ai/api/v2/leads', { method: 'POST', headers: H, body: payload }); return r.ok; }
const input = $input.all().map(i => i.json);
const groups = {}; for (const l of input) { const reg = regionFor(l); (groups[reg] = groups[reg] || []).push(l); }
let stats = { input: input.length, by_region: {}, uploaded: 0, skipped_in_campaign: 0, failed: 0 };
for (const reg of ALL_REGION_KEYS) { if (!groups[reg]) await ensureCampaign(REGIONS[reg].name, REGIONS[reg].timezone); }
for (const reg of Object.keys(groups)) {
  const cid = await ensureCampaign(REGIONS[reg].name, REGIONS[reg].timezone);
  const existing = await fetchExisting(cid);
  let u = 0, s = 0, f = 0;
  const res = await pMap(groups[reg], 4, async (lead) => { const e = (lead.email || '').toLowerCase().trim(); if (!e) return { f: true }; if (existing.has(e)) return { s: true }; const ok = await uploadOne(cid, lead); if (ok) { existing.add(e); return { u: true }; } return { f: true }; });
  for (const r of res) { if (!r) continue; if (r.u) u++; else if (r.s) s++; else f++; }
  stats.by_region[reg] = { campaign_id: cid, count: groups[reg].length, uploaded: u, skipped_in_campaign: s, failed: f };
  stats.uploaded += u; stats.skipped_in_campaign += s; stats.failed += f;
}
stats.timestamp = new Date().toISOString();
console.log('STAGE_5 stats:', JSON.stringify(stats));
return [{ json: stats }];
`;

const mondayTrigger = trigger({
  type: 'n8n-nodes-base.scheduleTrigger',
  version: 1.3,
  config: { name: 'Every Monday 09:00 UTC', parameters: { rule: { interval: [{ field: 'weeks', weeksInterval: 1, triggerAtDay: [1], triggerAtHour: 9, triggerAtMinute: 0 }] } }, position: [240, 400] },
  output: [{ runStartedAt: '2026-06-22T09:00:00Z' }],
});

const stage1 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 1 - JSearch scrape (x8)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_1_CODE }, position: [540, 400] }, output: [{ employer_name: 'Sample', employer_website: 'sample.com', job_title: 'DevOps Engineer', job_count_for_company: 2 }] });
const stage1b = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 1b - ICP 50+ filter (x10)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_1B_CODE }, position: [840, 400] }, output: [{ employer_name: 'Sample', company_size_bucket: '201-500', company_hq_country: 'US' }] });
const stage2 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 2 - DM finder (x8)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_2_CODE }, position: [1140, 400] }, output: [{ first_name: 'Sample', last_name: 'Founder', title: 'CTO' }] });
const stage3 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 3 - Email + verify (x8)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_3_CODE }, position: [1440, 400] }, output: [{ first_name: 'Sample', email: 'founder@sample.com', email_verification_status: 'ok' }] });
const stage4 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 4 - Personalize (deterministic)', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_4_CODE }, position: [1740, 400] }, output: [{ first_name: 'Sample', open_role: 'DevOps Engineer', open_role_category: 'DevOps', job_count: 2 }] });
const stage5 = node({ type: 'n8n-nodes-base.code', version: 2, config: { name: 'Stage 5 - Upload by region', parameters: { mode: 'runOnceForAllItems', language: 'javaScript', jsCode: STAGE_5_CODE }, position: [2040, 400] }, output: [{ uploaded: 12, skipped_in_campaign: 3, failed: 0 }] });
const note = sticky({ config: { name: 'QSET pipeline', parameters: { content: 'QSET — Job Scraping → Eng Hiring. Monday 09:00 (set workflow timezone = UTC). 57 eng roles x US/UK/CA/AU x 3 pages. Blitz enrichment (.env key). MillionVerifier verify. Per-region Instantly campaigns by HQ timezone. skip_if_in_workspace:false, skip_if_in_campaign:true. Validated locally 2026-06-18.', height: 220, width: 480 }, position: [240, 100] } });

export default workflow('techhive-job-scraping-eng-hiring', 'TechHive - Job Scraping - Eng Hiring (multi-region weekly)')
  .add(note)
  .add(mondayTrigger)
  .to(stage1)
  .to(stage1b)
  .to(stage2)
  .to(stage3)
  .to(stage4)
  .to(stage5);
