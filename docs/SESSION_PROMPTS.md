# Session prompts

Paste the matching block at the start or end of a session. The three tools
share the protocol in `AGENTS.md`; only the tool-specific notes differ.

`AGENTS.md` and `CLAUDE.md` are private local files, excluded from the
repository. These prompts require the local working copy that holds them.
Never stage or publish either instruction file.

Dates are Europe/London. Follow the confidentiality rule in `AGENTS.md`.

© Mark Hawksworth. All rights reserved.

---

## Claude Code — pre-session

```text
Read AGENTS.md (via this CLAUDE.md import) and docs/SESSION_HANDOFF.md
(newest entry at the top). Follow the Claude session protocol in CLAUDE.md
and the shared rules in AGENTS.md. If I opened with "Let's get started"
and an Eve brief, the brief binds. Continue from In progress and Next
steps; do not redo finished work; stay inside the brief's Out of scope
list. Use British English. Do not run the test suite at the start. You
may use /memory to check Claude auto memory, but do not treat it as the
shared handoff. Confirm the current branch, whether the tree is dirty,
and the latest handoff in two or three lines, then state the plan and
carry on.
```

## Claude Code — end-of-session

```text
Close this session under AGENTS.md and CLAUDE.md. Update
docs/SESSION_HANDOFF.md with a new top entry (date in Europe/London, tool
claude, model in use). Include: done this session, in progress, next
steps, known issues or blockers, files touched, and branch or commit.
If the file would then have more than five entries, move the oldest to
docs/SESSION_HANDOFF_ARCHIVE.md. Update CHANGELOG.md Unreleased only for
notable changes, the private roadmap.md if this session is done, and
memory.md only if a fact changed. Then make one combined Conventional
Commit that includes the work and the handoff. Never push, tag, or
force-push. Close with the eight-point Claude report, including
"Confidentiality: no playthrough details included."
```

---

## Grok Build CLI — pre-session

```text
Read AGENTS.md and docs/SESSION_HANDOFF.md (newest entry at the top).
Follow the session protocol in AGENTS.md. Continue from In progress and
Next steps; do not redo finished work. Use British English. You load
AGENTS.md automatically; if CLAUDE.md is also present, treat AGENTS.md as
canonical and treat CLAUDE.md as Claude-only notes (including "Claude
never pushes"). Do not run the full test suite at the start. Your
~/.grok/sessions and memory-v2 files are private logs, not the shared
handoff. Leave ~/.grok/AGENTS.md alone. Confirm the current branch,
whether the tree is dirty, and the latest handoff in two or three lines,
then wait for my task — or, if I said "Let's get started," state the
plan from the private roadmap and carry on.
```

## Grok Build CLI — end-of-session

```text
Close this session under the protocol in AGENTS.md. Update
docs/SESSION_HANDOFF.md with a new top entry (date in Europe/London, tool
grok, model in use). Include: done this session, in progress, next steps,
known issues or blockers, files touched, and branch or commit. If the
file would then have more than five entries, move the oldest to
docs/SESSION_HANDOFF_ARCHIVE.md. Update CHANGELOG.md Unreleased only for
notable changes, the private roadmap.md if this session is done, and
memory.md only if a fact changed. Then make one combined Conventional
Commit that includes the work and the handoff. Do not push, tag, or
force-push unless I asked, or unless you are carrying out a confirmed
release or sync. Do not bump VERSION or convert Unreleased into a dated
release section; that is Eve's release work.
```

---

## Codex CLI — pre-session

```text
Read AGENTS.md and docs/SESSION_HANDOFF.md (newest entry at the top).
Follow the session protocol in AGENTS.md. Continue from In progress and
Next steps; do not redo finished work. Use British English. You load
AGENTS.md automatically (global ~/.codex/AGENTS.md, then this repo file).
Do not run the full test suite at the start. Your ~/.codex/sessions
rollouts are private logs, not the shared handoff. Confirm the current
branch, whether the tree is dirty, and the latest handoff in two or three
lines, then wait for my task — or, if I said "Let's get started," state
the plan from the private roadmap and carry on.
```

## Codex CLI — end-of-session

```text
Close this session under the protocol in AGENTS.md. Update
docs/SESSION_HANDOFF.md with a new top entry (date in Europe/London, tool
codex, model in use). Include: done this session, in progress, next
steps, known issues or blockers, files touched, and branch or commit.
If the file would then have more than five entries, move the oldest to
docs/SESSION_HANDOFF_ARCHIVE.md. Update CHANGELOG.md Unreleased only for
notable changes, the private roadmap.md if this session is done, and
memory.md only if a fact changed. Then make one combined Conventional
Commit that includes the work and the handoff. Do not push, tag, or
force-push unless I asked, or unless you are carrying out a confirmed
release or sync. Do not bump VERSION or convert Unreleased into a dated
release section; that is Eve's release work.
```
