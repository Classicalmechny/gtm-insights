# Personal Assistant — IntentLedSales Internal Workspace

Shared Claude Code workspace for the IntentLedSales team. Contains 11 production skills, 3 client project archives, and links to the autonomous `AI-employee-brain` runtime.

## What's in here

| Path | What it is |
|---|---|
| [`.claude/skills/`](.claude/skills/) | 11 production skills (lead lists, infographics, carousels, ad research, deliverability tests, etc.) |
| [`.mcp.json`](.mcp.json) | Project-scoped MCP servers — auto-loaded by Claude Code on first use |
| [`CLAUDE.md`](CLAUDE.md) | Global operating prompt (prompt contracts, reverse prompting, agent loops, etc.) |
| [`clients/ayna/`](clients/ayna/) | Ayna niche-fashion lead pipeline run — 4,671 verified emails (Storeleads dump via Git LFS) |
| [`clients/techhive/`](clients/techhive/) | TechHive Campaign A (vibe-coding founders) — Trigify + Instantly delivery |
| [`clients/catsy/`](clients/catsy/) | Catsy Zapmail mailbox rotation + spam-test audits |
| `brain/` | Git submodule → [`AI-employee-brain`](https://github.com/anirudhgupta1177/AI-employee-brain) (Slack-fronted Claude agent on VPS) |

## First-time team setup (5 min)

```bash
# 1. Install prerequisites
brew install gh git-lfs

# 2. Clone with submodule + LFS
git clone --recurse-submodules https://github.com/anirudhgupta1177/personal-assistant.git
cd personal-assistant
git lfs pull

# 3. Open in Claude Code
claude
```

On first prompt that needs an MCP tool, Claude Code will ask you to approve the project MCPs from `.mcp.json`. Approve once — they stay approved for the session.

## Available MCP servers (pre-configured in [.mcp.json](.mcp.json))

| MCP | Use | Auth |
|---|---|---|
| `rapidapi-linkedin-bulk` | LinkedIn profile / post-engagement / company-employee scraping (37 tools). Resolves Trigify obfuscated URNs. | Shared RapidAPI key embedded |
| `rapidapi-jsearch` | Live job-board search across 20+ boards (LinkedIn/Indeed/Glassdoor/ZipRecruiter etc.). Hiring-signal prospecting. | Same RapidAPI key, one quota |

To add more team MCPs: edit [`.mcp.json`](.mcp.json) → commit → teammates get them on `git pull`. Quotas are shared.

## Available skills

| Skill | One-liner |
|---|---|
| [`build-cold-email-list`](.claude/skills/build-cold-email-list/) | Build production cold-email list from an ICP — routes across BlitzAPI, Ocean.io, Instantly Supersearch, niche directories |
| [`lead-list-from-strategy-doc`](.claude/skills/lead-list-from-strategy-doc/) | End-to-end TAM build from a Google Doc strategy brief |
| [`job-board-scraping`](.claude/skills/job-board-scraping/) | Hiring-signal prospecting via JSearch — companies actively hiring = buying signal |
| [`competitor-ad-research`](.claude/skills/competitor-ad-research/) | Meta Ad Library scrape → faster-whisper transcribe → analyst report |
| [`linkedin-carousel`](.claude/skills/linkedin-carousel/) | 6-9 slide LinkedIn doc-post carousel as PDF (Playwright renderer) |
| [`linkedin-infographic`](.claude/skills/linkedin-infographic/) | Single-page tall infographic (PNG + PDF) in IntentLedSales brand |
| [`campaign-optimization`](.claude/skills/campaign-optimization/) | Rebalance Instantly per-campaign daily_limit to mailbox capacity |
| [`smartlead-spam-test`](.claude/skills/smartlead-spam-test/) | Full deliverability audit on Smartlead workspaces |
| [`connect-spaceship-to-inboxkit`](.claude/skills/connect-spaceship-to-inboxkit/) | Point Spaceship domains at InboxKit Cloudflare NS, verify propagation |

Each skill has its own `skill.md` with triggers, full process, and references. Claude Code loads only the YAML headers into context — the body loads on demand (iceberg pattern).

## How skills get activated

Skills auto-trigger on natural-language prompts that match their `triggers:` block in YAML. Examples:

- "build a lead list for [client]" → `lead-list-from-strategy-doc` or `build-cold-email-list`
- "who's hiring SDRs in Austin?" → `job-board-scraping`
- "make a LinkedIn carousel on [topic]" → `linkedin-carousel`
- "research competitor ads for [brand]" → `competitor-ad-research`
- "audit Smartlead deliverability" → `smartlead-spam-test`

Or invoke explicitly with `/skill-name` (slash + skill name).

## Brain submodule

`brain/` points at the [`AI-employee-brain`](https://github.com/anirudhgupta1177/AI-employee-brain) repo — the 24/7 Slack-fronted agent that runs on the Huddle01 VPS. You don't need to touch it for day-to-day skill work, but it's there for context.

If you don't have access to `AI-employee-brain` yet, ping Anirudh — submodule clone will fail without read access.

## Conventions

- **Output dirs**: every skill writes to `output/<run_id>/` relative to the working dir. `run_id` defaults to `<date>_<slug>`.
- **No secrets in commits**: production API keys live in `.mcp.json` (shared team keys) or env vars. Personal tokens go in `~/.claude.json` (user scope, never committed).
- **Sample-validate-iterate**: every lead-list run pulls 20 random samples first, validates against ICP, then scales. Never run full pipeline blind.
- **Always read [`CLAUDE.md`](CLAUDE.md)** before starting — defines the agent loop, prompt-contract protocol, and learned rules across the whole workspace.

## Maintainers

- Anirudh Gupta — [@anirudhgupta1177](https://github.com/anirudhgupta1177)
