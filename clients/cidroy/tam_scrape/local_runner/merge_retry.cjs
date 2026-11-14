'use strict';
const fs = require('fs'), path = require('path');
const D = path.join(__dirname, '..');
const CSV = path.join(D, 'Cidroy_leads_FINAL_12k_with_phone.csv');
const CKPT = path.join(D, 'output', 'full', 'phone_retry.jsonl');
function parseCsv(text){const rows=[];let f='',row=[],q=false,i=0;while(i<text.length){const c=text[i];if(q){if(c==='"'){if(text[i+1]==='"'){f+='"';i+=2;continue;}q=false;i++;continue;}f+=c;i++;continue;}if(c==='"'){q=true;i++;continue;}if(c===','){row.push(f);f='';i++;continue;}if(c==='\r'){i++;continue;}if(c==='\n'){row.push(f);rows.push(row);row=[];f='';i++;continue;}f+=c;i++;}if(f.length||row.length){row.push(f);rows.push(row);}return rows;}
function writeCsv(file,header,rows){const esc=(v)=>{const s=v==null?'':String(v);return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};const lines=[header.map(esc).join(',')];for(const r of rows)lines.push(header.map((h)=>esc(r[h])).join(','));fs.writeFileSync(file,lines.join('\n'));}
const key=(l)=>(l.linkedin_url||(l.first_name+'|'+l.last_name+'|'+l.company_domain)).toLowerCase();
const rows=parseCsv(fs.readFileSync(CSV,'utf8'));const header=rows[0];
const leads=rows.slice(1).filter((r)=>r.length>=header.length-1).map((r)=>{const o={};header.forEach((h,k)=>{o[h]=r[k]!=null?r[k]:'';});return o;});
const map={};for(const l of fs.readFileSync(CKPT,'utf8').split('\n').filter(Boolean)){try{const e=JSON.parse(l);if(e.phone)map[e.k]=e.phone;}catch(_){}}
let added=0;for(const l of leads){const p=map[key(l)];if(p&&!(l.phone_number||'').trim()){l.phone_number=p;l.phone_source='quickenrich_namecompany';added++;}}
const total=leads.filter((l)=>(l.phone_number||'').trim()).length;
let target=CSV;
try{writeCsv(CSV,header,leads);}
catch(e){if(e.code==='EBUSY'){target=CSV.replace(/\.csv$/,'_updated.csv');writeCsv(target,header,leads);}else throw e;}
console.log(JSON.stringify({new_phones_added:added,total_with_phone:total,fill_rate:+(total/leads.length).toFixed(3),wrote:target,canonical_was_locked:target!==CSV},null,2));
