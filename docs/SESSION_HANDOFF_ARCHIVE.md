# Session handoff archive

Older handoff entries, still newest first. The live file
`docs/SESSION_HANDOFF.md` holds only the last 5 entries.

© Mark Hawksworth. All rights reserved.

<!-- Move entries here when SESSION_HANDOFF.md would otherwise exceed
     five entries. Do not edit history except to fix a factual error. -->

---

## 24 November 2026 (Europe/London) — Claude Code (Session 23)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Brief:** Neal's Session 23 brief, pasted by Mark (three stages, targeted tests only, one local commit). Old proposal prompts in `notes/` ignored as instructed.
- **Branch / commit:** main, local `feat: background pack import and backups, byte-difference explanation, faster save`, not pushed, not tagged

### Done this session

- Stage 1, Save timing: each part of a Save was timed on copies of the live files over six runs. Write, review, payload and status took under 0.2 s together; the reload after the write took most of the rest, and about half of that was `FamilyTokenIndex.rebuild` splitting every name into words again (twice per name), although a Save changes no name. That was the clear single cause. Fix: `_name_tokens` is an `lru_cache` (65,536 names) behind `extract_name_tokens`, which still returns a fresh list. Save went from 0.78 to 0.94 s down to 0.61 to 0.67 s (unprofiled runs). The 1 s limit and `Session7Speed` are unchanged.
- Stage 2, responsiveness: `read_pack_file` (engine) reads, decodes and parses a pack; `import_pack` runs it and `proposals_from_pack` on `MainWindow.jobs`, then `show_pack` opens the pack dialog. `BackupDialog` lists the folders (`read_archives`) and compares a copy (`compare_backup_in_full`) on the jobs worker through `BackupDialog.run`, which drops an answer once the dialog is closed (`done` sets `closed`) or another copy was chosen (`request`). A whole-file restore goes through `run` too, so closing during its read restores nothing; the lists and buttons wait meanwhile (`restoring`). The restore of ticked names still re-compares on the GUI thread (unchanged).
- Stage 3, why the bytes differ: `explain_byte_differences` / `describe_byte_differences` (engine, read only) report the encoding or BOM, line endings, comments, blank lines, unsupported lines and name lines written differently, with counts, the first 20 lines (`BYTE_EXPLAIN_SHOWN`) and a whole-file cap of 200,000 lines (`BYTE_EXPLAIN_MAX_LINES`); moved lines are reported as a different order. The Backups window shows it in a read-only panel only when the names match and the bytes do not. Help text updated.
- Tests: new `Session23Engine` (4) and `Session23Window` (4); `Session8Workers` waits for the listing before restoring.

### In progress

- Nothing.

### Next steps

- Neal: set everything to 3.9, run the full suite once, tag, build and prepare publication; Mark confirms before any push.

### Known issues / blockers

- None found. The 3.8 executable was launched once for a smoke test at that release, against the never-launch rule; the release itself is fine. This session launched nothing.

### Neal — release 3.9

- Reviewed `ffb6d66`. Set `VERSION`, the module header, the launcher banner, the README and CHANGELOG headers and the public roadmap to 3.9; dated the changelog section 24 November 2026 with an empty Unreleased kept.
- Ran the full offscreen suite once for the release: 384 tests in 59.460s, all passing; built the Windows executable from the release commit without launching it. Push and publication wait for Mark's confirmation.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`

---

## 24 November 2026 (Europe/London) — Session 22 and local v3.8 finalisation

### Neal — local release preparation

- Mark authorised local version alignment, dated changelog, checks, release commit and annotated v3.8 tag; no push, build or publication.
- Independently reviewed implementation commit `a7de817`; full offscreen regression passed: 376 tests in 67.832s, no failures or skips. This result predates version finalisation.
- Release source VERSION, apex version, launcher banner and README/CHANGELOG headers aligned to 3.8. Status explicitly says locally finalised; publication pending. Changelog dated 24 November 2026 with Unreleased retained; public roadmap synchronised. No executable built or launched.
- Fresh `git fetch origin main` found the implementation one commit ahead with no divergence before finalisation. Remote v3.7 was checked; v3.8 was absent at that check. Exact outgoing hashes/counts and final test results are supplied in Neal's close-out, not inferred here.
- Carry forward as proposed Stage 0 for Mark's selection: intermittent Save timing (not diagnosed). No unselected feature or performance fix included.
- Private roadmap and proposed next-session prompt remain local and untracked.
- Later on 24 November 2026, with Mark's approval, v3.8 was pushed, tagged and published on GitHub as the latest release.
- Testing policy confirmed by Mark on 24 November 2026: coding sessions run targeted tests only; Neal runs the full suite once per release, and not for documentation-only changes. The per-commit full-run rule is withdrawn.

### Claude Code implementation record (before local finalisation)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Branch / commit:** main, local `fix: confirm snapshot rollback and refresh agent guidance`, not pushed, not tagged

### Done this session

- Stage 0 (selected option 1): Edit > Roll back to snapshot now asks first (`MainWindow.rollback_box`, `confirm_rollback`). The question names the snapshot, its time and the open files, says the roll back replaces the working copy in memory only and that Undo takes it away. Cancel is the default and the escape button; Esc, Enter and the title-bar close cancel; only Roll back proceeds. Inspector field signals are held while it is up, so a draft is kept, not used. An expired snapshot still asks nothing and changes nothing. A confirmed roll back that changes nothing visible (including a repeat after a Save) leaves no empty Undo step. Submenu, Ctrl+Alt+K, RAM-only lifecycle and the limit of ten unchanged; engine unchanged.
- Stage 1 (selected option 4): `AGENTS.md` release field points to `VERSION`; the one-second rule has no fixed data counts; Neal replaces the old manager names in the workflow text; `CLAUDE.md` makes the selected brief authoritative; both say the private plan and memory files are updated locally and never staged.
- Stage 2: help text, CHANGELOG Unreleased, README "in development" note (not released). Oldest handoff entry moved to the archive.
- Tests: new `Session22RollbackConfirm` (4); `Session21Snapshots` and `Session21Speed` answer the question explicitly. Targeted runs green; full offscreen suite with the scratch temp root: 376 tests, OK, no failures or skips.

### In progress

- Nothing. v3.8 is unreleased; release preparation is Neal's, under Mark's authority.

### Next steps

- Neal: independent review of the outgoing delta and release preparation; Mark alone approves any push.
- Mark selects any further scope.

### Known issues / blockers

- Testing policy: resolved by Mark on 24 November 2026 (see the Neal entry above).
- Save timing in `Session7Speed`: an earlier full run measured Save just over the 1 s cap; it passed in this session's run. Not diagnosed; proposed as Stage 0 of the following session for Mark's decision.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `README.md`,
  `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`; private `roadmap.md` (local only, not staged)

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
