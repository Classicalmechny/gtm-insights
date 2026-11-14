/* ============================================================================
 * QSET pipeline — local Node runner / validator.
 *
 *   node run.cjs --smoke                 # tiny: ~8 roles, US, 1 page, cap funnel
 *   node run.cjs --smoke --no-upload     # same, but don't touch Instantly
 *   node run.cjs                         # full: all roles, all countries
 *   node run.cjs --pages 3 --cap 400 --per-company 2
 *
 * Reads keys from ../.env. Writes per-stage CSV + summary.json to ../output/<run>/.
 * ==========================================================================*/
'use strict';

const fs = require('fs');
const path = require('path');
const S = require('./stages.cjs');
const { ROLES } = require('./lib.cjs');

// ---- .env loader ----------------------------------------------------------
function loadEnv() {
  const p = path.join(__dirname, '..', '.env');
  const K = {};
  if (fs.existsSync(p)) {
    for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith('#') || !t.includes('=')) continue;
      const i = t.indexOf('=');
      K[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
  }
  for (const k of Object.keys(process.env)) if (k.startsWith('RAPIDAPI') || k.startsWith('BLITZ') || k.startsWith('INSTANTLY') || k.startsWith('MILLION')) K[k] = process.env[k];
  return K;
}

// ---- arg parsing ----------------------------------------------------------
const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const val = (f, d) => { const i = argv.indexOf(f); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };

// ---- CSV writer -----------------------------------------------------------
function writeCsv(file, rows) {
  if (!rows.length) return 0;
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [cols.join(',')];
  for (const r of rows) lines.push(cols.map((c) => esc(r[c])).join(','));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, lines.join('\n'));
  return rows.length;
}

(async () => {
  const K = loadEnv();
  const smoke = has('--smoke');
  const runId = val('--run-id', (smoke ? 'smoke_' : 'run_') + new Date().toISOString().slice(0, 16).replace(/[:T]/g, '').replace(/-/g, ''));
  const outDir = path.join(__dirname, '..', 'output', runId);

  const cfg = {
    roles: has('--roles-all') || !smoke ? ROLES
      : ['DevOps Engineer', 'Backend Developer', 'React Developer', 'Data Engineer', 'AI Engineer', 'Python Developer', 'Full Stack Developer', 'Cloud Engineer'],
    countries: (val('--countries', smoke ? 'US' : 'US,GB,CA,AU')).split(','),
    pagesPerRole: Number(val('--pages', smoke ? '1' : '3')),
    datePosted: val('--date-posted', smoke ? 'month' : 'week'),
    capCompanies: Number(val('--cap', smoke ? '70' : '100000')),
    maxQualified: Number(val('--max-qualified', smoke ? '12' : '100000')),
    perCompany: Number(val('--per-company', smoke ? '1' : '2')),
    upload: !has('--no-upload'),
  };

  const log = (step, data) => { console.log(`[${step}]`, JSON.stringify(data)); };
  console.log(`\n=== QSET pipeline — run ${runId} (${smoke ? 'SMOKE' : 'FULL'}) ===`);
  console.log('config:', JSON.stringify(cfg));
  const t0 = Date.now();

  // Stage 1
  const s1 = await S.stage1Scrape(K, cfg, log);
  let companies = s1.companies.slice(0, cfg.capCompanies);
  writeCsv(path.join(outDir, 'stage1_companies.csv'), companies);

  // Stage 1b
  const s1b = await S.stage1bFilter(K, companies, log);
  const qualified = s1b.qualified.slice(0, cfg.maxQualified);
  writeCsv(path.join(outDir, 'stage1b_qualified.csv'), qualified);

  // Stage 2
  const s2 = await S.stage2Dms(K, qualified, { perCompany: cfg.perCompany }, log);
  writeCsv(path.join(outDir, 'stage2_dms.csv'), s2.dms);

  // Stage 3
  const s3 = await S.stage3Emails(K, s2.dms, log);
  writeCsv(path.join(outDir, 'stage3_leads_verified.csv'), s3.leads);

  // Stage 4
  const s4 = S.stage4Personalize(s3.leads, log);
  writeCsv(path.join(outDir, 'stage4_personalized.csv'), s4.leads);

  // Stage 5 — upload by region (one campaign per region/timezone)
  let s5 = { totals: { uploaded: 0 }, by_region: { note: 'upload disabled' } };
  if (cfg.upload && s4.leads.length) {
    s5 = await S.uploadByRegion(K, s4.leads, log);
    writeCsv(path.join(outDir, 'stage5_personalized_all.csv'), s4.leads);
  }

  const summary = {
    run_id: runId, mode: smoke ? 'smoke' : 'full', elapsed_s: Math.round((Date.now() - t0) / 1000),
    funnel: {
      unique_companies: s1.stats.unique_companies, into_filter: companies.length,
      qualified: s1b.stats.qualified, into_dm: qualified.length,
      decision_makers: s2.stats.dms, verified_leads: s3.stats.kept,
      uploaded: s5.totals.uploaded || 0,
    },
    upload_by_region: s5.by_region,
    stage_stats: { s1: s1.stats, s1b: s1b.stats, s2: s2.stats, s3: s3.stats, s4: s4.stats },
  };
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log('\n=== SUMMARY ===');
  console.log(JSON.stringify(summary, null, 2));
  console.log(`\nOutputs → ${outDir}`);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
