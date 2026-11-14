# Final CSV Schema (Canonical)

```
first_name              # required, title case
last_name               # required, title case
email                   # required, lowercase, verified
title
company_name            # required
company_domain          # required, lowercase, no protocol, no www., no trailing /
linkedin_url
company_linkedin_url
company_industry
company_employee_count
country                 # full country name, not ISO-2
state
city
phone                   # E.164 if possible
email_verification_status  # "valid" | "accept_all"
email_risk              # "low" (valid) | "medium" (accept_all)
sources                 # comma-joined: e.g. "instantly_supersearch,ocean_dm"
[ai_variable_1]         # added when ai_variables.enabled = true, in order
[ai_variable_2]
...
[delivery.columns_extra...]  # any extra columns user requested
```

Notes:
- File encoding: UTF-8, no BOM.
- Line endings: `\r\n` for tool compatibility.
- Quoting: minimal (RFC 4180). Fields with `,` or `"` are double-quoted.
- Header row is mandatory.
- Empty cells are allowed for optional fields (state, city, phone) but
  NOT for required fields — rows missing required fields are dropped at
  export time.
