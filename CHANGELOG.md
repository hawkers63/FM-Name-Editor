# Changelog

Release: 2.3
Status: released
Application on disk: 2.3

The program on disk reports `VERSION = "2.3"`. The launcher banner says v2.3.

## Unreleased - Release 2.4 in progress

Not released. `VERSION` still reads 2.3. Release 2.4 is the interface around the workflow: Session 7 (layout, menus, grid, inspector, and grid speed; done) and Session 8 (view state, collections, background work).

Session 7 — layout, menus, grid, and inspector:

- **The window no longer freezes.** With both FM27 files open, opening them took about ten seconds, and so did every Save, Deploy, restore, bulk step, or added field; a cell edit or an undo took two to three seconds. Now opening both files takes well under a second, refreshing the views about a third of a second, a cell edit or an undo under a tenth, adding a field about a third, and a Save, review and write included, about half a second. The tables now sort in the editor itself instead of asking for every cell, size their columns from their text, and are refreshed once instead of several times. Searching and sorting are quicker too.
- **Menus.** File, Edit, View, Packs, Backups, Profiles, and Help hold every action, each with its keys beside it. The long row of thirteen buttons is gone.
- **One row at the top.** The product name, the database folder, the profile with **Record edits** and **Apply...**, **Quick load**, **Undo**, **Redo**, and, at the right-hand end, **Review changes**, which shows how many changes are pending and opens the same review as Save. It fits a 1280 by 820 window with room to spare, so the database is never pushed out of sight. New, Rename, and Delete profile are in the Profiles menu. The counts of clubs, competitions, and unsaved changes are in the status bar.
- **Names get the width.** The grid is sorted by long name. Click a heading to sort by it, again to reverse, and a third time to go back to file-section order; accents and capitals are ignored, and rows with nothing in that column go last. The ID column has moved to the inspector, and the File section column hides while one section is chosen. The long name takes the room that is left; the other columns fit their text. Sorting keeps the selected row selected, and adding a short name or code keeps your place in the list. The All lines table sorts the same way, and its third click goes back to file order.
- **The inspector shows both spellings.** For each field: the text on disk above the proposed text, whether it is unchanged, edited, or added and by which tool (for example "Edited (Bulk tool)"), and the file and line. An empty field reads "No short-name override" or "No code override", says where typing a name would add a line, and the heading shows the ID, file section, and language. Text that cannot be a name (empty, or with a double quote or a line break) stays in the field with the reason beside it, instead of quietly going back; Esc puts back the name in memory. The grid and the All lines table say in the status bar why they did not take a name.
- **Keys.** F2 edits the selected cell (the name, when the row is selected whole), Ctrl+Shift+C goes to the Changes tab, Ctrl+1 and Ctrl+2 to Entities and All lines, Ctrl+H opens Replace, and F1 lists every key. Double-clicking a row on the Changes tab shows its line on All lines, clearing the All lines filters when they would hide it.
- **States in words and colour.** Edited, Added, and Duplicate read as words and in their own colours, in the grids and in the inspector.
- Tests: 116, up from 106. New cover for the reason a name is refused, what the inspector shows for unchanged, edited, added, absent, and repeated fields, the sort orders, the menus and their keys (no key on two actions), the top row at 1280 by 820 with no overflow, the grid's sort and hidden columns, a refused inspector value kept in view, F2, Ctrl+Shift+C, double-clicking a change, and a timing check on copies of both FM27 files: open, refresh, edit, undo, add a field, undo and redo it, and Save, each within a second. One window test changed for the larger Edit menu. Twenty-one single-line breaks of the new rules each fail at least one test.

## 2.3 (11 November 2026)

Shipped in `fm_name_editor.py` and `FM Name Editor.bat`. Your spellings now outlive a write, every write is reviewed in one place, and whole operations can be undone. This is Stage 2 of the review of 2.1 (items A, B, and D), built in sessions 4, 5, and 6.

Session 4 — spelling profiles:

