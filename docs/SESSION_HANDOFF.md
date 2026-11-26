# Session handoff

Newest entry at the top. Keep only the last 5 entries here. Move older
entries to `docs/SESSION_HANDOFF_ARCHIVE.md`.

This file is the shared progress record for Claude Code, Grok Build CLI,
and Codex CLI. Update it at the end of every session.

© Mark Hawksworth. All rights reserved.

---

## 26 November 2026 (Europe/London) — Claude Code (Session 28)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Brief:** the Session 28 brief for release 3.13 (inspector and sidebar), pasted by Mark, building on note 10 sections 2 and 3. Implementation only: the version stays 3.12.
- **Branch / commit:** main, this local commit `feat: compact the inspector and organise the sidebar`; not pushed, not tagged

### Done this session

- Stage 0, checked first: each inspector field stacked On disk, Proposed, a counter, the file and line, and the raw line; the Illustrative card had three framed boxes; File sections was a flat, sorted `QListWidget` of section strings ("" for all); Collections showed a "None yet" paragraph; the sidebar was the entity splitter's left pane with no way to collapse it; F3 was free. Session 27's rail, 30 px grid and filter bar were the baseline and are unchanged. In real name files a trailing colon does not mark a continent (country headings often carry one), so the tree recognises continents by name and reads the rest from the order of the headings.
- Stage 1, inspector: the text on disk shows only when it differs from the text in memory, in a struck-through `disk_chip` ("No line yet" for an added line); the `disk` label keeps its text for screen readers and the older tests. The file and line, and the raw line, moved to one footer (`inspector_source`) for the field with the focus (the first field until another has it), and into each field's tooltip and accessible description. Engine `count_pill` builds the pill from `length_gauge`, so there is no second rule: "17 / 28", or the count alone where a field has no guide, at the gauge's level. The Session 20 counter line now shows only near or past the guide. `IllustrativePreviewCard.update_from_names` follows the typed values: a league-table row (position, place colour, short name, points), the long name over a score pill (code 2 - 1 OPP) and a ticker line, always against a made-up side; `ElidedLabel` keeps the table and ticker rows to one line. Fixed a latent card bug: after an unfold, the content kept the height it opened at as a cap, so names that came later were clipped. On a test file the inspector needs 482 px, down from 792, and fits without scrolling at 1280×800, 1100×700 and 1280×640, and at 125% and 150%.
- Stage 2, File sections tree: engine `section_heading` (now shared with the parser), `is_continent_heading` (`CONTINENT_HEADINGS`), `section_outline` (a continent heading groups the headings after it in the same file, until the next continent heading, a heading already under a continent earlier in that file, or an empty heading directly above another heading; the first continent found wins), `section_tree` (continents first, then the other sections, each with its count; an "X (heading only)" row for names directly under a continent heading, and "No file section", so nothing is dropped), `section_scope` and `in_section_scope`; `entity_shown` takes a set. Keys: "" is every section, a continent's name its whole group, `SECTION_OWN` and a name exactly one section (no real section starts with "#"). `SectionTree` keeps the keys, right-aligned counts, accessible text for each row, the folds while the window runs, and the search box over the tree. Saved searches store the key as before, so no file format changed. The outline takes about 4 ms and the tree under 1 ms on both FM27 files.
- Stage 3, sidebar: `sidebar_act` (F3) is a window action, not on the View menu, so the View menu, the command palette and every other key are unchanged; `sidebar_btn` beside the search box carries it ("Hide the sidebar ... (F3)" or "Show ...", accessible name "Sidebar"), and Keyboard shortcuts lists F3. `set_sidebar_shown` keeps every choice, gives the grid the room, gives the sidebar its width back when the splitter had squeezed it, and is kept as `view["sidebar"]`, as F4's `inspector` is.
- Stage 4, Collections: `collection_empty_btn`, New collection from selection, replaces the paragraph and calls `new_collection(True)`; it is off without a selection, and its tooltip and accessible description say why. A damaged collections file still shows its warning.
- Stage 5, tests: new `Session28Engine` (7), `Session28Inspector` (6), `Session28Preview` (4), `Session28Sections` (6), `Session28Sidebar` (5), `Session28Collections` (2) and `Session28Display` (1, at 125% and 150%); against the 3.12 code all 31 fail (25 errors, 6 failures). Old assertions were updated only where the brief replaced a widget: `Session7Window` and `Session8Window` (`section_list` to `section_tree`, and "None yet" to the button), `_Session20Window.choose_section`, `Session18Preview` (two tests) and the `Session20Gauges` cut test, for the new preview labels.
- Stage 6: CHANGELOG (Unreleased), the user guide (a new section, File sections and the sidebar, and new wording for the inspector and the length guides), the public roadmap's Next, this entry, and Session 23 moved to the archive.
- Targeted runs, offscreen, one process at a time, all passing: `Session28*` (31) in 8.8 s; Session 28 with `WindowSmoke`, `Session2Window`, `Session6Window`, `Session7Window`, `Session8Engine`, `Session8Window`, `Session8Scaling`, `Session9Settings`, `Session9Window`, `Session14Visual`, `Session14Display`, `Session15BatchRename`, `Session18Preview`, `Session19Engine`, `Session19IdColumn`, `Session19AddName`, `Session20Engine`, `Session20Search`, `Session20Gauges`, `Session20Cadence`, `Session21Fill`, `Session21Health`, `Session21Snapshots`, `Session22RollbackConfirm`, `Session27View`, `Session27Grid` and `Session27Filters` (180) in 51.7 s; `Session7Speed`, `Session20Speed` and `Session21Speed` (3) in 7.5 s. Full suite not run (Eve runs it).

