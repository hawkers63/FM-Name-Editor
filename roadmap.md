# FM Name Editor — roadmap

Release: 2.1
Status: released
Application on disk: 2.1

This roadmap records the work agreed on 11 November 2026. Release 2.0 is in the history below. Release 2.1 is now in `fm_name_editor.py` and `FM Name Editor.bat`.

The program on disk is a single PySide6 script. It opens Football Manager `.lnc` name files, lets you edit the quoted name, imports older edits by database ID, and writes the file back with untouched lines preserved byte for byte. Release 2.0 keeps that engine and adds the three decisions below.

## Locked decisions

1. **Viewing paradigm.** The side-by-side entity view is the primary default tab. The existing line-by-line table (16,448 name rows on the current FM27 files) stays as the second tab.
2. **Game integration.** Auto-detect the FM27 database, quick-load `2700\lnc\all`, and deploy with a fail-safe copy taken before any game file is replaced. A Licensing Health Inspector reports the mask files and can set aside the name-mask set.
3. **Bulk tools.** The first bulk set is the affix stripper, the competition sponsor cleanser, and title casing. Each one shows a preview before it changes a name.

## Where the program is now (1.1)

- `fm_name_editor.py` — application 1.1, 835 lines. Parse, edit, import-by-ID, byte-preserving save, one flat table.
- `FM Name Editor.bat` — launcher 1.0. It looks only at `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe`.
- `notes\note_01.txt` — original contract.
- `notes\note_02.txt` — review of 1.1. Defects B1–B7 are still unfixed.
- `notes\note_03.txt` — enhancement blueprint. A few paths and line-ending claims in that note are corrected in `memory.md`.

Releases 2.0 and 2.1 are published at https://github.com/hawkers63/FM-Name-Editor.

## Release 2.0 — work order

Bugfixes come first. Deploy writes into the Steam tree, and defect B1 can fail a save after a backup has already been copied, or crash the window.

### 1. Engine hardening (still shipped under the 2.0 number)

Apply the patches already written up in `notes\note_02.txt`.

| ID | Fix |
| --- | --- |
| B1 | Build the byte payload before any backup. Catch `OSError` and `UnicodeError` in the window. |
| B2 | Reject empty names, double quotes, and ASCII control characters (`name_is_legal`). Tabs inside a name stay legal. |
| B3 | Count older names skipped because they are blank or contain a quote. Do not pre-tick a row noted "Renamed since". |
| B4 | An import updates every row that shares `(command, id, language)`, not only the last. |
| B5 | Rebuild the type filter after import as well as after open. |
| B6 | Revert reports added rows that have no previous name, instead of claiming they were reverted. |
| B7 | Launcher tries `where python`, then the known Python 3.11 install. |

`VERSION` in the script and the version comment in the launcher move from 1.1 / 1.0 to **2.0** only when the feature work below is in the same release. A bugfix-only publish would be 1.2. This roadmap assumes one publish, at 2.0. Say if you want the 1.2 checkpoint instead.

### 2. Entity view and the darker window

Default tab is the entity view. The second tab is today's line view, including search, the type filter, import, problem lines, and revert.

Entity rules:

- A club is one row: section, ID, long name, short name, three-letter code, status. The three cells are the `CLUB_NAME_CHANGE`, `CLUB_SHORT_NAME_CHANGE`, and `CLUB_3LETTER_NAME_CHANGE` lines that share that ID.
- A competition is one row with long name, short name, and a six-letter column. Today's FM27 files contain no `COMP_6LETTER_NAME_CHANGE` lines, so that column is empty until a file has them.
- Stadiums, cities, nations, and awards are further chips on the same tab. Awards keep the language field, because two award lines can share an ID in different languages.
- An entity is the **union** of IDs. A missing short name or code is an empty cell, not a broken line. Only 242 clubs have a three-letter code in the current club file.
- Editing a filled cell uses the existing `set_name` path, so only the quoted name changes.
- Filling an empty cell appends one new legal line to the file that already holds that command family.
- Two name lines with the same command and ID are a warning. They are not silently merged.

Around the grid:

- Left list of `#` section headings (countries, and also continent headings such as Europe), with counts.
- Quick chips: All, Edited, Missing short name, Missing code. Clubs is the chip selected when the files load.
- Right-hand inspector for the selected entity: the same fields, plus Revert.
- Dark slate theme so the window is no longer the plain operating-system grey. Canvas `#13151b`, panel `#1a1e28`, border `#2a3040`, text `#e2e8f0`, muted `#8a94a6`, accent `#8b5cf6`, clean `#10b981`, filter `#06b6d4`, warning `#f59e0b`.

The line-view tab is not restyled into a different product. It receives the same dark theme and the engine fixes, and it stays the place for command-level inspection.

### 3. Auto-detect and one-click deploy

- Database root: `D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db`.
- Choose the highest version folder that contains `lnc\all` with the two FM27 name files. Today that is `2700`. The choice can be overridden when a later patch folder appears (`2730` or similar).
- Quick Load opens only:
  - `2700\lnc\all\FM27_Club_Names.lnc`
  - `2700\lnc\all\FM27_Fix.lnc`
