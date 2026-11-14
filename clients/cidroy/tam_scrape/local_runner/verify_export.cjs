/* ============================================================================
 * Standalone VERIFY + EXPORT — salvages the already-scraped emails.
 * Reads output/full/email_results.jsonl (the ~21k found emails), dedupes by
 * email, runs MillionVerifier (keep "ok" only), writes final.csv.
 * Resumable: appends to verify_results.jsonl, skips already-verified emails.
 *
 *   node verify_export.cjs
 * ==========================================================================*/
'use strict';
const fs = require('fs');
const path = require('path');
const R = require('./run.cjs');
const { loadKeys, pMap, millionVerify, writeCsv, CSV_COLS, normEmail } = R;

const outDir = path.join(__dirname, '..', 'output', 'full');
const emailFile = path.join(outDir, 'email_results.jsonl');
const verifyFile = path.join(outDir, 'verify_results.jsonl');
const finalCsv = path.join(outDir, 'final.csv');

function readJsonl(f) {
  if (!fs.existsSync(f)) return [];
  return fs.readFileSync(f, 'utf8').split('\n').filter(Boolean)
    .map((l) => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(Boolean);
}
const appendJsonl = (f, o) => fs.appendFileSync(f, JSON.stringify(o) + '\n');

(async () => {
  const K = loadKeys();
  if (!K.MILLIONVERIFIER_KEY) { console.error('missing MV key'); process.exit(1); }

  // 1. load scraped emails, dedupe by email (handles re-email duplicates)
  const rows = readJsonl(emailFile).filter((x) => x.email);
  const byEmail = new Map();
  for (const r of rows) { const e = normEmail(r.email); if (e && !byEmail.has(e)) byEmail.set(e, r); }
  const leads = [...byEmail.values()];
  console.log(`email rows: ${rows.length} | unique emails: ${leads.length}`);

  // 2. resume — skip already-verified
  const prior = readJsonl(verifyFile);
  const doneEmails = new Set(prior.map((x) => normEmail(x.email)));
  const okAll = prior.filter((x) => x.email_verification_status === 'ok');
  const todo = leads.filter((l) => !doneEmails.has(normEmail(l.email)));
  console.log(`already verified: ${prior.length} (ok ${okAll.length}) | to verify now: ${todo.length}`);

  // 3. verify
  const stats = { ok: okAll.length, catch_all: 0, invalid: 0, unknown: 0, disposable: 0, error: 0, done: 0 };
  await pMap(todo, async (r) => {
    const v = await millionVerify(K, r.email);
    stats[v.status] = (stats[v.status] || 0) + 1;
    const rec = Object.assign({}, r, { email_verification_status: v.status, source: 'blitz_people_search' });
    appendJsonl(verifyFile, rec);
    if (v.ok) okAll.push(rec);
    if (++stats.done % 500 === 0) console.log(`verified ${stats.done}/${todo.length} | ok ${okAll.length}`);
  }, 15);

  // 4. export — dedupe by email, enforce compulsory fields
  const seen = new Set(); const finalRows = [];
  for (const r of okAll) {
    const e = normEmail(r.email);
    if (!e || !r.first_name || !r.company_name) continue;
    if (seen.has(e)) continue;
    seen.add(e); finalRows.push(r);
  }
  writeCsv(finalCsv, finalRows, CSV_COLS);
  const summary = {
    unique_emails_verified: leads.length,
    verify_breakdown: stats,
    final_high_fit_leads: finalRows.length,
    output_csv: finalCsv,
  };
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log('\n=== DONE ===');
  console.log(JSON.stringify(summary, null, 2));
  console.log(`\nFINAL CSV → ${finalCsv}`);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