- **Profiles keep your spellings after Save and Deploy.** A profile is a named file of preferred spellings in the local `profiles` folder, with a note. Each spelling keeps the name the file on disk had when you recorded it (its baseline), the file it came from, and that file's SHA-256. Name packs stay as they are, for moving spellings between machines or people.
- **Record edits.** The new Profile controls sit in the row under the toolbar: a profile selector, **Record edits**, **Apply...**, and **Manage** (New, Rename, Delete). Record edits copies the unsaved name edits into the chosen profile, after a confirmation that counts new and replaced spellings. An edit that has already been saved is part of the file on disk, so record before you Save or Deploy; the message says so when there is nothing to record. With no profile chosen, Record edits offers to make one. Person rules are not names and are not recorded.
- **Apply.** Apply shows the profile against the open files in the same preview as a name pack, with the profile's spelling, the baseline it was recorded against, and a note for each row. A row is ticked only when the open file still has that baseline. It is left unticked, with a note, when the game has changed that name since, when the line has an unsaved edit of its own, or when another profile set it earlier in this session. A recorded added line is offered again for the file it came from. Apply changes memory only; Save or Deploy writes it.
- **Profiles are files you can trust.** They are written in one step through the same route as every other file. A damaged or hand-edited profile that cannot be read is named in the status bar and left alone. Delete moves the file into `profiles\deleted`, so it can be recovered by hand. The chosen profile is remembered between runs in `state\settings.json`. Save and Deploy never change a profile.
- **Previews fit their contents.** The pack and profile previews size their columns to the names in them.
- Tests: 80, up from 64. New cover for the profile file round trip, recording with baselines and counts, saved edits not being recorded, Apply with an unchanged, changed, or removed baseline, rows for files that are not open, unsaved edits and competing profiles, Save and Deploy leaving the profile file alone, record–Deploy–update–reopen–Apply, names, file names, rename, delete, unreadable profiles, the local settings file, and window tests for the profile controls. Every test now runs with the backups, profiles, and state folders pointed at a temporary folder, and window tests delete their windows, which brought the suite from 38 to about 4 seconds.

Session 5 — the Changes view and one review before every write:

- **A Changes tab.** Beside Entities and All lines, it lists every difference between the open files and the files on disk: the text on disk, the text to write, its state (Edited, Added, Restored, Removed, or Other lines), the reason (Manual edit, Bulk tool, Replace, Name pack, Older files, Profile with its name, or Restore), the type, ID, language, file, line, and destination. The tab title counts them. A filter narrows the list, ignoring accents.
- **Choose what each write takes.** Every change has an include tick. A change you untick is left out of the next Save or Deploy and stays pending in memory, ready for a later write. Left-out rows are shown greyed. The file on disk then holds exactly its old bytes plus the ticked changes: an unticked added line is not written, nor is the import heading above it, and a last line without an ending keeps it that way. Reverting a line clears its tick, so a later change to it starts ticked.
- **Review changes before Save and Deploy.** Both open the same dialog. It names each file and its destination, says what the write does to it, and names the backup folder the game files go into first. It reports whether Football Manager is running, which files changed on disk since the editor read them, problem lines, and command, ID, and language keys that are on more than one line. The rows carry the same ticks as the Changes tab, so a choice made in one shows in the other. A file changed on disk, a running game, or nothing ticked keeps the write button off, and the dialog says why. When the game check cannot be made, the dialog asks you to tick "I have closed Football Manager" first. The game is checked again when you press Save or Deploy, so a game started while you were reviewing still stops the write.
- **Save into the game folder is Deploy.** The review's title says so: "Save into the game folder, the same as Deploy". There is no quieter route into `lnc\all`.
- **Nothing is rewritten for nothing.** A file whose bytes would not change is not written and gets no backup. A Deploy of files that already hold these bytes now says there is nothing to write. (On 11 November 2026 a Deploy of the unchanged club file rewrote it with the same bytes and made a backup folder; it would now stop there.)
- **Restores stay visible until written.** A backup restored into an open file is listed with the reason Restore, and the status bar shows "Restore pending, not written yet" with the backup's folder until a Save or Deploy writes it. A restored file is written whole, so its rows tick and untick together.
- **Revert works from the Changes tab** on the rows selected there, and Ctrl+F goes to the Changes filter.
- Tests: 96, up from 80. New cover for the four kinds of change row and the "other lines" row, the reason each operation records, rebuilding the disk file from left-out changes in LF, CRLF, UTF-16, and a file without a final line ending, an unticked row staying pending after a write and then being written, a restored file written whole, a file that cannot be split, an external change before and after the review, a Deploy with nothing new, the review's title and checks, ticks shared between the Changes tab and the review, the review at 1280 by 820 with ten changes and no scrolling, an unknown game state, a game started during the review, the footer, and Revert from the Changes tab. A dialog that opens in a test without a stand-in now fails that test instead of hanging the run, and the tests run with the Windows fonts so window sizes match the desktop. Four window tests were changed to go through the review dialog. Fourteen single-line breaks of the new rules each fail at least one test.