- The Greek person-name file is UTF-16. Release 2.0 did not open it. Release 2.1 does, and writes it back as UTF-16.
- Deploy builds the full byte string first. If encoding fails, the game files are not opened for writing and no backup is taken.
- On success, copy the current game files into `C:\FM Name Editor\backups\<YYYYMMDD-HHMMSS>\`, then write the new bytes to `lnc\all`.
- Do not leave `.bak-*` files inside the game `lnc\all` folder. A save of a file that is **outside** the game tree still uses today's beside-file `.bak`.
- The confirmation names the destination path.
- If a Football Manager process is running, Deploy refuses and asks you to close the game. The program does not stop that process.

### 4. Licensing Health Inspector

The inspector reports status only, except for the name-mask set, which can be moved aside.

Toggle allowed, and only after a confirmation. The original is copied into the backup archive, then the file is renamed to the same name with `.disabled` added. Restore removes that suffix. Nothing is deleted. The file body is not edited.

- `2700\dbc\permanent\language\Licensing2.dbc`
- `2700\dbc\permanent\language\Licensing2_chn.dbc`
- `2700\dbc\permanent\japan_fake.dbc`
- `2700\edt\permanent\fake.edt`

Report only in 2.0. These affect kits, squads, or other rules, not just a displayed name. Several `.dbc` files are binary and must not be decoded or rewritten.

- `dbc\permanent\licensing_fm27.dbc`
- `dbc\permanent\license.dbc`
- `dbc\permanent\brazil_kits.dbc`
- `dbc\fv_licensing_changes.dbc`
- `edt\permanent\fm_27_germany_squad_list.ddt`
- `edt\permanent\japan.ddt`
- `edt\permanent\japan_international_players.ddt`
- `edt\permanent\SI_team_holland.ddt`

`Licensing2.dbc` lives under `dbc\permanent\language\`, not directly under `dbc\permanent\` as an earlier note suggested.

The same "close the game first" check used by Deploy applies here.

### 5. Bulk transformer

Acts on the entities in the current filter. A preview lists before and after. Apply marks the documents dirty. Disk writes still wait for Save or Deploy.

- **Affix stripper.** Whole tokens at the start or the end only: `FC`, `CF`, `FK`, `SK`, `AC`, `AS`, `AFC`, `SC`, `Calcio`. A token in the middle of a name is left alone.
- **Sponsor cleanser.** Competitions only. A short starter list (Sky Bet, Barclays, and a few other league sponsors) can be edited in the dialog. A phrase is removed when it leads or trails the name. It does not rewrite every competition on its own.
- **Title casing.** Names that are entirely capitals become title case. The small words `of`, `the`, `and`, `de`, `da`, `di`, `van`, `von`, and `y` stay lower case after the first word. A name that is not all capitals is left as it is, so existing capitals and accents stay.

## Checks when the code is written

Standard-library `unittest` only, on temporary copies. The Steam tree is not a test fixture.

- Read-only parse of both live name files: line counts, BOM, LF endings, entity totals.
- An unmodified temporary copy written back must match the original bytes.
- A legal rename, a rejected name that contains a newline, and a deploy into a temporary stand-in for `lnc\all` that proves the backup exists before the write.
- Launch the window once and exercise Quick Load (against a copy if the live game files should stay untouched), an entity edit, a bulk preview that is cancelled, and the line-view tab.

There is no browser surface. Verification is the tests plus one desktop pass.

## Release 2.1 — released

Shipped in `fm_name_editor.py` and `FM Name Editor.bat`.

- **Name packs.** Export edited names, or every database-id name, as JSON or CSV (`command`, `id`, `language`, `name`). Import shows a preview. Differing rows are pre-ticked. Rows missing from the open files stay unticked. Person-name rules are not part of a pack.
- **Backups.** The Backups window lists `C:\FM Name Editor\backups`, diffs a backed-up `.lnc` against the open file of the same name, and can restore that copy into memory. Save or Deploy writes it. The backup folder is not modified, and game files are not written from this window. Licensing files in an archive are listed and left alone.
- **Replace.** A regular expression, optional "ignore capitals", scoped to one section heading or to all sections. Preview is required. An illegal result is left out. The replace applies to database-id name lines only.
- **Greek person-name file.** `lnc\greek\person_name_changes.lnc` is UTF-16 LE with CRLF. Open, edit, and save keep that encoding. Each rule is `"COMMAND"`, `"GREEK"`, a matched ending, a number, and a replacement. The All lines tab shows the ending and the replacement. These rows are not clubs and do not appear on the entity grid.

Still out of scope: player statistics, form charts, and accounts. This program does not read a player database and it has no user accounts.

## Safety

- The only later features that write outside `C:\FM Name Editor` are Deploy and the licensing toggle, and only to the paths named above, after a backup and a confirmation.
- Do not delete game files. Do not edit disks or folders outside this project and the FM27 `2700` paths named here.
- PySide6 stays the only dependency unless you agree to another package.
- New interface text is British English.
- Game files, `.lnc` copies, and the `backups` folder are never committed when the GitHub repository is created.
