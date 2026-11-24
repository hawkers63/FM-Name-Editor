# Session handoff

Newest entry at the top. Keep only the last 5 entries here. Move older
entries to `docs/SESSION_HANDOFF_ARCHIVE.md`.

This file is the shared progress record for Claude Code, Grok Build CLI,
and Codex CLI. Update it at the end of every session.

© Mark Hawksworth. All rights reserved.

---

## 24 November 2026 (Europe/London) — Grok Bot (Neal)

- **Tool:** Grok Bot (Neal)
- **Model:** Grok Bot
- **Branch / commit:** main, local `docs: finalise Release 3.7 version, headers, changelog and README`, annotated tag `v3.7`, not pushed

### Done this session

- Reviewed Session 21 (`b8673e8`): the commit changes only `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `README.md`, `docs/SESSION_HANDOFF.md` and `docs/SESSION_HANDOFF_ARCHIVE.md`. No private files, no tag. Binding rules hold: suggestions fill only empty fields on an explicit action; Fix formatting is one undoable step and does not resolve a shared code; snapshots stay in memory, capped at ten, and rollback is one undo step without clearing the stack. Ctrl+Shift+D is still Deploy. Rollback is a submenu and does not ask for confirmation (reported; not changed in this pass).
- Ran the full suite once: 372 tests in 59.455s, all passing offscreen.
- Finalised Release 3.7: `VERSION`, the launcher banner, the README and CHANGELOG headers, a dated CHANGELOG section with an empty Unreleased section above it, the public roadmap, and this handoff. Private `roadmap.md` was updated and not staged. The executable was built and not launched. Release notes were written. Nothing was pushed.

### In progress

- Nothing. Waiting for Mark to confirm the push and the GitHub Release.

### Next steps

- After Mark confirms: push `main` then tag `v3.7`, and create the GitHub Release with the exe.
- Further sessions are to be planned.

### Known issues / blockers

- None that block the release. Rollback does not show a confirmation dialog (the brief had asked for one). Club names used as generic examples in tests and docs were left as they are for Mark to decide. The Session 21 handoff line about live-file health counts was not copied into the release notes.

### Files touched

- `fm_name_editor.py`, `FM Name Editor.bat`, `CHANGELOG.md`, `README.md`,
  `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`;
  private `roadmap.md` (not tracked)

---

## 24 November 2026 (Europe/London) — Claude Code (Session 21)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Branch / commit:** main, local `feat: short names and codes, name health and snapshots`, not pushed

### Done this session

- No brief was pasted and none was at the top of this file, so the scope came from Neal's last entry and the private roadmap: note 09 proposals 3 to 5, Release 3.7. Where the note left room, the decisions are listed under Known issues.
- Stage 0: Ctrl+Alt+D and Ctrl+Alt+K were free (Ctrl+Alt+S is Select same file section). A read-only baseline on a large real-world set of files found names to check (shared 3-letter codes in a file section, lower-case codes, a double space, and curly quotes). A health pass takes about 42 ms after a fast path for tidy names (68 ms without it).
- Stage 1 (proposal 3): `short_name_from`, `code_candidates`, `synthesise_siblings`, `sibling_suggestion` and `fill_siblings`. The inspector shows the suggestion first, with Use suggestion; Edit > Fill short name and code (Ctrl+Alt+D, in the palette and the busy actions) does the same. Clubs only, empty fields only, one Undo step, reason `suggest` ("Suggested").
- Stage 2 (proposal 4): `LintIssue`, `name_findings`, `lint_entity`, `name_health`, `health_summary`, `tidy_name` and `fix_formatting`. The status bar reads "Name health: N to check" (a link to a new `health` status filter, the "Name health" button) or "Name health: clean"; the grid's Status reads Check in amber, with the findings in its tooltip; the inspector shows a notice with Fix formatting. Edit > Fix formatting tidies the selected rows as one Undo step, reason `tidy`.
- Stage 3 (proposal 5): `Snapshot`, `take_snapshot`, `roll_back_to` and `SNAPSHOT_LIMIT` (10). Edit > Create snapshot... (Ctrl+Alt+K) and the Roll back to snapshot submenu, one Undo step; cleared in `adopt_documents`. `Operation` gained `note_rebase` (`_note_rebase`), so undoing or redoing a roll back that crossed a write matches the lines to the disk file again.
- User guide (three sections), CHANGELOG Unreleased, README "Planned for 3.7" line. The oldest handoff entry moved to the archive.

### In progress

- Nothing.

### Next steps

- Session 21 closes Release 3.7. Neal: verify, run the full suite once, finalise the version headers and the dated CHANGELOG section, then tag and push after Mark confirms.

### Known issues / blockers

- Decisions where the note left room: suggestions for clubs only, and only for empty fields; the note's AVL (Aston Villa) is an official league code no simple rule derives, so the rule gives AST, while ARS, BOU, NEW and CRY match; an en dash is not flagged; curly double quotes become ' because a straight double quote cannot sit inside a name; the grid's "pip" is the Status word Check, with colour and tooltip; the count's link applies a new Name health filter; Fix formatting acts on the selected rows, like Revert selected; the roll back is a submenu, not a dialog; snapshots are capped at ten.
- Opening a large real-world set of files may show a Name health count in amber if there is something to check; a shared code in a file section is the usual reason.
- Fill short name and code, and a roll back that adds or takes out lines, reload the views (about 0.6 s on a large data set), the same path as typing into an empty field.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `README.md`,
  `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`; private
  `roadmap.md` (not tracked)

---

## 22 November 2026 (Europe/London) — Grok Bot (Neal)

- **Tool:** Grok Bot (Neal)
- **Model:** Grok Bot
- **Branch / commit:** main, local `docs: finalise Release 3.6 version, headers, changelog and README`, annotated tag `v3.6`, not pushed

### Done this session

- Reviewed Session 20 (`516633f`): the commit changes only `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `README.md` and `docs/SESSION_HANDOFF.md`. No private files, no playthrough details, no tag. Ctrl+Shift+D is still Deploy. The length gauges are warnings only and never block or trim a name. Save, Deploy and the write pipeline were not changed.
- Ran the full suite once: 356 tests in 58.258s, all passing offscreen.
- Finalised Release 3.6: `VERSION`, the launcher banner, the README and CHANGELOG headers, a dated CHANGELOG section with an empty Unreleased section above it, the public roadmap, and this handoff. Private `roadmap.md` was updated and not staged. The executable was built and not launched. Release notes were written. Nothing was pushed.