### In progress

- Nothing.

### Next steps

- Eve: review, run the full suite once, and prepare release 3.13 with Mark's approval. The README's text and screenshots still show the 3.12 inspector and the flat File sections list (left alone, as the brief asked).

### Known issues / blockers

- None found. Two limits, by design: the tree reads the order of the headings, not geography, so a heading that is not a country but follows a continent's countries sits under that continent until one of the stop rules applies (every section stays selectable either way); and F3 is not on the View menu or in the command palette, which the brief kept unchanged, though it is on the sidebar button and in Keyboard shortcuts.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`

---

## 25 November 2026 (Europe/London) — Claude Code (Session 27)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Brief:** Eve's Session 27 brief for release 3.12, a calmer grid and less chrome (private `notes/session_3.12_brief.md`, building on note 10 section 2). Mark's fixed choices: 30 px rows, and the view switcher in a left-hand icon rail.
- **Branch / commit:** main, this local commit `feat: a slimmer view rail, a calmer grid and one filter bar`; not pushed, not tagged

### Done this session

- Stage 0, checked first: a `QTabWidget` held the three pages under the toolbar (`CHANGES_TAB = 2`; `refresh_status` wrote "Changes (N)"; the remembered view kept `tabs.currentIndex()`). The entity page had a row of family buttons, then the search, Saved searches and the status buttons in one row. All three grids had 24 px rows with gridlines.
- Stage 1: `ViewStack`, a `QStackedWidget` that keeps `addTab`, `tabText` and `currentIndex`, with a 44 px rail of three checkable icon buttons down the left edge. The icons are single-colour SVG string constants (`VIEW_ICONS`), drawn with `QSvgRenderer` in the theme's colours; no image files, no new package. Each button triggers its view's action and carries a tooltip with its keys and an accessible name; the Changes button shows the count under its icon (hidden at nought), and `tabText` still reads "Changes (N)". `CHANGES_TAB` stays 2. Keys, the View menu, the palette and the remembered view are unchanged.
- Stage 2: `calm_grid` gives the entity, All lines and Changes grids 30 px rows (`GRID_ROW_HEIGHT`), stripes, no grid, and a 1 px rule under each row (`QTableView#grid::item`, with an explicit `:selected` rule so the selection colours stay). `PillDelegate` paints statuses (a tinted pill per word in its `STATE_COLOUR_NAMES` colour, muted for a change left out) and codes. `CadenceDelegate` inherits it and paints a muted italic dash (`EMPTY_CELL_MARK`) in an empty short-name or code cell, with "No short-name override" or "No code override" as its tooltip. The model is untouched. Columns are widened for pills (`widen_for_pills`); the review dialog's table is left as it was.
- Stage 3: engine `status_shown` (the status test, now shared with `entity_shown`) and `filter_counts`. `FilterBar` holds the family buttons and the status filters, each with its count, and stacks the two groups when the window is too narrow (as with Segoe UI at 150%). `refresh_filter_counts` runs from `refresh_status`: one pass over the entities, 26 ms on both FM27 files. The search row works as before.
- Stage 4: CHANGELOG (Unreleased), the user guide sentences that named the tabs and the filters beside the search box, the public roadmap's 3.12 bullet, this entry, and the oldest live entry moved to the archive.
- Tests: new `Session27View` (5), `Session27Grid` (4), `Session27Filters` (6), all passing. Targeted runs, offscreen, all passing: `Session27*` with `Session20Engine` and `Session8Engine` (23); `WindowSmoke`, `Session2Window`, `Session6Window`, `Session7Window`, `Session8Window`, `Session9Window`, `Session14Visual`, `Session14Display`, `Session15BatchRename`, `Session19AddName`, `Session20Search`, `Session20Cadence`, `Session21Health` (95); `Session20Speed` and `Session7Speed` (2) at their limits, slowest keystroke 0.111 s, slowest Session 7 step 0.823 s (save). Full suite not run (Eve runs it).

