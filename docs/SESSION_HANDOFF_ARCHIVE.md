# Session handoff archive

Older handoff entries, still newest first. The live file
`docs/SESSION_HANDOFF.md` holds only the last 5 entries.

© Mark Hawksworth. All rights reserved.

<!-- Move entries here when SESSION_HANDOFF.md would otherwise exceed
     five entries. Do not edit history except to fix a factual error. -->

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

---

## 22 November 2026 (Europe/London) — Claude Code

- **Tool:** Claude Code
- **Model:** Opus 5.5 (`claude-opus-5-5`)
- **Branch / commit:** main, one local commit for Session 19
  (`feat: start folders and favourites, ID column and Add name`), not pushed

### Done this session (Session 19, Release 3.5, note 08)

- **Stage 0:** long-name sorting confirmed in source and left alone. The
  sort arrow is drawn, but it is small, grey, and at the far edge of the
  stretched Long name column, so the sorted heading is now bold (font role
  on both grid models). `QFileDialog` calls that passed "" or a bare file
  name: `open_dialog`, `ImportDialog.pick_old` and `pick_base`,
  `import_pack`, and `export_pack` ("fm-name-pack.json").
- **Stage 1:** every picker starts in the last folder File > Open used,
  else `lnc\all` of the selected database (from `GAME_DB_ROOT` and the
  selector), else the user folder, with the missing folder named in the
  status bar. File > Name files in the selected database, up to three
  favourites in the File menu, File > Favourite folders….
  `open_folder` and `favourite_folders` live in `state\settings.json`
  through `keep_settings`; bad entries are ignored; a damaged file is left
  byte for byte. Extra safeguard: Export name pack refuses a path in the
  game's folders (`in_game_tree`), since its picker can now open there.
- **Stage 2:** View > Show ID column, on by default and remembered
  (`id_column` in the view). **Decision 26 revised:** the entity grid
  shows the ID by default again; the inspector and All lines keep it.
  Width from `fit_columns`; numeric sort with empty or non-numeric IDs
  last; sorting adds no undo step.
- **Stage 3:** Edit > Add name… (`AddNameDialog`, `add_entity_lines`):
  lines go in through `append_entry` under `#Imported by FM Name Editor`
  in one `recording(...)` operation; an existing family and ID (compared
  by number) selects that row and adds nothing; nothing is written to disk.
- **Docs:** user guide, CHANGELOG **Unreleased**, README "Planned for
  3.5" line, private `roadmap.md`.
- **Tests:** new `Session19Engine` (7), `Session19Folders` (9),
  `Session19IdColumn` (4), `Session19AddName` (7); menu lists updated in
  `Session6Window`, `Session7Window` and `Session14Visual`. Targeted runs
  only; full suite not run (Neal runs it at release).

### In progress

- Nothing. Session 19 is the only session in Release 3.5.

### Next steps

- Neal: Release 3.5 (version headers, dated CHANGELOG section, full
  suite, tag, exe), pushed only once Mark confirms.
- `memory.md`: update decision 26 to say Session 19 revised it (the brief
  said not to read `memory.md` this session).
- Session 20 (Release 3.6, note 09) after the release.

### Known issues / blockers

- None found.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `README.md`,
  `docs/SESSION_HANDOFF.md`; private `roadmap.md` (not tracked)

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
