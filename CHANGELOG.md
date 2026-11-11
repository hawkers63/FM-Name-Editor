# Changelog

Release: 2.0
Status: released
Application on disk: 2.0

The program on disk reports `VERSION = "2.0"`. The launcher banner says v2.0. This folder has no older copy and no git history, so the gap between the Version 1.0 description in `notes\note_01.txt` and the 1.1 script is not recorded here as a list of invented changes.

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
