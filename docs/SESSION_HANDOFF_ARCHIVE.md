# Session handoff archive

Older handoff entries, still newest first. The live file
`docs/SESSION_HANDOFF.md` holds only the last 5 entries.

© Mark Hawksworth. All rights reserved.

<!-- Move entries here when SESSION_HANDOFF.md would otherwise exceed
     five entries. Do not edit history except to fix a factual error. -->

---

## 21 November 2026 (Europe/London) — Grok Bot (Jane)

- **Tool:** Grok Bot (Jane)
- **Model:** Grok Bot
- **Branch / commit:** main (workflow commit; local main also held the
  unreleased 3.4 session commits at the time this was written)

### Done this session

- Set up the multi-CLI session workflow so Claude Code, Grok Build CLI,
  and Codex CLI can share context on this project.
- Made `AGENTS.md` the public canonical instruction file (it was previously
  local-only) and kept the existing engine, write-safety, and test rules.
- Added a thin `CLAUDE.md` that imports `@AGENTS.md` and keeps the
  Claude-only brief, test, and never-push rules.
- Added `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`,
  `docs/SESSION_PROMPTS.md`, and a short public `docs/ROADMAP.md`.
- Added an **Unreleased** section to `CHANGELOG.md` and ignored
  `CLAUDE.local.md`.
- Left the private `roadmap.md`, `memory.md`, and `notes/` unpublished,
  and left the global `~/.grok/AGENTS.md` untouched.

### In progress

- Nothing in progress on this workflow.

### Next steps

- Use the prompts in `docs/SESSION_PROMPTS.md` at the start and end of
  the next coding session.
- Release 3.5 remains pending Mark's next brief.
- The 3.4 tag and executable, if not already on GitHub, stay with Neal's
  usual release steps.

### Known issues / blockers

- None for the workflow itself.

### Files touched

- `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `.gitignore`
- `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`,
  `docs/SESSION_PROMPTS.md`, `docs/ROADMAP.md`
