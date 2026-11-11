# FM Name Editor — project memory

Release: 2.1
Status: released
Application on disk: 2.1

Facts worth keeping. Measured on 11 November 2026 unless a line says otherwise. If a later patch of Football Manager 27 disagrees with a path or a count, trust the disk and update this file.

## Purpose

A single-user Windows desktop tool for Mark Hawksworth. It edits Football Manager name-change files (`.lnc`) so club, competition, and related names use the spellings he wants, then prepares those files for the game.

It is not a player database, not a shared service, and not affiliated with Sports Interactive.

## Locations

| What | Path |
| --- | --- |
| Project | `C:\FM Name Editor` |
| Program | `C:\FM Name Editor\fm_name_editor.py` |
| Launcher | `C:\FM Name Editor\FM Name Editor.bat` |
| Notes | `C:\FM Name Editor\notes\note_01.txt`, `note_02.txt`, `note_03.txt` |
| Python used by the launcher today | `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe` |
| Game database root | `D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db` |
| Active name files | `db\2700\lnc\all\FM27_Club_Names.lnc` and `FM27_Fix.lnc` |
| Intended GitHub remote | https://github.com/hawkers63/FM-Name-Editor |

Version folders seen under `db`: `2300`, `2330`, `2340`, `2400`, `2430`, `2600`, `2620`, `2700`. Name editing for FM27 uses `2700`. Later patch folders, if they gain an `lnc\all` pair, should be selectable. Do not assume `2700` is permanent.

There is no `GROK_ACCESS.txt` and no `.grok\role.md` in the project. The folder is a git checkout of https://github.com/hawkers63/FM-Name-Editor. Releases 2.0 and 2.1 are published there.

## What 2.1 does

`VERSION = "2.1"`. The launcher banner says v2.1. On top of 2.0 it adds name packs (JSON and CSV), a backup browser that restores into memory, section-scoped replace with a preview, and UTF-16 load/save for the Greek person-name file.

`lnc\greek\person_name_changes.lnc` is UTF-16 LE (BOM `FF FE`), CRLF, 120 lines, 80 rules: 42 `PERSON_FIRST_NAME_END_CHANGE` and 38 `PERSON_SECOND_NAME_END_CHANGE`. The shape is command, `"GREEK"`, matched ending, a number, replacement. Those rows are editable on All lines. They are not entities and they are not written into name packs.

Player statistics and accounts remain out of scope.

## What 2.0 does

`VERSION` was `"2.0"`. The entity tab is the default. Quick load, Deploy, the licensing inspector, and the bulk transformer are in the window. Defects B1–B7 from the 1.1 review are fixed.

Design rules already in the script, and still in force:

- A line that is not edited is written back byte for byte.
- A name edit replaces only the quoted name span.
- Save writes a timestamped `.bak` beside the file, then replaces the file. Release 2.0 changes this for paths inside the game tree: those backups go to `C:\FM Name Editor\backups\<timestamp>\` instead of sitting in `lnc\all`.
- Search ignores accents (`Skënderbeu` matches `skenderbeu`).
- Import matches on `(command, id, language)`.

The window is one flat table: Section, Type, ID, Name, Language, File, Status. Double-click edits the name. Edited rows are bold. Commands the parser does not treat as a simple name (`CHANGE_PLAYER_NAME`, `FAKE_NATIONAL_TEAM`, header rows, blank names) pass through unchanged.

Dependency: PySide6 only. Do not add packages unless Mark asks.

## File format (measured)

Both FM27 name files start with a UTF-8 BOM (`EF BB BF`) and use LF only. The club file has 8,935 LF bytes and no CR. Note 03's claim that the files are CRLF is wrong for this install. The editor already keeps the ending it found. Keep doing that.

`lnc\greek\person_name_changes.lnc` starts with `FF FE` (UTF-16 LE). Release 2.1 loads and writes it as UTF-16. A UTF-8 decode of that file fails, which is why 2.0 refused it.

A name line is a quoted command, a numeric ID, a quoted name, and an optional quoted language. Spacing is a mix of tabs and spaces. Parse quoted strings. Do not split on tabs alone.

Examples of shape (not a suggestion to edit these clubs):

```
"CLUB_NAME_CHANGE" 58 "KF Apolonia" ""
```

Lines that start with `#` are comments. A comment with real heading text becomes the section for the following rows (`#Albania`, `#England`, and also `#Europe`). The club file has 160 such headings.

Header rows such as `"CLUB_NAME_CHANGE" "" ""` and deliberately blank names are passed through. Unrecognised lines stay as they are.

Command counts on this install:

| File | Lines | Commands |
| --- | --- | --- |
| `FM27_Club_Names.lnc` | 8,935 | 4,079 `CLUB_NAME_CHANGE`, 4,298 `CLUB_SHORT_NAME_CHANGE`, 242 `CLUB_3LETTER_NAME_CHANGE` |
| `FM27_Fix.lnc` | 9,092 | 3,742 `COMP_LONG_NAME_CHANGE`, 3,778 `COMP_SHORT_NAME_CHANGE`, 272 `STADIUM_NAME_CHANGE`, 18 `AWARD_LONG_NAME_CHANGE`, 9 `AWARD_NAME_CHANGE`, 12 `CITY_NAME_CHANGE`, 1 `NATION_LONG_NAME_CHANGE`, 1 `NATION_SHORT_NAME_CHANGE`, 5 `CHANGE_PLAYER_NAME`, 2 `FAKE_NATIONAL_TEAM` |

