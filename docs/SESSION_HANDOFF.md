# Session handoff

Newest entry at the top. Keep only the last 5 entries here. Move older
entries to `docs/SESSION_HANDOFF_ARCHIVE.md`.

This file is the shared progress record for Claude Code, Grok Build CLI,
and Codex CLI. Update it at the end of every session.

© Mark Hawksworth. All rights reserved.

---

## 25 November 2026 (Europe/London) — Claude Code (Session 25)

- **Tool:** claude (Claude Code)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **Brief:** Eve's Session 25 brief for release 3.11 (private, in `notes/`), built on note 11 (a static bug hunt at `fd576c6`) and the two known issues in the Session 24 entry, with Mark's kick-off: targeted tests only, two local commits, no tag, build or push.
- **Branch / commit:** main, two local commits: `fix: keep unticked files out of Deploy, compare restore names exactly, undo restore flags`, then `chore: release 3.11`; not pushed, not tagged

### Done this session

- Stage 0: all four bugs (B1 to B4) and both Linux-only test failures (T1) still held at `fd576c6`; nothing was dropped.
- Stage 1 (B1): `ReviewFile.writes` is False when a file's payload leaves every change out (`left_out` above 0, `included` 0), wherever it goes, so Deploy neither replaces nor creates its destination and the document is not rebound to it. A file with no changes at all is compared as before, so Deploy still copies it. `build_payload` and the writer are unchanged.
- Stage 2 (B2): `_diff_rows` keeps `working_names` and `archived_names` on each row and shows two or more names each in quotes (`_shown_names`; a name never holds a quote). `fill_diff` puts the row on the tick box (`Qt.UserRole`; PySide6 hands back an equal dict, lists included), `ticked_rows` returns those rows, and `plan_selected_restore` compares the lists. A row without them is stale.
- Stage 3 (B3): `apply_selected_restore` returns at once for an empty plan, and otherwise records the document first (`_note_lines_of`), so Undo and Redo carry `restore_pending`, `restored_from` and `whole_excluded`. With the document recorded, Save, Undo, Redo left a clean document flagged as a pending restore (the new test failed at that point), so `Operation._settle` now clears the three flags of a recorded document that an undo or redo leaves clean. Undo and Redo of a selected restore are now structural, so they reload the views, as the restore itself already did.
- Stage 4 (B4): `show_diff(note)` puts the restore message ahead of "Comparing ...", of the comparison's sentence (`fill_diff(..., lead=...)`) and of a read error. Both restores pass it; choosing a copy passes none.
- Stage 5 (T1): the two `Session19Engine` tests pick their paths per system. Every Windows assertion still runs on Windows; the letter-case check is Windows only. The POSIX values were checked here against `posixpath` versions of the same rules; Eve checks Linux in the full run.
- Stage 6: user guide (Save and Deploy; Backups and overrides), CHANGELOG under Unreleased, public roadmap (3.11 under Next), and the oldest live handoff entry moved to the archive.
- Tests: new `Session25Review` (4), `Session25Engine` (8) and `Session25Window` (4, real worker threads). 15 failed before any fix; the Save, Undo, Redo test passed at first and failed once the document was recorded, as Stage 3 describes.

### In progress

- Nothing.

### Next steps

- Stage 7 (release prep, approved by Mark) follows in the `chore` commit.

### Known issues / blockers

- Found, not fixed (outside the brief): `roll_back_to` puts back a snapshot's restore flags. A roll back to a snapshot taken while a restore was pending, made after that restore was saved, leaves a clean file flagged as a pending restore, so later edits in it are grouped as a restore. That code is unchanged since Session 21.

### Files touched

- `fix` commit: `fm_name_editor.py`, `tests/test_engine.py`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `docs/SESSION_HANDOFF_ARCHIVE.md`

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
