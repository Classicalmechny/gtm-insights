# Progress — Switching Claude Accounts Without Losing History

**Date:** 2026-07-06
**Goal:** Re-login to Claude Code with a different account while keeping all existing tabs, history, and work.

---

## ✅ Verified: Your history is safe to switch accounts

Claude Code stores conversation history **locally on this PC**, tied to the **project folder path** — not to your account. Logging in with a different account only swaps a small credentials file; it never touches your history.

| What | Where it lives | Tied to account? |
|------|----------------|------------------|
| Login / account | `~/.claude/.credentials.json` (one small file) | ✅ Yes — this is the only thing that changes |
| Chats / tabs / history | `~/.claude/projects/<folder>/*.jsonl` | ❌ No — tied to the folder, stays put |

When you re-login, the new account opens the **same folders** and sees the **same history**, because history is read from the folder, not the account.

---

## ✅ Backup created (safety net)

A full copy of all local Claude history was made before any account change:

- **Location:** `~/Downloads/claude-history-backup-20260706-132637`
- **Size:** 311 MB (matches original exactly)
- **Contents:** 22 project folders, all `.jsonl` session files

**To restore** (only if ever needed): copy the folders from the backup back into `~/.claude/projects/`.

---

## How to switch accounts safely

1. In Claude Code, run `/login` (or `/logout` then `/login`).
2. Sign in with the new account.
3. Your tabs and history are exactly where they were.

---

## ⚠️ One distinction

- **Claude Code sessions** (VS Code, what you use here) → local, safe, survive the switch. ✅
- **claude.ai website chats** (browser, on claude.ai) → stored on Anthropic's servers under your account. The new account won't *show* the old account's web chats, but they aren't deleted — they stay under the old account and reappear if you log back in.

---

## Status: Complete

- [x] Confirmed history is stored locally and survives account switch
- [x] Full 311 MB backup created and verified
- [x] Safe switch steps documented
- [ ] (Your action) Run `/login` and sign in with the new account whenever ready
