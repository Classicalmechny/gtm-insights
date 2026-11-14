/* ============================================================================
 * Jotform Partner Directory pipeline — local runner / orchestrator.
 *
 *   node run.cjs --cap 5 --pages 1 --stop-after 2b   # cheap scrape+enrich smoke
 *   node run.cjs --cap 5                             # full chain smoke (<$1)
 *   node run.cjs                                     # FULL run (all ~231 partners)
 *   node run.cjs --from-stage3 ../output/<run>/stage3_qualified.csv  # resume 3b→6 on a saved stage-3 CSV
 *
 * Flags:
 *   --cap N           limit to first N partners through the expensive stages
 *   --pages N         only scrape the first N listing pages (default: all 11)
 *   --stop-after S    stop after stage S (1 | 2 | 2b | 3 | 3b | 4 | 5 | 6)
 *   --from-stage3 CSV skip stages 1-3, load companies from CSV, run 3b→6
 *   --run-id ID       custom run id (default: run_<timestamp>)
 *
 * Reads keys from ../.env. Writes per-stage CSV + summary.json to ../output/<run>/.
 * ==========================================================================*/
'use strict';

const fs = require('fs');
const path = require('path');
const S = require('./stages.cjs');
const { writeCsv, readCsv } = require('./lib.cjs');

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
  for (const k of Object.keys(process.env)) if (/^(BLITZ|MILLION|DEEPINFRA|RAPIDAPI)/.test(k)) K[k] = process.env[k];
  return K;
}

const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const val = (f, d) => { const i = argv.indexOf(f); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };

const STAGE_ORDER = ['1', '2', '2b', '3', '3b', '4', '5', '6'];
function reached(stopAfter, stage) {
  if (!stopAfter) return false;
  return STAGE_ORDER.indexOf(stage) >= STAGE_ORDER.indexOf(stopAfter);
}

(async () => {
  const K = loadEnv();
  const cap = Number(val('--cap', '0')) || 0;
  const pages = Number(val('--pages', '0')) || 0;
  const stopAfter = val('--stop-after', '');
  const fromStage3 = val('--from-stage3', '');
  const runId = val('--run-id', 'run_' + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, ''));
  const outDir = path.join(__dirname, '..', 'output', runId);
  const log = (step, data) => console.log(`[${step}]`, JSON.stringify(data));
  const t0 = Date.now();
  const summary = { run_id: runId, stages: {} };

  console.log(`\n=== Jotform Partner Directory pipeline — run ${runId} ===`);
  console.log('config:', JSON.stringify({ cap: cap || 'all', pages: pages || 'all', stopAfter: stopAfter || 'none', fromStage3: fromStage3 || 'no' }));

  let companies; // company-level rows feeding Stage 3b onward

  if (fromStage3) {
    const abs = path.isAbsolute(fromStage3) ? fromStage3 : path.resolve(process.cwd(), fromStage3);
    companies = readCsv(abs);
    if (cap) companies = companies.slice(0, cap);
    log('resume', { from: abs, companies: companies.length });
  } else {
    // Stage 1
    const s1 = await S.stage1Listing(K, pages ? { pages } : {}, log);
    writeCsv(path.join(outDir, 'stage1_partners.csv'), s1.partners);
    summary.stages.s1 = s1.stats;
    let partners = cap ? s1.partners.slice(0, cap) : s1.partners;
    if (reached(stopAfter, '1')) return finish();

    // Stage 2
    const s2 = await S.stage2Details(K, partners, {}, log);
    writeCsv(path.join(outDir, 'stage2_companies.csv'), s2.companies);
    summary.stages.s2 = s2.stats;
    if (reached(stopAfter, '2')) return finish();

    // Stage 2b
    const s2b = await S.stage2bEnrich(K, s2.companies, {}, log);
    writeCsv(path.join(outDir, 'stage2b_enriched.csv'), s2b.companies);
    summary.stages.s2b = s2b.stats;
    if (reached(stopAfter, '2b')) return finish();

    // Stage 3
    const s3 = await S.stage3Firmographics(K, s2b.companies, log);
    writeCsv(path.join(outDir, 'stage3_qualified.csv'), s3.companies);
    summary.stages.s3 = s3.stats;
    companies = s3.companies;
    if (reached(stopAfter, '3')) return finish();
  }

  // Stage 3b — LinkedIn-Bulk recovery for Blitz misses
  const s3b = await S.stage3bRecover(K, companies, log);
  writeCsv(path.join(outDir, 'stage3b_recovered.csv'), s3b.companies);
  summary.stages.s3b = s3b.stats;
  companies = s3b.companies;
  if (reached(stopAfter, '3b')) return finish(companies);

  // Stage 4
  const s4 = await S.stage4Dms(K, companies, {}, log);
  writeCsv(path.join(outDir, 'stage4_dms.csv'), s4.dms);
  summary.stages.s4 = s4.stats;
  if (reached(stopAfter, '4')) return finish(companies);

  // Stage 5
  const s5 = await S.stage5Emails(K, s4.dms, log);
  writeCsv(path.join(outDir, 'stage5_leads_verified.csv'), s5.leads);
  summary.stages.s5 = s5.stats;
  if (reached(stopAfter, '5')) return finish(companies, s5.leads);

  // Stage 6
  const s6 = S.stage6Assemble(companies, s5.leads, log);
  writeCsv(path.join(outDir, 'jotform_partner_leads.csv'), s6.rows, s6.cols);
  summary.stages.s6 = s6.stats;
  return finish(companies, s5.leads, s6);

  function finish() {
    summary.elapsed_s = Math.round((Date.now() - t0) / 1000);
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
    console.log('\n=== SUMMARY ===');
    console.log(JSON.stringify(summary, null, 2));
    console.log(`\nOutputs → ${outDir}`);
  }
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