Session 6 — undo and redo for whole operations:

- **Undo and Redo.** Ctrl+Z undoes and Ctrl+Y redoes (Ctrl+Shift+Z too). A new Edit menu names the step, for example "Undo bulk: strip affix (14 names)" or "Undo add 3-letter code: ARS".
- **Whole operations, one step each.** A cell edit in the grid, the All lines table, or the inspector; a short name or code added beside its sibling; a bulk tool; Replace; a name pack; older edits; a profile; a backup restored into an open file; and Revert. Each undoes as one step, back to exactly the text in memory before it: an added line goes, along with the import heading it brought and the line ending it gave its neighbour, and a person rule gets both its ending and its replacement back. The reason each line shows in the Changes tab comes back too.
- **Undo goes past Save and Deploy.** A write does not clear the history; it marks the point that was written. Undoing past it makes the files differ from disk again, and the Changes tab says so with the reason "Undo or redo": a line the write added and the undo took out shows as Removed, and the next Save or Deploy takes it out of the file. Opening other files starts a new history.
- **Undo is memory only.** Like every edit, it changes the open files in memory. The files on disk change only when you Save or Deploy, after the review.
- Tests: 106, up from 96. New cover for each kind of operation undone and redone to identical memory (the bytes, every line's text and disk record, reasons, profile marks, the restore state, and the unsaved flag), a person rule's two fields, an insertion after a last line with no ending, the import heading, undo and redo across a write, a restore undone after it was written, operations that change nothing, and window tests for the Edit menu, the shortcuts, an added field, bulk, Revert, a restore, and the clean point after a Save. Fourteen single-line breaks of the undo rules each fail at least one test.

## 2.2 (11 November 2026)

Shipped in `fm_name_editor.py` and `FM Name Editor.bat`. A correctness and write-safety release built from the review of 2.1 (findings F1–F6). It adds no new features beyond what those repairs need; the window looks the same apart from a few labels and the Backups window.

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

Session 3 — correctness and write safety, part three (review finding F6, backup identity, and the backup comparison):

- **Each file is replaced in one step.** Every write goes to a temporary file beside its destination, is flushed to disk, and is swapped in with a single `os.replace`. A failure leaves that file as it was, and the temporary file is removed. Save, Deploy, backup copies, the `.bak` beside an outside file, and pack export all take this route.
- **A file changed on disk is not overwritten.** Before anything is replaced, each file is read again and compared with the bytes the editor read when it opened the file, or last wrote it. If another program changed or removed it, nothing is written, and the message names the file and explains how to carry your edits across. A Deploy over a file that is not the one you opened has nothing to compare with; it is backed up and replaced, as before.
- **A failed write puts the earlier files back.** Save and Deploy replace files one at a time, not as one batch. If a later file cannot be replaced (for example, because another program holds it open), the files already replaced are put back from the copy taken before the write, a newly created file is removed again, and the message lists every file and where it stands. If a file cannot be put back, the message says so and names the backup copy that holds its previous version.
- **Backups describe themselves.** Each backup folder now holds a `manifest.json` recording the operation, the time, the database folder, the editor version, how the operation ended, and for each file its original path, size, SHA-256, encoding, BOM, date, and what happened to it. Two files with the same name get separate copies, and every copy keeps its original's date.
- **The Backups window matches by path.** A backed-up file is compared with, and restored into, the open file it came from, even when another open file has the same name. Backups made before 2.2 have no manifest and are matched by name, as before, and the window says so. Each backup in the list shows its operation, its file count, and any ending other than complete. `manifest.json` itself is not listed.
- **An honest comparison.** The Backups window reports differences in supported names and, separately, whether the files are byte-identical. A changed comment, blank line, or line ending no longer reads as a match.
- **Licensing toggle.** Its backup copy takes the same route and gets a manifest. The rename is one step inside one folder and never replaces a file: when both a name-mask file and its `.disabled` copy exist, the toggle refuses and the inspector shows "Present, and a .disabled copy too".
- Tests: 64, up from 50. New cover for a single-file write that fails, a failed first or second replacement, removal of a newly created file, a file that cannot be put back, files changed or removed on disk, two open files with one destination, manifests for UTF-8 and UTF-16 files, same-name copies, matching by path, the two-part comparison, the licensing rename, and window tests for a failed Deploy, a refused Save, and the Backups window.

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