### In progress

- Nothing.

### Next steps

- Eve: review, run the full suite once, and prepare release 3.12 with Mark's approval. README still says "Changes tab" in a few places, and its screenshots (`docs/images/main-window.png`, `changes-tab.png`) show the old tab bar.

### Known issues / blockers

- None found. A few status-bar messages and tooltips still say "tab" (for example "Select rows on the Entities tab first."); the brief limited wording changes to the user guide.

### Files touched

- `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`

---

### Eve — release 3.12

- Session 27 commit reviewed. All 431 tests passed offscreen on Windows in 68.629 seconds, none skipped. Mark confirmed the interface was working well.
- Version synchronised across the source, launcher and release documents for the annotated source tag.

## 25 November 2026 (Europe/London) — Claude Code (Session 26)

- **Tool:** claude (Claude Code)
- **Model:** Claude Sonnet 5.5 (`claude-sonnet-5-5`)
- **Brief:** Mark's Session 26 brief for release 3.11.1 (snapshot roll-back fix), pasted at kick-off: targeted tests only, two local commits, no tag, build or push.
- **Branch / commit:** main, local `48116e9` `fix: clear stale restore flags after a snapshot roll back`, then `chore: release 3.11.1`; not pushed, not tagged

### Done this session

- Stage 0: the bug still held. `roll_back_to` put a snapshot's `restore_pending`, `restored_from` and `whole_excluded` back through `_put_doc`, so a roll back to a snapshot taken while a restore was pending, made after that restore was saved, left a clean file flagged as a pending restore.
- Stage 1: at the end of each document's pass in `roll_back_to`, a document that is clean has its three restore flags cleared, as `Operation._settle` does for Undo and Redo. A document left genuinely pending keeps them. No new UI or keys.
- Tests: new `Session26Engine` (5): roll back after the restore was saved (failed first), roll back to a pending restore, Undo of a roll back (failed first), a roll back across a Save, and a roll back to identical lines.
- Stage 2: CHANGELOG, this entry, and the oldest live entry moved to the archive. There is no `USER_GUIDE`; the README's snapshot wording is still right.
- Stage 3 (release prep, approved by Mark): 3.11.1 in `VERSION`, the module header and underline, a "Release 3.11.1" paragraph, the launcher banner (CRLF kept), README (badge, headers, "New in 3.11.1", history row), CHANGELOG (header, `## 3.11.1`, empty Unreleased) and the public roadmap. No download link or SHA-256.

### In progress

- Nothing.

### Next steps

- Eve: run the full suite once, tag `v3.11.1`, build, and ask Mark before pushing. When publishing: set the README and CHANGELOG status to released, drop "(ready for release; not yet published)", add the download bullet and SHA-256, and set the Tests badge (411 at 3.11; this session adds 5).

