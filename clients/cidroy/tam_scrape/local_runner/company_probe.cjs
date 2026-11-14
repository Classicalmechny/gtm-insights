/* Probe /v2/search/companies + /v2/search/employee-finder shapes & quality. */
'use strict';
const R = require('./run.cjs');
const { CFG, loadKeys, httpJson } = R;
const BLITZ = 'https://api.blitz-api.ai';

(async () => {
  const K = loadKeys();
  const H = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };

  // ---- company search ----
  const body = {
    company: {
      employee_range: CFG.employeeRange,
      industry: { include: CFG.industryInclude, exclude: CFG.industryExclude },
      location: { country_code: CFG.countries },
    },
    max_results: 10,
  };
  console.log('=== /v2/search/companies ===');
  console.log('req:', JSON.stringify(body));
  let r = await httpJson(`${BLITZ}/v2/search/companies`, { method: 'POST', headers: H, body });
  console.log('status', r.status, 'total', r.json && r.json.total_results, 'cursor?', !!(r.json && r.json.cursor));
  if (r.status !== 200) { console.log('raw:', (r.text || '').slice(0, 1500)); }
  const cos = (r.json && (r.json.results || r.json.companies || r.json.data)) || [];
  console.log('returned', cos.length);
  console.log('first company keys:', cos[0] ? Object.keys(cos[0]).join(',') : '(none)');
  for (const c of cos.slice(0, 10)) {
    console.log(JSON.stringify({ name: c.name || c.company_name, domain: c.domain || c.website || c.company_domain, li: c.linkedin_url || c.company_linkedin_url, size: c.employee_range || c.size || c.employee_count, industry: c.industry, country: (c.hq && c.hq.country_code) || c.country_code || c.country }));
  }

  // ---- employee finder on the first company ----
  const c0 = cos[0];
  const coLi = c0 && (c0.linkedin_url || c0.company_linkedin_url);
  if (coLi) {
    console.log('\n=== /v2/search/employee-finder (company:', coLi, ') ===');
    const ef = await httpJson(`${BLITZ}/v2/search/employee-finder`, { method: 'POST', headers: H, body: {
      company_linkedin_url: coLi,
      people: { job_title: { include: CFG.titleInclude, exclude: CFG.titleExclude } },
      max_results: 5,
    } });
    console.log('status', ef.status);
    const emps = (ef.json && (ef.json.results || ef.json.people || ef.json.data)) || [];
    console.log('returned', emps.length, '| first keys:', emps[0] ? Object.keys(emps[0]).join(',') : '(none)');
    for (const e of emps.slice(0, 5)) {
      const exp = (e.experiences || []).find((x) => x && x.job_is_current) || (e.experiences || [])[0] || {};
      console.log(JSON.stringify({ name: e.full_name, title: exp.job_title || e.headline, company: exp.company_name, li: e.linkedin_url }));
    }
    if (ef.status !== 200) console.log('raw:', (ef.text || '').slice(0, 1200));
  }
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