There are **no** `COMP_6LETTER_NAME_CHANGE` lines today. The friendly-name table in the script already knows that command. The competition entity view keeps the column, empty.

Long-name IDs and short-name IDs are not the same set. An entity is the union. Empty short-name or code cells are expected. The club file's 4,298 `CLUB_SHORT_NAME_CHANGE` tokens include the blank header line, so the entity view has 4,297 clubs. Note 01's "about 4,297 clubs" matches that union.

`CHANGE_PLAYER_NAME` has three name parts (for example a first name, an empty middle, and a surname). It is not a single quoted name. Leave it out of the name grid.

Award lines can carry a language such as `English`. The identity of an award row includes that language.

Accented letters and the BOM must survive a round trip.

## Licensing files (corrected)

Note 03 places `Licensing2.dbc` in `dbc\permanent\`. On this install it is in `dbc\permanent\language\`.

Name-mask files. Release 2.0 may rename these to `*.disabled` after copying them into the project backup archive. It does not edit their bytes.

- `db\2700\dbc\permanent\language\Licensing2.dbc` (8,451 bytes)
- `db\2700\dbc\permanent\language\Licensing2_chn.dbc` (2,000 bytes)
- `db\2700\dbc\permanent\japan_fake.dbc` (193 bytes, binary, header begins `03 01 63 62 64`)
- `db\2700\edt\permanent\fake.edt` (197 bytes, plain text, CRLF)

Report only. Do not toggle these in 2.0.

- `db\2700\dbc\permanent\licensing_fm27.dbc`
- `db\2700\dbc\permanent\license.dbc` (binary, same `cbd.` style header)
- `db\2700\dbc\permanent\brazil_kits.dbc`
- `db\2700\dbc\fv_licensing_changes.dbc`
- `db\2700\edt\permanent\fm_27_germany_squad_list.ddt`
- `db\2700\edt\permanent\japan.ddt` (UTF-8 text, short)
- `db\2700\edt\permanent\japan_international_players.ddt`
- `db\2700\edt\permanent\SI_team_holland.ddt`

Binary `.dbc` files are opaque. Do not try to pretty-print or patch them.

## Defects fixed in 2.0

From `notes\note_02.txt`. Fixed in the 2.0 program. The notes below record what was wrong in 1.1.

- **B1.** `LncDoc.save` copies the `.bak` before `to_bytes`. A `UnicodeEncodeError` is not an `OSError`, so `MainWindow.save` does not catch it. The backup can exist and the window can die.
- **B2.** `setData` rejects an empty name and a double quote. It accepts CR, LF, and other control characters, which split the record on the next load.
- **B3.** `build_proposals` drops a blank or quoted older name without counting it. With an "original" file supplied, every difference is pre-ticked, including rows noted "Renamed since".
- **B4.** `index` keeps the last entry for a key. Import then updates one duplicate and leaves the earlier line.
- **B5.** `import_old` does not rebuild the type combo. A new command family cannot be filtered until the files are opened again.
- **B6.** `revert_selected` skips imported rows and still says "Reverted N name(s)." when nothing changed.
- **B7.** The launcher's `PY` and `APPDIR` are hard-coded to this PC. `APPDIR` stays `C:\FM Name Editor` until the program is installed elsewhere. Only the Python lookup changes in 2.0.

## Decisions locked on 11 November 2026

1. Entity view is the default tab. The 16,448-row line view is the second tab.
2. Auto-detect, quick-load, and deploy into `2700\lnc\all`, with backups under `C:\FM Name Editor\backups\`. Licensing Health Inspector as listed above.
3. Bulk tools in 2.0: affix stripper (`FC`, `CF`, `FK`, `SK`, `AC`, `AS`, `AFC`, `SC`, `Calcio`, whole token, start or end only), competition sponsor cleanser (editable starter list, leading or trailing phrase, preview required), title casing (all-capitals names only; small words `of`, `the`, `and`, `de`, `da`, `di`, `van`, `von`, `y`).

Name packs, the backup browser, section-scoped replace, and the Greek UTF-16 file shipped in 2.1. Player statistics and user accounts stay out of scope.

Theme colours reserved for the 2.0 window: canvas `#13151b`, panel `#1a1e28`, border `#2a3040`, text `#e2e8f0`, muted `#8a94a6`, accent `#8b5cf6`, clean `#10b981`, filter `#06b6d4`, warning `#f59e0b`.

## Repository rules for the later GitHub publish

- Do not commit anything from `D:\Steam\...`.
- Do not commit `backups\`, timestamped `.bak` files, or copies of `.lnc`, `.dbc`, `.edt`, or `.ddt` game data.
- Do not commit `__pycache__`.
- Do not push, and do not run `git init`, until Mark asks in that session.
- British English in documents, comments, and interface text.
- Keep the copyright banner on a file exactly as it is, if one is ever added. The current script has none.

## Out of scope on purpose

Note 02 already set these aside. They stay aside.

- Charts of player statistics or team form. There is no player database in this program.
- User roles and accounts.
- Matplotlib, Plotly, or any second GUI toolkit.
