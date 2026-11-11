# FM Name Editor

Release: 2.0
Status: released
Application on disk: 2.0

A Windows desktop editor for Football Manager 27 `.lnc` name files. It lets you change club, competition, stadium, and related spellings, carry edits across from an older game's files by database ID, and write the file back without disturbing lines you did not touch.

This project is a personal tool. It is not affiliated with Sports Interactive or Sega.

The program you can run today is **2.0**. How that release was shaped is in [roadmap.md](roadmap.md). Facts about the FM27 files on this PC are in [memory.md](memory.md). Version notes are in [CHANGELOG.md](CHANGELOG.md).

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

## What 2.0 does

- **Entities** is the first tab. A club or competition is one row: long name, short name, and code. **All lines** keeps the original table.
- Search ignores accents. Filter by section, type, edited rows, or a missing short name or code.
- Double-click a cell to edit it. Filling an empty short name or code adds one line next to its sibling.
- **Quick load FM27** opens the two UTF-8 name files in the selected database folder (`2700` on this PC).
- **Deploy to FM27** writes those files into `lnc\all` after copying the current game files into `backups`. Save of a file outside the game tree still writes a `.bak` beside it.
- **Licensing** can rename the four name-mask files to `.disabled`, or restore them. It does not edit their contents. Other licensing files are listed and left alone.
- **Bulk tools** preview an affix strip, a competition sponsor clean, or title casing, then apply the preview in memory.
- Import older edits matched on command, database ID, and language. A stock rename between versions is not ticked for you.

Close Football Manager before Deploy or a licensing toggle. The editor will refuse while `fm.exe` is running. It does not close the game for you.

Lines that are not simple name commands are kept as they are. That includes comments, blank lines, player-name lines, and anything the parser does not recognise.

## Game files

On this PC the FM27 name files are:

`D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db\2700\lnc\all\`

Use **Quick load FM27**, Open, or drop the two `.lnc` files onto the launcher. Do not point the program at `lnc\greek\person_name_changes.lnc`. That file is UTF-16.

## Publish

The public repository is https://github.com/hawkers63/FM-Name-Editor. Release 2.0 is the first commit published from this folder. Game data and backups do not belong in that repository.
