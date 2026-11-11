# Changelog

Release: 2.1
Status: released
Application on disk: 2.1

The program on disk reports `VERSION = "2.1"`. The launcher banner says v2.1.

## Unreleased — Release 2.2 in progress

Not released. `VERSION` still reads 2.1. Session 1 of Release 2.2 was done on 11 November 2026; sessions 2 and 3 follow.

Session 1 — correctness and write safety, part one (review findings F1, F2, F3):

- **One game-write preflight.** Save, Deploy, and the licensing toggle call the same check before touching the game tree. Save into the game folder was unguarded before; now it is refused while Football Manager is running, with the same message Deploy gives, and it asks for confirmation naming the exact files. When the process list cannot be read, the dialog says so and defaults to No instead of treating the game as closed.
- **Every field of a new line is checked.** Command, database id (ASCII digits), name, and language are validated before a line is formed, at pack import, older-file import, and entity-field insertion. A quote, a line break, or a control character in a language field is rejected and counted as a skipped row instead of becoming a second record in the file.
- **End-of-file insertion.** Filling an empty entity field beside a last line that has no line ending now gives that line its ending first, so the two commands no longer run together. Covered for LF, CRLF, and UTF-16 files.
- Tests: 33, up from 26. New cover for the preflight states, process-list failures, field checks, pack and older-file rejection, end-of-file insertion, and a window test of the refused Save.

## 2.1 (11 November 2026)

Shipped in `fm_name_editor.py` and `FM Name Editor.bat`.

- CSV and JSON name packs. Export edited names or every database-id name. Import previews the pack and applies the ticked rows in memory.
- Backup browser: list the archive, diff a backed-up `.lnc` against the open file, restore into memory. Save or Deploy writes the result. The window does not delete backups or write the game tree.
- Find and replace with a regular expression, scoped by section, with a preview.
- The UTF-16 Greek person-name file opens, edits, and saves as UTF-16. Person-name rules stay on the All lines tab.

Player statistics and accounts are not in this release. There is no player database and no account store.

## 2.0 (11 November 2026)

Shipped in `fm_name_editor.py` and `FM Name Editor.bat`. Specified in `roadmap.md`.

Agreed scope:

- Fix review defects B1–B7 (`notes\note_02.txt`), including a launcher that finds Python on `PATH` before using the known 3.11 install.
- Side-by-side entity view as the default tab (long name, short name, and code on one row). The current line-by-line table remains the second tab.
- Dark slate theme.
- Auto-detect FM27 `db\2700\lnc\all`, quick-load the two UTF-8 name files, and deploy with a backup under `C:\FM Name Editor\backups\` taken only after the new bytes have been built.
- Licensing Health Inspector. Toggle limited to the four name-mask files listed in `memory.md`. Other licensing files are reported and left alone.
- Bulk transformer: affix stripper, competition sponsor cleanser, title casing. Preview before apply.

Explicitly not in 2.0: name-pack export, backup browser, regex replace, player statistics, accounts, and the UTF-16 Greek person-name file. See Release 2.1 in `roadmap.md`.

## 1.1 (on disk)

The script header calls this 1.1. Behaviour present in `fm_name_editor.py`:

- Open one or more `.lnc` files, or start them by dropping them on the launcher.
- Accent-insensitive search, filter by command type, and a "changed only" filter.
- Edit a name in the table. Edited rows are bold and can be reverted to the name from when the file was opened.
- Import older edits by `(command, id, language)`, with an optional unedited original so unchanged stock names can be skipped.
- Save writes a timestamped `.bak` beside the file and preserves BOM, encoding, and the original line ending of each line.
- Problem lines are shown and written back unchanged.

Known limits, to be fixed in 2.0: B1–B7 in `notes\note_02.txt` and `memory.md`.

## 1.0 (specified, not separately archived)

`notes\note_01.txt` describes Version 1.0 as browse and search, edit, import older edits by ID, and save with a `.bak` and byte-for-byte untouched lines. That contract is what 1.1 implements. No separate 1.0 file is in this folder.
