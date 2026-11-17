# FM Name Editor

Release: 2.6.1
Status: released
Application on disk: 2.6.1

A Windows desktop editor for Football Manager 27 `.lnc` name files. It lets you change club, competition, stadium, and related spellings, carry edits across from an older game's files by database ID, and write the file back without disturbing lines you did not touch.

This project is a personal tool. It is not affiliated with Sports Interactive or Sega.

The program you can run today is **2.6.1**. Version notes are in [CHANGELOG.md](CHANGELOG.md). The roadmap and the working notes stay on this PC and are not part of the public repository.

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

## Build a Windows executable

A tracked PyInstaller spec and launcher build a one-file, windowed `FM Name Editor.exe` from the source. Install PyInstaller once:

```
python -m pip install pyinstaller
```

Then double-click `build_exe.bat`, or run it from a terminal:

```
build_exe.bat
```

It finds `python` on PATH (with the same fallback as the launcher), runs PyInstaller against `FM Name Editor.spec`, and prints where the exe landed. The result is `dist\FM Name Editor.exe`: a windowed (no console) build that carries `icon\football.ico` and a Windows version resource (product name, file and product version from `VERSION`, LegalCopyright with the notice at the foot of this file).

The exe stands on its own: the backups, profiles, and state folders sit beside it, so it works wherever it is unpacked. PyInstaller is a build tool only; the runtime still needs only PySide6.

`/build/` and `/dist/` are kept out of the repository; the exe itself is never committed. Each release's exe is attached to its GitHub Release.

## What 2.6.1 adds

2.6.1 is a small follow-up to 2.6. The editing workflow is unchanged.

- **A link to the repository.** **Help > About FM Name Editor** shows https://github.com/hawkers63/FM-Name-Editor directly beneath the copyright line; click it to open the page in your browser.
- **The status-bar tooltip names it too.** Hovering the short copyright shows the full copyright, the repository address, and the LICENSE pointer.
- **A steadier speed test.** The one-second timing check re-measures once after a single slow step caused by a busy PC, so a passing spike no longer fails the suite. A real slowdown still fails.

## What 2.6 adds

2.6 gets the editor ready for a public repository. The editing workflow is unchanged; it adds the copyright notice inside the program, its own icon, and a Windows executable for each release.

- **About FM Name Editor.** **Help > About FM Name Editor** shows the version and the copyright: "Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved." Directly beneath it, a clickable link to the public repository at <https://github.com/hawkers63/FM-Name-Editor> opens in the default browser. The software is proprietary, not open source; see [LICENSE](LICENSE).
- **The copyright in the status bar.** A short "(c) 2026 Mark Hawksworth" sits beside the metrics, with the full line, the repository URL, and the LICENSE pointer in its tooltip.
- **Its own icon.** The football icon, in sizes from 16 to 256 pixels, is on every window and dialog and on the exe.
- **A Windows executable.** From 2.6, each GitHub Release carries `FM Name Editor.exe`, a one-file windowed build that needs no Python install. Its backups, profiles, and state folders sit beside the exe, so give it a folder of its own. See **Build a Windows executable** above to build it yourself.

## What 2.5 changes

2.5 is a corrective release. Nothing new to learn; it puts right six faults found in 2.4, and it ships on its own so that the licensing safety fix does not wait for 3.0.

- **Licensing looks for the game again after you answer.** The licensing toggle checks for a running copy of Football Manager before its question and again after Yes, the same as Save and Deploy. If the game is running by then, it stops with "Nothing was renamed". If that second check cannot be made, it asks "Have you closed Football Manager?" with No as the default, rather than reusing your earlier answer.
- **One licensing toggle at a time.** Only one toggle runs at a time, and closing the Licensing window (Close, Esc, or the title-bar button) cancels one that is still waiting. The rename does exactly the disable or restore you confirmed; if the file changed in the meantime, it stops instead of renaming it back.
- **Profile Apply checks every line it would change.** Where a name is on more than one line, **Apply...** now checks each line it would change, in any order and across both files, and the note names the file and line of each problem. Lines that already have your spelling are left as they are, because Apply would not change them anyway.
- **A wrong value no longer stops the window opening.** A value of the wrong type in `state\settings.json` is ignored. A collections file with the same fault is named in the Collections panel and left alone.
- **A damaged settings file is named and left alone.** If `state\settings.json` cannot be read, the status bar names it and the file is left exactly as it is, instead of being quietly written over. Nothing is saved for the rest of that run, even if you fix the file meanwhile; to recover, fix or move the file and restart the editor.
- **Refused text stays in the inspector.** Text that cannot be a name now stays, with its reason, through edits to other fields, reloads, and Undo.
- **No file actions during background work.** **Export pack**, the profile **New**, **Rename**, and **Delete** actions, and **Collections > Add selected to** are switched off while files are opened, a backup is read, or the game is checked.

