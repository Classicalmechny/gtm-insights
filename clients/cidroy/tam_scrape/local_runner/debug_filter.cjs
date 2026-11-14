/* Page a few times; show company distribution + kept density. Reuses run.cjs config. */
'use strict';
const R = require('./run.cjs');
const { CFG, titleIsDM, loadKeys, httpJson, currentExp, searchBody } = R;
const PAGES = Number(process.argv[2] || 5);

(async () => {
  const K = loadKeys();
  const H = { 'x-api-key': K.BLITZAPI_KEY, 'Content-Type': 'application/json' };
  const tally = { raw: 0, headline: 0, company: 0, title: 0, kept: 0 };
  const coCount = {};
  let cursor = null;
  for (let pg = 0; pg < PAGES; pg++) {
    const r = await httpJson('https://api.blitz-api.ai/v2/search/people', { method: 'POST', headers: H, body: searchBody(cursor, 50) });
    const rows = (r.json && (r.json.results || r.json.people || r.json.data)) || [];
    if (pg === 0) console.log('total_results', r.json && r.json.total_results);
    for (const p of rows) {
      tally.raw++;
      const exp = currentExp(p);
      const co = (exp.company_name || '').trim();
      const hl = p.headline || '';
      const title = (exp.job_title || '').trim();
      coCount[co] = (coCount[co] || 0) + 1;
      if (CFG.headlineExclude.find((re) => re.test(hl))) { tally.headline++; continue; }
      if (CFG.companyExclude.find((re) => re.test(co))) { tally.company++; continue; }
      if (!titleIsDM(title)) { tally.title++; continue; }
      tally.kept++;
    }
    cursor = r.json && r.json.cursor;
    if (!cursor) break;
    await new Promise((s) => setTimeout(s, 220));
  }
  console.log('TALLY', JSON.stringify(tally), 'kept_density', (tally.kept / tally.raw).toFixed(3));
  const top = Object.entries(coCount).sort((a, b) => b[1] - a[1]).slice(0, 20);
  console.log('TOP COMPANIES (by count in sample):');
  for (const [name, n] of top) console.log(`  ${n}\t${name}`);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
