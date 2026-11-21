# FM Name Editor — guide for coding agents

Shared project instructions for Claude Code, Codex CLI, and Grok Build CLI.
This file is the single source of truth for rules that every tool must
follow. Claude-only notes live in `CLAUDE.md`, which imports this file.

A single-file PySide6 desktop editor for Football Manager 27 `.lnc` name
files, written for one person on one Windows PC. Read this file first in
every session.

© Mark Hawksworth. All rights reserved.

## Project

- **Name:** FM Name Editor
- **Purpose:** A Windows desktop editor for Football Manager 27 `.lnc` name
  files. Change club, competition, stadium, and related spellings, preview
  and review every write, keep archive copies, and write the file back
  without disturbing a line you did not touch.
- **Repository:** https://github.com/hawkers63/FM-Name-Editor
- **Local path (Hawkeye):** `C:\FM Name Editor`
- **Current release:** 3.4 (`VERSION` in `fm_name_editor.py`)
- **Licence:** Proprietary, all rights reserved (see `LICENSE`).

The facts that change (paths, counts, defect status) live in `memory.md`;
the detailed numbered session plan lives in `roadmap.md`. Both of those
stay on this PC and are not in the public repository. Shared progress that
must survive a switch of tool lives in `docs/SESSION_HANDOFF.md`. The short
public plan lives in `docs/ROADMAP.md`.

## Files that matter

| File | What it is |
| --- | --- |
| `fm_name_editor.py` | The whole program. Engine first, GUI inside `run_gui()` with lazy Qt imports. `VERSION` near the top. |
| `FM Name Editor.bat` | Launcher. Finds `python` on PATH, falls back to the 3.11 install, offers to pip-install PySide6. Version banner in its header comment. |
| `tests/test_engine.py` | Standard-library `unittest`. Temporary fixtures plus read-only round trips and a timing check on copies of the live game files, and offscreen window tests. |
| `tests/offscreen_screen.json` | The offscreen screen the window tests run on: 1920 by 1040 free, like this PC's desktop at 100%. |
| `AGENTS.md` | Public. Canonical instructions for every coding tool. |
| `CLAUDE.md` | Public. Thin Claude Code pointer that imports this file, plus Claude-only session rules. |
| `CHANGELOG.md`, `README.md` | Public. Each carries a `Release / Status / Application on disk` header that must agree with `VERSION`. |
| `docs/SESSION_HANDOFF.md` | Public. Shared session progress for every tool. Newest entry at the top; keep only the last 5 entries, and move older ones to `docs/SESSION_HANDOFF_ARCHIVE.md`. |
| `docs/SESSION_PROMPTS.md` | Public. Pre-session and end-of-session prompts to paste into each tool. |
| `docs/ROADMAP.md` | Public. Short high-level plan. |
| `roadmap.md` | Private. The numbered session plan and what each session must deliver. Tells you which session is next. |
| `memory.md` | Private. Measured facts about this PC's game files, decisions already made, and the defect ledger. |
| `notes/note_NN.txt` | Private. Mark's briefs and the review notes each release grew from. The highest number is the current brief. |

## Session protocol

Mark often opens a session with **"Let's get started."** When you start work,
whether from that phrase or a pasted pre-session prompt:

