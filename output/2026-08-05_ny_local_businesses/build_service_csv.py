#!/usr/bin/env python3
"""Join workflow-generated Service notes onto the 146 verified-ok leads."""
import csv, html, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = (r"C:\Users\ISHWAR CHANDR SHARMA\.claude\projects"
           r"\c--Users-ISHWAR-CHANDR-SHARMA-Downloads-Outbound-Work-personal-assistant"
           r"\b9a57236-ee43-4778-815e-e5c2a2435166\subagents\workflows\wf_d5b96c44-cf3\journal.jsonl")
OUT = os.path.join(HERE, "ny_local_verified_ai_service.csv")

leads = json.load(open(os.path.join(HERE, "verified_ok_for_service.json"), encoding="utf-8"))

notes = {}
for line in open(JOURNAL, encoding="utf-8"):
    rec = json.loads(line)
    if rec.get("type") != "result":
        continue
    val = rec.get("result") or rec.get("value") or {}
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            continue
    for n in (val.get("notes") or []):
        notes[int(n["i"])] = html.unescape(n["service"]).strip()

missing = [l["i"] for l in leads if l["i"] not in notes]
print(f"notes: {len(notes)}, leads: {len(leads)}, missing: {missing}")

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["company_name", "industry", "state", "country", "website", "email", "Service"])
    for l in leads:
        w.writerow([l["company_name"], l["industry"], l["state"], l["country"],
                    l["website"], l["email"], notes.get(l["i"], "")])
print("OUT:", OUT)
