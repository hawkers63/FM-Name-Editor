# FM Name Editor — guide for Claude

A single-file PySide6 desktop editor for Football Manager 27 `.lnc` name files, written for one person on one Windows PC. Read this file first in every session. The facts that change (paths, counts, defect status) live in `memory.md`; the plan lives in `roadmap.md`. Both of those stay on this PC and are not in the public repository.

## Files that matter

| File | What it is |
| --- | --- |
| `fm_name_editor.py` | The whole program. Engine first, GUI inside `run_gui()` with lazy Qt imports. `VERSION` near the top. |
| `FM Name Editor.bat` | Launcher. Finds `python` on PATH, falls back to the 3.11 install, offers to pip-install PySide6. Version banner in its header comment. |
| `tests/test_engine.py` | Standard-library `unittest`. Temporary fixtures plus two read-only round trips of the live game files and offscreen window tests. |
| `CHANGELOG.md`, `README.md` | Public. Each carries a `Release / Status / Application on disk` header that must agree with `VERSION`. |
| `roadmap.md` | Private. The numbered session plan and what each session must deliver. Tells you which session is next. |
| `memory.md` | Private. Measured facts about this PC's game files, decisions already made, and the defect ledger. |
| `notes/note_NN.txt` | Private. Mark's briefs and the review notes each release grew from. The highest number is the current brief. |

## Session protocol

Mark opens a session with **"Let's get started."** When you see that:

1. Read `CLAUDE.md`, `memory.md`, `roadmap.md`, `CHANGELOG.md`, the highest-numbered note in `notes\`, and `git status` / `git log --oneline -5`.
2. Run the test suite (command below) and confirm it is green before touching anything.
3. Find the session marked **next** in `roadmap.md`. Say in a few lines what that session will deliver, then do it. Do not pull work forward from later sessions unless it is a one-line prerequisite.
4. Work in the order the roadmap gives: engine change, tests for it, then GUI, then documents.
5. End the session with: tests green; `CHANGELOG.md` updated (an **Unreleased** section until the release ships); `roadmap.md` updated (this session marked done, the next one marked next, anything left over written into it); `memory.md` updated if a fact changed; one commit; one push to `origin main`.
6. Close with a short summary: what shipped, what is verified, what is next.

If a session cannot finish in one sitting, split it. Write the remainder into the roadmap as the next session before you stop. Never leave the working tree with failing tests at the end of a session.

### Releasing

A release closes when the last session in it is done. Then, in one commit: bump `VERSION`, the launcher banner, and the three `Release / Status / Application on disk` headers; move **Unreleased** to a dated release section in `CHANGELOG.md`; refresh `README.md`; commit; tag `vX.Y`; push the branch and the tag.

## Rules that do not change

- **Byte preservation.** A line that is not edited is written back byte for byte. BOM, encoding (UTF-8 or UTF-16 LE), and each line's own ending survive. A name edit replaces only the quoted span.
- **Unsaved means the bytes differ.** `LncDoc.dirty` compares the working lines with `baseline_bytes`, the file as last read or written. Change lines through `Entry.set_name` and `Entry.set_source`, or call `doc.touch()` after any other change to `entries`, a line's text, or its ending. After a successful write of the whole working copy call `doc.mark_clean(payload)` with the bytes written; a partial write settles with `doc.settle_written(lines, payload)` (`write_documents` does both). Each line keeps its disk text and ending (`orig_raw`, `orig_eol`) and the operation that last changed it (`reason`, a key of `CHANGE_REASONS`): an operation that changes lines must pass its reason. A restore keeps the disk baseline (`replace_working`) and never resets the originals.
- **Preview, then memory, then disk.** Bulk tools, imports, replace, and restore change memory only. Only Save and Deploy write files, only through the Review changes dialog (`MainWindow.review_and_write`, built on `WriteReview`), and only after a backup. Unticked changes (`Entry.excluded`) are left out of the bytes written (`build_payload`) and stay pending; a restored backup is written whole. A file whose bytes would not change is not written.
- **One write path.** Never write a file with `write_bytes` or `open(..., "w")`. One file goes through `write_file_atomically` (a temporary sibling, flushed, then `os.replace`). Documents go through `write_documents` (via `save_documents`, `deploy_documents`, or `LncDoc.save`): it refuses a file that changed on disk since it was read (`ExternalChangeError`), backs up game files into `backups\<stamp>\` with a `manifest.json`, replaces files one at a time, and puts already-replaced files back if a later one fails (`WriteError` lists each file's state). Never describe a set of files as written atomically.
- **The game tree is sacred.** Writes outside `C:\FM Name Editor` go only to the paths named in `memory.md`, after an archive copy and a confirmation. Never delete game files. Never use the Steam tree as a write fixture in tests. Refuse to write game files while `fm.exe` is running; never stop that process.
- **One dependency.** PySide6 only. No second GUI toolkit, no charts, no AI SDK, no service. Ask before adding any package.
- **One module.** Keep the engine and GUI in `fm_name_editor.py`, engine helpers free of Qt imports so the tests can import them.
- **Nothing in the repository from `D:\Steam`.** No `.lnc`, `.dbc`, `.edt`, `.ddt` copies, no `backups\`, no `.bak-*`, no `__pycache__`, and no `notes\`, `memory.md`, `roadmap.md`, `profiles\`, or `state\`.
- **Local files.** Spelling profiles live in `profiles\` and local settings in `state\settings.json`, both written through `write_file_atomically`. Save and Deploy never change a profile; only Record edits, New, Rename, and Delete do. Deleting a profile moves it into `profiles\deleted`.
- **British English** in interface text, comments, and documents. Plain words over jargon.
- **Honest labels.** An absent override is "No short-name override", not "Missing". The comment heading a row sits under is its "File section", not its country.
- Tests are standard-library `unittest`, run from the project root, writing only to temporary directories. `setUpModule` points `BACKUP_ROOT`, `PROFILE_ROOT`, and `STATE_ROOT` at a temporary folder for the whole run, and makes an unattended `QDialog.exec` fail the test instead of hanging the run: window tests stand in for it (`press_write` presses Write in the review dialog) and patch `QMessageBox` calls. The module sets `QT_QPA_FONTDIR` so offscreen window sizes match the desktop. Window tests clean up with `close_window`, which deletes the window; without that every later window test gets slower.

## Commands

```
python -m unittest discover -s tests -v
python fm_name_editor.py
python fm_name_editor.py "FM27_Club_Names.lnc" "FM27_Fix.lnc"
```

Set `QT_QPA_PLATFORM=offscreen` when running the suite without a desktop. `python` on PATH is 3.11.1 with PySide6 6.12.

## Git

Remote: `https://github.com/hawkers63/FM-Name-Editor` (`origin`, branch `main`). Push with git; the credential manager holds the login. Commits end with the attribution line given in the session. Branch before experiments; `main` holds released or session-complete work only.