1. Read `AGENTS.md` and `docs/SESSION_HANDOFF.md` (newest entry at the top).
   Also read `CHANGELOG.md` and run `git status` / `git log --oneline -5`.
   If they are present on this PC, also read `memory.md`, `roadmap.md`, and
   the highest-numbered note in `notes\`.
2. Continue from *In progress* and *Next steps* in the handoff, and from the
   session marked **next** in the private `roadmap.md`. Do not redo finished
   work, and do not pull work forward from later sessions unless it is a
   one-line prerequisite.
3. Follow the tool-specific notes:
   - **Claude Code:** follow `CLAUDE.md` as well (Neal's session brief,
     Stage 0, Out of scope, acceptance tests, the test-suite rule, the
     eight-point close-out, and never push).
   - **Codex CLI and Grok Build CLI:** this file is enough. Both load
     `AGENTS.md` automatically. Grok also loads `CLAUDE.md` if it is
     present; treat that file as Claude-only notes, not as a second
     rulebook.
4. Do not run the full test suite at the start of a session (see
   [Test suite](#test-suite-keep-runs-to-a-minimum)).
5. Work in this order: engine change, tests for it, then GUI, then documents.
6. **End of session — one combined commit.** Targeted tests for what you
   changed must be green. Then, in the same sitting, update:
   - `docs/SESSION_HANDOFF.md` — a new entry at the top (date in
     Europe/London, tool, model, done, in progress, next steps, known
     issues or blockers, files touched, branch or commit). Keep only the
     last 5 entries here; move older entries, still newest first, to
     `docs/SESSION_HANDOFF_ARCHIVE.md`.
   - `CHANGELOG.md` — an **Unreleased** section until the release ships,
     for user-visible or otherwise notable changes.
   - `roadmap.md` (private, if present) — this session marked done, the
     next one marked next, anything left over written into it.
   - `docs/ROADMAP.md` — only if the public plan changed.
   - `memory.md` (private, if present) — only if a fact changed.
   Then make **one** Conventional Commit (`feat:`, `fix:`, `test:`,
   `docs:`) that includes the session's work and the handoff updates
   together. Do not leave a failing targeted test at the end of a session.
   If a session cannot finish in one sitting, split it: write the remainder
   into the private roadmap as the next session, update the handoff, and
   commit what is complete.
7. Close with a short summary: what shipped, what is verified, what is next.

Do not treat a tool's private memory or session log as the shared record.
Claude auto memory, Codex rollouts under `~/.codex/sessions`, and Grok
sessions or memory under `~/.grok/` stay on this PC and are not committed.

### Test suite: keep runs to a minimum (Mark's rule, 18 November 2026)

Full runs make Hawkeye lag and sometimes freeze, so:

1. No test run at the start of a session.
2. Never run the full suite at the end of a session, before a commit, or
   for the release handover.
3. While working, run only the tests for what you are changing: one test
   method for red/green, then its class (for example
   `python -m unittest discover -s tests -k Session7Speed`).
4. Run the window (UI) tests only when UI code changed, and then only the
   relevant classes. If a menu, submenu, or shortcut changes, also run `-k`
   on every class that asserts menu contents (search `tests\test_engine.py`
   for `edit_menu`, `menus`, and `shortcut_rows`).
5. Never two test processes at once, and nothing left running in the
   background.
6. Your session summary lists the targeted tests you ran and their
   results, plus "full suite not run (Neal runs it at release)".
7. Neal runs the full suite once per release while verifying, before
   asking Mark to push.

### Releasing

A release closes when the last session in it is done. At that point you
stop and hand over to Neal, Mark's repository and release manager. In that
session:

1. Finish the session as usual: targeted tests green, the session's
   entries under **Unreleased** in `CHANGELOG.md`, the handoff, the private
   `roadmap.md` and `memory.md` updated, and one commit. Do not push it.
2. Leave the release itself to Neal. Do not bump `VERSION`, the launcher
   banner, or the three `Release / Status / Application on disk` headers;
   do not move **Unreleased** to a dated release section; do not create or
   push a `vX.Y` tag; do not push the branch.
3. Close by telling Mark that the release's sessions are done and Neal can
   take over.

Neal then checks the files against the repository (including the ahead
count, with `git log origin/main..main`), finalises the version headers,
the dated release section in `CHANGELOG.md`, and `README.md`, runs the
full test suite once, makes the release commit and the annotated `vX.Y`
tag, and pushes the branch and the tag only once Mark confirms, then
builds `FM Name Editor.exe` with `build_exe.bat` (see the README) and
attaches `dist\FM Name Editor.exe` to the GitHub Release. The exe itself
is never committed. The next session starts only when Mark says
**"Let's get started."** again.

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

Remote: `https://github.com/hawkers63/FM-Name-Editor` (`origin`, branch `main`, public). Work on `main`. Branch before experiments; `main` holds released or session-complete work only.

Session commits stay local on `main` until Neal or Jane pushes them, and only when Mark has confirmed a sync or a release (see **Releasing**). Claude Code never pushes, tags, or force-pushes. Do not force-push. Commits use Conventional Commits and, when the session brief gives an attribution line, end with that line.

The global Grok file `~/.grok/AGENTS.md` is personal and must be left alone; do not copy it into this repository or move rules out of it.
