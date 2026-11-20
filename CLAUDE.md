# FM Name Editor — guide for Claude

A single-file PySide6 desktop editor for Football Manager 27 `.lnc` name files, written for one person on one Windows PC. Read this file first in every session. The facts that change (paths, counts, defect status) live in `memory.md`; the plan lives in `roadmap.md`. Both of those stay on this PC and are not in the public repository.

## Files that matter

| File | What it is |
| --- | --- |
| `fm_name_editor.py` | The whole program. Engine first, GUI inside `run_gui()` with lazy Qt imports. `VERSION` near the top. |
| `FM Name Editor.bat` | Launcher. Finds `python` on PATH, falls back to the 3.11 install, offers to pip-install PySide6. Version banner in its header comment. |
| `tests/test_engine.py` | Standard-library `unittest`. Temporary fixtures plus read-only round trips and a timing check on copies of the live game files, and offscreen window tests. |
| `tests/offscreen_screen.json` | The offscreen screen the window tests run on: 1920 by 1040 free, like this PC's desktop at 100%. |
| `CHANGELOG.md`, `README.md` | Public. Each carries a `Release / Status / Application on disk` header that must agree with `VERSION`. |
| `roadmap.md` | Private. The numbered session plan and what each session must deliver. Tells you which session is next. |
| `memory.md` | Private. Measured facts about this PC's game files, decisions already made, and the defect ledger. |
| `notes/note_NN.txt` | Private. Mark's briefs and the review notes each release grew from. The highest number is the current brief. |

## Session protocol

Mark opens a session with **"Let's get started."**, followed by the standing rules and a **session brief** that Neal writes for each session (numbered stages, an **Out of scope** list, and acceptance tests for each stage). The brief and the standing rules bind; where they are stricter than this file, follow them. When you see that:

1. Read `CLAUDE.md`, `memory.md`, `roadmap.md`, `CHANGELOG.md`, the note named in the brief (otherwise the highest-numbered note in `notes\`), and `git status` / `git log --oneline -5`.
2. Do not run the test suite at the start of a session (see **Test suite** below).
3. Do the stages in the brief, in order, starting with **Stage 0** if there is one (follow-ups and bugs reported but not fixed in an earlier session). Without a brief, take the session marked **next** in `roadmap.md`. State the plan in three to five lines, then carry on without waiting; stop and ask only if the plan would go outside the brief. Never start anything on the **Out of scope** list, and do not pull work forward from later sessions unless it is a one-line prerequisite.
4. Work in this order: engine change, tests for it, then GUI, then documents.
5. End the session with: the targeted tests for what you changed green (see **Test suite**); `CHANGELOG.md` updated (an **Unreleased** section until the release ships); `roadmap.md` updated (this session marked done, the next one marked next, anything left over written into it); `memory.md` updated if a fact changed; one commit (Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`; a separate `test:` commit is fine). **Never push.** Session commits stay local on `main` until Neal releases them (see **Releasing**).
6. Close with this report, in this order: (1) what shipped, stage by stage; (2) commit hash(es) and changed files; (3) the targeted tests run, with counts and results, and "Full suite not run (Neal runs it at release)."; (4) version sync: `VERSION`, the launcher banner, and the README and CHANGELOG headers unchanged, with this session's entries under **Unreleased**; (5) "Private files not tracked: confirmed"; (6) bugs found but not fixed, or "none"; (7) "Confidentiality: no playthrough details included."; (8) what is next, or "Release X.Y ready for Neal".

If a session cannot finish in one sitting, split it. Write the remainder into the roadmap as the next session before you stop. Never leave the working tree with a failing targeted test at the end of a session.

### Releasing

A release closes when the last session in it is done (for example, Session 8 closed Release 2.4). At that point you stop and hand over to Neal, Mark's repository and release manager. In that session:

1. Finish the session as usual: targeted tests green, the session's entries under **Unreleased** in `CHANGELOG.md`, `roadmap.md` and `memory.md` updated, and one commit. Do not push it.
2. Leave the release itself to Neal. Do not bump `VERSION`, the launcher banner, or the three `Release / Status / Application on disk` headers; do not move **Unreleased** to a dated release section; do not create or push a `vX.Y` tag; do not push the branch.
3. Close by telling Mark that the release's sessions are done and Neal can take over. List the targeted tests you ran and their results, and say "full suite not run (Neal runs it at release)".