## What 2.4 adds

- **A window that answers at once.** With both FM27 name files open, opening them took about ten seconds, and so did every Save, Deploy, restore, bulk step, or added field. Now opening takes under a second, an edit or an undo under a tenth, and a Save, review included, about half a second. **Open**, **Quick load**, reading a backup to restore, and the check for a running copy of Football Manager run in the background. The window stays drawn, with the grids and every action that opens, changes, or writes files switched off until the work finishes.
- **Menus and one top row.** File, Edit, View, Packs, Backups, Profiles, Collections, and Help hold every action, with its keys beside it (**Help > Keyboard shortcuts**, or F1, lists them all). The top row keeps the database, the profile with **Record edits** and **Apply...**, **Quick load**, **Undo**, **Redo**, and **Review changes**, which shows how many changes are pending and opens the review before a Save (Ctrl+S).
- **Names get the room.** The grid is sorted by long name; click a heading to sort by it. The ID column has moved to the panel on the right, and the File section column hides while one section is chosen.
- **The panel on the right shows both spellings.** For each field: the text on disk above the text to write, whether it is unchanged, edited, or added and by which tool, and the file and line. Text that cannot be a name stays where you typed it with the reason beside it; Esc puts back the name.
- **Your own collections.** Select rows and choose **Collections > Add selected to** (or right-click) to keep sets such as "My save" or "Names to review". They are listed above the file sections with a ★ in cyan, and live in the local `state\collections.json`, never in the name files.
- **Saved searches and a section search.** **Saved searches** keeps a search under a name. A box above the file sections narrows that long list as you type.
- **It remembers how you left it.** Window size and place, tab, family, filter, both sort orders, the column widths you set yourself, and the panes come back next time. Since 2.5, a damaged `state\settings.json` is named in the status bar and left alone.
- **Fits 100%, 125%, and 150% scaling.** At 150% the window now fits the screen instead of running off the bottom, keyboard focus shows as a cyan outline (it was invisible), and the include tick's empty box is clearly visible.
- Keys: F2 edits a cell, Ctrl+Shift+C goes to Changes, Ctrl+Z and Ctrl+Y undo and redo. Double-click a change to see its line.

## What 2.3 adds

- **Spelling profiles.** A profile keeps your preferred spellings in the local `profiles` folder, each with the name the game file had when you recorded it. Save and Deploy never change a profile. When the game's files change, **Apply...** offers your spellings again and ticks only those whose name the game has not changed since. Since 2.4 the profile selector, **Record edits**, and **Apply...** sit in the top row, and New, Rename, and Delete are in the **Profiles** menu.
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
- Double-click a cell to edit it, or press F2. Filling an empty short name or code adds one line next to its sibling.
- **Quick load** opens the two UTF-8 name files in the selected database folder (`2700` on this PC).
- **File > Deploy to FM27** writes those files into `lnc\all` after copying the current game files into `backups`. Save of a file outside the game tree still writes a `.bak` beside it.
- **File > Licensing files** can rename the four name-mask files to `.disabled`, or restore them. It does not edit their contents. Other licensing files are listed and left alone.
- **Edit > Bulk tools** preview an affix strip, a competition sponsor clean, or title casing, then apply the preview in memory.
- Import older edits matched on command, database ID, and language. A stock rename between versions is not ticked for you.

Close Football Manager before Save into the game folder, Deploy, or a licensing toggle. The editor refuses while `fm.exe` is running. It does not close the game for you.

Lines that are not simple name commands are kept as they are. That includes comments, blank lines, player-name lines, and anything the parser does not recognise.

## Game files

On this PC the FM27 name files are:

`D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db\2700\lnc\all\`

Use **Quick load**, **File > Open files**, or drop `.lnc` files onto the launcher. Quick load still opens the two UTF-8 name files in `lnc\all`. Open `lnc\greek\person_name_changes.lnc` yourself when you want the Greek ending rules. That file is UTF-16 and the editor keeps it that way.

## Publish

The public repository is https://github.com/hawkers63/FM-Name-Editor. Releases 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, and 2.6.1 are published there. Game data and backups do not belong in that repository.

## Licence

Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved. This is proprietary software, not open source. See [LICENSE](LICENSE) for the terms. The public repository is at <https://github.com/hawkers63/FM-Name-Editor>; **Help > About FM Name Editor** shows the same link in the editor.