### In progress

- Nothing. Waiting for Mark to confirm the push and the GitHub Release.

### Next steps

- After Mark confirms: push `main` then tag `v3.6`, and create the GitHub Release with the exe.
- Session 21 (Release 3.7, note 09 proposals 3 to 5).

### Known issues / blockers

- None for the release.

### Files touched

- `fm_name_editor.py`, `FM Name Editor.bat`, `CHANGELOG.md`, `README.md`,
  `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`; private `roadmap.md` (not
  tracked)
---

## 22 November 2026 (Europe/London) — Claude Code (Session 20)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Branch / commit:** main, local `feat: search scope and aliases, name-length gauges and keyboard cadence`, not pushed

### Done this session

- Stage 0: checked keys before changing anything. Alt+A, Alt+Down, Alt+Up and Ctrl+Shift+L were free; Shift+Enter already acted as Enter in a line edit; Tab and Enter in the grid editor had Qt's default handling. Baseline search keystroke at 4,297 clubs: 51–74 ms across all sections, 33–43 ms in one section (after the 200 ms typing pause).
- Stage 1 (note 09 proposal 1): a scope label and Search all sections (N) beside the entity search box, Edit > Search all sections (Alt+A), a "No matches in … Found N in other sections" link that clears the filter, and a built-in club alias table used only when the words find nothing. The grid filter and the elsewhere count share one engine test, `entity_shown`.
- Stage 2 (proposal 2): length counters under Long name, Short name and 3-letter code against `NAME_LENGTH_GUIDES` (28 / 14 / 3), grey, amber or red with words; the code is flagged for lower case or a length other than 3. The Illustrative card shows a name past its guide cut with an ellipsis, with a note. Warnings only.
- Stage 3 (proposal 6): Alt+Down / Shift+Enter / Alt+Up in an inspector field; Edit > Copy long name to short name (Ctrl+Shift+L, in the palette); Tab / Shift+Tab / Enter in the grid's cell editor through a `CadenceDelegate`.
- User guide (three new sections), CHANGELOG Unreleased, README "Planned for 3.6" line.

### In progress

- Nothing.

### Next steps

- Session 21 (Release 3.7): note 09 proposals 3 to 5, as the private roadmap plans.

### Known issues / blockers

- None. After the change a search keystroke takes 60–95 ms across all sections and 44–100 ms in one section; the slowest case is a search that finds nothing in a section and tries the alias and the other sections.
- THEME gained a `problem` colour (coral, the same value as the nation badge) because the brief's "problem" key did not exist; amber is the existing `warning` key, not `edited`, which is violet and means Edited.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `README.md`,
  `docs/SESSION_HANDOFF.md`; private `roadmap.md` (not tracked)
---

## 22 November 2026 (Europe/London) — Grok Bot (Neal)

- **Tool:** Grok Bot (Neal)
- **Model:** Grok Bot
- **Branch / commit:** main, local `docs: finalise Release 3.5 version, headers, changelog and README`, annotated tag `v3.5`, not pushed

### Done this session

- Reviewed Session 19 (`dd67263`): the commit changes only `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `README.md` and `docs/SESSION_HANDOFF.md`. No private files, no playthrough details, no tag. The export-pack guard (`in_game_tree`) is used only there; Save and Deploy are unchanged.
- Ran the full suite once: 331 tests in 50.390s, all passing offscreen.
- Finalised Release 3.5: `VERSION`, the launcher banner, the README and CHANGELOG headers, a dated CHANGELOG section with an empty Unreleased section above it, the public roadmap, and this handoff. Private `roadmap.md` and decision 26 in `memory.md` were updated and not staged. The executable was built and not launched. Release notes were written. Nothing was pushed.

### In progress

- Nothing. Waiting for Mark to confirm the push and the GitHub Release.

### Next steps

- After Mark confirms: push `main` then tag `v3.5`, and create the GitHub Release with the exe.
- Session 20 (Release 3.6, note 09 stage 1).

### Known issues / blockers

- None for the release. An uncommitted edit to `AGENTS.md` (Token-lean workflow) was left as it is and was not staged.

### Files touched

- `fm_name_editor.py`, `FM Name Editor.bat`, `CHANGELOG.md`, `README.md`,
  `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`; private `roadmap.md` and
  `memory.md` (not tracked)