Neal then checks the files against the repository (including the ahead count, with `git log origin/main..main`), finalises the version headers, the dated release section in `CHANGELOG.md`, and `README.md`, runs the full test suite once, makes the release commit and the annotated `vX.Y` tag, pushes the branch and the tag only once Mark confirms, then builds `FM Name Editor.exe` with `build_exe.bat` (see the README) and attaches `dist\FM Name Editor.exe` to the GitHub Release. The exe itself is never committed. At each release Neal also brings this file up to date with the current workflow, and writes the brief for the next session. The next session starts only when Mark says **"Let's get started."** again.

### Test suite: keep runs to a minimum (Mark's rule, 18 November 2026)

Full runs make Hawkeye lag and sometimes freeze, so:

1. No test run at the start of a session.
2. Never run the full suite at the end of a session, before a commit, or for the release handover.
3. While working, run only the tests for what you are changing: one test method for red/green, then its class (for example `python -m unittest discover -s tests -k Session7Speed`).
4. Run the window (UI) tests only when UI code changed, and then only the relevant classes. If a menu, submenu, or shortcut changes, also run `-k` on every class that asserts menu contents (search `tests\test_engine.py` for `edit_menu`, `menus`, and `shortcut_rows`); Release 3.2 shipped a stale `Session6Window` menu assertion that only the full run caught.
5. Never two test processes at once, and nothing left running in the background.
6. Your session summary lists the targeted tests you ran and their results, plus "full suite not run (Neal runs it at release)".
7. Neal runs the full suite once per release while verifying, before asking Mark to push.

## Rules that do not change

