# FM Name Editor

Release: 2.3
Status: released
Application on disk: 2.3

A Windows desktop editor for Football Manager 27 `.lnc` name files. It lets you change club, competition, stadium, and related spellings, carry edits across from an older game's files by database ID, and write the file back without disturbing lines you did not touch.

This project is a personal tool. It is not affiliated with Sports Interactive or Sega.

The program you can run today is **2.3**. Version notes are in [CHANGELOG.md](CHANGELOG.md). The roadmap and the working notes stay on this PC and are not part of the public repository.

## Run it

Double-click `FM Name Editor.bat`, or drop `.lnc` files onto that launcher.

The launcher uses `python` on PATH when it can, and otherwise:

`C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe`

If PySide6 is missing, the launcher offers to install it for that interpreter. You can also start the script yourself:

```
python fm_name_editor.py
python fm_name_editor.py "FM27_Club_Names.lnc" "FM27_Fix.lnc"
```

Requires Python 3.11 or later and PySide6. No other packages.

## What 2.3 adds

- **Spelling profiles.** A profile keeps your preferred spellings in the local `profiles` folder, each with the name the game file had when you recorded it. Save and Deploy never change a profile. When the game's files change, **Apply...** offers your spellings again and ticks only those whose name the game has not changed since. The profile selector, **Record edits**, **Apply...**, and **Manage** sit in the row under the toolbar.
- **The Changes tab** lists every difference between the open files and the files on disk: the text on disk, the text to write, whether the line is edited, added, restored, or removed, which tool changed it, and the file and line. Each change has a tick.
- **Review changes before every write.** Save and Deploy both show the changes, where each file goes, the backup folder, whether the game is running, and any file that changed on disk since the editor read it. An unticked change is left out of the write and stays pending. A file whose bytes would not change is not written. Save into the game folder is the same operation as Deploy, and the review says so.
- **Undo and Redo** for whole operations: Ctrl+Z and Ctrl+Y, or the **Edit** menu, which names the step. A bulk tool, a name pack, a profile, a restore, or a Revert undoes as one step, and undo goes back past a Save or Deploy. Undo changes memory only; the next Save or Deploy writes the result.

## What 2.2 changes

2.2 is a safety release. Nothing new to learn; the editor is more careful about every file it writes.

- **Save into the game folder is guarded like Deploy.** Save, Deploy, and the licensing toggle all refuse while Football Manager is running, and each one names the exact files before it writes. If the editor cannot tell whether the game is running, it says so and the answer defaults to No.
- **Files are replaced one at a time, with a way back.** Each file is written to a temporary file beside it and swapped in, in one step. If a later file fails, the files already replaced are put back from the backup copy, and a message lists where every file stands. A set of files is not one atomic step, and the editor does not claim it is.
- **A file changed by another program is not overwritten.** If a name file changed on disk after the editor opened it, Save and Deploy stop without writing and tell you how to carry your edits across: export them as a name pack, open the files again, and import the pack.
- **Unsaved means the bytes differ.** The editor compares what it would write with the file on disk, so the close prompt cannot be skipped by an edit and a revert. A restored backup stays pending until you Save or Deploy it.
- **Backups describe themselves.** Each backup folder holds a `manifest.json` with the operation, the time, the database folder, and each file's original path, size, SHA-256, encoding, and how the write ended. The **Backups** window matches a copy to the open file by its original path, and reports name differences and byte-identical files separately.
- **Checked fields and plainer labels.** A pack or older file cannot slip a quote or line break into a new line. The filters read **No short-name override** and **No code override**, and the section column is **File section**: the comment heading a row sits under, not a reliable country.

## What 2.1 adds

- **Export pack** and **Import pack** move spellings as JSON or CSV, matched on command, database ID, and language. A preview comes first.
- **Replace** finds a regular expression in one section, or in all sections, and shows the before and after list before it changes anything.
- **Backups** lists the archive, compares a backed-up name file with the open one, and can put that copy back into the editor. Save or Deploy writes it.
- The Greek person-name file (`lnc\greek\person_name_changes.lnc`) opens as UTF-16. Its ending rules are on **All lines**, not on the entity grid.

## What 2.0 does

- **Entities** is the first tab. A club or competition is one row: long name, short name, and code. **All lines** keeps the original table.
- Search ignores accents. Filter by file section, type, edited rows, **No short-name override**, or **No code override**. An absent override is not an error; the game may supply that name itself.
- Double-click a cell to edit it. Filling an empty short name or code adds one line next to its sibling.
- **Quick load FM27** opens the two UTF-8 name files in the selected database folder (`2700` on this PC).
- **Deploy to FM27** writes those files into `lnc\all` after copying the current game files into `backups`. Save of a file outside the game tree still writes a `.bak` beside it.
- **Licensing** can rename the four name-mask files to `.disabled`, or restore them. It does not edit their contents. Other licensing files are listed and left alone.
- **Bulk tools** preview an affix strip, a competition sponsor clean, or title casing, then apply the preview in memory.
- Import older edits matched on command, database ID, and language. A stock rename between versions is not ticked for you.

Close Football Manager before Save into the game folder, Deploy, or a licensing toggle. The editor refuses while `fm.exe` is running. It does not close the game for you.

Lines that are not simple name commands are kept as they are. That includes comments, blank lines, player-name lines, and anything the parser does not recognise.

## Game files

On this PC the FM27 name files are:

`D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db\2700\lnc\all\`

Use **Quick load FM27**, Open, or drop `.lnc` files onto the launcher. Quick load still opens the two UTF-8 name files in `lnc\all`. Open `lnc\greek\person_name_changes.lnc` yourself when you want the Greek ending rules. That file is UTF-16 and the editor keeps it that way.

## Publish

The public repository is https://github.com/hawkers63/FM-Name-Editor. Releases 2.0, 2.1, 2.2, and 2.3 are published there. Game data and backups do not belong in that repository.

## Licence

Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved. This is proprietary software, not open source. See [LICENSE](LICENSE) for the terms.
