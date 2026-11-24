# FM Name Editor — guide for Claude

@AGENTS.md

Shared project rules, commands, files, confidentiality, and the cross-tool
session protocol live in `AGENTS.md`. The notes below apply to **Claude
Code only**. Keep this file short: Grok Build CLI also loads `CLAUDE.md`
alongside `AGENTS.md`, so repeating the canonical rules here would load
them twice in Grok.

© Mark Hawksworth. All rights reserved.

## Session protocol (Claude Code)

Mark opens a session with **"Let's get started."**, followed by the
standing rules and the **session brief** selected for that session
(numbered stages, an **Out of scope** list, and acceptance tests for each
stage). The selected brief is authoritative, with the standing rules;
where they are stricter than this file or `AGENTS.md`, follow them. When you see that:

1. Read `CLAUDE.md` (and the imported `AGENTS.md`), `docs/SESSION_HANDOFF.md`,
   `CHANGELOG.md`, and `git status` / `git log --oneline -5`. If they are
   present on this PC, also read `memory.md`, `roadmap.md`, and the note
   named in the brief (otherwise the highest-numbered note in `notes\`).
2. Do not run the test suite at the start of a session (see **Test suite**
   in `AGENTS.md`).
3. Do the stages in the brief, in order, starting with **Stage 0** if there
   is one (follow-ups and bugs reported but not fixed in an earlier
   session). Without a brief, take the session marked **next** in
   `roadmap.md`, and continue from the latest handoff entry. State the plan
   in three to five lines, then carry on without waiting; stop and ask only
   if the plan would go outside the brief. Never start anything on the
   **Out of scope** list, and do not pull work forward from later sessions
   unless it is a one-line prerequisite.
4. Work in this order: engine change, tests for it, then GUI, then documents.
5. End the session as `AGENTS.md` describes: targeted tests green; one
   combined Conventional Commit (`feat:`, `fix:`, `test:`, `docs:`) that
   includes the work, `docs/SESSION_HANDOFF.md`, `CHANGELOG.md`
   (**Unreleased** until the release ships). Update the private `roadmap.md`
   / `memory.md` locally if they changed; never stage them. **Never push.** Session
   commits stay local on `main` until Neal releases them (see **Releasing**
   in `AGENTS.md`).
6. Close with this report, in this order: (1) what shipped, stage by stage;
   (2) commit hash(es) and changed files; (3) the targeted tests run, with
   counts and results, and "Full suite not run (Neal runs it).";
   (4) version sync: `VERSION`, the launcher banner, and the README and
   CHANGELOG headers unchanged, with this session's entries under
   **Unreleased**; (5) "Private files not tracked: confirmed"; (6) bugs
   found but not fixed, or "none"; (7) "Confidentiality: no playthrough
   details included."; (8) what is next, or "Release X.Y ready for Neal".

If a session cannot finish in one sitting, split it. Write the remainder
into the private roadmap as the next session, update the handoff, and
commit what is complete before you stop. Never leave the working tree with
a failing targeted test at the end of a session.

Use `/memory` if you need to inspect or tidy Claude auto memory. Do not
treat auto memory as the shared project record; other tools cannot see it.

## Git (Claude Code)

Remote: `https://github.com/hawkers63/FM-Name-Editor` (`origin`, branch
`main`, public). **Claude never pushes, tags, or force-pushes.** Session
commits stay local on `main`; Neal pushes them with the release, and only
after Mark confirms (see **Releasing** in `AGENTS.md`). Commits use
Conventional Commits and end with the attribution line given in the
session. Branch before experiments; `main` holds released or
session-complete work only.

Neal keeps this file up to date with the current Claude workflow; Mark
selects the brief for each session.
