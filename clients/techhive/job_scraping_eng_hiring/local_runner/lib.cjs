/* ============================================================================
 * QSET — Job Scraping → Eng Hiring → Cold Email — pipeline library
 *
 * Single source of truth for the stage logic. Written in CommonJS using
 * require('https') / require('url').URL so the SAME functions run:
 *   - locally via Node (run.cjs) for validation, and
 *   - inside n8n Code nodes (n8n's sandbox has no fetch/URL globals).
 *
 * Client:  QSET (Chhatrapati Technologies LLP, https://qset.in)
 * ICP:     50+ employee tech companies (US/UK/CA/AU/EU) actively hiring
 *          engineers. Staff-augmentation pitch keyed off the open role.
 * Enrichment: Blitz API only (no Instantly SuperSearch). Verify: MillionVerifier.
 * ==========================================================================*/
'use strict';

const https = require('https');
const { URL } = require('url');

// ---------------------------------------------------------------------------
// 0. CONFIG  (the ONLY part that changes per client)
// ---------------------------------------------------------------------------

// Stage-1 scrape titles. Category headers and leadership titles are NOT scraped
// (leadership titles are decision-maker targets, used in the Stage-2 cascade).
const ROLES = [
  // Full Stack
  'Full Stack Developer', 'Senior Full Stack Developer', 'Lead Full Stack Engineer',
  'MERN Stack Developer', 'MEAN Stack Developer', 'Full Stack JavaScript Developer',
  // Backend
  'Backend Developer', 'Senior Backend Engineer', 'Python Developer', 'Node.js Developer',
  'Java Backend Developer', 'Golang Developer', 'Ruby on Rails Developer', '.NET Developer',
  // Frontend
  'React Developer', 'Senior React Developer', 'Angular Developer', 'Vue.js Developer',
  'Frontend Engineer', 'UI Engineer',
  // DevOps / Cloud
  'DevOps Engineer', 'Senior DevOps Engineer', 'Lead DevOps Engineer',
  'Site Reliability Engineer', 'Cloud Engineer', 'AWS Solutions Architect',
  'Platform Engineer', 'Infrastructure Engineer', 'Kubernetes Engineer',
  'Terraform Engineer', 'CI/CD Engineer', 'Release Engineer',
  // Data Engineering
  'Data Engineer', 'Senior Data Engineer', 'Analytics Engineer', 'ETL Developer',
  'Data Pipeline Engineer', 'Snowflake Engineer', 'dbt Developer',
  'Apache Spark Engineer', 'Airflow Developer',
  // AI / ML
  'AI Engineer', 'ML Engineer', 'Senior ML Engineer', 'Deep Learning Engineer',
  'NLP Engineer', 'Computer Vision Engineer', 'LLM Engineer', 'AI Research Engineer',
  'MLOps Engineer', 'Data Scientist', 'Applied Scientist', 'Generative AI Engineer',
  'AI Solutions Architect', 'RAG Engineer', 'AI Automation Engineer', 'Prompt Engineer',
  'AI Platform Engineer',
];

const COUNTRIES = ['US', 'GB', 'CA', 'AU']; // JSearch country codes (GB == UK)

// open_role_category buckets — ordered; first match wins. Matched against the
// normalized job title / role query (lowercased).
const CATEGORY_RULES = [
  ['AI/ML', /\b(ai|ml|machine learning|deep learning|nlp|computer vision|llm|mlops|generative|rag|data scientist|applied scientist|prompt)\b/],
  ['Data Engineering', /\b(data engineer|analytics engineer|etl|data pipeline|snowflake|dbt|spark|airflow)\b/],
  ['DevOps', /\b(devops|sre|site reliability|cloud engineer|solutions architect|platform engineer|infrastructure|kubernetes|terraform|ci\/cd|release engineer)\b/],
  ['Frontend', /\b(react|angular|vue|frontend|front end|ui engineer)\b/],
  ['Full Stack', /\b(full ?stack|mern|mean)\b/],
  ['Backend', /\b(backend|back end|python developer|node|java|golang|go developer|ruby|rails|\.net)\b/],
];