- **Byte preservation.** A line that is not edited is written back byte for byte. BOM, encoding (UTF-8 or UTF-16 LE), and each line's own ending survive. A name edit replaces only the quoted span.
- **Unsaved means the bytes differ.** `LncDoc.dirty` compares the working lines with `baseline_bytes`, the file as last read or written. Change lines through `Entry.set_name` and `Entry.set_source`, or call `doc.touch()` after any other change to `entries`, a line's text, or its ending. After a successful write of the whole working copy call `doc.mark_clean(payload)` with the bytes written; a partial write settles with `doc.settle_written(lines, payload)` (`write_documents` does both). Each line keeps its disk text and ending (`orig_raw`, `orig_eol`) and the operation that last changed it (`reason`, a key of `CHANGE_REASONS`): an operation that changes lines must pass its reason. A restore keeps the disk baseline (`replace_working`) and never resets the originals.
- **Preview, then memory, then disk.** Bulk tools, imports, replace, and restore change memory only. Only Save and Deploy write files, only through the Review changes dialog (`MainWindow.review_and_write`, built on `WriteReview`), and only after a backup. Unticked changes (`Entry.excluded`) are left out of the bytes written (`build_payload`) and stay pending; a restored backup is written whole. A file whose bytes would not change is not written.
- **Undo takes back whole operations.** Every change to lines made in the window runs inside an `Operation` (`MainWindow.recording`, or a model's `operation_done` signal) so Undo can take it back as one step; a new way of changing lines must be recorded too. `Entry.set_name`, `Entry.set_source`, `insert_name_after`, `append_entry`, and `replace_working` note what they touch; other code that changes `entries`, a line's text, or its ending must call `_note_lines_of`, `_note_line`, or `_note_ending` first. Undo never touches the disk baseline: a write in between stays written, and `LncDoc.rebase` works out again which lines are on disk.
- **One write path.** Never write a file with `write_bytes` or `open(..., "w")`. One file goes through `write_file_atomically` (a temporary sibling, flushed, then `os.replace`). Documents go through `write_documents` (via `save_documents`, `deploy_documents`, or `LncDoc.save`): it refuses a file that changed on disk since it was read (`ExternalChangeError`), backs up game files into `backups\<stamp>\` with a `manifest.json`, replaces files one at a time, and puts already-replaced files back if a later one fails (`WriteError` lists each file's state). Never describe a set of files as written atomically.
- **The game tree is sacred.** Writes outside `C:\FM Name Editor` go only to the paths named in `memory.md`, after an archive copy and a confirmation. Never delete game files. Never use the Steam tree as a write fixture in tests. Refuse to write game files while `fm.exe` is running; never stop that process.
- **One dependency.** PySide6 only. No second GUI toolkit, no charts, no AI SDK, no service. Ask before adding any package.
- **One module.** Keep the engine and GUI in `fm_name_editor.py`, engine helpers free of Qt imports so the tests can import them.
- **The window answers within a second.** With both FM27 files open there are 16,448 lines and 4,297 clubs, so nothing a click does may ask a model for every row. The grids sort in Python on the model (`sort_entities`, `sort_entries`, `reorder_rows`), never through the proxy, which only filters. Columns are sized from their texts (`fit_columns`), never with `resizeColumnToContents` on a big table. A reload resets each model once (`reload_views`), and an edit that moves no lines refreshes through `MainWindow.after_edit`. `Session7Speed` times this on copies of the live files.
- **Slow work runs on a worker.** Opening files, reading a backup, and the check for a running game go through `MainWindow.jobs` (`Jobs.start(text, work, done, failed)`). The work touches no widget or model: it reads files or runs a process and returns a value, and `done` or `failed` runs on the GUI thread. While a job runs, `set_busy` switches off the grids and every action in `busy_actions`; a new action that opens, changes, or writes files belongs in that list. A game check that fails counts as unknown, never as closed. Writes stay on the GUI thread: they are short and settle the documents the views show.
- **Nothing in the repository from `D:\Steam`.** No `.lnc`, `.dbc`, `.edt`, `.ddt` copies, no `backups\`, no `.bak-*`, no `__pycache__`, and no `notes\`, `memory.md`, `roadmap.md`, `profiles\`, or `state\`.
- **Local files.** Spelling profiles live in `profiles\`; local settings (the remembered view, saved searches, the chosen profile) in `state\settings.json`; collections in `state\collections.json`. All are written through `write_file_atomically`. Save and Deploy never change a profile; only Record edits, New, Rename, and Delete do. Deleting a profile moves it into `profiles\deleted`; deleting a collection keeps it under "deleted" in its file. A damaged local file is named and left alone, never overwritten.
- **Confidentiality.** Mark's own Football Manager playthrough never appears in code, tests, documents, commits, or your replies: no save names, his club, in-game dates, or screenshots of a real save. Use invented or generic examples.
- **British English** in interface text, comments, and documents. Plain words over jargon.
- **Honest labels.** An absent override is "No short-name override", not "Missing". The comment heading a row sits under is its "File section", not its country.
- Tests are standard-library `unittest`, run from the project root, writing only to temporary directories. `setUpModule` points `BACKUP_ROOT`, `PROFILE_ROOT`, and `STATE_ROOT` at a temporary folder for the whole run, and makes an unattended `QDialog.exec`, or an unpatched `QMessageBox` static call, fail the test instead of hanging the run: window tests stand in for it (`press_write` presses Write in the review dialog) and patch the `QMessageBox` calls they expect. The module sets `QT_QPA_FONTDIR` so offscreen window sizes match the desktop. Window tests clean up with `close_window`, which deletes the window; without that every later window test gets slower. A window that is shown and active takes real keys (`QTest.keyClick`), shortcuts included; a double-click needs a click first. The module runs offscreen windows on `tests/offscreen_screen.json` and makes the application in `setUpModule`; it sets `editor.JOBS_INLINE` so a job runs at once on the calling thread, and the worker tests (`Session8Workers`) set it back to test the threads. `close_window` switches off `remember_on_close`, so one test's view does not reach the next window. `QMenu.exec` cannot be patched from the class; test a menu by building it (as `grid_menu` does).

## Commands

```
python -m unittest discover -s tests -k <ClassOrMethod>   # targeted run while working
python -m unittest discover -s tests -v                  # full suite: Neal, once per release
python fm_name_editor.py
python fm_name_editor.py "FM27_Club_Names.lnc" "FM27_Fix.lnc"
```

Set `QT_QPA_PLATFORM=offscreen` when running tests without a desktop. `python` on PATH is 3.11.1 with PySide6 6.12.

## Git

Remote: `https://github.com/hawkers63/FM-Name-Editor` (`origin`, branch `main`, public). **Claude never pushes, tags, or force-pushes.** Session commits stay local on `main`; Neal pushes them with the release, and only after Mark confirms (see **Releasing**). Commits use Conventional Commits and end with the attribution line given in the session. Branch before experiments; `main` holds released or session-complete work only.