### Known issues / blockers

- None found.

### Files touched

- `fix` commit: `fm_name_editor.py`, `tests/test_engine.py`
- `chore` commit: `fm_name_editor.py`, `FM Name Editor.bat`, `README.md`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`

### Eve — release 3.11.1

- Reviewed `48116e9` and `a9980a5`: the fix is the one condition at the end of each document's pass in `roll_back_to`, cleared only when the document is clean; the five `Session26Engine` tests cover the stale case, a genuine pending restore, Undo, a roll back across a Save and identical lines. Conventional Commits, licence and copyright headers intact, no private files tracked, no playthrough details. Version 3.11.1 agrees in the module header, `VERSION`, the launcher banner, the README, the CHANGELOG and the public roadmap.
- Ran the full suite once, offscreen on this PC: 416 tests in 78 s, all passing, none skipped (the game's name files are here, so the live-file tests ran).
- Set both statuses to released, dropped "ready for release" from "New in 3.11.1", added a "What 3.11.1 adds" block with the download bullet and SHA-256, and set the Tests badge to 416. Public roadmap: 3.11.1 now, 3.11 done.
- Built the Windows executable from this tree without launching it: 49,061,343 bytes, version resources 3.11.1, SHA-256 `e441accb3dba14bd69776a6460b46a258531e48426f9f48df82438f9b05e65db`. Tagged `v3.11.1`.
- Mark approved the push and publication. `main` (3 commits) and the tag `v3.11.1` went to origin; the release was published as Latest with the exe attached, and a fresh download checked: 49,061,343 bytes, digest matching the local hash. The browser's passkey prompt could not work in OpenBot's browser, so the release went out through `gh` after Mark re-signed in.

---

## 25 November 2026 (Europe/London) — Claude Code (Session 25)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Brief:** Eve's Session 25 brief for release 3.11 (private, in `notes/`), built on note 11 (a static bug hunt at `fd576c6`) and the two known issues in the Session 24 entry, with Mark's kick-off: targeted tests only, two local commits, no tag, build or push.
- **Branch / commit:** main, local `8732239` `fix: keep unticked files out of Deploy, compare restore names exactly, undo restore flags`, then `chore: release 3.11`; not pushed, not tagged

### Done this session

- Stage 0: all four bugs (B1 to B4) and both Linux-only test failures (T1) still held at `fd576c6`; nothing was dropped.
- Stage 1 (B1): `ReviewFile.writes` is False when a file's payload leaves every change out (`left_out` above 0, `included` 0), wherever it goes, so Deploy neither replaces nor creates its destination and the document is not rebound to it. A file with no changes at all is compared as before, so Deploy still copies it. `build_payload` and the writer are unchanged.
- Stage 2 (B2): `_diff_rows` keeps `working_names` and `archived_names` on each row and shows two or more names each in quotes (`_shown_names`; a name never holds a quote). `fill_diff` puts the row on the tick box (`Qt.UserRole`; PySide6 hands back an equal dict, lists included), `ticked_rows` returns those rows, and `plan_selected_restore` compares the lists. A row without them is stale.
- Stage 3 (B3): `apply_selected_restore` returns at once for an empty plan, and otherwise records the document first (`_note_lines_of`), so Undo and Redo carry `restore_pending`, `restored_from` and `whole_excluded`. With the document recorded, Save, Undo, Redo left a clean document flagged as a pending restore (the new test failed at that point), so `Operation._settle` now clears the three flags of a recorded document that an undo or redo leaves clean. Undo and Redo of a selected restore are now structural, so they reload the views, as the restore itself already did.
- Stage 4 (B4): `show_diff(note)` puts the restore message ahead of "Comparing ...", of the comparison's sentence (`fill_diff(..., lead=...)`) and of a read error. Both restores pass it; choosing a copy passes none.
- Stage 5 (T1): the two `Session19Engine` tests pick their paths per system. Every Windows assertion still runs on Windows; the letter-case check is Windows only. The POSIX values were checked here against `posixpath` versions of the same rules; Eve checks Linux in the full run.
- Stage 6: user guide (Save and Deploy; Backups and overrides), CHANGELOG under Unreleased, public roadmap (3.11 under Next), and the oldest live handoff entry moved to the archive.
- Stage 7 (release prep, approved by Mark): 3.11 in the module header and `VERSION`, a "Release 3.11" paragraph after 3.10's in the module docstring, the launcher banner (CRLF kept), the README badge, header lines (ready for release; not yet published), a "New in 3.11" paragraph above 3.10's, a history row and a "What 3.11 adds" block (no download link or SHA-256), the CHANGELOG header (ready for release) with `## 3.11 (25 November 2026)` and an empty Unreleased, and the public roadmap (3.11 now, 3.10 done).
- Tests: new `Session25Review` (4), `Session25Engine` (8) and `Session25Window` (4, real worker threads). 15 failed before any fix; the Save, Undo, Redo test passed at first and failed once the document was recorded, as Stage 3 describes.