// ---- Stage 1b — ICP firmographic filter (TechHive: SMALL companies, 1–50) --
// TechHive wants companies with FEWER than 50 employees (buckets 1-10 / 11-50).
// Drop anything 51+. Unknown headcount is kept + flagged.
const SIZE_TOO_SMALL = new Set([]);                                                   // nothing too small
const SIZE_TOO_BIG = new Set(['51-200', '201-500', '501-1000', '1001-5000', '5001-10000', '10001+']); // 51+ → drop
const EMP_FLOOR = 1;
const EMP_CEIL = 50;

// HQ must be in a target geo. Empty/unknown HQ is KEPT (don't over-reject).
const ALLOWED_HQ = new Set([
  'US', 'GB', 'UK', 'CA', 'AU', 'IE', 'NZ',                 // English-speaking
  'DE', 'FR', 'NL', 'SE', 'ES', 'IT', 'PL', 'PT', 'DK',     // Europe
  'NO', 'FI', 'BE', 'CH', 'AT', 'IE', 'CZ', 'RO',
]);

// QSET TARGETS healthcare/fintech/retail/etc — so only exclude competitor
// industries: staffing/recruiting/outsourcing + government.
const EXCLUDE_INDUSTRY = [
  'staffing', 'recruiting', 'recruitment', 'executive search',
  'outsourcing', 'offshoring', 'human resources services',
  'government administration', 'public administration', 'international affairs',
];

// Employer-name excludes: FAANG/enterprise (in-house, 10k+), the big IT-services
// competitors, staffing firms, and job-board reposters.
const EXCLUDE_EMPLOYER = [
  // FAANG / mega-cap (in-house eng, 10k+)
  'google', 'alphabet', 'meta', 'facebook', 'instagram', 'whatsapp', 'amazon',
  'aws', 'apple', 'microsoft', 'azure', 'netflix', 'nvidia', 'intel', 'ibm',
  'oracle', 'salesforce', 'sap', 'adobe', 'cisco', 'dell', 'hp inc', 'hewlett',
  'tesla', 'spacex', 'uber', 'lyft', 'airbnb', 'paypal', 'visa', 'mastercard',
  'walmart', 'jpmorgan', 'goldman sachs', 'deloitte', 'pwc', 'kpmg', 'ernst',
  'twitter', 'x corp', 'tiktok', 'bytedance', 'openai', 'anthropic', 'deepmind',
  // IT-services / staff-aug competitors
  'infosys', 'tata consultancy', 'tcs', 'wipro', 'accenture', 'cognizant',
  'hcl', 'hcltech', 'capgemini', 'tech mahindra', 'ltimindtree', 'mindtree',
  'mphasis', 'persistent systems', 'birlasoft', 'hexaware', 'zensar', 'coforge',
  'dxc', 'genpact', 'epam', 'globant', 'endava', 'thoughtworks', 'nagarro',
  'virtusa', 'unisys', 'ntt data', 'atos', 'sopra', 'igate', 'syntel',
  // staffing / recruiting agencies
  'robert half', 'kforce', 'teksystems', 'tek systems', 'insight global',
  'randstad', 'hays', 'experis', 'adecco', 'michael page', 'aerotek',
  'apex systems', 'collabera', 'cybercoders', 'motion recruitment', 'dice',
  // job-board reposters
  'jobot', 'lensa', 'jobleads', 'ladders', 'ziprecruiter', 'talent.com',
  'joblist', 'get it recruit', 'crossover', 'turing', 'braintrust',
];

