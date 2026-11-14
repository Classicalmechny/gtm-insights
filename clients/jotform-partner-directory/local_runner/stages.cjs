/* ============================================================================
 * Jotform Partner Directory pipeline — Stage 1–6 implementations.
 * Blitz + MillionVerifier logic adapted from clients/qset/.../stages.cjs.
 * ==========================================================================*/
'use strict';

const L = require('./lib.cjs');
const {
  JOTFORM_BASE, DIRECTORY_PATH, TOTAL_PAGES, BLITZ, ICP_BUCKETS, EXCL_T, EMP_FINDER_LEVELS,
  sleep, httpJson, fetchHtml, pMap, normDomain, normLi, normEmail,
  decodeEntities, stripTags, classText, classListText, modalChips, hrefForDataJfa,
  isLargeReseller, classifyBucket, deepinfraSummary,
  liSuggestCompany, liCompanyData, nameTokensMatch,
} = L;

const noop = () => {};

// ===========================================================================
// STAGE 1 — Listing scrape (pages 1..N) → unique partners
// ===========================================================================
function parseCards(html) {
  const out = [];
  const blocks = html.split(/<div class="jf-card flex flex-col/);
  for (let i = 1; i < blocks.length; i++) {
    const block = '<div class="jf-card flex flex-col' + blocks[i];
    const slugM = /\/partnership\/partner-directory\/([^/"]+)\//.exec(block);
    if (!slugM) continue;
    const slug = decodeEntities(slugM[1]).trim();
    let tier = '', name = '';
    const aria = /aria-label="([^"]*)"/.exec(block);
    if (aria) {
      const a = decodeEntities(aria[1]);
      const idx = a.indexOf(': ');
      if (idx > 0) { tier = a.slice(0, idx); name = a.slice(idx + 2); } else name = a;
    }
    const title = classText(block, 'jf-card--title'); if (title) name = title;
    const badge = classText(block, 'jf-card--image-badge'); if (badge) tier = badge;
    const desc = classText(block, 'jf-card--description');
    out.push({
      company_name: name.trim(),
      partner_slug: slug,
      partner_profile_url: `${JOTFORM_BASE}${DIRECTORY_PATH}${slug}/`,
      partner_tier: tier.trim(),
      short_description: desc,
    });
  }
  return out;
}

async function stage1Listing(K, opts = {}, log = noop) {
  const pages = opts.pages || TOTAL_PAGES;
  const bySlug = new Map();
  let scannedPages = 0;
  for (let p = 1; p <= pages; p++) {
    const url = `${JOTFORM_BASE}${DIRECTORY_PATH}?page=${p}`;
    const r = await fetchHtml(url);
    if (!r.ok || !r.text) { log('stage1.page_err', { p, status: r.status }); continue; }
    const cards = parseCards(r.text);
    if (!cards.length) { log('stage1.empty_page', { p }); break; }
    for (const c of cards) { const k = c.partner_slug.toLowerCase(); if (!bySlug.has(k)) bySlug.set(k, c); }
    scannedPages = p;
    log('stage1.page', { p, cards: cards.length, total: bySlug.size });
    await sleep(150);
  }
  const partners = [...bySlug.values()];
  const stats = { pages: scannedPages, partners: partners.length };
  log('STAGE1', stats);
  return { partners, stats };
}

// ===========================================================================
// STAGE 2 — Detail-modal scrape (per slug)
// ===========================================================================
function parseDetail(html) {
  const website = hrefForDataJfa(html, 'partner-url') || hrefForDataJfa(html, 'visit-website');
  const em = /partner_email=([^&"'\s]+)/i.exec(html);
  let contact = '';
  if (em) { try { contact = normEmail(decodeURIComponent(em[1])); } catch (_) { contact = normEmail(em[1]); } }
  return {
    company_name: classText(html, 'jf-modal--company-name'),
    company_location: classText(html, 'jf-modal--location'),
    languages: modalChips(html, 'jf-modal--languages'),
    full_description: classText(html, 'jf-modal--company-about'),
    services: modalChips(html, 'jf-modal--services'),
    speciality: modalChips(html, 'jf-modal--speciality'),
    industries: modalChips(html, 'jf-modal--industries'),
    company_website: website,
    partner_contact_email: contact,
  };
}

async function stage2Details(K, partners, opts = {}, log = noop) {
  const out = await pMap(partners, async (pn) => {
    const r = await fetchHtml(pn.partner_profile_url);
    if (!r.ok || !r.text) { log('stage2.err', { slug: pn.partner_slug, status: r.status }); return Object.assign({}, pn, { _detail_error: r.status }); }
    const d = parseDetail(r.text);
    return Object.assign({}, pn, d, {
      company_name: d.company_name || pn.company_name,
      partner_tier: pn.partner_tier, // tier comes from the listing card badge (modal only has a label)
      company_domain: normDomain(d.company_website || ''),
    });
  }, opts.concurrency || 5);
  const companies = out.filter(Boolean);
  const stats = { input: partners.length, scraped: companies.length, with_website: companies.filter((c) => c.company_domain).length };
  log('STAGE2', stats);
  return { companies, stats };
}

// ===========================================================================
// STAGE 2b — Service enrichment (direct homepage fetch + DeepInfra)
// ===========================================================================
async function stage2bEnrich(K, companies, opts = {}, log = noop) {
  const stats = { input: companies.length, website_llm: 0, jotform_llm: 0, jotform_raw: 0, empty: 0 };
  const out = await pMap(companies, async (c) => {
    let ctx = '', base = '';
    if (c.company_website) {
      const url = /^https?:\/\//.test(c.company_website) ? c.company_website : 'https://' + c.company_website;
      const r = await fetchHtml(url);
      if (r.ok && r.text) { const txt = stripTags(r.text); if (txt.length >= 200) { ctx = txt; base = 'website'; } }
    }
    const jfText = [c.services, c.speciality, c.full_description].filter(Boolean).join('. ').trim();
    if (!ctx && jfText) { ctx = jfText; base = 'jotform'; }

    let summary = '', source = '';
    if (ctx) summary = await deepinfraSummary(K, ctx);
    if (summary) { source = base === 'website' ? 'website_llm' : 'jotform_llm'; }
    // Deterministic fallback so the column is never empty when we have source data.
    if (!summary) {
      const det = [c.services, c.speciality].filter(Boolean).join('; ') || (c.full_description || '').slice(0, 240);
      if (det) { summary = det; source = 'jotform_raw'; }
    }
    if (source === 'website_llm') stats.website_llm++;
    else if (source === 'jotform_llm') stats.jotform_llm++;
    else if (source === 'jotform_raw') stats.jotform_raw++;
    else stats.empty++;
    return Object.assign({}, c, { services_enriched: summary, services_enriched_source: source });
  }, opts.concurrency || 3);
  log('STAGE2b', stats);
  return { companies: out.filter(Boolean), stats };
}

// ===========================================================================
// STAGE 3 — Company → LinkedIn + firmographics (Blitz). Keeps ALL companies.
// ===========================================================================
async function stage3Firmographics(K, companies, log = noop) {
  const headers = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const stats = { input: companies.length, no_domain: 0, li_found: 0, enriched: 0, large: 0 };
  const out = await pMap(companies, async (c) => {
    let li = '';
    if (c.company_domain) {
      const r = await httpJson(`${BLITZ}/v2/enrichment/domain-to-linkedin`, { method: 'POST', headers, body: { domain: c.company_domain } });
      if (r.ok && r.json && r.json.found) li = normLi(r.json.company_linkedin_url || '');
    } else stats.no_domain++;
    let size = '', industry = '', hq = '', emp = '';
    if (li) {
      stats.li_found++;
      const e = await httpJson(`${BLITZ}/v2/enrichment/company`, { method: 'POST', headers, body: { company_linkedin_url: li } });
      if (e.ok && e.json && (e.json.found || e.json.company)) {
        const co = e.json.company || e.json;
        size = (co.size || '').trim();
        industry = (co.industry || '').trim();
        emp = Number(co.employees_on_linkedin || 0) || '';
        hq = ((co.hq || {}).country_code || '').toUpperCase();
        stats.enriched++;
      }
    }
    const large = isLargeReseller(c.partner_tier, emp);
    if (large) stats.large++;
    return Object.assign({}, c, {
      company_linkedin_url: li,
      company_size_bucket: size ? `${size} employees` : '', // " employees" stops Excel coercing "11-50" → a date
      company_industry: industry,
      company_hq_country: hq,
      company_employees_on_linkedin: emp,
      is_large_reseller: large ? 'yes' : 'no',
    });
  }, 8);
  log('STAGE3', stats);
  return { companies: out.filter(Boolean), stats };
}

// ===========================================================================
// STAGE 3b — LinkedIn-Bulk recovery for Blitz-missed companies (RapidAPI)
// ===========================================================================
async function stage3bRecover(K, companies, log = noop) {
  const stats = { input: companies.length, already_resolved: 0, attempted: 0, recovered: 0, no_match: 0, no_name: 0 };
  const out = await pMap(companies, async (c) => {
    if (c.company_linkedin_url) { stats.already_resolved++; return Object.assign({}, c, { company_resolution_source: 'blitz' }); }
    const name = (c.company_name || '').trim();
    if (!name) { stats.no_name++; return Object.assign({}, c, { company_resolution_source: '' }); }
    stats.attempted++;
    // Domain cross-check guard: only accept a match whose LinkedIn website domain
    // matches the partner's Jotform domain (defeats generic-name false positives,
    // e.g. "Cutting Edge Digital" → "Cutting Edge Digital Marketing"). Need a domain.
    const coreA = normDomain(c.company_domain || '').split('.')[0].replace(/-/g, '');
    if (!coreA) { stats.no_match++; return Object.assign({}, c, { company_resolution_source: '' }); }
    const sres = await liSuggestCompany(K, name);
    const candidates = (sres || []).filter((s) => s.urn && nameTokensMatch(name, s.title || '')).slice(0, 4);
    let data = null;
    for (const cand of candidates) {
      const d = await liCompanyData(K, `https://www.linkedin.com/company/${cand.urn}`);
      if (!d) continue;
      const coreB = normDomain(d.websiteUrl || '').split('.')[0].replace(/-/g, '');
      if (coreB && coreA === coreB) { data = d; break; }
    }
    if (!data) { stats.no_match++; return Object.assign({}, c, { company_resolution_source: '' }); }
    const li = normLi(data.url || `https://linkedin.com/company/${data.universalName || ''}`);
    const range = data.employeeCountRange || {};
    const bucket = (range.start != null && range.end != null) ? `${range.start}-${range.end} employees` : '';
    const empForLarge = range.start || data.employeeCount || 0;
    const hq = ((data.headquarter || {}).country || '').toUpperCase();
    const large = isLargeReseller(c.partner_tier, empForLarge);
    stats.recovered++;
    return Object.assign({}, c, {
      company_linkedin_url: li,
      company_size_bucket: bucket,
      company_industry: data.industry || '',
      company_hq_country: hq,
      company_employees_on_linkedin: data.employeeCount || '',
      is_large_reseller: large ? 'yes' : 'no',
      company_resolution_source: 'linkedin_bulk',
    });
  }, 4);
  log('STAGE3b', stats);
  return { companies: out.filter(Boolean), stats };
}

// ===========================================================================
// STAGE 4 — Decision-maker finding, one per ICP bucket (Blitz)
// ===========================================================================
function personFrom(res) {
  const p = res.person || res || {};
  const exp = (p.experiences || [{}])[0] || {};
  return {
    first_name: (p.first_name || '').trim(),
    last_name: (p.last_name || '').trim(),
    title: (exp.job_title || p.headline || '').trim(),
    linkedin_url: normLi(p.linkedin_url || ''),
    person_country: (p.location || {}).country_code || '',
    person_city: (p.location || {}).city || '',
  };
}
function mergeDm(c, p, bucketKey, source) {
  if (!p.first_name && !p.last_name) return null;
  return Object.assign({}, c, {
    icp_bucket: bucketKey,
    first_name: p.first_name,
    last_name: p.last_name,
    title: p.title,
    person_linkedin_url: p.linkedin_url,
    person_location: [p.person_city, p.person_country].filter(Boolean).join(', '),
    dm_source: source,
  });
}
async function stage4Dms(K, companies, opts = {}, log = noop) {
  const headers = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const stats = { companies: companies.length, no_li: 0, dms: 0, fallback_used: 0 };
  const nested = await pMap(companies, async (c) => {
    const li = normLi(c.company_linkedin_url || '');
    if (!li) { stats.no_li++; return []; }
    const isLarge = c.is_large_reseller === 'yes';
    const seen = new Set();
    const rows = [];
    for (const b of ICP_BUCKETS) {
      if (b.largeOnly && !isLarge) continue;
      const w = await httpJson(`${BLITZ}/v2/search/waterfall-icp-keyword`, {
        method: 'POST', headers,
        body: { company_linkedin_url: li, cascade: [{ include_title: b.titles, exclude_title: EXCL_T }], max_results: 1 },
      });
      const res = (w.ok && w.json && w.json.results) || [];
      if (!res.length) continue;
      const p = personFrom(res[0]);
      const key = p.linkedin_url || (p.first_name + ' ' + p.last_name).toLowerCase();
      if (seen.has(key)) continue;
      const row = mergeDm(c, p, b.key, 'waterfall');
      if (row) { rows.push(row); seen.add(key); }
    }
    if (!rows.length) {
      const ef = await httpJson(`${BLITZ}/v2/search/employee-finder`, {
        method: 'POST', headers, body: { company_linkedin_url: li, job_level: EMP_FINDER_LEVELS, max_results: 3, page: 1 },
      });
      const eres = (ef.ok && ef.json && ef.json.results) || [];
      if (eres.length) {
        stats.fallback_used++;
        for (const r of eres) {
          const p = personFrom(r);
          const key = p.linkedin_url || (p.first_name + ' ' + p.last_name).toLowerCase();
          if (seen.has(key)) continue;
          const bk = classifyBucket(p.title, isLarge) || 'A';
          const row = mergeDm(c, p, bk, 'employee_finder');
          if (row) { rows.push(row); seen.add(key); }
        }
      }
    }
    stats.dms += rows.length;
    return rows;
  }, 6);
  const dms = nested.flat().filter(Boolean);
  log('STAGE4', stats);
  return { dms, stats };
}

// ===========================================================================
// STAGE 5 — Email find (Blitz) + verify (MillionVerifier, ok-only)
// ===========================================================================
async function millionVerify(K, email) {
  if (!K.MILLIONVERIFIER_KEY) return { ok: false, status: '' };
  const r = await httpJson(`https://api.millionverifier.com/api/v3/?api=${K.MILLIONVERIFIER_KEY}&email=${encodeURIComponent(email)}&timeout=10`);
  if (!r.ok || !r.json) return { ok: false, status: 'error' };
  const res = (r.json.result || '').toLowerCase(); // ok | catch_all | unknown | invalid | disposable
  return { ok: res === 'ok', status: res };
}
async function stage5Emails(K, dms, log = noop) {
  const headers = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const stats = { input: dms.length, email_found: 0, ok: 0, kept_unverified: 0, dropped_no_li: 0 };
  const out = await pMap(dms, async (row) => {
    const li = normLi(row.person_linkedin_url || '');
    let email = '';
    if (li) {
      const r = await httpJson(`${BLITZ}/v2/enrichment/email`, { method: 'POST', headers, body: { person_linkedin_url: li } });
      email = normEmail((r.json && r.json.email) || '');
    }
    if (email) {
      stats.email_found++;
      const v = await millionVerify(K, email);
      if (v.ok) { stats.ok++; return Object.assign({}, row, { email, email_status: 'ok' }); }
      // Unverified email → keep the person (name/title/LinkedIn) but blank the email
      // and flag the real status. Keep only if we have a LinkedIn to reach them.
      if (li) { stats.kept_unverified++; return Object.assign({}, row, { email: '', email_status: v.status || 'unknown' }); }
      stats.dropped_no_li++; return null;
    }
    // No email found at all — keep the person if reachable via LinkedIn.
    if (li) { stats.kept_unverified++; return Object.assign({}, row, { email: '', email_status: 'not_found' }); }
    stats.dropped_no_li++; return null;
  }, 8);
  const leads = out.filter(Boolean);
  log('STAGE5', stats);
  return { leads, stats };
}

// ===========================================================================
// STAGE 6 — Final assembly (companies × verified DMs, company-only fallback)
// ===========================================================================
const FINAL_COLS = [
  'company_name', 'partner_tier', 'partner_profile_url', 'company_website', 'company_domain',
  'company_location', 'services', 'speciality', 'industries', 'services_enriched',
  'services_enriched_source', 'languages', 'company_description', 'partner_contact_email',
  'company_linkedin_url', 'company_resolution_source', 'company_size_bucket', 'company_industry', 'company_hq_country',
  'is_large_reseller', 'icp_bucket', 'first_name', 'last_name', 'title', 'person_linkedin_url',
  'person_location', 'email', 'email_status',
];
function pick(obj, cols) { const o = {}; for (const c of cols) o[c] = obj[c] == null ? '' : obj[c]; return o; }

function stage6Assemble(companies, leads, log = noop) {
  const byKey = new Map();
  for (const l of leads) { const k = l.company_domain || l.partner_slug; if (!byKey.has(k)) byKey.set(k, []); byKey.get(k).push(l); }
  const rows = [];
  let withLeads = 0, companyOnly = 0;
  for (const c of companies) {
    const k = c.company_domain || c.partner_slug;
    const ls = byKey.get(k) || [];
    if (ls.length) { withLeads++; for (const l of ls) rows.push(pick(l, FINAL_COLS)); }
    else { companyOnly++; rows.push(pick(c, FINAL_COLS)); }
  }
  const stats = { companies: companies.length, verified_leads: leads.length, rows: rows.length, companies_with_leads: withLeads, company_only_rows: companyOnly };
  log('STAGE6', stats);
  return { rows, cols: FINAL_COLS, stats };
}

module.exports = {
  stage1Listing, stage2Details, stage2bEnrich, stage3Firmographics, stage3bRecover,
  stage4Dms, stage5Emails, stage6Assemble, millionVerify,
  parseCards, parseDetail, FINAL_COLS,
};
