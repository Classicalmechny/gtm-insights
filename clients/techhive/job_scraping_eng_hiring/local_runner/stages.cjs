/* ============================================================================
 * QSET pipeline — Stage 1-5 implementations + Instantly campaign creator.
 * Pure functions of (K = keys, log) so they run locally and inside n8n.
 * ==========================================================================*/
'use strict';

const L = require('./lib.cjs');
const {
  ROLES, COUNTRIES, DM_CASCADE, EMP_FINDER_LEVELS, PER_COMPANY_DEFAULT,
  SIZE_TOO_SMALL, SIZE_TOO_BIG, EMP_FLOOR, EMP_CEIL, ALLOWED_HQ,
  EXCLUDE_INDUSTRY, EXCLUDE_EMPLOYER, CAMPAIGN_NAME, REGIONS, ALL_REGION_KEYS, regionForLead,
  httpJson, pMap, normDomain, normLi, normEmail,
  categorize, normalizeOpenRole,
} = L;

const BLITZ = 'https://api.blitz-api.ai';
const INST = 'https://api.instantly.ai';
const JSEARCH = 'https://jsearch.p.rapidapi.com/search';

const noop = () => {};

// ===========================================================================
// STAGE 1 — JSearch scrape → unique companies hiring (with all roles + count)
// ===========================================================================
async function stage1Scrape(K, opts = {}, log = noop) {
  const roles = opts.roles || ROLES;
  const countries = opts.countries || COUNTRIES;
  const pages = opts.pagesPerRole || 1;
  const datePosted = opts.datePosted || 'week';
  const isExcludedName = (n) => {
    const x = (n || '').toLowerCase();
    return EXCLUDE_EMPLOYER.some((k) => x.includes(k));
  };

  const jobs = [];
  const queries = [];
  for (const role of roles) for (const c of countries) for (let p = 1; p <= pages; p++) queries.push({ role, c, p });

  const headers = { 'x-rapidapi-host': 'jsearch.p.rapidapi.com', 'x-rapidapi-key': K.RAPIDAPI_KEY };
  let empty = 0;
  await pMap(queries, async (q) => {
    const url = \`\${JSEARCH}?query=\${encodeURIComponent(q.role + ' in ' + q.c)}&page=\${q.p}&num_pages=1&country=\${q.c.toLowerCase()}&date_posted=\${datePosted}&employment_types=FULLTIME\`;
    const r = await httpJson(url, { headers });
    if (!r.ok || !r.json) { log('jsearch.err', { role: q.role, c: q.c, p: q.p, status: r.status }); return; }
    const items = r.json.data || [];
    if (!items.length) empty++;
    for (const j of items) { j._role = q.role; jobs.push(j); }
  }, opts.concurrency || 8);

  // collapse to one row per company-domain (fallback name); track distinct roles
  const byKey = new Map();
  const roleSet = new Map();
  for (const j of jobs) {
    const name = (j.employer_name || '').trim();
    if (!name || isExcludedName(name)) continue;
    const domain = normDomain(j.employer_website || '');
    const key = domain || name.toLowerCase();
    if (!roleSet.has(key)) roleSet.set(key, new Set());
    roleSet.get(key).add(j._role);
    const posted = j.job_posted_at_datetime_utc || '';
    const row = {
      employer_name: name,
      employer_website: domain,
      employer_linkedin: (j.employer_linkedin || '').trim(),
      job_title: (j.job_title || '').trim(),
      job_id: (j.job_id || '').trim(),
      job_apply_link: (j.job_apply_link || '').trim(),
      job_posted_at: posted,
      job_city: (j.job_city || '').trim(),
      job_state: (j.job_state || '').trim(),
      job_country: (j.job_country || '').trim(),
      job_description_snippet: (j.job_description || '').slice(0, 400),
      job_role_query: j._role,
    };
    const prev = byKey.get(key);
    if (!prev) byKey.set(key, row);
    else if (posted && posted > (prev.job_posted_at || '')) byKey.set(key, row);
  }
  const companies = [];
  for (const [key, row] of byKey) {
    const roles2 = [...roleSet.get(key)].sort();
    row.job_count_for_company = roles2.length;
    row.all_roles_seen = roles2.join(' | ');
    companies.push(row);
  }
  companies.sort((a, b) => b.job_count_for_company - a.job_count_for_company);
  const stats = { queries: queries.length, empty_pages: empty, raw_jobs: jobs.length, unique_companies: companies.length };
  log('STAGE1', stats);
  return { companies, stats };
}

// ===========================================================================
// STAGE 1b — ICP firmographic filter via Blitz (INVERTED: keep 50+, drop <50/10k+)
// ===========================================================================
async function stage1bFilter(K, companies, log = noop) {
  const headers = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const isExclInd = (i) => { const x = (i || '').toLowerCase(); return EXCLUDE_INDUSTRY.some((k) => x.includes(k)); };

  const stats = { input: companies.length, no_li: 0, no_enrich: 0, too_small: 0, too_big: 0, industry: 0, hq: 0, qualified: 0, flagged_unknown: 0 };
  const out = await pMap(companies, async (c) => {
    const domain = normDomain(c.employer_website || '');
    let li = normLi(c.employer_linkedin || '');
    if (!li && domain) {
      const r = await httpJson(\`\${BLITZ}/v2/enrichment/domain-to-linkedin\`, { method: 'POST', headers, body: { domain } });
      if (r.ok && r.json && r.json.found) li = normLi(r.json.company_linkedin_url || '');
    }
    if (!li) { stats.no_li++; return null; }

    const e = await httpJson(\`\${BLITZ}/v2/enrichment/company\`, { method: 'POST', headers, body: { company_linkedin_url: li } });
    if (!e.ok || !e.json || !e.json.found) { stats.no_enrich++; return null; }
    const co = e.json.company || e.json;
    const size = (co.size || '').trim();
    const industry = (co.industry || '').trim();
    const emp = Number(co.employees_on_linkedin || 0) || 0;
    const hq = co.hq || {};
    const hqCountry = (hq.country_code || '').toUpperCase();

    // confirmed-too-small / too-big → drop
    if (SIZE_TOO_SMALL.has(size) || (emp && emp < EMP_FLOOR)) { stats.too_small++; return null; }
    if (SIZE_TOO_BIG.has(size) || (emp && emp > EMP_CEIL)) { stats.too_big++; return null; }
    if (isExclInd(industry)) { stats.industry++; return null; }
    if (hqCountry && !ALLOWED_HQ.has(hqCountry)) { stats.hq++; return null; }

    // headcount verified iff we had a bucket or LI count confirming 50–10k
    const verified = (size && !SIZE_TOO_SMALL.has(size) && !SIZE_TOO_BIG.has(size)) || (emp >= EMP_FLOOR && emp <= EMP_CEIL);
    if (!verified) stats.flagged_unknown++;
    stats.qualified++;
    return Object.assign({}, c, {
      company_linkedin_url: li,
      company_size_bucket: size,
      company_industry: industry,
      company_employees_on_linkedin: emp,
      company_hq_country: hqCountry,
      company_hq_city: hq.city || '',
      company_founded_year: co.founded_year || '',
      headcount_verified: verified ? 'yes' : 'no_flagged',
    });
  }, 10);

  const qualified = out.filter(Boolean);
  log('STAGE1b', stats);
  return { qualified, stats };
}

// ===========================================================================
// STAGE 2 — Decision-maker finder (Blitz waterfall → employee-finder fallback)
// ===========================================================================
function personFromWaterfall(res) {
  const p = res.person || {};
  const exp = (p.experiences || [{}])[0] || {};
  return {
    first_name: (p.first_name || '').trim(),
    last_name: (p.last_name || '').trim(),
    title: (exp.job_title || p.headline || '').trim(),
    headline: (p.headline || '').trim(),
    linkedin_url: normLi(p.linkedin_url || ''),
    person_country: (p.location || {}).country_code || '',
    person_city: (p.location || {}).city || '',
    blitz_icp_rank: res.ranking, blitz_icp_layer: res.icp,
  };
}
function personFromEf(res) {
  const exp = (res.experiences || [{}])[0] || {};
  return {
    first_name: (res.first_name || '').trim(),
    last_name: (res.last_name || '').trim(),
    title: (exp.job_title || res.headline || '').trim(),
    headline: (res.headline || '').trim(),
    linkedin_url: normLi(res.linkedin_url || ''),
    person_country: (res.location || {}).country_code || '',
    person_city: (res.location || {}).city || '',
    blitz_icp_rank: null, blitz_icp_layer: null,
  };
}
function mergeDm(c, p, source) {
  if (!p.first_name || !p.last_name) return null;
  return {
    first_name: p.first_name, last_name: p.last_name, title: p.title, headline: p.headline,
    linkedin_url: p.linkedin_url, person_country: p.person_country, person_city: p.person_city,
    company_name: c.employer_name || '', company_domain: c.employer_website || '',
    company_linkedin_url: c.company_linkedin_url || '',
    company_size_bucket: c.company_size_bucket || '', company_industry: c.company_industry || '',
    company_employees_on_linkedin: c.company_employees_on_linkedin || '',
    company_hq_country: c.company_hq_country || '', company_hq_city: c.company_hq_city || '',
    headcount_verified: c.headcount_verified || '',
    job_title_hiring: c.job_title || '', job_apply_link: c.job_apply_link || '',
    job_city: c.job_city || '', job_country: c.job_country || '',
    job_role_query: c.job_role_query || '', job_description_snippet: c.job_description_snippet || '',
    job_count_for_company: c.job_count_for_company || 1, all_roles_seen: c.all_roles_seen || '',
    dm_source: source, blitz_icp_rank: p.blitz_icp_rank, blitz_icp_layer: p.blitz_icp_layer,
  };
}
async function stage2Dms(K, companies, opts = {}, log = noop) {
  const perCompany = opts.perCompany || PER_COMPANY_DEFAULT;
  const headers = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const stats = { companies: companies.length, waterfall_hits: 0, fallback_hits: 0, no_dm: 0, dms: 0 };

  const nested = await pMap(companies, async (c) => {
    const li = normLi(c.company_linkedin_url || c.employer_linkedin || '');
    if (!li) { stats.no_dm++; return []; }
    let rows = [];
    const w = await httpJson(\`\${BLITZ}/v2/search/waterfall-icp-keyword\`, { method: 'POST', headers, body: { company_linkedin_url: li, cascade: DM_CASCADE, max_results: perCompany } });
    const wres = (w.ok && w.json && w.json.results) || [];
    if (wres.length) {
      stats.waterfall_hits++;
      rows = wres.slice(0, perCompany).map((r) => mergeDm(c, personFromWaterfall(r), 'waterfall')).filter(Boolean);
    } else {
      const ef = await httpJson(\`\${BLITZ}/v2/search/employee-finder\`, { method: 'POST', headers, body: { company_linkedin_url: li, job_level: EMP_FINDER_LEVELS, max_results: perCompany, page: 1 } });
      const eres = (ef.ok && ef.json && ef.json.results) || [];
      if (eres.length) { stats.fallback_hits++; rows = eres.slice(0, perCompany).map((r) => mergeDm(c, personFromEf(r), 'employee_finder')).filter(Boolean); }
      else stats.no_dm++;
    }
    stats.dms += rows.length;
    return rows;
  }, 8);

  const dms = nested.flat().filter(Boolean);
  log('STAGE2', stats);
  return { dms, stats };
}

// ===========================================================================
// STAGE 3 — Email enrichment (Blitz) + verification (MillionVerifier + MX floor)
// ===========================================================================
async function millionVerify(K, email) {
  if (!K.MILLIONVERIFIER_KEY) return { ok: false, status: '', source: '' };
  const r = await httpJson(\`https://api.millionverifier.com/api/v3/?api=\${K.MILLIONVERIFIER_KEY}&email=\${encodeURIComponent(email)}&timeout=10\`, { method: 'GET' });
  if (!r.ok || !r.json) return { ok: false, status: 'error', source: 'millionverifier' };
  const res = (r.json.result || '').toLowerCase(); // ok | catch_all | unknown | invalid | disposable
  return { ok: res === 'ok', status: res, source: 'millionverifier' };
}
async function stage3Emails(K, dms, log = noop) {
  const headers = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const stats = { input: dms.length, blitz_found: 0, mv_valid: 0, mv_catch_all: 0, dropped_no_email: 0, dropped_bad_verify: 0, kept: 0 };

  const out = await pMap(dms, async (row) => {
    const li = normLi(row.linkedin_url || '');
    if (!li) { stats.dropped_no_email++; return null; }
    const r = await httpJson(\`\${BLITZ}/v2/enrichment/email\`, { method: 'POST', headers, body: { person_linkedin_url: li } });
    const email = normEmail((r.json && r.json.email) || '');
    if (!email) { stats.dropped_no_email++; return null; }
    stats.blitz_found++;

    const v = await millionVerify(K, email);
    if (v.status === 'ok') stats.mv_valid++;
    else if (v.status === 'catch_all') stats.mv_catch_all++;
    if (!v.ok) { stats.dropped_bad_verify++; return null; } // drop invalid/unknown/disposable/error

    stats.kept++;
    return Object.assign({}, row, {
      email,
      email_provider: 'blitz',
      email_verified: 'yes',
      email_verification_status: v.status,
      email_verification_source: v.source,
      email_risk: v.status === 'catch_all' ? 'accept_all' : '',
    });
  }, 8);

  const leads = out.filter(Boolean);
  log('STAGE3', stats);
  return { leads, stats };
}

// ===========================================================================
// STAGE 4 — Personalization variables (deterministic, NO LLM / NO Firecrawl)
// ===========================================================================
function stage4Personalize(leads, log = noop) {
  const stats = { input: leads.length, categories: {} };
  for (const l of leads) {
    const open_role = normalizeOpenRole(l.job_title_hiring, l.job_role_query);
    // Categorize off the normalized role + the search query (not the raw JD,
    // which can mention unrelated tech e.g. "AI" in a Data Engineer posting).
    const open_role_category = categorize(open_role + ' ' + (l.job_role_query || ''));
    const job_count = Number(l.job_count_for_company || 1) || 1;
    l.open_role = open_role;
    l.open_role_category = open_role_category;
    l.job_count = job_count;
    l.job_count_phrase = job_count > 1 ? \`multiple roles (\${job_count})\` : open_role;
    stats.categories[open_role_category] = (stats.categories[open_role_category] || 0) + 1;
  }
  log('STAGE4', stats);
  return { leads, stats };
}

// ===========================================================================
// STAGE 5 — Instantly: ensure campaign (create + 4-email sequence) → upload
// ===========================================================================
const SIG = \`<div><br></div><div>{{sendingAccountName}} </div><div>Partnerships {{RANDOM | @TechHive | - TechHive}}</div>\`;
const SEQUENCE_STEPS = [
  { delay: 1, subject: '{{open_role}} opening',
    body: \`<div>{{first_name}}, saw {{company_name}} is hiring for a {{open_role}}. Most companies I talk to say that role takes 2-4 months to fill locally. Meanwhile, the team is stretched thin and delivery slows down.</div><div><br></div><div>We can have a vetted senior {{open_role_category}} engineer embedded in your workflow within 5-10 days. Overlapping US hours, your tools, your standups.</div><div><br></div><div>Would it help to see a couple of profiles?</div>\` + SIG },
  { delay: 3, subject: '', // threaded reply (no subject)
    body: \`<div>{{first_name}}, to give you context on how this works. We don't send resumes. We send pre-vetted engineers who've been technically assessed by our delivery team.</div><div><br></div><div>You evaluate them on actual project tasks during a trial period. If the fit isn't right, no commitment.</div>\` + SIG },
  { delay: 4, subject: 'engineering hiring alternative',
    body: \`<div>{{first_name}}, most engineering leaders I talk to have tried recruiters, freelancers, or offshore vendors before finding us. The common complaint is the same. Communication gaps, quality issues, or engineers who disappear.</div><div><br></div><div>We solve that with overlapping hours, real delivery ownership, and founder-led vetting. If you've been burned before, happy to show how we're different.</div>\` + SIG },
  { delay: 4, subject: 'quick question',
    body: \`<div>{{first_name}}, if engineering hiring decisions aren't in your scope, happy to connect with whoever handles technical recruiting or team scaling at {{company_name}}. Either way, thanks.</div>\` + SIG },
];

function buildCampaignPayload(name, timezone) {
  return {
    name,
    campaign_schedule: {
      schedules: [{
        name: 'Mon-Fri business hours',
        timing: { from: '09:00', to: '17:00' },
        days: { 1: true, 2: true, 3: true, 4: true, 5: true },
        timezone: timezone || 'America/Detroit',
      }],
      start_date: null, end_date: null,
    },
    sequences: [{ steps: SEQUENCE_STEPS.map((s) => ({ type: 'email', delay: s.delay, delay_unit: 'days', pre_delay_unit: 'days', variants: [{ subject: s.subject, body: s.body }] })) }],
    text_only: false, first_email_text_only: true,
    daily_limit: 100000,
    stop_on_reply: true,
    stop_on_auto_reply: false,
    link_tracking: false,
    open_tracking: false,
    email_list: [],
  };
}

/** Find-or-create a campaign by name (idempotent). region = {name, timezone}. */
async function ensureCampaign(K, region, log = noop) {
  const H = { Authorization: \`Bearer \${K.INSTANTLY_KEY}\`, 'Content-Type': 'application/json' };
  const name = (region && region.name) || CAMPAIGN_NAME;
  const tz = (region && region.timezone) || 'America/Detroit';
  // find existing by exact name (paginate)
  let cursor = null;
  for (let i = 0; i < 20; i++) {
    const url = \`\${INST}/api/v2/campaigns?limit=100\` + (cursor ? \`&starting_after=\${cursor}\` : '');
    const list = await httpJson(url, { headers: H });
    const items = (list.json && list.json.items) || [];
    const found = items.find((c) => c.name === name);
    if (found) { log('campaign.found', { id: found.id, name }); return found.id; }
    cursor = list.json && (list.json.next_starting_after || list.json.next_cursor);
    if (!cursor || items.length < 100) break;
  }
  // create (status defaults to draft/paused — NOTHING sends until activated + mailboxes assigned)
  const r = await httpJson(\`\${INST}/api/v2/campaigns\`, { method: 'POST', headers: H, body: buildCampaignPayload(name, tz) });
  if (!r.ok || !r.json || !r.json.id) throw new Error('campaign create failed: ' + r.status + ' ' + r.text.slice(0, 300));
  log('campaign.created', { id: r.json.id, name, timezone: tz });
  return r.json.id;
}

/** Pre-create all region campaigns (US/UK/CA/AU/EMEA) so they exist even empty. */
async function ensureAllRegionCampaigns(K, log = noop) {
  const ids = {};
  for (const reg of ALL_REGION_KEYS) ids[reg] = await ensureCampaign(K, REGIONS[reg], log);
  return ids;
}

/** Group leads by region, ensure each region's campaign, upload to each. */
async function uploadByRegion(K, leads, log = noop) {
  const groups = {};
  for (const l of leads) { const reg = regionForLead(l); (groups[reg] = groups[reg] || []).push(l); }
  const result = { by_region: {}, totals: { uploaded: 0, skipped_existing: 0, failed: 0 } };
  for (const reg of Object.keys(groups)) {
    const campaignId = await ensureCampaign(K, REGIONS[reg], log);
    const { stats } = await stage5Upload(K, groups[reg], campaignId, log);
    result.by_region[reg] = { campaign_id: campaignId, count: groups[reg].length, ...stats };
    result.totals.uploaded += stats.uploaded; result.totals.skipped_existing += stats.skipped_existing; result.totals.failed += stats.failed;
  }
  log('UPLOAD_BY_REGION', result.totals);
  return result;
}

async function fetchExistingEmails(K, campaignId) {
  const H = { Authorization: \`Bearer \${K.INSTANTLY_KEY}\`, 'Content-Type': 'application/json' };
  const emails = new Set();
  let cursor = null;
  for (let i = 0; i < 50; i++) {
    const body = { campaign: campaignId, limit: 100 };
    if (cursor) body.starting_after = cursor;
    const r = await httpJson(\`\${INST}/api/v2/leads/list\`, { method: 'POST', headers: H, body });
    const items = (r.json && (r.json.items || r.json.data)) || [];
    for (const l of items) { const e = normEmail(l.email); if (e) emails.add(e); }
    cursor = r.json && (r.json.next_starting_after || r.json.next_cursor);
    if (!cursor || items.length < 100) break;
  }
  return emails;
}

async function stage5Upload(K, leads, campaignId, log = noop) {
  const H = { Authorization: \`Bearer \${K.INSTANTLY_KEY}\`, 'Content-Type': 'application/json' };
  const existing = await fetchExistingEmails(K, campaignId);
  const stats = { input: leads.length, uploaded: 0, skipped_existing: 0, failed: 0, campaign: campaignId, existing_before: existing.size };
  const uploaded = [];
  for (const lead of leads) {
    const email = normEmail(lead.email);
    if (!email) { stats.failed++; continue; }
    if (existing.has(email)) { stats.skipped_existing++; continue; }
    const payload = {
      campaign: campaignId,
      email,
      first_name: lead.first_name || '',
      last_name: lead.last_name || '',
      company_name: lead.company_name || '',
      website: lead.company_domain || '',
      skip_if_in_workspace: false, // per spec: no cross-campaign dedupe
      skip_if_in_campaign: true,   // block re-adding to THIS campaign on weekly re-runs
      verify_leads_on_import: false,
      custom_variables: {
        first_name: lead.first_name || '',
        company_name: lead.company_name || '',
        open_role: lead.open_role || '',
        open_role_category: lead.open_role_category || '',
        job_count: String(lead.job_count || 1),
        // audit / display
        job_title_hiring: lead.job_title_hiring || '',
        all_roles_seen: lead.all_roles_seen || '',
        job_apply_link: lead.job_apply_link || '',
        person_title: lead.title || '',
        linkedin_url: lead.linkedin_url || '',
        icp_size_bucket: lead.company_size_bucket || '',
        icp_industry: lead.company_industry || '',
        icp_hq_country: lead.company_hq_country || '',
        icp_employees_li: String(lead.company_employees_on_linkedin || ''),
        icp_headcount_verified: lead.headcount_verified || '',
        email_risk: lead.email_risk || '',
      },
    };
    const r = await httpJson(\`\${INST}/api/v2/leads\`, { method: 'POST', headers: H, body: payload });
    if (r.ok) { stats.uploaded++; existing.add(email); uploaded.push(Object.assign({}, lead, { instantly_lead_id: (r.json && r.json.id) || '' })); }
    else { stats.failed++; log('upload.fail', { email, status: r.status, body: r.text.slice(0, 200) }); }
  }
  log('STAGE5', stats);
  return { uploaded, stats };
}

module.exports = {
  stage1Scrape, stage1bFilter, stage2Dms, stage3Emails, stage4Personalize,
  ensureCampaign, ensureAllRegionCampaigns, uploadByRegion, fetchExistingEmails, stage5Upload,
  buildCampaignPayload, SEQUENCE_STEPS,
};