// Stage-2 decision-maker cascade (Blitz waterfall-icp). ALL layers are senior
// technical DECISION-MAKERS (budget/hiring authority) — Founder/CEO/President →
// CxO/VP → Director/Head/Eng-Manager. NO recruiters/talent. Up to PER_COMPANY
// per company. Location omitted: company is already geo-qualified.
const EXCL_T = ['assistant', 'intern', 'former', 'ex-', 'advisor', 'board', 'consultant', 'freelance'];
const DM_CASCADE = [
  { include_title: ['Founder', 'Co-Founder', 'Cofounder', 'CEO', 'Chief Executive Officer', 'President', 'Owner', 'Managing Director', 'Technical Founder'],
    exclude_title: EXCL_T },
  { include_title: ['CTO', 'CIO', 'CDO', 'CISO', 'Chief Technology Officer', 'Chief Technical Officer', 'Chief Information Officer', 'Chief Data Officer', 'Chief AI Officer', 'Chief Product Officer', 'EVP Engineering', 'SVP Engineering', 'VP Engineering', 'VP of Engineering', 'VP Technology', 'VP Software', 'VP Product', 'VP Infrastructure', 'VP Data', 'Head of Engineering', 'Head of Technology'],
    exclude_title: EXCL_T },
  { include_title: ['Director of Engineering', 'Director of Software', 'Director of Technology', 'Director of Platform', 'Director of Infrastructure', 'Director of Data', 'Director of AI', 'Director of Product', 'Head of Platform', 'Head of Infrastructure', 'Head of AI', 'Head of Machine Learning', 'Head of Data', 'Head of Software', 'Senior Engineering Manager', 'Engineering Manager'],
    exclude_title: EXCL_T },
];
const EMP_FINDER_LEVELS = ['C-Team', 'VP', 'Director', 'Head'];
const PER_COMPANY_DEFAULT = 3;

// One campaign per region so each is sent in its own business-hours timezone.
// Timezones are the exact strings Instantly's enum accepts (probed 2026-06-18).
const REGIONS = {
  US: { name: 'TechHive - Job Scraping - Eng Hiring [US]', timezone: 'America/Detroit' },
  UK: { name: 'TechHive - Job Scraping - Eng Hiring [UK]', timezone: 'Europe/Isle_of_Man' },
  CA: { name: 'TechHive - Job Scraping - Eng Hiring [CA]', timezone: 'America/Detroit' },
  AU: { name: 'TechHive - Job Scraping - Eng Hiring [AU]', timezone: 'Australia/Melbourne' },
  EMEA: { name: 'TechHive - Job Scraping - Eng Hiring [EMEA]', timezone: 'Europe/Belgrade' },
};
// Always-create these (so AU/EMEA exist even before a lead routes there).
const ALL_REGION_KEYS = ['US', 'UK', 'CA', 'AU', 'EMEA'];
const COUNTRY_TO_REGION = { US: 'US', GB: 'UK', UK: 'UK', CA: 'CA', AU: 'AU', NZ: 'AU' };
// Continental Europe + Middle East + Africa (UK is its OWN region, excluded here).
const EMEA_COUNTRIES = new Set([
  'IE', 'DE', 'FR', 'NL', 'SE', 'ES', 'IT', 'PL', 'PT', 'DK', 'NO', 'FI', 'BE', 'CH', 'AT', 'CZ', 'RO',
  'HU', 'GR', 'SK', 'BG', 'HR', 'LU', 'LT', 'LV', 'EE', 'SI', 'RS', 'UA',           // rest of Europe
  'AE', 'SA', 'IL', 'TR', 'QA', 'KW', 'EG', 'ZA', 'NG', 'KE', 'MA',                 // ME + Africa
]);
/** Route a lead to a regional campaign by company HQ (fallback job country). EMEA→EMEA, unknown→US. */
function regionForLead(lead) {
  const hq = (lead.company_hq_country || '').toUpperCase();
  const jc = (lead.job_country || '').toUpperCase();
  return COUNTRY_TO_REGION[hq] || (EMEA_COUNTRIES.has(hq) ? 'EMEA' : null) ||
         COUNTRY_TO_REGION[jc] || (EMEA_COUNTRIES.has(jc) ? 'EMEA' : null) || 'US';
}
const CAMPAIGN_NAME = 'TechHive - Job Scraping - Eng Hiring [US/CA]'; // legacy single-campaign name