### In progress

- Nothing.

### Next steps

- Eve: run the full suite once (on Linux too, for the two `Session19Engine` tests), tag `v3.11`, build, and ask Mark before pushing.
- Eve, when publishing: set the README and CHANGELOG status to released, drop "(ready for release; not yet published)" from "New in 3.11", add the download bullet and SHA-256, and set the Tests badge from the full run (395 at 3.10; this session adds 16).

### Known issues / blockers

- Found, not fixed (outside the brief): `roll_back_to` puts back a snapshot's restore flags. A roll back to a snapshot taken while a restore was pending, made after that restore was saved, leaves a clean file flagged as a pending restore, so later edits in it are grouped as a restore. That code is unchanged since Session 21.

### Eve — release 3.11

- Reviewed `8732239` and `1392eb5` against the brief: B1 to B4 and T1 done as briefed, Conventional Commits, no private files tracked, licence and copyright headers intact, no playthrough details. Version 3.11 agrees in the module header, `VERSION`, the launcher banner, the README, the CHANGELOG and the public roadmap.
- Ran the full suite once, offscreen on Linux (Mark's choice, to spare this PC): 411 tests in about 16 s, all passing, 5 skipped because the game's own name files are not there. The two `Session19Engine` tests now pass on Linux.
- Set both statuses to released, dropped "ready for release" from "New in 3.11", added the download bullet and set the Tests badge to 411. Built the Windows executable from the release source without launching it. Push and publication wait for Mark's confirmation.
- The snapshot roll-back restore-flag bug above is in the private roadmap as a proposal for the next release.

### Files touched

- `fix` commit: `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`
- `chore` commit: `fm_name_editor.py`, `FM Name Editor.bat`, `README.md`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`

---

## 25 November 2026 (Europe/London) — Claude Code (Session 24)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Brief:** Eve's Session 24 brief for release 3.10 (private, in `notes/`), with Mark's kick-off: four stages, targeted tests only, two local commits, no tag, build or push.
- **Branch / commit:** main, local `01f0c38` `fix: restore selected names in the background and refuse stale rows`, then `chore: release 3.10`; not pushed, not tagged

### Done this session

- Stage 0: the five problems in the brief all still held. `restore_selected_names` compared on the GUI thread, read the backup a second time in `_apply_selected_restore`, walked every line for each tick, checked staleness by key only, and wrote the table's text as the name.
- Stage 1 (engine): `plan_selected_restore(doc, archive_file, ticked)` reads the backup once, groups both files (`_diff_groups`) and compares them again (`_diff_rows`, which `diff_documents` now runs too, with the same output). It returns `(changes, stale)`: a ticked row is stale unless the fresh comparison still has it with the same open name and backup name, and it can be restored by name (`restorable_by_name`). When anything is stale, `changes` is empty. `apply_selected_restore` gives the open lines the planned backup names through one dict of the open lines. It keeps `set_name(..., "restore")`, `restore_pending`, `restored_from`, `whole_excluded = False` and `touch()`. `diff_row_key` gives a shown row's comparison key.
- Stage 2 (GUI): `BackupDialog.restore_selected_names` collects the ticks (`ticked_rows`) and asks the same question. It then calls `restoring(True)` and `run(plan_selected_restore ...)`. `finish_selected_restore` either applies the plan in one `Operation` (`push_operation`, `reload_views`, `show_diff`, the same summary), or warns, applies nothing and compares again. A read error goes to `restore_failed`. The GUI-thread `compare_with_backup` call and the second `LncDoc` read are gone.
- Reasoned deviations, both in the part being rewritten. (1) The lookup key is the comparison key (`_diff_key`), so a person rule's ending is part of it. Person rules share their number and language, so with (command, ID, language) alone another rule would be changed. The ending rides in the ID column's UserRole. (2) A row that a name alone cannot restore (only in one file, or a different number of lines) has no tick box, and its tooltip points to Restore into open file. Before, ticking one did nothing, or wrote every backup name into one line, and still said it had restored it. The plan treats such a row as stale if one is passed in.
- Stage 3: the help sentence; CHANGELOG under Unreleased; "Neal" to "Eve" where it names the current release manager in `AGENTS.md`, `CLAUDE.md`, `docs/SESSION_PROMPTS.md` and the build comment in `.gitignore`; four root-anchored private files added to `.gitignore` (`git check-ignore` lists all four and not the tracked archive); the oldest live entry moved to the archive.
- Tests: new `Session24Engine` (6) and `Session24Window` (5, real worker threads).
- Stage 4 (release prep, approved by Mark): 3.10 set in the module header and `VERSION`, a "Release 3.10" paragraph added to the module docstring (after 3.9's, as each release has done), the launcher banner (CRLF kept), the README badge, header lines, a "New in 3.10" paragraph above 3.9's, a history row and a "What 3.10 adds" block, the CHANGELOG header (ready for release) with `## 3.10 (25 November 2026)` and an empty Unreleased, and the public roadmap (3.10 now, 3.9 done). Nothing compares the version as text or a float: the `.spec` reads 3.10 as (3, 10, 0, 0).

### In progress

- Nothing.

### Next steps

- Eve: run the full suite once, tag `v3.10`, build, and ask Mark before pushing.
- Eve, when publishing: set the README and CHANGELOG status to released, drop "(ready for release; not yet published)" from "New in 3.10", and add the download bullet and SHA-256. The history row already links to the `v3.10` tag page. The README Tests badge still says 376 (out of date since 3.9); set it from the full run.

### Known issues / blockers

- Found, not fixed: undoing a selected restore leaves `restore_pending` set (since Session 18), because the operation records only the lines. The file then counts as a restored, whole-file write until it is saved or opened again. The brief keeps `restore_pending` as it was.
- Found, not fixed: with real worker threads, the comparison that `show_diff` starts after either restore replaces the "Restored ..." summary a moment later (since Session 23). Whole-file restore is out of scope, so both stay alike.

### Eve — release 3.10

- Reviewed `01f0c38` and `f3a9688` against the brief: all four stages done, Conventional Commits, no private files tracked, the four new `.gitignore` lines ignore their files, Eve named in the guides, licence and copyright headers intact, no playthrough details. Version 3.10 agrees in the module header, `VERSION`, the launcher banner, the README, the CHANGELOG and the public roadmap.
- Ran the full suite once, offscreen on Linux (Mark's choice, to spare this PC): 395 tests in about 17 s; 388 passed, 5 skipped because the game's own name files are not there, and 2 failed only because they use Windows paths (`Session19Engine.test_favourites_keep_up_to_three_real_folders` and `test_the_view_keeps_the_id_column_and_packs_stay_out_of_the_game`; code unchanged since 3.5).
- Set both statuses to released, dropped "ready for release" from "New in 3.10", added the download bullet and set the Tests badge to 395. Built the Windows executable from the release source without launching it. Push and publication wait for Mark's confirmation.

### Files touched

- `fix` commit: `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md`, `docs/SESSION_PROMPTS.md`, `.gitignore`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`
- `chore` commit: `fm_name_editor.py`, `FM Name Editor.bat`, `README.md`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`

---
