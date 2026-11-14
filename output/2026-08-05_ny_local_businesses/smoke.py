#!/usr/bin/env python3
import csv, json, os, requests
from enrich_emails import IN_CSV, MV_KEY, dm_for_company, scrape_domain

rows = list(csv.DictReader(open(IN_CSV, encoding="utf-8")))
r = rows[3]  # litigationgod.com — has real domain + linkedin
print("company:", r["company_name"], r["domain"], r["linkedin_url"])
print("web emails:", scrape_domain(r["domain"]))
print("dm:", json.dumps(dm_for_company(r["linkedin_url"]), indent=2)[:600])
c = requests.get("https://api.millionverifier.com/api/v3/credits",
                 params={"api": MV_KEY}, timeout=30)
print("mv credits:", c.text[:200])