// ---------------------------------------------------------------------------
// 1. HELPERS  (identical block lives at the top of every n8n Code node)
// ---------------------------------------------------------------------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** HTTP w/ JSON, retry on 429/5xx/network w/ exponential backoff. */
async function httpJson(rawUrl, opts = {}) {
  const { method = 'GET', headers = {}, body = null, timeout = 60000, retries = 5 } = opts;
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

/** Bounded-concurrency map. Per-item errors resolve to null; pool keeps draining. */
async function pMap(items, mapper, concurrency = 8) {
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
const cleanLi = normLi;

// ---------------------------------------------------------------------------
// 2. ROLE NORMALIZATION  (Stage 4 — deterministic, no LLM)
// ---------------------------------------------------------------------------
function categorize(text) {
  const t = (text || '').toLowerCase();
  for (const [label, re] of CATEGORY_RULES) if (re.test(t)) return label;
  return 'Software Engineering';
}
// Acronyms / special-case tokens to fix after title-casing (email-facing copy).
const ACRONYMS = {
  ai: 'AI', ml: 'ML', ui: 'UI', ux: 'UX', api: 'API', aws: 'AWS', gcp: 'GCP',
  sre: 'SRE', qa: 'QA', nlp: 'NLP', llm: 'LLM', etl: 'ETL', sql: 'SQL',
  mern: 'MERN', mean: 'MEAN', ios: 'iOS', php: 'PHP', sdk: 'SDK', rag: 'RAG',
  devops: 'DevOps', mlops: 'MLOps', dbt: 'dbt', golang: 'Golang',
};
function fixCase(s) {
  return s.split(/\s+/).map((w) => {
    const low = w.toLowerCase().replace(/[.,]/g, '');
    if (ACRONYMS[low]) return ACRONYMS[low];
    if (low === '.net') return '.NET';
    if (low === 'ci/cd') return 'CI/CD';
    if (low === 'node.js' || low === 'nodejs') return 'Node.js';
    if (low === 'vue.js') return 'Vue.js';
    return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
  }).join(' ').trim();
}
/** Tidy, title-cased display version of the open role for {{open_role}}. */
function normalizeOpenRole(jobTitle, roleQuery) {
  let t = (jobTitle || '').trim();
  if (!t) return roleQuery || 'Software Engineer';
  t = t.replace(/\([^)]*\)/g, '').replace(/[-–|,/].*$/, '').trim(); // strip parens & trailing clauses
  t = t.replace(/\b(remote|hybrid|onsite|contract|full[- ]?time|w2|c2c|usa?|uk|\d{4,})\b/gi, '').trim();
  t = t.replace(/^.*\bis hiring:?\s*/i, '').trim(); // drop "Acme is hiring: " prefixes
  if (!t || t.length > 48) t = roleQuery || (t ? t.slice(0, 48) : 'Software Engineer');
  return fixCase(t);
}

module.exports = {
  ROLES, COUNTRIES, CATEGORY_RULES, DM_CASCADE, EMP_FINDER_LEVELS, PER_COMPANY_DEFAULT,
  SIZE_TOO_SMALL, SIZE_TOO_BIG, EMP_FLOOR, EMP_CEIL, ALLOWED_HQ,
  EXCLUDE_INDUSTRY, EXCLUDE_EMPLOYER, CAMPAIGN_NAME,
  REGIONS, ALL_REGION_KEYS, COUNTRY_TO_REGION, EMEA_COUNTRIES, regionForLead,
  sleep, httpJson, pMap, normDomain, normLi, normEmail, cleanLi,
  categorize, normalizeOpenRole,
};
