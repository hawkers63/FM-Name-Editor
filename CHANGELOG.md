# Changelog

Release: 2.1
Status: released
Application on disk: 2.1

The program on disk reports `VERSION = "2.1"`. The launcher banner says v2.1.

## Unreleased — Release 2.2 in progress

Not released. `VERSION` still reads 2.1. Sessions 1 and 2 of Release 2.2 were done on 11 November 2026; session 3 follows.

Session 1 — correctness and write safety, part one (review findings F1, F2, F3):

- **One game-write preflight.** Save, Deploy, and the licensing toggle call the same check before touching the game tree. Save into the game folder was unguarded before; now it is refused while Football Manager is running, with the same message Deploy gives, and it asks for confirmation naming the exact files. When the process list cannot be read, the dialog says so and defaults to No instead of treating the game as closed.
- **Every field of a new line is checked.** Command, database id (ASCII digits), name, and language are validated before a line is formed, at pack import, older-file import, and entity-field insertion. A quote, a line break, or a control character in a language field is rejected and counted as a skipped row instead of becoming a second record in the file.
- **End-of-file insertion.** Filling an empty entity field beside a last line that has no line ending now gives that line its ending first, so the two commands no longer run together. Covered for LF, CRLF, and UTF-16 files.
- Tests: 33, up from 26. New cover for the preflight states, process-list failures, field checks, pack and older-file rejection, end-of-file insertion, and a window test of the refused Save.

Session 2 — correctness and write safety, part two (review findings F4 and F5, plus load and label items):

- **Unsaved means the bytes differ.** Each open file remembers the bytes it was read as, or last written as. It counts as unsaved whenever the lines in memory would write different bytes. Before, an edit followed by a revert could clear the flag while memory still differed from the file, so closing could skip the save prompt.
- **A restore stays pending until it is written.** Restoring a backup keeps the file on disk as the baseline. Restored rows that differ from the disk file show as Edited, rows the disk file does not have show as Added, and disk rows the backup lacks are counted as unsaved. Edited-only export after a restore lists exactly the rows that differ from disk. Reverting a restored row puts back the text on disk. Restoring a copy that matches the disk file leaves nothing unsaved.
- **Revert restores Greek person rules in full.** Both the matched ending and the replacement come back, and the status line counts person rules separately. The All lines view no longer overwrites its revert message straight away.
- **Opening files is all or nothing.** Every file is read first. If one cannot be read or decoded, a message names it and the files already open stay open. Before, a bad encoding could escape the error handler and a failed open emptied the workspace. The import dialog now catches decoding errors too.
- **Plainer labels.** "Missing short name" and "Missing code" are now "No short-name override" and "No code override". "Section" is now "File section", with a hint that it is the comment heading in the file and not a reliable country. The unsaved count includes restored and removed rows, and says "file differs from disk" when only comments or layout differ.
- Tests: 50, up from 33. New cover for restore baselines and pending state, repeated and failed restores, Greek rule revert in every order, all-or-nothing opening, the close prompt after a restore, and the new labels.
Housekeeping:

- **Proprietary licence.** A `LICENSE` file now states that FM Name Editor is copyright Mark Hawksworth (hawkers63), all rights reserved, with no copying, distribution, modification, reverse engineering, sublicensing or commercial use without prior written consent. `fm_name_editor.py` carries the matching copyright banner.
- `.gitignore` now keeps the local `profiles/` and `state/` folders out of the repository.

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
