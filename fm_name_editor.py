#!/usr/bin/env python3
"""
FM Name Editor v3.6
===================
Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved.
Proprietary and confidential. No copying, distribution, modification,
reverse engineering, sublicensing or commercial use without prior written
consent. See LICENSE.

Browse and edit Football Manager .lnc name files. Clubs and competitions
are shown side by side (long name, short name, code). The line-by-line
table is still there. Edits can be carried across from an older version
by database ID, deployed into the FM27 database, and transformed in bulk.
Release 2.1 added name packs, a backup browser, section-scoped replace,
and the UTF-16 Greek person-name file. Release 2.2 makes every write
safe: one game-write check, checked fields, a disk baseline for unsaved
state, and files replaced one at a time with a way back. Release 2.3
adds spelling profiles that outlive Save and Deploy, a Changes view with
one review before every write, and undo and redo for whole operations.
Release 2.4 builds the window around that work: menus and one header row,
a grid that answers within a second, an inspector with the text on disk
above the proposed text, a remembered view, collections, saved searches,
and slow work on worker threads. Release 2.5 corrects six faults found
in 2.4: licensing looks for the game again after its question, profile
Apply checks every line it would change, and a damaged settings file is
named and left alone. Release 2.6 makes the editor ready to publish:
the copyright in Help > About and the status bar, its own icon, and a
Windows executable built for each release. Release 2.6.1 adds a link to
the public repository in Help > About and the status-bar tooltip.
Release 3.0 begins the update-migration workflow: a profile can carry
its spellings forward when Football Manager releases a new database,
the database selector names the version it is looking at, and a
cross-file override inspector, review hints, and saved Bulk-tools
rules close the release. The application icon is now rendered from
the vector artwork at 16 to 256 pixels.
Release 3.1 finishes the saved Bulk-tools rules and makes a visual
pass: every rule on the Bulk tools dialog is kept, a tick on each
preview row chooses what is applied, and the window gains named
colours, type badges, the remaining keys, a user guide, and the
version in the header.
Release 3.2 adds smart selection and batch renaming: select similar
names, Edit > Selection, Batch rename selected (Ctrl+B) with a ticked
preview applied as one undo step, Tools > Harmonise terminology, and
a command palette (Ctrl+Shift+P).
Release 3.3 adds shared-word selection from a multi-row right-click,
a Batch rename suggestion taken from the selection, and pinned spelling
pairs that Harmonise, Select similar and Ctrl+B all pick up.
Release 3.4 adds an illustrative preview card in the inspector
(table row, scoreboard, and ticker) and per-name restore from a
backup, still only into memory until Save or Deploy.
Release 3.5 adds file pickers that start in the last Open folder or
lnc\all, up to three favourite folders, the ID column on the entity
grid (on by default), and Edit > Add name for an ID the open files
do not mention. Export name pack refuses a path in the game's folders.
Release 3.6 adds a search box that names the section it searches,
a few common club aliases, name-length counters against typical
guides, and faster keyboard moves between rows in the inspector
and along a row in the grid.

Requires:  pip install PySide6
Run:       python fm_name_editor.py [file1.lnc file2.lnc ...]

Design rules
------------
* Lines you do not touch are written back byte-for-byte as they were read.
* Editing a name replaces only the quoted name on that line.
* Bytes are built before any backup. Every file is written to a temporary
  file beside it and swapped in with os.replace, one file at a time. A file
  that changed on disk since it was read is not overwritten. If a later file
  fails, the files already replaced are put back.
* A file inside the game tree is copied into the project's backups folder
  first, with a manifest.json naming where each copy came from. A file
  outside the game tree gets a timestamped .bak beside it instead.
* Save and Deploy show every change first, in Review changes. A change
  left unticked is not written and stays pending in memory; a restored
  backup is written whole.
* UTF-16 files, including the Greek person-name file, are written back
  in the encoding they were opened with.
* Slow work (opening files, reading a backup, the check for a running
  game) runs on a worker thread that touches no widget or model. Writes
  stay on the main thread.
"""
from __future__ import annotations

import contextlib
import csv
import fnmatch
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

APP_NAME = "FM Name Editor"
VERSION = "3.6"

COPYRIGHT_FULL = (
    "Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved.")
COPYRIGHT_NOTE = "Proprietary software, not open source. See LICENSE."
COPYRIGHT_SHORT = "(c) 2026 Mark Hawksworth"
REPOSITORY_URL = "https://github.com/hawkers63/FM-Name-Editor"


def project_root() -> Path:
    """The folder that holds this application's own files.

    Running from source on this PC it is the project folder; when the
    .exe built by build_exe.bat runs, it is the folder that holds the
    .exe, so the backups, profiles, and state folders sit beside the
    exe and the build works wherever it is unpacked.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(r"C:\FM Name Editor")


def resource_path(name: str) -> "Path | None":
    """The path of a file shipped with the application (an icon, say).

    Works from source and from a PyInstaller build. When frozen, it
    looks first under ``sys._MEIPASS`` (where PyInstaller unpacks its
    data) and then beside the exe. Returns ``None`` when nothing has
    the file, so the window still opens without one.
    """
    bases: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bases.append(Path(meipass))
        bases.append(Path(sys.executable).resolve().parent)
    else:
        bases.append(Path(__file__).resolve().parent)
    for base in bases:
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


GAME_DB_ROOT = Path(
    r"D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db")
PROJECT_ROOT = project_root()
BACKUP_ROOT = PROJECT_ROOT / "backups"
PROFILE_ROOT = PROJECT_ROOT / "profiles"
STATE_ROOT = PROJECT_ROOT / "state"
ICON_FILE = "icon/football.ico"
NAME_FILES = ("FM27_Club_Names.lnc", "FM27_Fix.lnc")

# --------------------------------------------------------------------------
# Engine (no GUI code below until the "GUI" marker)
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r'"([^"]*)"|([^\s"]+)')
CMD_RE = re.compile(r"^[A-Z0-9_]+$")
BOM = b"\xef\xbb\xbf"

FRIENDLY = {
    "CLUB_NAME_CHANGE": "Club - long name",
    "CLUB_SHORT_NAME_CHANGE": "Club - short name",
    "CLUB_3LETTER_NAME_CHANGE": "Club - 3-letter code",
    "COMP_LONG_NAME_CHANGE": "Competition - long name",
    "COMP_SHORT_NAME_CHANGE": "Competition - short name",
    "COMP_6LETTER_NAME_CHANGE": "Competition - 6-letter code",
    "STADIUM_NAME_CHANGE": "Stadium",
    "CITY_NAME_CHANGE": "City",
    "AWARD_NAME_CHANGE": "Award",
    "AWARD_LONG_NAME_CHANGE": "Award - long name",
    "AWARD_SHORT_NAME_CHANGE": "Award - short name",
    "NATION_LONG_NAME_CHANGE": "Nation - long name",
    "NATION_SHORT_NAME_CHANGE": "Nation - short name",
    "NATION_3LETTER_NAME_CHANGE": "Nation - 3-letter code",
    "NATIONALITY_NAME_CHANGE": "Nationality",
    "PERSON_FIRST_NAME_END_CHANGE": "Person - first name ending",
    "PERSON_SECOND_NAME_END_CHANGE": "Person - second name ending",
}

# The slate theme's colours, by name (Session 14). The style sheet, the state
# colours in the grids, the include tick, and the type badges all read them
# from here, so a colour is changed in one place. A colour that carries meaning
# always has a word beside it on screen: Edited, Added, Duplicate, a line's type.
THEME = {
    "window": "#13151b",        # window and dialog background
    "panel": "#1a1e28",         # menus, inputs, tables, buttons, the header row
    "stripe": "#161b26",        # alternate table rows
    "rule": "#2a3040",          # borders and grid lines
    "hover": "#232838",
    "text": "#e2e8f0",
    "muted": "#8a94a6",         # secondary text, left-out rows
    "disabled": "#5c6577",
    "accent": "#8b5cf6",        # selection, Review changes, a ticked box
    "accent_hover": "#7c4ff0",
    "on_accent": "#ffffff",     # text on the accent
    "edited": "#a78bfa",        # "Edited": lighter than the accent, so it reads on slate
    "added": "#10b981",         # "Added", and good news
    "warning": "#f59e0b",       # "Duplicate", competing values, refused text
    "problem": "#f87171",       # a name past its typical length guide (Session 20)
    "focus": "#06b6d4",         # keyboard focus, collections
    "focus_text": "#67e8f9",
    # The badge before a line's type, one per family; the type's words sit beside it.
    "badge_club": "#60a5fa",
    "badge_comp": "#f472b6",
    "badge_stadium": "#a3e635",
    "badge_city": "#fb923c",
    "badge_nation": "#f87171",
    "badge_award": "#fde047",
    "badge_person": "#94a3b8",
}
# The state words in the grids, and the theme colour each is drawn in. A
# repeated key is named first, then a name to check, then added, then edited.
STATE_COLOUR_NAMES = {"Duplicate": "warning", "Check": "warning",   # Check: Session 21
                      "Added": "added", "Edited": "edited"}

THEME_QSS = """
QWidget { background-color: $window; color: $text; font-size: 13px; }
QMainWindow, QDialog { background-color: $window; }
QToolBar {
    background: $panel; border: 0; border-bottom: 1px solid $rule;
    spacing: 6px; padding: 4px;
}
QStatusBar { background: $panel; color: $muted; }
QStatusBar QLabel { padding: 0 6px; }
QMenuBar { background: $panel; color: $text; }
QMenuBar::item { background: transparent; padding: 4px 10px; }
QMenuBar::item:selected { background: $rule; }
QToolBar QLabel { background: transparent; color: $muted; padding: 0 2px 0 6px; }
QToolBar QWidget#spacer { background: transparent; }
QToolBar QLabel#product {
    color: $text; font-weight: bold; font-size: 14px; padding: 0 10px 0 4px;
}
QToolBar QToolButton {
    background: transparent; color: $text; border: 1px solid transparent;
    padding: 3px 8px; border-radius: 4px;
}
QToolBar QToolButton:hover { border-color: $rule; background: $hover; }
QToolBar QToolButton:disabled { color: $disabled; }
QToolBar QToolButton#review {
    background: $accent; color: $on_accent; border-color: $accent; font-weight: bold;
}
QToolBar QToolButton#review:hover { background: $accent_hover; }
QToolBar QToolButton#review:disabled {
    background: transparent; color: $disabled; border-color: $rule; font-weight: normal;
}
QLabel#metrics { color: $muted; background: transparent; padding: 2px 6px; }
QLabel#muted { color: $muted; background: transparent; }
QLabel#warning { color: $warning; background: transparent; }
QLabel#problem { color: $problem; background: transparent; }
QLabel#blocked { color: $warning; background: transparent; font-weight: bold; }
QLabel#ok { color: $added; background: transparent; }
QLabel#edited { color: $edited; background: transparent; }
QLabel#added { color: $added; background: transparent; }
QLabel#title { background: transparent; font-weight: bold; font-size: 15px; }
QLabel#raw {
    color: $muted; background: transparent; font-family: Consolas, monospace; font-size: 12px;
}
QPushButton#small { padding: 1px 8px; }
QPushButton:focus, QToolBar QToolButton:focus { border-color: $focus; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus,
QListWidget:focus, QTableView:focus, QTableWidget:focus { border: 1px solid $focus; }
QCheckBox:focus, QRadioButton:focus { color: $focus_text; }
QTabBar::tab:focus { color: $focus_text; }
QLineEdit#invalid { border: 1px solid $warning; }
QFrame#rule { background: $rule; max-height: 1px; border: 0; }
QLabel#heading { background: transparent; font-weight: bold; }
QMenu { background: $panel; color: $text; border: 1px solid $rule; }
QMenu::item { padding: 4px 18px; }
QMenu::item:selected { background: $accent; color: $on_accent; }
QMenu::item:disabled { color: $muted; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTableView, QTableWidget {
    background: $panel; color: $text; border: 1px solid $rule;
    selection-background-color: $accent; selection-color: $on_accent;
}
QHeaderView::section {
    background: $panel; color: $muted; border: 1px solid $rule; padding: 4px;
}
QTableView, QTableWidget {
    alternate-background-color: $stripe; gridline-color: $rule;
}
QPushButton {
    background: $panel; color: $text; border: 1px solid $rule;
    padding: 4px 10px; border-radius: 4px;
}
QPushButton:hover { border-color: $accent; }
QPushButton:checked { background: $accent; color: $on_accent; border-color: $accent; }
QTabBar::tab {
    background: $panel; color: $muted; padding: 6px 14px; border: 1px solid $rule;
}
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QListWidget::item:selected, QTableWidget::item:selected {
    background: $accent; color: $on_accent;
}
QComboBox QAbstractItemView {
    background: $panel; color: $text; selection-background-color: $accent;
}
QSplitter::handle { background: $rule; }
QLabel { background: transparent; }
QCheckBox, QRadioButton { background: transparent; spacing: 6px; }
QFrame#preview_frame { background: $panel; border: 1px solid $rule; border-radius: 4px; }
QLabel#preview_cell { background: transparent; color: $text; padding: 2px 4px; }
QWidget#illustrative_card { background: $panel; border: 1px solid $rule; border-radius: 4px; }
QWidget#illustrative_header { background: transparent; }
QLabel#scoreboard_name { background: transparent; color: $text; }
QLabel#ticker_label { background: transparent; color: $muted; }
"""


def theme_style_sheet(theme=None) -> str:
    """The window's style sheet, with every colour taken from ``theme`` (default THEME)."""
    from string import Template
    return Template(THEME_QSS).substitute(THEME if theme is None else theme)


def state_colour_name(text: str) -> str:
    """The theme colour for a status text, or "" for none: a repeated key first,
    then a name to check, then added, then edited."""
    for word, name in STATE_COLOUR_NAMES.items():
        if word in text:
            return name
    return ""


FILE_SECTION_HINT = (
    "The # comment heading this line sits under in the name file. It is file "
    "structure, not a reliable country. In FM27_Fix.lnc, for instance, the Premier "
    "League lines come before the #England heading, so they sit under the heading "
    "above it.")

# Help > User guide: what the editor does and in what order, in plain words.
USER_GUIDE = (
    ("Open the name files",
     "Quick load opens the two FM27 name files (FM27_Club_Names.lnc and FM27_Fix.lnc) "
     "from the database folder chosen at the top. File > Open files opens any .lnc "
     "files. Its file picker starts in the folder you last opened from, or else in "
     "lnc\\all of the selected database. File > Name files in the selected database "
     "opens the picker in that lnc\\all, and File > Favourite folders keeps up to three "
     "more folders, such as a Steam library on another drive, which the File menu then "
     "lists. Import older edits and the name packs start in the same folder. Opening "
     "runs in the background; the window stays usable."),
    ("Find and edit names",
     "The Entities tab shows one row per club, competition, stadium, city, nation, or "
     "award, with its long name, short name, and code side by side. Choose a family with "
     "the buttons above the grid, narrow it with the search box (Ctrl+F), a file "
     "section, or a collection, and edit a cell with F2 or a double-click. The "
     "inspector on the right (F4 shows or hides it) shows the text on disk above the "
     "proposed text for the selected row, the line as it stands in the file, and an "
     "Illustrative card with table-row, scoreboard and ticker previews of the long, "
     "short and code spellings. The grid shows each row's ID, by which a row is "
     "matched across versions; View > Show ID column hides or shows it, and a click on "
     "its heading sorts by number. The sorted column's heading is bold. All lines lists "
     "every name line and person rule; Changes lists every difference from the files "
     "on disk."),
    ("Search scope and club aliases",
     "While a file section or a collection narrows the grid, the search box says so, "
     "for example In: England (42), and Search all sections (Alt+A, also on the Edit "
     "menu) shows every section again, keeping the words typed. When the words find "
     "nothing in the section but do find rows elsewhere, a line under the search box "
     "says how many; click it to search every section. It only counts: the search is "
     "never widened on its own. When the words find nothing at all, a few common short "
     "names for well-known clubs are tried, among the clubs in the open files only: "
     "Wolves, Spurs, Man Utd, Man City, Barca or Barça, Inter, PSG, BVB, and Juve. The "
     "line then reads Matched via alias, with the word you typed. Words that could mean "
     "many clubs, such as City or United, are not aliases. Accents and capital letters "
     "are ignored, as everywhere in the search."),
    ("Name length guides",
     "Under Long name, Short name, and 3-letter code the inspector counts the letters "
     "against a typical guide: 28 for a long name, 14 for a short name, and 3 for a "
     "code. The count turns amber within two of the guide and red past it; a code is "
     "also flagged when it holds a lower-case letter or is not three characters long. "
     "These are typical guides, not game rules: skins differ, and nothing is blocked, "
     "trimmed, or changed. A name past its guide is kept whole and saved as typed; only "
     "the Illustrative card shows it cut with an ellipsis, as a skin might show it."),
    ("Keyboard moves",
     "In an inspector field, Alt+Down or Shift+Enter keeps what you typed, moves to the "
     "next row shown in the grid, and puts you back in the same field with its text "
     "selected; Alt+Up does the same for the row before. Rows hidden by the search or a "
     "filter are skipped, and the first and last rows stay where they are. Each field "
     "you change is its own Undo step; an unchanged field records nothing. Edit > Copy "
     "long name to short name (Ctrl+Shift+L, also in the command palette) puts the long "
     "name into the Short name field for trimming; nothing changes until you press "
     "Enter. In a grid cell opened with F2, Tab keeps it and opens the next name on the "
     "same row (Shift+Tab the one before), and Enter keeps it and opens the cell below."),
    ("Short name and code from the long name",
     "For a club with no short name or no 3-letter code, the inspector suggests them from "
     "the long name, for example Man Utd and MUN for Manchester United. Club-type words "
     "such as FC or AFC go, a few long words are shortened (United to Utd, and any "
     "spelling pairs you pinned), and words are dropped until the short name fits its "
     "guide of 14; a single long word is never cut. The code is three capital letters A "
     "to Z, from the initials or the first letters, and avoids the codes of the other "
     "clubs in the same file section where it can. The suggestion is shown first: Use "
     "suggestion, or Edit > Fill short name and code (Ctrl+Alt+D), adds only the empty "
     "fields, as one Undo step. A field that has a line is never changed, and nothing is "
     "written until Save or Deploy."),
    ("Name health",
     "The status bar counts the open names with something to check: a space at an end or "
     "two in a row, a non-breaking or zero-width space, typographic punctuation (curly "
     "quotes, a backtick or an accent used as an apostrophe, an em dash), a 3-letter code "
     "in lower case, and a 3-letter code another club uses in the same file section. The "
     "file section stands in for a division, which the files do not record. Click the "
     "count, or choose Name health beside the search box, to list them: their Status "
     "reads Check, and the inspector names each finding. Fix formatting (on the Edit "
     "menu, and in the inspector) tidies the names of the selected rows as one Undo "
     "step: ends trimmed, plain single spaces, straight quotes, a plain dash, and codes "
     "in capitals. A shared code is yours to decide, so it is left alone. These are "
     "checks only: nothing changes until you choose."),
    ("Snapshots",
     "Edit > Create snapshot (Ctrl+Alt+K) keeps the open files' lines as they are now, "
     "under a name you give, in memory only: nothing is written to disk, and snapshots "
     "go when files are opened again. Edit > Roll back to snapshot lists them, newest "
     "first; choosing one puts every open file's lines back as they were then, as one "
     "Undo step, so Undo takes the roll back away again. After a Save or Deploy, a roll "
     "back leaves the differences as unsaved changes to review. Up to ten are kept; "
     "taking another lets the oldest go, and the status bar says which."),
    ("Add a name for an ID",
     "The name files hold spelling overrides, not every club in the game, so a club "
     "that keeps the game's own name has no line to find. Edit > Add name adds lines "
     "for an ID the game already uses: choose the family, type the ID and the long name, "
     "and optionally the short name, the code, and a language (blank means English). "
     "It does not create a club, and the editor does not look IDs up, so check the ID "
     "against this version of the game. When the open files already have that ID, "
     "nothing is added and its row is selected instead. The lines go at the end of the "
     "file under #Imported by FM Name Editor, one Undo takes them all back, and nothing "
     "is written until Save or Deploy."),
    ("Tools change memory only",
     "Bulk tools, Replace, Import older edits, name packs, profile Apply and Migrate, "
     "and restoring a backup change the open files in memory and mark them unsaved. "
     "Each shows a preview first. Bulk tools start from your saved rules (the affix "
     "set, sponsors, small words, casing, scope, and a never-change list); every "
     "preview row has a tick, and only ticked rows are applied. Undo (Ctrl+Z) takes "
     "back a whole operation."),
    ("Select similar names and batch rename",
     "Right-click a name and use Select similar names, or Edit > Selection to select "
     "a word (Ctrl+Shift+W), wildcard or regular expression (Ctrl+Shift+S). Only visible "
     "rows are selected. With two or more rows selected, Select similar names leads "
     "with the words those rows already share, most shared first, with an honest count "
     "of visible and total matches; words that would only reselect the current rows "
     "are left off. Ctrl+B opens Batch rename selected: when the selection has a "
     "shared word, the dialogue states the basis in plain words and fills the preview "
     "with the matching preset (United → Utd and the rest), which you can clear or "
     "change. Short names already in the other form start unticked with a reason. "
     "Choose long names, short names or existing codes, review the live preview and "
     "untick any change to leave it out. Apply is one undo step and writes nothing. "
     "Tools > Harmonise terminology finds mixed club spellings and opens the same "
     "preview for a chosen direction. Ctrl+Shift+P searches commands, saved searches, "
     "collections and name words; F1 still lists keyboard shortcuts."),
    ("Pinned spelling pairs",
     "Beside the built-in pairs (United / Utd, City / Cty, Saint / St. / St and the "
     "rest), pin pairs you actually use (Rovers / Rvrs, Borough / Boro). Pin from "
     "Harmonise or from a Batch rename preview that shows both forms. Once pinned, "
     "Select similar offers \"Also select the other form\" with the same counts, "
     "Harmonise lists the pair under the built-ins with a count for each form, and "
     "the Ctrl+B suggestion may offer the pair from the selection. The editor never "
     "invents a pair, and deleting a pin never renames a club. Pins live in "
     "state\\rules.json with the other Bulk-tools rules; Save and Deploy do not "
     "touch the list."),
    ("Save and Deploy",
     "Only Save (Ctrl+S) and Deploy (Ctrl+Shift+D) write files, and only through "
     "Review changes, where each change has a tick. Unticked changes are left out and "
     "stay pending. A copy of every game file is kept in the backups folder first, "
     "files are replaced one at a time, and nothing is written to the game while "
     "Football Manager is running. Deploy writes the name files into lnc\\all of the "
     "chosen database folder."),
    ("Spelling profiles",
     "A profile keeps your preferred spellings after Save and Deploy. Record edits "
     "before you save; Apply them again when the game's files change; Migrate carries "
     "them forward to a new version of Football Manager, ticking only the spellings "
     "the game has not changed itself."),
    ("Backups and overrides",
     "Backups > Browse and restore compares a backup with the open files and restores "
     "it into memory. The diff table has a Restore checkbox for each name; tick the "
     "names you want and press Restore selected names to restore only those spellings "
     "as one undo step. Whole-file restore is still available. Right-click a row and "
     "choose Show overrides across files to see every line in the database folder that "
     "names the same entity. The editor does not know the game's load order and does "
     "not claim to."),
    ("Where your files live",
     "Backups, spelling profiles, and settings (the remembered view, saved searches, "
     "collections, and the Bulk-tools rules in state\\rules.json) are kept in the "
     "backups, profiles, and state folders beside the program. A damaged settings or "
     "rules file is named in the status bar and left alone."),
)

PACK_FORMAT = "fm-name-pack"
PACK_VERSION = 1
PROFILE_FORMAT = "fm-name-profile"
PROFILE_VERSION = 1
STATE_FILE = "settings.json"
ARCHIVE_FORMAT = "fm-name-editor-archive"
ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
# How an operation recorded in a backup manifest ended.
ARCHIVE_RESULTS = {
    "pending": "outcome not recorded",
    "complete": "complete",
    "stopped": "stopped before any file was replaced",
    "rolled back": "stopped; the files already replaced were put back",
    "partly written": "stopped part-way; some files hold the new version",
}
# What happened to one file, as recorded in a backup manifest.
FILE_OUTCOMES = {
    "written": "written",
    "not written": "not written",
    "failed": "unchanged, because its replacement failed",
    "restored": "put back as it was",
    "removed": "removed again",
    "left written": "left holding the new version",
    "renamed": "renamed",
}
UTF8_BOM = BOM
UTF16_LE_BOM = b"\xff\xfe"
UTF16_BE_BOM = b"\xfe\xff"


def friendly(cmd: str) -> str:
    return FRIENDLY.get(cmd, cmd)


def count_of(number: int, word: str, plural: str = "") -> str:
    """"1 name", "14 names": a count for a menu or a message."""
    if number == 1:
        return f"{number:,} {word}"
    return f"{number:,} {plural or word + 's'}"


def field_is_legal(text: str) -> bool:
    """Return True when text can sit inside one quoted .lnc field.

    Empty is legal: the language field usually is. A double quote would end
    the field early, and an ASCII control character (including CR and LF)
    would split the record on the next load. Tabs are allowed because they
    sit inside the quotes and do not split the line.
    """
    if '"' in text:
        return False
    return all(ord(ch) >= 32 or ch == "\t" for ch in text)


def name_is_legal(new: str) -> bool:
    """Return True when new can be stored as a non-empty quoted name field."""
    return bool(new) and field_is_legal(new)


def name_problem(text: str, noun: str = "name") -> str:
    """Why text cannot be stored as a name, in one sentence; "" when it can.

    It is "" exactly when name_is_legal(text) is true. The window shows the
    sentence beside the field instead of quietly putting the old name back.
    ``noun`` is "name" or "ending" (a person rule's matched ending).
    """
    article = "An" if noun[:1] in "aeiou" else "A"
    if not text:
        return f"{article} {noun} cannot be empty. To take an edit back, use Revert or Undo."
    if '"' in text:
        return (f'{article} {noun} cannot contain a double quote ("): the file would '
                f"read the {noun} as ending there.")
    if not field_is_legal(text):
        return (f"{article} {noun} cannot contain a line break or another control "
                "character: the file would split the line there.")
    return ""


def id_is_legal(id_: str) -> bool:
    """Return True for an ASCII decimal database id such as ``740``."""
    return bool(id_) and id_.isascii() and id_.isdigit()


def is_name_command(cmd: str) -> bool:
    """True for a command the editor treats as a simple quoted-name change."""
    return (
        CMD_RE.match(cmd) is not None
        and cmd.endswith("_NAME_CHANGE")
        and cmd != "CHANGE_PLAYER_NAME"
    )


def build_name_line(cmd: str, id_: str, name: str, lang: str) -> str:
    """Form one name line from its four fields.

    Every field is checked here, so a bad value from a pack or an older
    file cannot write a second record into the output.

    Raises:
        ValueError: a field would break the one-record-per-line format.
    """
    if not is_name_command(cmd):
        raise ValueError(f"Not a name command: {cmd!r}")
    if not id_is_legal(id_):
        raise ValueError(f"Not a database id: {id_!r}")
    if not name_is_legal(name):
        raise ValueError(f"Not a legal name: {name!r}")
    if not field_is_legal(lang):
        raise ValueError(f"Not a legal language: {lang!r}")
    return f'"{cmd}"\t{id_}\t"{name}"\t"{lang}"'


def fold(text: str) -> str:
    """Lower-case and strip accents, for accent-insensitive searching and sorting."""
    if text.isascii():
        return text.lower()     # nothing to strip; the same answer, many times faster
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").casefold()


ROW_KINDS = ("name", "person")

# Which operation last changed a line in memory, as the Changes view words it.
CHANGE_REASONS = {
    "manual": "Manual edit",
    "bulk": "Bulk tool",
    "batch_rename": "Batch rename",
    "replace": "Replace",
    "pack": "Name pack",
    "import": "Older files",
    "profile": "Profile",
    "restore": "Restore",
    "undo": "Undo or redo",
    "suggest": "Suggested",         # Session 21: Fill short name and code
    "tidy": "Fix formatting",       # Session 21
    "snapshot": "Snapshot",         # Session 21: a roll back that crossed a write
}


class Entry:
    """One line of a .lnc file."""

    __slots__ = ("doc", "raw", "eol", "kind", "cmd", "id", "name", "lang",
                 "span", "section", "orig_name", "imported", "lineno", "_fold",
                 "source", "orig_source", "source_span", "profile_mark",
                 "orig_raw", "orig_eol", "reason", "excluded")

    def __init__(self, doc, raw, eol, lineno):
        self.doc = doc
        self.raw = raw          # line text without the line ending
        self.eol = eol          # original line ending, kept as-is
        self.lineno = lineno
        self.kind = "other"     # name | person | comment | blank | other | problem
        self.cmd = self.id = self.name = self.lang = ""
        self.span = None        # (start, end) of the quoted name inside raw
        self.section = ""
        self.orig_name = ""
        self.source = ""        # person-rule ending that is being replaced
        self.orig_source = ""
        self.source_span = None
        self.imported = False
        self._fold = None
        self.profile_mark = None    # (profile name, name it set) after a profile apply
        self.orig_raw = None        # the line's text on disk; None for a line the file lacks
        self.orig_eol = ""          # the line's ending on disk
        self.reason = None          # key of CHANGE_REASONS for the last change in memory
        self.excluded = False       # True leaves this change out of the next Save or Deploy

    @property
    def key(self):
        return (self.cmd, self.id, self.lang.casefold())

    @property
    def changed(self) -> bool:
        return (
            self.imported
            or self.name != self.orig_name
            or self.source != self.orig_source
        )

    def search_text(self) -> str:
        if self._fold is None:
            self._fold = fold(f"{self.name} {self.source} {self.id} {self.section}")
        return self._fold

    def _note_edit(self) -> None:
        self._fold = None
        self.doc.touch()

    def set_name(self, new: str, reason: str | None = "manual"):
        """Replace the quoted name. ``reason`` records which operation did it."""
        _note_line(self)
        start, end = self.span
        self.raw = self.raw[:start] + '"' + new + '"' + self.raw[end:]
        self.span = (start, start + len(new) + 2)
        self.name = new
        self.reason = reason
        self._note_edit()

    def set_source(self, new: str, reason: str | None = "manual"):
        """Replace the quoted ending on a person-name rule.

        The replacement name sits later on the line, so its span moves
        when the ending changes length.
        """
        _note_line(self)
        start, end = self.source_span
        self.raw = self.raw[:start] + '"' + new + '"' + self.raw[end:]
        new_end = start + len(new) + 2
        delta = new_end - end
        self.source_span = (start, new_end)
        if self.span is not None and self.span[0] >= end:
            name_start, name_end = self.span
            self.span = (name_start + delta, name_end + delta)
        self.source = new
        self.reason = reason
        self._note_edit()


def try_set_name(entry: Entry, new: str, reason: str = "manual") -> bool:
    """Rename one line when the text is a single legal field."""
    cleaned = new.strip()
    if not name_is_legal(cleaned) or cleaned == entry.name:
        return False
    entry.set_name(cleaned, reason)
    return True


def try_set_source(entry: Entry, new: str, reason: str = "manual") -> bool:
    """Change the matched ending on a person-name rule."""
    if entry.kind != "person" or entry.source_span is None:
        return False
    cleaned = new.strip()
    if not name_is_legal(cleaned) or cleaned == entry.source:
        return False
    entry.set_source(cleaned, reason)
    return True


def revert_entry(entry: Entry) -> str:
    """Put one name line or person rule back to the text on disk.

    A person rule has two editable fields, the matched ending and the
    replacement. Both are restored. Returns "added" for a row that is not
    in the file on disk (there is nothing to put back), "name" or "rule"
    when text was restored, and "same" when nothing differed. A reverted
    line forgets its reason and its include tick, so a later change to it
    starts ticked.
    """
    if entry.imported:
        return "added"
    restored = False
    if entry.kind == "person" and entry.source != entry.orig_source:
        entry.set_source(entry.orig_source, None)
        restored = True
    if entry.name != entry.orig_name:
        entry.set_name(entry.orig_name, None)
        restored = True
    entry.reason = None
    entry.excluded = False
    if not restored:
        return "same"
    return "rule" if entry.kind == "person" else "name"


def revert_entries(entries) -> dict:
    """Revert each entry. Returns a count for every outcome of revert_entry."""
    counts = {"name": 0, "rule": 0, "added": 0, "same": 0}
    for entry in entries:
        counts[revert_entry(entry)] += 1
    return counts


def line_reason(entry: Entry) -> str:
    """The operation that last changed a line, in words: "Bulk tool", "Profile Mine".

    A profile is named only while the line still holds the name it set.
    """
    key = entry.reason or ""
    if key == "profile":
        mark = entry.profile_mark
        if mark is not None and mark[1] == entry.name:
            return f"Profile {mark[0]}"
    return CHANGE_REASONS.get(key, "")


def entry_status(entry: Entry) -> str:
    """"Added", "Edited", or "": a line's state for the All lines table."""
    if entry.imported:
        return "Added"
    return "Edited" if entry.changed else ""


def is_person_command(cmd: str) -> bool:
    return cmd.startswith("PERSON_") and cmd.endswith("_CHANGE")


def decode_lnc_bytes(data: bytes) -> tuple[str, str, bool]:
    """Return text, encoding name, and whether a BOM was present.

    UTF-16 is recognised only from its BOM. Other files are UTF-8, or
    Windows-1252 when the bytes are not UTF-8.
    """
    if data.startswith(UTF16_LE_BOM):
        return data[2:].decode("utf-16-le"), "utf-16-le", True
    if data.startswith(UTF16_BE_BOM):
        return data[2:].decode("utf-16-be"), "utf-16-be", True
    if data.startswith(UTF8_BOM):
        return data[len(UTF8_BOM):].decode("utf-8"), "utf-8", True
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252", False


def parse_line(entry: Entry):
    text = entry.raw
    stripped = text.strip().lstrip("\ufeff")
    if not stripped:
        entry.kind = "blank"
        return
    if stripped.startswith("#"):
        entry.kind = "comment"
        return
    if not stripped.startswith('"'):
        entry.kind = "other"          # e.g. a stray credit line; passed through
        return
    toks = list(TOKEN_RE.finditer(text))
    leftover = TOKEN_RE.sub("", text).strip()
    if not toks or toks[0].group(1) is None or not CMD_RE.match(toks[0].group(1)):
        entry.kind = "problem"
        return
    cmd = toks[0].group(1)
    entry.cmd = cmd
    if is_person_command(cmd):
        _parse_person(entry, toks, leftover)
        return
    is_name_cmd = cmd.endswith("_NAME_CHANGE") and cmd != "CHANGE_PLAYER_NAME"
    if not is_name_cmd:
        entry.kind = "other"          # player names, FAKE_NATIONAL_TEAM etc.
        return
    if len(toks) >= 2 and toks[1].group(1) == "":
        entry.kind = "other"          # header line: "CLUB_NAME_CHANGE" "" ""
        return
    ok = (
        not leftover
        and len(toks) >= 3
        and toks[1].group(2) is not None and toks[1].group(2).isdigit()
        and all(t.group(1) is not None for t in toks[2:])
        and all(t.group(1) == "" for t in toks[4:])
    )
    if not ok:
        entry.kind = "problem"
        return
    if toks[2].group(1).strip() == "":
        entry.kind = "other"          # deliberately blank name; passed through
        return
    entry.kind = "name"
    entry.id = toks[1].group(2)
    entry.name = entry.orig_name = toks[2].group(1)
    entry.span = toks[2].span()
    entry.lang = toks[3].group(1) if len(toks) > 3 else ""


def _parse_person(entry: Entry, toks, leftover: str) -> None:
    """Parse ``"CMD" "LANG" "ending" number "replacement"``.

    The number stays in ``id`` so the line table can show it. It is not a
    database id, and these rows are kept out of the entity grid.
    """
    ok = (
        not leftover
        and len(toks) == 5
        and toks[1].group(1) is not None
        and toks[2].group(1) is not None and toks[2].group(1).strip() != ""
        and toks[3].group(2) is not None and toks[3].group(2).isdigit()
        and toks[4].group(1) is not None and toks[4].group(1).strip() != ""
    )
    if not ok:
        entry.kind = "problem"
        return
    entry.kind = "person"
    entry.lang = toks[1].group(1)
    entry.source = entry.orig_source = toks[2].group(1)
    entry.source_span = toks[2].span()
    entry.id = toks[3].group(2)
    entry.name = entry.orig_name = toks[4].group(1)
    entry.span = toks[4].span()


def parse_lnc_bytes(doc, data: bytes):
    """Split file bytes into lines and parse each one.

    Returns (entries, encoding, has_bom, default_eol). Nothing else is
    touched, so a file that fails to decode raises before any state changes.
    ``doc`` owns the new entries; pass None to parse a copy for comparison.

    Raises:
        UnicodeError: the bytes are not valid in the encoding they announce.
    """
    text, encoding, has_bom = decode_lnc_bytes(data)
    section = ""
    default_eol = "\r\n" if "\r\n" in text else "\n"
    entries: list[Entry] = []
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        body = line.rstrip("\r\n")
        entry = Entry(doc, body, line[len(body):], n)
        entry.orig_raw, entry.orig_eol = entry.raw, entry.eol
        parse_line(entry)
        if entry.kind == "comment":
            heading = body.strip().lstrip("#").strip().rstrip(":").strip()
            if heading and not set(heading) <= set("=-_*~ "):
                section = heading
        entry.section = section
        entries.append(entry)
    return entries, encoding, has_bom, default_eol


def adopt_disk_originals(entries, on_disk) -> list:
    """Compare restored lines with the lines on disk and set their originals.

    Rows are matched by key, in file order among rows that share a key. A
    matched row takes the disk text as its original (the name and ending,
    and the whole line with its line ending), so it shows as edited when it
    differs. A row with no match is marked added. Returns the disk rows
    that no restored row matched.
    """
    def numbered(rows):
        seen: dict = {}
        for row in rows:
            if row.kind not in ("name", "person"):
                continue
            count = seen.get(row.key, 0)
            seen[row.key] = count + 1
            yield (row.key, count), row

    pool = dict(numbered(on_disk))
    for slot, row in numbered(entries):
        match = pool.pop(slot, None)
        if match is None:
            row.imported = True
        else:
            row.orig_name = match.name
            row.orig_source = match.source
            row.orig_raw = match.raw
            row.orig_eol = match.eol
    return list(pool.values())


class LncDoc:
    """A whole .lnc file, kept line-by-line so it can be written back exactly.

    ``baseline_bytes`` is the file as it is on disk: read at load, replaced
    when a write succeeds. ``dirty`` compares the working lines with it.
    Each line also keeps its own text and ending on disk (``orig_raw`` and
    ``orig_eol``), so a write can take some changes and leave others out,
    see payload_lines.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.entries: list[Entry] = []
        self.has_bom = False
        self.encoding = "utf-8"
        self.default_eol = "\n"
        self.baseline_bytes = b""
        self.removed_rows: list[Entry] = []
        self.restore_pending = False    # the lines came from a backup and are not written yet
        self.restored_from = None       # that backup copy, when known
        self.whole_excluded = False     # a file written whole is left out of the next write
        self.disk_version = 0           # moves on every write, so an undo can tell it crossed one
        self._revision = 0
        self._dirty_stamp = None
        self._dirty_value = False
        self._separable_stamp = None
        self._separable_value = True
        self.load()

    def load(self):
        data = self.path.read_bytes()
        self._read_into(data)
        self.baseline_bytes = data

    def _read_into(self, data: bytes) -> None:
        """Replace the in-memory lines from already-read bytes.

        The path is left as it is. Assignment happens after a successful
        decode, so a bad file does not wipe the lines already loaded.
        """
        entries, encoding, has_bom, default_eol = parse_lnc_bytes(self, data)
        self.encoding = encoding
        self.has_bom = has_bom
        self.default_eol = default_eol
        self.entries = entries
        self.removed_rows = []
        self.restore_pending = False
        self.restored_from = None
        self.whole_excluded = False
        self.touch()

    def encode_text(self, text: str) -> bytes:
        """Encode file text the way this document is stored, BOM included.

        Raises:
            UnicodeEncodeError: the text does not fit self.encoding.
        """
        body = text.encode(self.encoding)
        if self.encoding == "utf-16-le":
            return (UTF16_LE_BOM if self.has_bom else b"") + body
        if self.encoding == "utf-16-be":
            return (UTF16_BE_BOM if self.has_bom else b"") + body
        return (UTF8_BOM if self.has_bom else b"") + body

    def to_bytes(self) -> bytes:
        """Serialise every line, preserving BOM, encoding, and line endings.

        Raises:
            UnicodeEncodeError: the working text does not fit self.encoding.
                Callers should catch this and leave the original file untouched.
        """
        return self.encode_text("".join(entry.raw + entry.eol for entry in self.entries))

    def touch(self) -> None:
        """Note that the working lines changed, so ``dirty`` is worked out again.

        Entry.set_name and Entry.set_source call this. Anything else that
        changes ``entries``, a line's raw text, or a line's ending must too.
        """
        self._revision += 1

    @property
    def dirty(self) -> bool:
        """True when the working lines would write different bytes from the disk file.

        The comparison is with ``baseline_bytes``, so no run of edits and
        reverts can clear it while memory differs from the file. Text that
        cannot be encoded counts as different. The answer is kept until the
        next ``touch``.
        """
        stamp = (self._revision, self.encoding, self.has_bom)
        if stamp != self._dirty_stamp:
            try:
                self._dirty_value = self.to_bytes() != self.baseline_bytes
            except UnicodeError:
                self._dirty_value = True
            self._dirty_stamp = stamp
        return self._dirty_value

    def mark_clean(self, payload: bytes | None = None) -> None:
        """Accept the working lines as what is on disk now.

        Call it after a successful write of the whole working copy, passing
        the bytes that were written. The originals reset, added flags clear,
        reasons and include ticks are forgotten, a pending restore is done,
        and ``payload`` becomes the disk baseline. A write that left some
        changes out settles with settle_written instead.
        """
        if payload is None:
            payload = self.to_bytes()
        for entry in self.entries:
            entry.orig_raw = entry.raw
            entry.orig_eol = entry.eol
            entry.reason = None
            entry.excluded = False
            if entry.kind in ROW_KINDS:
                entry.orig_name = entry.name
                entry.orig_source = entry.source
                entry.imported = False
        self.baseline_bytes = payload
        self.removed_rows = []
        self.restore_pending = False
        self.restored_from = None
        self.whole_excluded = False
        self.disk_version += 1
        self.touch()

    def settle_written(self, lines, payload: bytes) -> None:
        """Accept a write that took only some of the changes.

        ``lines`` is what payload_lines returned for the bytes written. Each
        of those lines now has that text and ending on disk. A change that
        was written as it is in memory is a change no longer; one that was
        left out keeps its original, so it stays pending. An added line that
        was left out is not on disk, so it stays added.
        """
        for entry, text, eol, as_is in lines:
            entry.orig_raw = text
            entry.orig_eol = eol
            if as_is and entry.kind in ROW_KINDS:
                entry.orig_name = entry.name
                entry.orig_source = entry.source
                entry.imported = False
                entry.reason = None
                entry.excluded = False
        self.baseline_bytes = payload
        self.disk_version += 1
        self.touch()

    def rebase(self) -> None:
        """Work out again which working lines are on disk, after an undo or redo crossed a write.

        Name lines and person rules are matched to the disk file the way a
        restore matches them (adopt_disk_originals): by key, in file order.
        A matched line takes the disk text as its original, an unmatched one
        is added, and a disk row that nothing matched is removed. Other lines
        count as on disk when they read the same, in the same order, as the
        disk file's. When anything does not line up, the file's changes are
        written together (see ``separable``).
        """
        on_disk = parse_lnc_bytes(None, self.baseline_bytes)[0] if self.baseline_bytes else []
        for entry in self.entries:
            entry.orig_raw = None
            if entry.kind in ROW_KINDS:
                entry.imported = False
        self.removed_rows = adopt_disk_originals(self.entries, on_disk)
        for entry in self.entries:
            if entry.kind in ROW_KINDS and entry.changed and entry.reason is None:
                entry.reason = "undo"
        mine = [entry for entry in self.entries if entry.kind not in ROW_KINDS]
        theirs = [(entry.raw, entry.eol) for entry in on_disk if entry.kind not in ROW_KINDS]
        if [(entry.raw, entry.eol) for entry in mine] == theirs:
            for entry in mine:
                entry.orig_raw, entry.orig_eol = entry.raw, entry.eol
        self.touch()

    def replace_working(self, data: bytes, source=None) -> None:
        """Make the working lines match ``data`` while the disk baseline stays put.

        Restore uses this; ``source`` is the backup copy, when there is one.
        The bytes are decoded first, so a bad backup changes nothing.
        Restored rows are then compared with the disk file, see
        adopt_disk_originals. Disk rows that the backup lacks are kept in
        ``removed_rows``. The result is pending until a write succeeds, and
        until then its changes are written together (``grouped``): the
        backup's lines have taken the place of the file's own.
        """
        self.apply_working(self.prepare_working(data, source))

    def prepare_working(self, data: bytes, source=None) -> "PreparedLines":
        """The first half of replace_working: parse ``data`` and match it to the disk file.

        Nothing in this document changes, so a worker thread may run it: it
        builds new lines and reads only ``baseline_bytes``, which only a
        write replaces. Raises UnicodeError for bytes that do not decode.
        """
        entries, encoding, has_bom, default_eol = parse_lnc_bytes(self, data)
        for entry in entries:
            entry.orig_raw = None       # where a backup line sits on disk is not known
            if entry.kind in ROW_KINDS:
                entry.reason = "restore"
        removed: list[Entry] = []
        if self.baseline_bytes:
            on_disk = parse_lnc_bytes(None, self.baseline_bytes)[0]
            removed = adopt_disk_originals(entries, on_disk)
        return PreparedLines(entries, encoding, has_bom, default_eol, removed,
                             Path(source) if source is not None else None)

    def apply_working(self, prepared: "PreparedLines") -> None:
        """The second half of replace_working: take the prepared lines. GUI thread only."""
        _note_lines_of(self)
        self.encoding = prepared.encoding
        self.has_bom = prepared.has_bom
        self.default_eol = prepared.default_eol
        self.entries = prepared.entries
        self.removed_rows = prepared.removed
        self.restore_pending = True
        self.restored_from = prepared.source
        self.whole_excluded = False
        self.touch()

    @property
    def separable(self) -> bool:
        """True when each change in this file can be written, or left out, on its own.

        That holds when leaving every change out gives back the file on disk
        exactly, and taking every change gives the working copy exactly. A
        restored backup never qualifies. The answer is kept until the next
        ``touch``.
        """
        if self.restore_pending:
            return False
        stamp = (self._revision, self.encoding, self.has_bom)
        if stamp != self._separable_stamp:
            try:
                none = self.encode_text(lines_text(payload_lines(self, lambda _entry: False)))
                every = self.encode_text(lines_text(payload_lines(self, lambda _entry: True)))
                value = none == self.baseline_bytes and every == self.to_bytes()
            except UnicodeError:
                value = False
            self._separable_stamp = stamp
            self._separable_value = value
        return self._separable_value

    @property
    def grouped(self) -> bool:
        """True when this file's changes can only be written together, as one file."""
        return self.restore_pending or not self.separable

    def save(self, backup: bool = True) -> None:
        """Write this document back to its own path.

        It takes the same route as every other write, see write_documents:
        the bytes are built first, the file must still hold what was read,
        and it is replaced through a temporary file. ``backup`` keeps a
        ``.bak-<date>`` copy beside it. Game files are saved with
        save_documents, which copies them into the project's backups folder
        instead.
        """
        write_documents("Save", [(self, self.path, "beside" if backup else "none")])

    def names(self):
        return [e for e in self.entries if e.kind == "name"]

    def persons(self):
        return [e for e in self.entries if e.kind == "person"]

    def editable(self):
        """Name lines and person-name rules, in file order.

        Person rules stay out of ``names()`` so a pack or an entity view
        cannot treat their number field as a database id.
        """
        return [e for e in self.entries if e.kind in ("name", "person")]

    def problems(self):
        return [e for e in self.entries if e.kind == "problem"]

    def append_entry(self, cmd, id_, name, lang, reason: str = "manual") -> Entry:
        """Add a name line at the end of the file, under an import heading.

        The heading is written only while an added line under it is.

        Raises:
            ValueError: a field is not legal. Nothing is added then.
        """
        raw = build_name_line(cmd, id_, name, lang)
        _note_lines_of(self)
        if self.entries and not self.entries[-1].eol:
            _note_ending(self.entries[-1])
            self.entries[-1].eol = self.default_eol
        marker = "#Imported by FM Name Editor"
        if not any(e.raw.strip() == marker for e in self.entries):
            m = Entry(self, marker, self.default_eol, len(self.entries) + 1)
            m.kind = "comment"
            m.section = "Imported by FM Name Editor"
            self.entries.append(m)
        e = Entry(self, raw, self.default_eol, len(self.entries) + 1)
        parse_line(e)
        e.section = "Imported by FM Name Editor"
        e.imported = True
        e.reason = reason
        self.entries.append(e)
        self.touch()
        return e


class PreparedLines:
    """Lines read for a document by LncDoc.prepare_working, waiting for apply_working."""

    __slots__ = ("entries", "encoding", "has_bom", "default_eol", "removed", "source")

    def __init__(self, entries, encoding, has_bom, default_eol, removed, source):
        self.entries = entries
        self.encoding = encoding
        self.has_bom = has_bom
        self.default_eol = default_eol
        self.removed = removed
        self.source = source


def payload_lines(doc: LncDoc, include) -> list:
    """The lines a write would put on disk: the file as read, plus the included changes.

    ``include(entry)`` is asked about each changed name line or person
    rule. A left-out edit is written as its text on disk, and a left-out
    added line is not written at all. The import heading that append_entry
    puts above added lines is written only when an included added line
    follows it. A line keeps its ending on disk, except that a line which
    had none, as the last line of the file, gets the file's usual ending
    when an included line now follows it.

    Returns a list of (entry, text, ending, as_is), one per line written,
    where ``as_is`` is True when the line is written as it is in memory.
    Use it only for a document whose changes are not grouped (see
    LncDoc.grouped); a restored backup is written whole.
    """
    out: list = []
    held: list = []                         # new lines that are not rows, waiting for a row
    for entry in doc.entries:
        if entry.orig_raw is None:          # a line the file on disk does not have
            if entry.kind in ROW_KINDS:
                if include(entry):
                    out.extend(held)
                    held = []
                    out.append([entry, entry.raw, entry.eol, True])
            else:
                held.append([entry, entry.raw, entry.eol, True])
            continue
        held = []
        if entry.kind in ROW_KINDS and entry.changed and not include(entry):
            out.append([entry, entry.orig_raw, entry.eol, False])
        else:
            out.append([entry, entry.raw, entry.eol, True])
    last = len(out) - 1
    for position, item in enumerate(out):
        entry = item[0]
        if entry.orig_raw is not None and position == last:
            item[2] = entry.orig_eol
        elif not item[2]:
            item[2] = doc.default_eol
    return [tuple(item) for item in out]


def lines_text(lines) -> str:
    """Join what payload_lines returned into file text."""
    return "".join(text + eol for _entry, text, eol, _as_is in lines)


# ---- undo and redo -----------------------------------------------------------

_RECORDING: list = []           # operations being recorded; normally none or one


def _note_line(entry) -> None:
    """Tell any operation being recorded that this line's text is about to change."""
    for operation in _RECORDING:
        operation.note_line(entry)


def _note_lines_of(doc) -> None:
    """Tell any operation being recorded that doc's list of lines is about to change."""
    for operation in _RECORDING:
        operation.note_doc(doc)


def _note_ending(entry) -> None:
    """Tell any operation being recorded that this line's ending is about to change."""
    for operation in _RECORDING:
        operation.note_ending(entry)


def _note_rebase(doc) -> None:
    """Tell any operation being recorded that doc's lines were matched to the disk file
    again, so its undo and redo match them again too (Session 21: a roll back to a
    snapshot taken before a write)."""
    for operation in _RECORDING:
        operation.note_rebase(doc)


def _line_state(entry) -> tuple:
    return (entry.name, entry.source, entry.reason, entry.profile_mark)


def _doc_state(doc) -> tuple:
    return (list(doc.entries), doc.encoding, doc.has_bom, doc.default_eol,
            list(doc.removed_rows), doc.restore_pending, doc.restored_from, doc.whole_excluded)


def _put_line(entry, state) -> None:
    """Give a line the name, ending, reason, and profile mark it had in ``state``.

    A line that is back to its text on disk forgets its include tick, as
    after a revert, so a later change to it starts ticked.
    """
    name, source, reason, mark = state
    if entry.kind == "person" and entry.source != source:
        entry.set_source(source, reason)
    if entry.name != name:
        entry.set_name(name, reason)
    entry.reason = reason
    entry.profile_mark = mark
    if not entry.changed:
        entry.excluded = False
    elif entry.reason is None:
        entry.reason = "undo"       # it differs from disk only because a write came between


def _put_doc(doc, state) -> None:
    """Give a document the list of lines and the restore state it had in ``state``."""
    (entries, doc.encoding, doc.has_bom, doc.default_eol, removed,
     doc.restore_pending, doc.restored_from, doc.whole_excluded) = state
    doc.entries = list(entries)
    doc.removed_rows = list(removed)
    for number, entry in enumerate(doc.entries, 1):
        entry.lineno = number
    doc.touch()


class Operation:
    """One change to the open files that can be undone and redone as a whole.

    Record it by using it as a context manager around the code that makes
    the change. A line whose name or ending is about to change, a line
    ending about to change, and a document whose list of lines is about to
    change are each noted on first touch, and their after-state is taken
    when the block ends; undo() and redo() then move between the two
    exactly. The disk baseline is never part of it: a write in between
    stays written. When an undo or redo swaps the lines of a document that
    was written since, LncDoc.rebase works out again which of them are on
    disk. ``label`` is how the Edit menu names it.
    """

    def __init__(self, label: str):
        self.label = label
        self._lines: dict = {}      # entry -> [before, after]
        self._endings: dict = {}    # entry -> [before, after]
        self._docs: dict = {}       # doc -> [before, after]
        self._versions: dict = {}   # doc -> its disk_version when last applied, undone, or redone
        self._rebase: set = set()   # docs matched to the disk file again whenever it moves

    def __enter__(self) -> "Operation":
        _RECORDING.append(self)
        return self

    def __exit__(self, kind, value, trace) -> bool:
        _RECORDING.remove(self)
        for entry, pair in self._lines.items():
            pair[1] = _line_state(entry)
        for entry, pair in self._endings.items():
            pair[1] = entry.eol
        for doc, pair in self._docs.items():
            pair[1] = _doc_state(doc)
        return False

    def _seen(self, doc) -> None:
        if doc is not None:
            self._versions.setdefault(doc, doc.disk_version)

    def note_line(self, entry) -> None:
        if entry not in self._lines:
            self._lines[entry] = [_line_state(entry), None]
            self._seen(entry.doc)

    def note_ending(self, entry) -> None:
        if entry not in self._endings:
            self._endings[entry] = [entry.eol, None]
            self._seen(entry.doc)

    def note_doc(self, doc) -> None:
        if doc not in self._docs:
            self._docs[doc] = [_doc_state(doc), None]
            self._seen(doc)

    def note_rebase(self, doc) -> None:
        self._rebase.add(doc)
        self._seen(doc)

    @property
    def changed(self) -> bool:
        """True when undoing it would change some text: a name, an ending, or a list of lines.

        A reason or a profile mark on its own does not count; a line that
        was renamed and named back again is not a change.
        """
        return (any(before[:2] != after[:2] for before, after in self._lines.values())
                or any(before != after for before, after in self._endings.values())
                or self.structural)

    @property
    def structural(self) -> bool:
        """True when lines were added, removed, or swapped, not only renamed."""
        return any(before != after for before, after in self._docs.values())

    @property
    def touched_entries(self) -> list:
        """Entries whose name or ending this operation changed, in note order."""
        seen: dict = {}
        for entry in self._lines:
            seen[entry] = None
        for entry in self._endings:
            seen.setdefault(entry, None)
        return list(seen)

    @property
    def docs(self) -> list:
        """The documents it touched."""
        return list(self._versions)

    def undo(self) -> None:
        """Put back every line and document as it was before the change."""
        for entry, (before, _after) in reversed(list(self._lines.items())):
            _put_line(entry, before)
        for entry, (before, _after) in self._endings.items():
            entry.eol = before
        for doc, (before, _after) in self._docs.items():
            _put_doc(doc, before)
        self._settle()

    def redo(self) -> None:
        """Make the change again, exactly as it was made."""
        for doc, (_before, after) in self._docs.items():
            _put_doc(doc, after)
        for entry, (_before, after) in self._endings.items():
            entry.eol = after
        for entry, (_before, after) in self._lines.items():
            _put_line(entry, after)
        self._settle()

    def _settle(self) -> None:
        for doc in self._versions:
            if ((doc in self._docs and doc.disk_version != self._versions[doc])
                    or doc in self._rebase):
                doc.rebase()
            self._versions[doc] = doc.disk_version
            doc.touch()


class LoadError(Exception):
    """A file being opened could not be read or decoded."""

    def __init__(self, path, reason):
        self.path = Path(path)
        self.reason = str(reason)
        super().__init__(f"Could not open {self.path}:\n{self.reason}")


def open_documents(paths) -> list[LncDoc]:
    """Read and parse every path before returning any of them.

    Raises:
        LoadError: a file could not be read or decoded. No documents are
            returned then, so the caller's open files stay as they were.
    """
    staged = []
    for raw in paths:
        try:
            staged.append(LncDoc(raw))
        except (OSError, UnicodeError) as exc:
            raise LoadError(raw, exc) from exc
    return staged


def index(docs) -> dict:
    """key -> Entry. If a key appears more than once, the last one wins."""
    out = {}
    for d in docs:
        for e in d.names():
            out[e.key] = e
    return out


def index_all(docs) -> dict:
    """Map (command, id, language) to every name row with that key.

    Unlike index(), earlier duplicates are kept. The first row in file
    order is first in the list.
    """
    out: dict = {}
    for doc in docs:
        for entry in doc.names():
            out.setdefault(entry.key, []).append(entry)
    return out


class Proposal:
    __slots__ = ("cmd", "id", "lang", "new", "target", "target_rows",
                 "section", "checked", "base", "note", "doc")

    def __init__(self, cmd, id_, lang, new, target, section, checked, base="", note="",
                 target_rows=None, doc=None):
        self.cmd, self.id, self.lang, self.new = cmd, id_, lang, new
        self.base = base          # name in the unedited older original, if known
        self.note = note
        self.target = target      # Entry in the current file, or None if missing
        self.section = section
        self.checked = checked
        self.doc = doc            # file a missing row is added to; None lets pick_doc_for choose
        if target_rows is None:
            self.target_rows = [target] if target is not None else []
        else:
            self.target_rows = list(target_rows)


def build_proposals(target_docs, old_docs, base_docs=None):
    """Compare older files against the loaded files.

    Returns (changes, missing, stats). stats['skipped'] counts older name
    lines that could not be written as one legal line: a blank name, a
    double quote or control character, or an illegal id or language.

    A proposed change is pre-ticked only when an unedited original was
    supplied and the row is a genuine personal edit. Rows noted
    'Renamed since' stay unticked so a stock spelling change is not
    written back by accident.
    """
    tgt_rows = index_all(target_docs)
    old = index(old_docs)
    base = index(base_docs) if base_docs else None
    changes, missing = [], []
    stats = {"old": len(old), "same": 0, "stock": 0, "skipped": 0}
    for key, oe in old.items():
        name = oe.name.strip()
        if not name_is_legal(name) or not id_is_legal(oe.id) or not field_is_legal(oe.lang):
            stats["skipped"] += 1
            continue
        if base is not None and key in base and base[key].name.strip() == name:
            stats["stock"] += 1
            continue
        rows = tgt_rows.get(key, [])
        te = rows[-1] if rows else None
        base_name, note = "", ""
        if base is not None:
            if key in base:
                base_name = base[key].name.strip()
                if te is not None and te.name != base_name:
                    note = "Renamed since"
            else:
                note = "Your addition"
        pre_tick = base is not None and note != "Renamed since"
        if len(rows) > 1:
            extra = f"Duplicate id ({len(rows)} rows)"
            note = f"{note}; {extra}" if note else extra
        if te is None:
            missing.append(Proposal(
                oe.cmd, oe.id, oe.lang, name, None, oe.section, False,
                base_name, note))
        elif all(row.name == name for row in rows):
            stats["same"] += 1
        else:
            changes.append(Proposal(
                oe.cmd, oe.id, oe.lang, name, te, te.section,
                pre_tick, base_name, note, rows))
    return changes, missing, stats


def pick_doc_for(cmd, docs):
    """Choose which loaded file a brand-new entry should be appended to."""
    family = cmd.split("_")[0]
    best, best_n = docs[0], -1
    for d in docs:
        n = sum(1 for e in d.names() if e.cmd.split("_")[0] == family)
        if n > best_n:
            best, best_n = d, n
    return best


def apply_proposals(changes, missing, docs, reason: str = "import"):
    """Write ticked proposals into the loaded documents.

    A change updates every duplicate row, so two lines with the same
    database id cannot drift apart. A name that would break the line is
    left untouched. ``reason`` is recorded on each line changed or added:
    "import" for older files, "pack" for a name pack, "profile" for a
    spelling profile.
    """
    n = 0
    for proposal in changes:
        if not proposal.checked:
            continue
        rows = proposal.target_rows or (
            [proposal.target] if proposal.target is not None else [])
        for target in rows:
            if target is not None and try_set_name(target, proposal.new, reason):
                n += 1
    added = []
    for proposal in missing:
        if not proposal.checked:
            continue
        doc = proposal.doc if proposal.doc is not None else pick_doc_for(proposal.cmd, docs)
        try:
            added.append(doc.append_entry(
                proposal.cmd, proposal.id, proposal.new, proposal.lang, reason))
        except ValueError:
            continue
    return n, added


# --------------------------------------------------------------------------
# Entities, bulk tools, deploy, licensing
# --------------------------------------------------------------------------

# slot key, column label, .lnc command
FAMILY_FIELDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "club": (
        ("long", "Long name", "CLUB_NAME_CHANGE"),
        ("short", "Short name", "CLUB_SHORT_NAME_CHANGE"),
        ("code", "3-letter code", "CLUB_3LETTER_NAME_CHANGE"),
    ),
    "comp": (
        ("long", "Long name", "COMP_LONG_NAME_CHANGE"),
        ("short", "Short name", "COMP_SHORT_NAME_CHANGE"),
        ("code", "6-letter code", "COMP_6LETTER_NAME_CHANGE"),
    ),
    "stadium": (
        ("long", "Name", "STADIUM_NAME_CHANGE"),
    ),
    "city": (
        ("long", "Name", "CITY_NAME_CHANGE"),
    ),
    "nation": (
        ("long", "Long name", "NATION_LONG_NAME_CHANGE"),
        ("short", "Short name", "NATION_SHORT_NAME_CHANGE"),
        ("code", "3-letter code", "NATION_3LETTER_NAME_CHANGE"),
    ),
    "award": (
        ("name", "Name", "AWARD_NAME_CHANGE"),
        ("long", "Long name", "AWARD_LONG_NAME_CHANGE"),
        ("short", "Short name", "AWARD_SHORT_NAME_CHANGE"),
    ),
}

FAMILY_LABELS = {
    "club": "Clubs",
    "comp": "Competitions",
    "stadium": "Stadiums",
    "city": "Cities",
    "nation": "Nations",
    "award": "Awards",
}

CMD_SLOT: dict[str, tuple[str, str]] = {
    cmd: (family, slot)
    for family, fields in FAMILY_FIELDS.items()
    for slot, _label, cmd in fields
}


def badge_family(cmd: str) -> str:
    """The family whose badge a line's type is drawn with: a key of FAMILY_FIELDS,
    "person" for a person rule, or "" for a command with no badge."""
    if cmd in CMD_SLOT:
        return CMD_SLOT[cmd][0]
    if cmd.startswith("PERSON_"):
        return "person"
    return ""

TEXT_SLOTS = {"long", "short", "name"}
AFFIXES = ("FC", "CF", "FK", "SK", "AC", "AS", "AFC", "SC", "Calcio")
SMALL_WORDS = {"of", "the", "and", "de", "da", "di", "van", "von", "y"}
STARTER_SPONSORS = (
    "Sky Bet",
    "Barclays",
    "Carabao",
    "cinch",
    "William Hill",
    "Papa Johns",
    "Enterprise",
    "Vertu",
)

# Session 13: review hints. A local list of suspicious baselines, shown in the
# inspector for the matching key. Hints are shown, never applied: the tool
# flags, the user decides.
REVIEW_HINTS = {
    # (command, id, language): the hint to show
    ("CLUB_NAME_CHANGE", "740", ""): (
        "Hint: the game's own spelling here is 'Wolverhamption', a likely "
        "typo of 'Wolverhampton Wanderers'. This is a note only; the editor "
        "never applies hints automatically."),
}


def review_hint(command: str, id_: str, language: str) -> str:
    """Returns the hint for one key, or "" when there is none.

    A hint is shown in the inspector for the matching entry; it is never
    applied. Keys that are not in ``REVIEW_HINTS`` have no hint.
    """
    return REVIEW_HINTS.get((command, id_, language), "")


# Session 13: cross-file override inspector. A key may be set in several
# ``.lnc`` files under the same database folder; the tool shows the overlap
# and does not claim to know the game's load order (note 05, C).
OVERRIDE_STATES = {
    "reference": "First seen",
    "identical": "Same value",
    "competing": "Different value",
    "unsupported_command": "Unsupported command",
    "malformed": "Could not be read",
}


class Override:
    """One ``.lnc`` line in a database folder that matches a chosen key.

    ``file`` is the path, ``line`` is its 1-based line number, ``command``,
    ``id``, ``language``, ``name`` are the four quoted fields, and ``state``
    is a key of ``OVERRIDE_STATES``. ``reference`` is the first identical
    line seen in the scan; later identical lines share its value, and
    ``competing`` lines carry a different one.
    """

    __slots__ = ("file", "line", "command", "id", "language", "name", "state")

    def __init__(self, file, line, command, id_, language, name, state):
        self.file = file
        self.line = line
        self.command = command
        self.id = id_
        self.language = language
        self.name = name
        self.state = state

MASK_FILES = (
    Path("dbc/permanent/language/Licensing2.dbc"),
    Path("dbc/permanent/language/Licensing2_chn.dbc"),
    Path("dbc/permanent/japan_fake.dbc"),
    Path("edt/permanent/fake.edt"),
)
REPORT_FILES = (
    Path("dbc/permanent/licensing_fm27.dbc"),
    Path("dbc/permanent/license.dbc"),
    Path("dbc/permanent/brazil_kits.dbc"),
    Path("dbc/fv_licensing_changes.dbc"),
    Path("edt/permanent/fm_27_germany_squad_list.ddt"),
    Path("edt/permanent/japan.ddt"),
    Path("edt/permanent/japan_international_players.ddt"),
    Path("edt/permanent/SI_team_holland.ddt"),
)


class NameEntity:
    """One club, competition, or other named thing, grouped by database ID."""

    __slots__ = ("family", "id", "lang", "section", "slots")

    def __init__(self, family: str, id_: str, lang: str):
        self.family = family
        self.id = id_
        self.lang = lang
        self.section = ""
        self.slots: dict[str, list[Entry]] = {}

    def entries(self):
        for group in self.slots.values():
            yield from group

    def name_in(self, slot: str) -> str:
        group = self.slots.get(slot) or []
        return group[0].name if group else ""

    def duplicate(self) -> bool:
        return any(len(group) > 1 for group in self.slots.values())

    def changed(self) -> bool:
        return any(entry.changed for entry in self.entries())

    def missing(self, slot: str) -> bool:
        known = {item[0] for item in FAMILY_FIELDS[self.family]}
        if slot not in known:
            return False
        return not self.slots.get(slot)


def entity_status(entity: NameEntity, health=None) -> str:
    """Short status for the entity grid.

    ``health`` is a name_health result (Session 21): an entity in it reads
    "Check", after a repeated key.
    """
    parts = []
    if entity.duplicate():
        parts.append("Duplicate")
    if health and entity_key(entity) in health:
        parts.append("Check")
    added = any(entry.imported for entry in entity.entries())
    edited = any(entry.changed and not entry.imported for entry in entity.entries())
    if added:
        parts.append("Added")
    if edited:
        parts.append("Edited")
    return ", ".join(parts)


def build_entities(docs) -> list[NameEntity]:
    """Group name lines into entities.

    Clubs, competitions, stadiums, cities, and nations group by ID.
    Awards also keep the language, because one ID can have several.
    A missing short name or code is an empty slot, not a broken line.
    """
    found: dict[tuple, NameEntity] = {}
    for doc in docs:
        for entry in doc.names():
            placed = CMD_SLOT.get(entry.cmd)
            if placed is None:
                continue
            family, slot = placed
            lang = entry.lang if family == "award" else ""
            key = (family, entry.id, lang)
            entity = found.get(key)
            if entity is None:
                entity = NameEntity(family, entry.id, lang)
                found[key] = entity
            entity.slots.setdefault(slot, []).append(entry)
    for entity in found.values():
        for slot, _label, _cmd in FAMILY_FIELDS[entity.family]:
            group = entity.slots.get(slot)
            if group and group[0].section:
                entity.section = group[0].section
                break

    def sort_key(entity: NameEntity):
        try:
            number = int(entity.id)
        except ValueError:
            number = 0
        return (entity.family, fold(entity.section), number, entity.lang)

    return sorted(found.values(), key=sort_key)


# The inspector's heading for one entity: "Club 740".
ENTITY_KINDS = {
    "club": "Club",
    "comp": "Competition",
    "stadium": "Stadium",
    "city": "City",
    "nation": "Nation",
    "award": "Award",
}
# How a field reads in the inspector. A field with no line is "none", and
# reads as no_override_text says: absent is neutral, not missing.
FIELD_STATES = {"same": "Unchanged", "edited": "Edited", "added": "Added"}


def no_override_text(family: str, slot: str) -> str:
    """"No short-name override", "No code override": an empty field, in words."""
    if slot == "code":
        return "No code override"
    for key, label, _cmd in FAMILY_FIELDS[family]:
        if key == slot:
            return f"No {label.lower().replace(' ', '-')} override"
    return "No override"


# ----- Session 20: search scope, club aliases, length guides -----

def entity_shown(entity: NameEntity, words, section: str = "", mode: str = "all",
                 keys=None, alias: str = "", health=None) -> bool:
    """Whether the entity grid shows an entity: the one test the grid's filter
    and the "found elsewhere" count share.

    ``words`` are folded search words; every one must appear in the
    entity's file section, ID, language, or names. With ``alias`` (a club's
    formal name from CLUB_ALIASES) the words are not used: every word of the
    alias must appear in the entity's names instead. ``section`` and
    ``keys`` (a collection's members, or None) are the scope; "" and None
    mean every section. The "health" mode shows the entities in ``health``,
    a name_health result (Session 21).
    """
    if keys is not None and entity_key(entity) not in keys:
        return False
    if section and entity.section != section:
        return False
    if mode == "edited" and not entity.changed():
        return False
    if mode == "missing_short" and not entity.missing("short"):
        return False
    if mode == "missing_code" and not entity.missing("code"):
        return False
    if mode == "health" and not (health and entity_key(entity) in health):
        return False
    names = [entity.name_in(slot) for slot, _label, _cmd in FAMILY_FIELDS[entity.family]]
    if alias:
        hay = fold(" ".join(names))
        return all(word in hay for word in fold(alias).split())
    if words:
        hay = fold(" ".join([entity.section, entity.id, entity.lang, *names]))
        return all(word in hay for word in words)
    return True


def count_shown(entities, words, mode: str = "all", alias: str = "", health=None) -> int:
    """How many entities a search finds in every section, whatever the scope."""
    return sum(1 for entity in entities
               if entity_shown(entity, words, "", mode, None, alias, health))


# Common short names for well-known clubs, each with the formal name it stands
# for. Searched only when the words typed find nothing, and only among the
# clubs in the open files: no network, no game database. Words that could mean
# many clubs ("City", "United") are left out on purpose.
CLUB_ALIASES = {
    "Wolves": "Wolverhampton Wanderers",
    "Spurs": "Tottenham Hotspur",
    "Man Utd": "Manchester United",
    "Man City": "Manchester City",
    "Barca": "Barcelona",
    "Barça": "Barcelona",
    "Inter": "Internazionale",
    "PSG": "Paris Saint-Germain",
    "BVB": "Borussia Dortmund",
    "Juve": "Juventus",
}
_FOLDED_ALIASES = {" ".join(fold(alias).split()): name for alias, name in CLUB_ALIASES.items()}


def alias_for(text: str) -> str:
    """The formal club name an alias stands for, or "" (accents and capitals ignored)."""
    return _FOLDED_ALIASES.get(" ".join(fold(text).split()), "")


def scope_label(scope: str, count: int) -> str:
    """The search box's scope: "In: England (42)"."""
    return f"In: {scope} ({count:,})"


# Typical lengths before a Football Manager skin cuts a name short. They are
# guides, not game rules: skins differ, and the editor never blocks, trims, or
# changes a name for them. Kept here so they are changed in one place.
NAME_LENGTH_GUIDES = {"long": 28, "short": 14, "code": 3}
GUIDE_NEAR = 2                  # the counter turns amber this close to its guide
# A guide applies to the fields with these labels; a competition's 6-letter
# code, and a stadium's or city's single name, have none.
GUIDED_LABELS = {"Long name": "long", "Short name": "short", "3-letter code": "code"}


def length_guide(family: str, slot: str) -> int:
    """The typical length guide for a field, or 0 when it has none."""
    for key, label, _cmd in FAMILY_FIELDS.get(family, ()):
        if key == slot and GUIDED_LABELS.get(label) == slot:
            return NAME_LENGTH_GUIDES[slot]
    return 0


def length_gauge(family: str, slot: str, text: str) -> tuple[str, str, str] | None:
    """The counter under an inspector field: (text, level, tooltip), or None.

    The level is "muted" within the guide, "warning" (amber) within
    GUIDE_NEAR of it, and "problem" past it. A 3-letter code is a problem
    when it holds a lower-case letter or is not three characters long; an
    empty field is an absent override, never a problem. A warning only:
    nothing is blocked, trimmed, or changed.
    """
    guide = length_guide(family, slot)
    if not guide:
        return None
    count = len(text.strip())
    shown = f"{count} / {guide}"
    if slot == "code":
        flags = []
        if text.strip() != text.strip().upper():
            flags.append("lower case")
        if count and count != guide:
            flags.append(f"not {guide} characters")
        tip = (f"Codes are typically {guide} capital letters. Skins differ: this is a "
               "guide, not a game rule, and nothing is changed or blocked.")
        if flags:
            return f"{shown} · {', '.join(flags)}", "problem", tip
        return shown, "muted", tip
    noun = {"long": "long names", "short": "short names"}[slot]
    where = ("on the match scoreboard and in banners" if slot == "long"
             else "in tables and small panels")
    tip = (f"Football Manager skins typically cut {noun} longer than {guide} characters "
           f"{where}. Skins differ: this is a guide, not a game rule, and nothing is "
           "changed or blocked.")
    if count > guide:
        return f"{shown} · over the guide", "problem", tip
    if count >= guide - GUIDE_NEAR:
        return f"{shown} · near the guide", "warning", tip
    return shown, "muted", tip


def cut_to_guide(text: str, guide: int) -> str:
    """A name as a skin might cut it: within ``guide`` characters, ending in an ellipsis.

    Illustrative only. Text within the guide, or a field with no guide (0),
    comes back as it is.
    """
    if not guide or len(text) <= guide:
        return text
    return text[:guide - 1].rstrip() + "…"


# ----- Session 21 (note 09, proposals 3 to 5): short names and codes from a long
# name, name health, and snapshots of the open files kept in memory -----

# Words a club's short name usually leaves out at either end of its long name:
# the club-type letters, and words for the club or the game itself.
SIBLING_AFFIXES = frozenset(fold(word) for word in AFFIXES + (
    "SV", "TSV", "FSV", "VfB", "VfL", "TSG", "SpVgg", "BSC", "CD", "UD", "SD", "RC",
    "RCD", "SS", "SSC", "US", "ACF", "OGC", "AJ", "IF", "BK", "FF",
    "Club", "Clube", "Football", "Fútbol", "Futebol"))
# A long name too long for a short one is cut before the first joining word.
SIBLING_JOINERS = frozenset({"de", "del", "do", "da", "di", "of", "and", "&"})
# Words in front of a place that a short name drops when it needs the room.
SIBLING_DESCRIPTORS = frozenset(fold(word) for word in (
    "Borussia", "Olympique", "Eintracht", "Bayer", "Deportivo", "Racing", "Fortuna"))
# Words a short name shortens when it needs the room, keyed by their folded form.
# A pinned spelling pair (Session 17) is used the same way, and wins.
SIBLING_ABBREVIATIONS = {
    "united": "Utd", "manchester": "Man", "sheffield": "Sheff", "wednesday": "Wed",
    "nottingham": "Nott'm", "monchengladbach": "M'gladbach", "saint": "St.",
}
_NUMBER_WORD = re.compile(r"\d+\.?")


def _is_number(word: str) -> bool:
    return _NUMBER_WORD.fullmatch(word) is not None


def _strip_sibling_ends(words) -> list:
    """Drop club-type words from both ends, and joining words from the end.

    At least one word is kept. A number in front goes with a club-type word
    after it, as in "1. FC Köln".
    """
    words = list(words)
    while len(words) > 1:
        if fold(words[0]) in SIBLING_AFFIXES:
            words.pop(0)
        elif len(words) > 2 and _is_number(words[0]) and fold(words[1]) in SIBLING_AFFIXES:
            words.pop(0)
        else:
            break
    while len(words) > 1 and (fold(words[-1]) in SIBLING_AFFIXES
                              or fold(words[-1]) in SIBLING_JOINERS):
        words.pop()
    return words


def short_name_from(long_name: str, pairs=()) -> str:
    """A short name suggested from a long name, within the short-name guide when it can be.

    The club-type words at either end go first ("AFC Bournemouth" ->
    "Bournemouth", "Real Sociedad de Fútbol" -> "Real Sociedad"). A name
    still too long then loses, in turn and only while it is too long: its
    numbers; long words, by SIBLING_ABBREVIATIONS and the pinned pairs
    (``pairs``, (full, short)); the words from the first joining word on
    ("Club Atlético de Madrid" -> "Atlético"), or the words before it when
    they only describe ("Olympique de Marseille" -> "Marseille"); a
    describing word in front ("Borussia M'gladbach" -> "M'gladbach"); and
    then words from the end. A single word is never cut, so a long one is
    left for the length counter to flag. "" for an empty name.
    """
    guide = NAME_LENGTH_GUIDES["short"]
    words = _strip_sibling_ends(long_name.split())

    def fits(items) -> bool:
        return len(" ".join(items)) <= guide

    if not words or fits(words):
        return " ".join(words)
    kept = [word for word in words if not _is_number(word)]
    if kept and len(kept) < len(words):
        words = _strip_sibling_ends(kept)
    if not fits(words):
        table = dict(SIBLING_ABBREVIATIONS)
        table.update((fold(full), short) for full, short in pairs)
        words = [table.get(fold(word), word) for word in words]
    if not fits(words):
        for number in range(1, len(words)):
            if fold(words[number]) in SIBLING_JOINERS:
                before = _strip_sibling_ends(words[:number])
                after = words[number + 1:]
                if after and all(fold(word) in SIBLING_DESCRIPTORS for word in before):
                    words = _strip_sibling_ends(after)
                else:
                    words = before
                break
    while len(words) > 1 and not fits(words) and fold(words[0]) in SIBLING_DESCRIPTORS:
        words = words[1:]
    while len(words) > 1 and not fits(words):
        words = _strip_sibling_ends(words[:-1])
    return " ".join(words)


def code_candidates(long_name: str) -> list[str]:
    """3-letter codes for a long name, the likeliest first, in capital letters A to Z.

    The words are the long name's after its club-type ends are dropped,
    without joining words or numbers, split at hyphens, accents taken off.
    Three or more words give their initials first ("Queens Park Rangers"
    -> QPR); then come the first three letters ("Arsenal" -> ARS,
    "Newcastle United" -> NEW); the first letter of one word and two of
    the next (MUN), or two and one (MAU); then other letters in order. A
    name with no letters A to Z (in another script, say) has none.
    """
    letters = []
    for word in _strip_sibling_ends(long_name.split()):
        if fold(word) in SIBLING_JOINERS or _is_number(word):
            continue
        for part in word.split("-"):
            text = re.sub(r"[^A-Z]", "", fold(part).upper())
            if text:
                letters.append(text)
    found: list[str] = []

    def add(code: str) -> None:
        if len(code) == 3 and code not in found:
            found.append(code)

    if not letters:
        return found
    if len(letters) >= 3:
        add("".join(word[0] for word in letters[:3]))
    joined = "".join(letters)
    add(joined[:3])
    if len(letters) >= 2:
        add(letters[0][:1] + letters[1][:2])
        add(letters[0][:2] + letters[1][:1])
    for source in (letters[0], joined):
        for second in range(1, len(source)):
            for third in range(second + 1, len(source)):
                add(source[0] + source[second] + source[third])
    return found


def synthesise_siblings(long_name: str, taken_codes=(), pairs=()) -> tuple[str, str]:
    """A suggested short name and 3-letter code for a club's long name.

    The code is the first of code_candidates that no other club in the
    file section uses (``taken_codes``, any case); when every one is taken,
    the first, which Name health then flags. Either may be "" when nothing
    can be suggested. A suggestion only: nothing is changed here.
    """
    taken = {code.strip().upper() for code in taken_codes}
    codes = code_candidates(long_name)
    code = next((item for item in codes if item not in taken), codes[0] if codes else "")
    return short_name_from(long_name, pairs), code


def sibling_suggestion(entity: NameEntity, entities, pairs=()) -> dict:
    """What Fill short name and code would add for a club: {"short": text, "code": text}.

    Only a club with a long name gets one, and only for a field that has no
    line yet: a field with a line is never changed. The code avoids the codes
    of the other clubs in the same file section, when it can. Empty when
    there is nothing to fill.
    """
    if entity.family != "club" or not entity.name_in("long").strip():
        return {}
    empty = [slot for slot in ("short", "code") if not entity.slots.get(slot)]
    if not empty:
        return {}
    taken = [other.name_in("code") for other in entities
             if other.family == "club" and other.section == entity.section
             and other is not entity]
    short, code = synthesise_siblings(entity.name_in("long"), taken, pairs)
    made = {"short": short, "code": code}
    return {slot: made[slot] for slot in empty if name_is_legal(made[slot])}


def fill_siblings(entity: NameEntity, names: dict, reason: str = "suggest") -> int:
    """Add the short name and code in ``names`` as new lines, in memory. Returns lines added.

    A field that already has a line is left alone. Each new line goes just
    after the entity's last line before it in field order (long name, short
    name, code), so the file keeps that order, and takes its file section.
    Record it as one operation.
    """
    added = 0
    for slot in ("short", "code"):
        text = names.get(slot, "").strip()
        if not text or entity.slots.get(slot):
            continue
        anchor = None
        for key, _label, _cmd in FAMILY_FIELDS[entity.family]:
            if key == slot:
                break
            group = entity.slots.get(key)
            if group:
                anchor = group[-1]
        if anchor is None:
            continue
        try:
            created = insert_name_after(anchor, command_for(entity.family, slot), entity.id,
                                        text, entity.lang, reason)
        except ValueError:
            continue
        entity.slots.setdefault(slot, []).append(created)
        added += 1
    return added


# Name health: things in a name that are easy to miss and easy to put right.
# Shown, never applied on their own: Fix formatting puts right the ones it can.
TYPOGRAPHIC_MARKS = {           # each with the plain character Fix formatting uses
    "‘": "'", "’": "'", "´": "'", "`": "'",
    # A straight double quote would end the quoted field, so curly ones become '.
    "“": "'", "”": "'",
    "—": "-",              # em dash
}
INVISIBLE_SPACES = {            # non-breaking and zero-width spaces
    " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
}
LINT_KINDS = {
    "ends": "Space at an end",
    "spaces": "Two spaces in a row",
    "invisible": "Non-breaking or zero-width space",
    "punctuation": "Typographic punctuation",
    "case": "Lower-case code",
    "clash": "Code shared in the file section",
}
# Families whose code is a 3-letter code (a club's, a nation's): the ones whose
# codes are checked for case and shared within a file section.
THREE_LETTER_FAMILIES = frozenset(family for family in FAMILY_FIELDS
                                  if length_guide(family, "code") == 3)


class LintIssue:
    """One name-health finding: ``kind`` (a key of LINT_KINDS), the field ``slot``,
    the sentence the inspector shows, and whether Fix formatting puts it right."""

    __slots__ = ("kind", "slot", "text", "fixable")

    def __init__(self, kind: str, slot: str, text: str, fixable: bool = True):
        self.kind = kind
        self.slot = slot
        self.text = text
        self.fixable = fixable

    def __repr__(self) -> str:
        return f"LintIssue({self.kind!r}, {self.slot!r}, {self.text!r})"


def _unusual(text: str) -> bool:
    return "`" in text or not text.isascii()


def name_findings(text: str, label: str, slot: str, code: bool = False) -> list[LintIssue]:
    """The formatting findings for one name; ``code`` checks a 3-letter code's case too."""
    found = []
    lead, trail = text[:1].isspace(), text[-1:].isspace()
    if lead or trail:
        where = "both ends" if lead and trail else "the start" if lead else "the end"
        found.append(LintIssue("ends", slot, f"{label} has a space at {where}."))
    if "  " in text:
        found.append(LintIssue("spaces", slot, f"{label} has two spaces in a row."))
    if _unusual(text):
        if any(ch in INVISIBLE_SPACES for ch in text):
            found.append(LintIssue(
                "invisible", slot, f"{label} has a non-breaking or zero-width space."))
        marks = "".join(dict.fromkeys(ch for ch in text if ch in TYPOGRAPHIC_MARKS))
        if marks:
            found.append(LintIssue(
                "punctuation", slot,
                f"{label} has typographic punctuation ({' '.join(marks)})."))
    if code and text != text.upper():
        found.append(LintIssue("case", slot, f"{label} has lower-case letters."))
    return found


def _shared_code(entity: NameEntity) -> str:
    """The 3-letter code compared with the file section's other codes, or ""."""
    if entity.family not in THREE_LETTER_FAMILIES:
        return ""
    return entity.name_in("code").strip().upper()


def _clash_issue(entity: NameEntity, code: str, others) -> LintIssue:
    label = next(label for key, label, _cmd in FAMILY_FIELDS[entity.family] if key == "code")
    names = [other.name_in("long") or f"ID {other.id}" for other in others]
    if len(names) == 1:
        who = names[0]
    elif len(names) == 2:
        who = f"{names[0]} and {names[1]}"
    else:
        kind = ENTITY_KINDS[entity.family].lower()
        who = f"{len(names)} other {kind}s, including {names[0]} and {names[1]}"
    return LintIssue("clash", "code",
                     f"{label} {code} is also used by {who} in this file section.", False)


# Each family's fields as name health reads them: (slot, label, checked as a code).
_HEALTH_FIELDS = {family: tuple((slot, label, family in THREE_LETTER_FAMILIES and slot == "code")
                                for slot, label, _cmd in fields)
                  for family, fields in FAMILY_FIELDS.items()}


def _looks_tidy(text: str, code: bool) -> bool:
    """A quick test that a name has nothing for name_findings to say (most names)."""
    return (text.isascii() and "`" not in text and "  " not in text
            and not text[:1].isspace() and not text[-1:].isspace()
            and not (code and text != text.upper()))


def _format_findings(entity: NameEntity) -> list[LintIssue]:
    found = []
    slots = entity.slots
    for slot, label, code in _HEALTH_FIELDS[entity.family]:
        group = slots.get(slot)
        if not group:
            continue
        seen = set()
        for entry in group:
            text = entry.name
            if text not in seen and not _looks_tidy(text, code):
                seen.add(text)
                found.extend(name_findings(text, label, slot, code))
    return found


def lint_entity(entity: NameEntity, section_entities=()) -> list[LintIssue]:
    """Name health for one entity: spaces at the ends or doubled, non-breaking or
    zero-width spaces, typographic punctuation (curly quotes, a backtick or an
    accent as an apostrophe, an em dash), a 3-letter code in lower case, and a
    3-letter code another club (or nation) in ``section_entities`` shares in the
    same file section. A file section stands in for a division: the files do
    not say which division a club plays in.
    """
    found = _format_findings(entity)
    code = _shared_code(entity)
    if code:
        others = [other for other in section_entities
                  if other is not entity and other.family == entity.family
                  and other.section == entity.section and _shared_code(other) == code]
        if others:
            found.append(_clash_issue(entity, code, others))
    return found


def name_health(entities) -> dict:
    """lint_entity for every entity at once: {entity_key: [LintIssue, ...]}, issues only.

    The shared codes are grouped in one pass, so the whole of both FM27
    files is checked in a few tens of milliseconds.
    """
    entities = list(entities)
    codes = [_shared_code(entity) for entity in entities]
    groups: dict[tuple, list] = {}
    for entity, code in zip(entities, codes):
        if code:
            groups.setdefault((entity.family, entity.section, code), []).append(entity)
    found = {}
    for entity, code in zip(entities, codes):
        issues = _format_findings(entity)
        if code:
            group = groups[(entity.family, entity.section, code)]
            if len(group) > 1:
                issues.append(_clash_issue(entity, code,
                                           [other for other in group if other is not entity]))
        if issues:
            found[entity_key(entity)] = issues
    return found


def health_summary(health: dict) -> tuple[int, int]:
    """(entities Fix formatting can help, entities sharing a code) in a name_health result."""
    fixable = sum(1 for issues in health.values() if any(issue.fixable for issue in issues))
    shared = sum(1 for issues in health.values() if any(issue.kind == "clash" for issue in issues))
    return fixable, shared


def tidy_name(text: str, code: bool = False) -> str:
    """A name as Fix formatting leaves it.

    Non-breaking spaces become plain ones and zero-width ones go; curly
    quotes, a backtick or an accent used as an apostrophe become ' and an
    em dash becomes -; spaces in a row become one, and the ends are
    trimmed. ``code`` also puts a 3-letter code in capitals.
    """
    if _unusual(text):
        text = "".join(INVISIBLE_SPACES.get(ch, TYPOGRAPHIC_MARKS.get(ch, ch)) for ch in text)
    text = re.sub(" {2,}", " ", text).strip()
    return text.upper() if code else text


def fix_formatting(entities, reason: str = "tidy") -> int:
    """Fix formatting in memory for these entities' names. Returns the lines changed.

    Only the quoted name of a line changes (tidy_name). A shared code is not
    a formatting fault, so it is left for you to decide. Record it as one
    operation.
    """
    changed = 0
    for entity in entities:
        code_family = entity.family in THREE_LETTER_FAMILIES
        for slot, _label, _cmd in FAMILY_FIELDS[entity.family]:
            for entry in entity.slots.get(slot) or ():
                tidy = tidy_name(entry.name, code_family and slot == "code")
                if tidy != entry.name and name_is_legal(tidy):
                    entry.set_name(tidy, reason)
                    changed += 1
    return changed


# Snapshots: the open files' working lines at one moment, kept in memory only.
SNAPSHOT_LIMIT = 10             # the oldest is let go when an eleventh is taken


class Snapshot:
    """The working lines of the open files as they were at one moment.

    For each document: its state (the lines, encoding, ending, and restore
    flags), each line's name, reason, profile mark and ending, and the disk
    version then. Nothing is written to disk; a snapshot lasts until the
    files are opened again.
    """

    __slots__ = ("label", "taken", "states")

    def __init__(self, label: str, taken: datetime, states: dict):
        self.label = label
        self.taken = taken
        self.states = states


def take_snapshot(docs, label: str, taken: datetime | None = None) -> Snapshot:
    """Keep the open files' working lines, in memory, under ``label``."""
    states = {doc: (_doc_state(doc),
                    [(entry, _line_state(entry), entry.eol) for entry in doc.entries],
                    doc.disk_version)
              for doc in docs}
    return Snapshot(label, taken or datetime.now(), states)


def roll_back_to(snapshot: Snapshot) -> list:
    """Put the working lines back as they were when ``snapshot`` was taken. Returns the lines changed.

    Run it inside an Operation, so one Undo takes the roll back away. Only
    lines that differ are touched. The disk baseline stays put: where a
    write came between, the lines are matched to the disk file again
    (LncDoc.rebase), so a line that differs from the file now is a pending
    change. A line put back to its text on disk forgets its include tick.
    """
    touched = []
    for doc, (doc_state, lines, version) in snapshot.states.items():
        if _doc_state(doc) != doc_state:
            _note_lines_of(doc)
            _put_doc(doc, doc_state)
        for entry, state, eol in lines:
            if entry.eol != eol:
                _note_ending(entry)
                entry.eol = eol
                touched.append(entry)
            if _line_state(entry) != state:
                _note_line(entry)
                name, source, reason, mark = state
                if entry.kind == "person" and entry.source != source:
                    entry.set_source(source, reason)
                if entry.name != name:
                    entry.set_name(name, reason)
                entry.reason, entry.profile_mark = reason, mark
                touched.append(entry)
        if doc.disk_version != version:
            _note_rebase(doc)
            doc.rebase()
        mine = set(touched)
        for entry, _state, _eol in lines:
            if entry.kind not in ROW_KINDS:
                continue
            if not entry.changed:
                entry.excluded = False
            elif entry.reason in (None, "undo") and entry in mine:
                entry.reason = "snapshot"
        doc.touch()
    return list(dict.fromkeys(touched))


def describe_lines(entries) -> str:
    """Where lines sit in memory: "FM27_Club_Names.lnc, line 1034", or several."""
    by_file: dict[str, list[int]] = {}
    for entry in entries:
        by_file.setdefault(entry.doc.path.name, []).append(entry.lineno)
    parts = []
    for name, numbers in by_file.items():
        if len(numbers) == 1:
            parts.append(f"{name}, line {numbers[0]}")
        else:
            listed = ", ".join(str(number) for number in numbers[:-1])
            parts.append(f"{name}, lines {listed} and {numbers[-1]}")
    return "; ".join(parts)


class FieldView:
    """One field of an entity as the inspector shows it.

    ``state`` is a key of FIELD_STATES, or "none" when the open files have
    no line for the field. ``on_disk`` is the text in the file on disk, or
    None when the file has no such line yet. ``current`` is the text in
    memory, ``reason`` the operation that changed it, ``where`` the file and
    line (or, for an empty field, where typing a name would add one), and
    ``count`` the number of lines that carry the field. ``hint`` is any
    review-hint note the field carries (empty for most fields; Session 13).
    ``raw`` is the first line's text in memory, without its ending (Session 14).
    """

    __slots__ = ("slot", "label", "state", "current", "on_disk", "reason",
                 "where", "count", "hint", "raw")

    def __init__(self, slot: str, label: str):
        self.slot = slot
        self.label = label
        self.state = "none"
        self.current = ""
        self.on_disk = None
        self.reason = ""
        self.where = ""
        self.count = 0
        self.hint = ""
        self.raw = ""

    @property
    def marker(self) -> str:
        """The field-level change marker, in text: "Edited (Bulk tool)", "Added"."""
        text = FIELD_STATES.get(self.state, "")
        if self.reason:
            text += f" ({self.reason})"
        if self.count > 1:
            text += f", on {self.count} lines"
        return text


def describe_fields(entity: NameEntity) -> list[FieldView]:
    """Each field of an entity, with its text on disk and in memory, for the inspector.

    A field on several lines (a repeated key) is described from its first
    line, as the grid shows it, and ``where`` names every line.
    """
    anchor = next(entity.entries(), None)
    views = []
    for slot, label, _cmd in FAMILY_FIELDS[entity.family]:
        view = FieldView(slot, label)
        group = entity.slots.get(slot) or []
        if not group:
            if anchor is not None:
                view.where = (f"Typing a name adds a line after line {anchor.lineno} "
                              f"of {anchor.doc.path.name}.")
            views.append(view)
            continue
        first = group[0]
        view.current = first.name
        view.raw = first.raw
        view.count = len(group)
        view.where = describe_lines(group)
        if first.imported:
            view.state = "added"
        elif first.changed:
            view.state, view.on_disk = "edited", first.orig_name
        else:
            view.state, view.on_disk = "same", first.name
        if view.state != "same":
            view.reason = line_reason(first)
        view.hint = review_hint(first.cmd, first.id, first.lang)
        views.append(view)
    return views


def _id_number(id_: str) -> int:
    return int(id_) if id_.isascii() and id_.isdigit() else -1


def entity_text(entity: NameEntity, key: str, health=None) -> str:
    """The text of one entity-grid column: "section", "id", "lang", "status", or a field.

    ``health`` (a name_health result) adds "Check" to the status.
    """
    if key == "section":
        return entity.section
    if key == "id":
        return entity.id
    if key == "lang":
        return entity.lang
    if key == "status":
        return entity_status(entity, health)
    return entity.name_in(key)


def entry_text(entry: Entry, key: str) -> str:
    """The text of one All lines column: "section", "type", "id", "name", "lang", "file", "status"."""
    if key == "section":
        return entry.source if entry.kind == "person" else entry.section
    if key == "type":
        return friendly(entry.cmd)
    if key == "id":
        return entry.id
    if key == "name":
        return entry.name
    if key == "lang":
        return entry.lang
    if key == "file":
        return entry.doc.path.name
    if key == "status":
        return entry_status(entry)
    return ""


def _sorted_by_text(rows, text_of, key: str, descending: bool) -> list:
    """Sort rows by one column. IDs go by number; text ignores accents and capitals.

    Rows with nothing in a text column go last in either direction, so a
    sort by short name does not open on a page of empty cells. So do rows
    whose ID is empty or not a number when the IDs are sorted (Session
    19). Ties keep the order the rows came in. An empty ``key`` keeps that
    order too.
    """
    rows = list(rows)
    if not key:
        return rows
    if key == "id":
        numbered = [(_id_number(text_of(row, "id")), row) for row in rows]
        known = [pair for pair in numbered if pair[0] >= 0]
        known.sort(key=lambda pair: pair[0], reverse=descending)
        return [row for _number, row in known] + [row for number, row in numbered if number < 0]
    keyed = [(fold(text_of(row, key)), row) for row in rows]
    filled = [pair for pair in keyed if pair[0]]
    filled.sort(key=lambda pair: pair[0], reverse=descending)
    return [row for _text, row in filled] + [row for text, row in keyed if not text]


def sort_entities(entities, key: str, descending: bool = False, health=None) -> list:
    """Entities in grid order for one column (see _sorted_by_text). The default is the long name.

    Pass the entities in build_entities order (file section, then ID), so
    ties and an empty ``key`` follow it. ``health`` sorts the status with
    its "Check" (Session 21).
    """
    if health:
        return _sorted_by_text(entities, lambda entity, column: entity_text(
            entity, column, health), key, descending)
    return _sorted_by_text(entities, entity_text, key, descending)


def sort_entries(entries, key: str, descending: bool = False) -> list:
    """Name lines in table order for one column (see _sorted_by_text). The default is file order."""
    return _sorted_by_text(entries, entry_text, key, descending)


def command_for(family: str, slot: str) -> str:
    for slot_key, _label, cmd in FAMILY_FIELDS[family]:
        if slot_key == slot:
            return cmd
    raise KeyError((family, slot))


def insert_name_after(anchor: Entry, cmd: str, id_: str, name: str, lang: str,
                      reason: str = "manual") -> Entry:
    """Insert a new name line just after a sibling, keeping its section.

    A sibling that is the last line of a file may have no line ending. It
    gets the document's usual ending first, so the two commands do not run
    together on one line.

    Raises:
        ValueError: a field is not legal. Nothing is inserted then.
    """
    doc = anchor.doc
    raw = build_name_line(cmd, id_, name, lang)
    entry = Entry(doc, raw, doc.default_eol, anchor.lineno + 1)
    parse_line(entry)
    if entry.kind != "name":
        raise ValueError(f"Could not form a name line for {cmd}")
    _note_lines_of(doc)
    if not anchor.eol:
        _note_ending(anchor)
        anchor.eol = doc.default_eol
    entry.section = anchor.section
    entry.imported = True
    entry.reason = reason
    index_at = doc.entries.index(anchor) + 1
    doc.entries.insert(index_at, entry)
    for number, item in enumerate(doc.entries, 1):
        item.lineno = number
    doc.touch()
    return entry


def set_entity_field(entity: NameEntity, slot: str, new: str, docs,
                     reason: str = "manual") -> bool:
    """Write one cell. Existing lines are all updated. An empty cell adds a line.

    Duplicate lines that share the command and ID are all set to the same
    text, and the entity stays marked Duplicate so the extra line is visible.
    """
    cleaned = new.strip()
    if not name_is_legal(cleaned):
        return False
    group = list(entity.slots.get(slot) or [])
    if group:
        if all(entry.name == cleaned for entry in group):
            return False
        changed = False
        for entry in group:
            if try_set_name(entry, cleaned, reason):
                changed = True
        return changed
    cmd = command_for(entity.family, slot)
    anchor = next(entity.entries(), None)
    try:
        if anchor is not None:
            created = insert_name_after(anchor, cmd, entity.id, cleaned, entity.lang, reason)
        else:
            created = pick_doc_for(cmd, docs).append_entry(
                cmd, entity.id, cleaned, entity.lang, reason)
            created.section = entity.section
    except ValueError:
        return False
    entity.slots.setdefault(slot, []).append(created)
    return True


# ---- Edit > Add name: lines for an ID the open files do not mention (Session 19) ----

def find_entity(entities, family: str, id_: str):
    """The first entity of ``family`` with this database ID, in any language, or None.

    IDs compare by number, so 0740 finds 740: the game reads both as one
    record. An ID that is not digits finds nothing.
    """
    number = _id_number(id_)
    if number < 0:
        return None
    return next((entity for entity in entities
                 if entity.family == family and _id_number(entity.id) == number), None)


def add_name_problem(family: str, id_: str, names: dict, lang: str) -> str:
    """Why Edit > Add name cannot add these lines, in one sentence; "" when it can.

    ``names`` maps the family's field keys (see FAMILY_FIELDS) to the text
    typed. The ID is digits only. The family's first field (a club's long
    name) must be filled; the others are optional. Every name, and the
    language, must fit one quoted field. A blank language is English.
    """
    if family not in FAMILY_FIELDS:
        return "Choose what the name is for: a club, a competition, and so on."
    id_ = id_.strip()
    if not id_:
        return "Type the ID the game already uses for it. The editor does not look IDs up."
    if not id_is_legal(id_):
        return "An ID is digits only, such as 740."
    fields = FAMILY_FIELDS[family]
    first_slot, first_label, _cmd = fields[0]
    if not names.get(first_slot, "").strip():
        kind = ENTITY_KINDS[family].lower()
        article = "An" if kind[:1] in "aeiou" else "A"
        return f"{article} {kind} needs a {first_label.lower()}."
    for slot, label, _cmd in fields:
        text = names.get(slot, "").strip()
        problem = name_problem(text) if text else ""
        if problem:
            return f"{label}: {problem}"
    if not field_is_legal(lang.strip()):
        return 'A language cannot contain a double quote (") or a line break.'
    return ""


def add_entity_lines(docs, family: str, id_: str, names: dict, lang: str,
                     reason: str = "manual") -> list:
    """Add the name lines of an ID the open files do not mention yet, in memory.

    Every line goes at the end of one file, the one pick_doc_for chooses
    for the family's first command, under "#Imported by FM Name Editor"
    (LncDoc.append_entry), in the family's field order. An empty field
    adds no line. The ID is written without leading zeros. Check
    add_name_problem and find_entity first. Nothing is written to disk.

    Raises:
        ValueError: a field is not legal. Nothing is added then.
    """
    fields = FAMILY_FIELDS[family]
    number = str(int(id_.strip()))
    lang = lang.strip()
    lines = [(cmd, names.get(slot, "").strip()) for slot, _label, cmd in fields]
    lines = [(cmd, text) for cmd, text in lines if text]
    for cmd, text in lines:
        build_name_line(cmd, number, text, lang)    # every line is checked before one is added
    doc = pick_doc_for(fields[0][2], docs)
    return [doc.append_entry(cmd, number, text, lang, reason) for cmd, text in lines]


def strip_affix(name: str, affixes=AFFIXES) -> str:
    """Remove one leading and one trailing affix token. A lone token is kept."""
    tokens = name.split(" ")
    folded = {item.casefold() for item in affixes}
    changed = False
    if len(tokens) > 1 and tokens[0].casefold() in folded:
        tokens = tokens[1:]
        changed = True
    if len(tokens) > 1 and tokens[-1].casefold() in folded:
        tokens = tokens[:-1]
        changed = True
    if not changed:
        return name
    return " ".join(tokens).strip()


def _cap_token(token: str) -> str:
    parts = re.split(r"([-'’])", token)
    out = []
    for part in parts:
        if part in "-'’":
            out.append(part)
        elif part:
            out.append(part[:1].upper() + part[1:].lower())
    return "".join(out)


WORD_CASE_LENGTH = 4    # in "words" casing, an all-capital word this long is re-cased


def title_case_name(name: str, small_words=None, mode: str = "capitals") -> str:
    """Title-case a name that is entirely capitals.

    ``small_words`` (default ``SMALL_WORDS``) stay lower case after the first
    word. With ``mode="words"``, a name that mixes cases also has each word of
    four or more letters written wholly in capitals re-cased, so "Club ATLETICO
    Madrid" is fixed while "FC", "AFC", and "USA" stay as they are. Any other
    name is returned unchanged.
    """
    small = {word.casefold() for word in (SMALL_WORDS if small_words is None else small_words)}
    letters = [ch for ch in name if ch.isalpha()]
    if not letters:
        return name
    words = name.split(" ")
    if all(ch.isupper() for ch in letters):
        cased = []
        for index, word in enumerate(words):
            bare = word.casefold().strip(".'’")
            if index > 0 and bare in small:
                cased.append(word.lower())
            else:
                cased.append(_cap_token(word))
        return " ".join(cased)
    if mode != "words":
        return name
    cased = []
    for word in words:
        letters_in = [ch for ch in word if ch.isalpha()]
        if len(letters_in) >= WORD_CASE_LENGTH and all(ch.isupper() for ch in letters_in):
            cased.append(_cap_token(word))
        else:
            cased.append(word)
    return " ".join(cased)


def strip_sponsor(name: str, sponsors: list[str]) -> str:
    """Remove a sponsor phrase from the start or the end of a competition name."""
    result = name.strip()
    ordered = sorted(
        {item.strip() for item in sponsors if item.strip()},
        key=len,
        reverse=True,
    )
    for sponsor in ordered:
        folded = result.casefold()
        if folded.startswith(sponsor.casefold() + " "):
            result = result[len(sponsor):].strip()
        elif folded.endswith(" " + sponsor.casefold()):
            result = result[: -len(sponsor)].strip()
    if not result:
        return name
    return result


class BulkEdit:
    """One preview row. Nothing is written until apply_bulk.

    ``included`` is the row's tick: apply_bulk changes only included rows.
    """

    __slots__ = ("entity", "slot", "entry", "before", "after", "included", "reason")

    def __init__(self, entity: NameEntity, slot: str, entry: Entry, before: str, after: str):
        self.entity = entity
        self.slot = slot
        self.entry = entry
        self.before = before
        self.after = after
        self.included = True
        self.reason = ""            # auto-untick note, shown as a row tooltip


def _transform_name(kind: str, before: str, sponsors: list[str], rules: "Rules | None" = None) -> str:
    if kind == "affix":
        return strip_affix(before, rules.affixes if rules is not None else AFFIXES)
    if kind == "sponsor":
        return strip_sponsor(before, sponsors)
    if kind == "title":
        if rules is None:
            return title_case_name(before)
        return title_case_name(before, rules.small_words, rules.casing)
    raise ValueError(kind)


def preview_bulk(entities, kind: str, sponsors: list[str] | None = None,
                 rules: "Rules | None" = None) -> list[BulkEdit]:
    """Build the before/after list for the entities given.

    Codes are left alone. The sponsor cleanser only looks at competitions.
    Each source line is listed on its own, so duplicate IDs are not collapsed.
    ``rules`` (default: the built-in ones) supplies the affix set, the small
    words, the casing preference, and the per-key exceptions: an entity whose
    key is an exception is never listed.
    """
    edits = []
    phrases = list(sponsors if sponsors is not None
                   else (rules.sponsors if rules is not None else []))
    skipped = rules.exception_keys() if rules is not None else frozenset()
    for entity in entities:
        if kind == "sponsor" and entity.family != "comp":
            continue
        if skipped and entity_key(entity) in skipped:
            continue
        for slot, _label, _cmd in FAMILY_FIELDS[entity.family]:
            if slot not in TEXT_SLOTS:
                continue
            for entry in entity.slots.get(slot) or []:
                before = entry.name
                after = _transform_name(kind, before, phrases, rules)
                if after != before and name_is_legal(after):
                    edits.append(BulkEdit(entity, slot, entry, before, after))
    return edits


def apply_bulk(edits, docs, reason: str = "bulk") -> int:
    """Apply a preview. Returns how many lines changed.

    Only rows whose tick is on (``included``; Replace's edits have no tick and
    all count) are applied. docs is unused; each edit already points at its
    line. ``reason`` is "bulk" for the bulk tools and "replace" for Replace.
    """
    del docs
    count = 0
    for edit in edits:
        if not getattr(edit, "included", True):
            continue
        if try_set_name(edit.entry, edit.after, reason):
            count += 1
    return count


COMMON_FOOTBALL_STOP_WORDS = frozenset({
    "and", "the", "for", "von", "van", "der", "del", "des", "de", "di",
    "da", "la", "le", "el", "of",
})

# Two-letter football marks worth keeping: a club-name descriptor, not a
# distinctive word of its own, so it sorts behind longer tokens in a menu.
SHORT_FOOTBALL_MARKS = frozenset({"ac", "sc", "cf", "fk", "sk", "fc"})

# label, mode, find, replacement; codes are never selected by a preset.
BATCH_RENAME_PRESETS = (
    ("United → Utd", "replace", "United", "Utd"),
    ("City → Cty", "replace", "City", "Cty"),
    ("Cty → City", "replace", "Cty", "City"),
    ("Town → Twn", "replace", "Town", "Twn"),
    ("Twn → Town", "replace", "Twn", "Town"),
    ("Athletic → Ath", "replace", "Athletic", "Ath"),
    ("Association → Assoc", "replace", "Association", "Assoc"),
    ("International → Intl", "replace", "International", "Intl"),
    ("Saint → St", "replace", "Saint", "St"),
    ("Sporting → Sp", "replace", "Sporting", "Sp"),
    ("Wanderers → Wand", "replace", "Wanderers", "Wand"),
    ("Strip trailing FC", "remove_suffix", "FC", ""),
    ("Strip leading FC", "remove_prefix", "FC", ""),
)


def find_batch_preset_for_token(token: str) -> tuple[str, str] | None:
    """Return the Replace preset ``(source, target)`` whose source matches, or None."""
    fold = token.casefold()
    for _label, mode, source, target in BATCH_RENAME_PRESETS:
        if mode == "replace" and source.casefold() == fold:
            return source, target
    return None


def extract_name_tokens(name: str) -> list[str]:
    """Return significant whole words, with short football marks last.

    Whole words only; bracketed qualifiers and stop words are dropped. A
    two-letter word is kept only when it is in SHORT_FOOTBALL_MARKS (AC, SC,
    CF, FK, SK, FC); other two-letter words drop. Marks go after the richer
    tokens so a menu leads with distinctive words.
    """
    text = re.sub(r"\([^)]*\)|\[[^]]*\]|\{[^}]*\}", " ",
                  unicodedata.normalize("NFC", name))
    tokens, descriptors, seen = [], [], set()
    for token in re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, re.UNICODE):
        key = token.casefold()
        if key in seen or key in COMMON_FOOTBALL_STOP_WORDS:
            continue
        if len(token) < 3 and key not in SHORT_FOOTBALL_MARKS:
            continue
        seen.add(key)
        (descriptors if key in SHORT_FOOTBALL_MARKS else tokens).append(token)
    return tokens + descriptors


def _name_search_map(text: str, case_sensitive: bool, match_accents: bool):
    """Normalise graphemes while retaining their exact spans in the source."""
    parts, starts, ends = [], [], []
    clusters = []
    for position, char in enumerate(text):
        if unicodedata.category(char).startswith("M") and clusters:
            clusters[-1][1] = position + 1
        else:
            clusters.append([position, position + 1])
    for start, end in clusters:
        part = unicodedata.normalize("NFC", text[start:end])
        if not match_accents:
            part = "".join(ch for ch in unicodedata.normalize("NFD", part)
                           if unicodedata.category(ch) != "Mn")
        if not case_sensitive:
            part = part.casefold()
        parts.append(part)
        starts.extend([start] * len(part))
        ends.extend([end] * len(part))
    return "".join(parts), starts, ends


def _literal_name_matches(text, term, case_sensitive=False, match_accents=True,
                          whole_word=True):
    normal, starts, ends = _name_search_map(text, case_sensitive, match_accents)
    needle = _name_search_map(term, case_sensitive, match_accents)[0]
    if not needle:
        return
    expression = re.escape(needle)
    if whole_word:
        expression = r"(?<!\w)" + expression + r"(?!\w)"
    for match in re.finditer(expression, normal):
        start, end = match.span()
        # A match must not split a case-fold expansion, such as ß → ss.
        if start and starts[start] == starts[start - 1]:
            continue
        if end < len(ends) and ends[end - 1] == ends[end]:
            continue
        yield starts[start], ends[end - 1]


def entity_matches_token(entity: NameEntity, token: str,
                         case_sensitive: bool = False) -> bool:
    """Match a whole word in any existing text-name override of an entity."""
    token = token.strip()
    if not token:
        return False
    needle = unicodedata.normalize("NFC", token)
    if not case_sensitive:
        needle = needle.casefold()
    expression = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)")
    for slot, entries in entity.slots.items():
        if slot not in TEXT_SLOTS:
            continue
        for entry in entries:
            normal = (entry.name if entry.name.isascii()
                      else unicodedata.normalize("NFC", entry.name))
            text = normal if case_sensitive else normal.casefold()
            if not expression.search(text):
                continue
            # Only uncommon expansions or remaining combining marks need the
            # source-span check used by replacement. Ordinary names need no map.
            if (not normal.isascii()
                    and (len(text) != len(normal)
                         or any(unicodedata.category(char).startswith("M") for char in normal))):
                if next(_literal_name_matches(entry.name, token, case_sensitive), None) is None:
                    continue
            return True
    return False


def entity_token_set(entity: NameEntity) -> frozenset:
    """Folded whole-word tokens across an entity's text-name overrides."""
    folds = set()
    for slot in TEXT_SLOTS:
        for entry in entity.slots.get(slot) or []:
            for token in extract_name_tokens(entry.name):
                folds.add(token.casefold())
    return frozenset(folds)


class FamilyTokenIndex:
    """Per-family whole-word token index for selection menus.

    Built once when a family is loaded or reloaded, refreshed per entity
    for a later edit or undo/redo. Opening a menu only reads it: a lookup
    is O(1) and the whole-family build is a single pass over the entities.
    A match on a fold ignores accents and capitals, the same as the menu's
    reselection uses. The index stores ``(family, id, lang)`` keys so an
    entity can be rebuilt and still match its old rows.
    """

    __slots__ = ("by_family", "entity_tokens", "display")

    def __init__(self):
        self.by_family: dict[str, dict[str, set]] = {}
        self.entity_tokens: dict[tuple, frozenset] = {}
        self.display: dict[str, str] = {}

    def rebuild(self, entities) -> None:
        """Replace every family's map from the entities given."""
        self.by_family = {}
        self.entity_tokens = {}
        self.display = {}
        for entity in entities:
            self._record(entity, entity_token_set(entity))

    def refresh(self, entity: NameEntity) -> None:
        """Rewrite one entity's tokens; removes stale folds from the family."""
        key = (entity.family, entity.id, entity.lang)
        family_map = self.by_family.setdefault(entity.family, {})
        before = self.entity_tokens.get(key, frozenset())
        after = entity_token_set(entity)
        for fold in before - after:
            bucket = family_map.get(fold)
            if bucket is not None:
                bucket.discard(key)
                if not bucket:
                    family_map.pop(fold, None)
        if after:
            for fold in after - before:
                family_map.setdefault(fold, set()).add(key)
            self.entity_tokens[key] = after
        else:
            self.entity_tokens.pop(key, None)
        self._record_display(entity, after)

    def entities_with(self, family: str, fold: str) -> set:
        """Entity keys in ``family`` whose names contain this folded token."""
        return self.by_family.get(family, {}).get(fold, set())

    def count(self, family: str, fold: str) -> int:
        return len(self.entities_with(family, fold))

    def entity_folds(self, entity: NameEntity) -> frozenset:
        return self.entity_tokens.get(
            (entity.family, entity.id, entity.lang), frozenset())

    def display_for(self, fold: str) -> str:
        """The first display spelling seen for the fold, or the fold itself."""
        return self.display.get(fold, fold)

    def _record(self, entity: NameEntity, folds: frozenset) -> None:
        key = (entity.family, entity.id, entity.lang)
        if folds:
            self.entity_tokens[key] = folds
            family_map = self.by_family.setdefault(entity.family, {})
            for fold in folds:
                family_map.setdefault(fold, set()).add(key)
        self._record_display(entity, folds)

    def _record_display(self, entity: NameEntity, folds: frozenset) -> None:
        if not folds:
            return
        for slot in TEXT_SLOTS:
            for entry in entity.slots.get(slot) or []:
                for token in extract_name_tokens(entry.name):
                    fold = token.casefold()
                    if fold in folds and fold not in self.display:
                        self.display[fold] = token


def shared_entity_tokens(entities, index: "FamilyTokenIndex | None" = None
                         ) -> list[tuple[str, int]]:
    """Fold → count across the entities, two or more occurrences only.

    Highest count first, ties broken by the folded token for stable menu
    order. ``index`` is used when given, so repeat calls on the same
    selection do not re-tokenise a name.
    """
    counts: dict[str, int] = {}
    for entity in entities:
        folds = (index.entity_folds(entity) if index is not None
                 else entity_token_set(entity))
        for fold in folds:
            counts[fold] = counts.get(fold, 0) + 1
    shared = [(fold, count) for fold, count in counts.items() if count >= 2]
    shared.sort(key=lambda row: (-row[1], row[0]))
    return shared


def suggest_batch_token(entities, index: "FamilyTokenIndex | None" = None
                        ) -> tuple[str, int, int]:
    """The significant word in the most of the given names, and how it ranks.

    Returns ``(fold, count, total)``: the folded token present in the most
    entities (ties broken by length, then by the fold), the count, and the
    size of the selection. ``("", 0, total)`` when no word is shared by at
    least two of them. Short football marks (AC, SC, CF, FK, SK, FC) win
    only when no longer token shares the same count.
    """
    total = sum(1 for _ in entities)
    counts: dict[str, int] = {}
    for entity in entities:
        folds = (index.entity_folds(entity) if index is not None
                 else entity_token_set(entity))
        for fold in folds:
            counts[fold] = counts.get(fold, 0) + 1
    shared = {fold: count for fold, count in counts.items() if count >= 2}
    if not shared:
        return "", 0, total

    def rank(item):
        fold, count = item
        mark = 1 if fold in SHORT_FOOTBALL_MARKS else 0
        return -count, mark, -len(fold), fold

    fold, count = min(shared.items(), key=rank)
    return fold, count, total


class BatchRenameRule:
    """The transformation and matching choices for one batch preview."""

    __slots__ = ("mode", "find", "replacement", "whole_word", "case_sensitive",
                 "match_accents", "preserve_case")

    def __init__(self, mode="replace", find="", replacement="", whole_word=True,
                 case_sensitive=False, match_accents=True, preserve_case=False):
        self.mode = mode
        self.find = find
        self.replacement = replacement
        self.whole_word = whole_word
        self.case_sensitive = case_sensitive
        self.match_accents = match_accents
        self.preserve_case = preserve_case


def _replacement_case(replacement: str, matched: str) -> str:
    letters = "".join(ch for ch in matched if ch.isalpha())
    if letters and letters.isupper():
        return replacement.upper()
    if letters and letters.islower():
        return replacement.lower()
    if matched.istitle():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _batch_transformer(rule: BatchRenameRule):
    modes = {"replace", "regex", "add_prefix", "remove_prefix", "add_suffix", "remove_suffix"}
    if rule.mode not in modes:
        raise ValueError("Choose a recognised batch rename mode.")
    if rule.mode == "regex":
        try:
            expression = re.compile(rule.find, 0 if rule.case_sensitive else re.IGNORECASE)
            # Parse backreferences even when none of the chosen names matches.
            expression.sub(rule.replacement, "")
        except (re.error, IndexError) as exc:
            raise ValueError(f"Regular expression: {exc}") from exc

        def regex_transform(before):
            return expression.sub(rule.replacement, before).strip() if rule.find else before

        return regex_transform

    def transform(before):
        if rule.mode.startswith("add_"):
            affix = (rule.replacement or rule.find).strip()
            if not affix:
                return before
            return (f"{affix} {before.strip()}" if rule.mode == "add_prefix"
                    else f"{before.strip()} {affix}")
        term = rule.find.strip() if rule.mode.startswith("remove_") else rule.find
        if not term:
            return before
        matches = list(_literal_name_matches(before, term, rule.case_sensitive,
                                             rule.match_accents, rule.whole_word))
        if rule.mode == "remove_prefix":
            matches = [(start, end) for start, end in matches if not before[:start].strip()]
        elif rule.mode == "remove_suffix":
            matches = [(start, end) for start, end in matches if not before[end:].strip()]
        result, last = [], 0
        for start, end in matches:
            result.append(before[last:start])
            replacement = "" if rule.mode.startswith("remove_") else rule.replacement
            result.append(_replacement_case(replacement, before[start:end])
                          if rule.preserve_case else replacement)
            last = end
        result.append(before[last:])
        return "".join(result).strip() if matches else before

    return transform


def preview_batch_rename(entities, rule: BatchRenameRule, slots=("long", "short", "name"),
                         auto_sync_short=False, include_unchanged=False) -> list[BulkEdit]:
    """Preview existing lines only; a refused transformation changes no memory."""
    transform = _batch_transformer(rule)
    selected_slots = frozenset(slots)
    edits, seen = [], set()
    for entity in entities:
        entity_edits = []
        for slot, _label, _cmd in FAMILY_FIELDS[entity.family]:
            if slot not in selected_slots:
                continue
            for entry in entity.slots.get(slot) or []:
                if entry in seen:
                    continue
                seen.add(entry)
                after = transform(entry.name)
                problem = name_problem(after)
                if problem:
                    raise ValueError(f"{ENTITY_KINDS[entity.family]} {entity.id}: {problem}")
                if after != entry.name or include_unchanged:
                    edit = BulkEdit(entity, slot, entry, entry.name, after)
                    edit.included = after != entry.name
                    entity_edits.append(edit)
        if (auto_sync_short and "short" not in selected_slots
                and any(edit.slot in {"long", "name"} and edit.before != edit.after
                        for edit in entity_edits)):
            short_entries = entity.slots.get("short") or []
            if short_entries and all(not entry.changed for entry in short_entries):
                for entry in short_entries:
                    after = transform(entry.name)
                    problem = name_problem(after)
                    if problem:
                        raise ValueError(f"{ENTITY_KINDS[entity.family]} {entity.id}: {problem}")
                    if after != entry.name or include_unchanged:
                        edit = BulkEdit(entity, "short", entry, entry.name, after)
                        edit.included = after != entry.name
                        entity_edits.append(edit)
        edits.extend(entity_edits)
    return edits


def apply_batch_rename(edits, docs) -> int:
    """Validate the complete ticked preview, then change its lines in memory."""
    live_docs = set(docs)
    live_entries, chosen = {}, {}
    for edit in edits:
        if not edit.included or edit.before == edit.after:
            continue
        entry = edit.entry
        if entry.doc not in live_docs:
            raise ValueError("The open files changed. Refresh the batch rename preview.")
        if entry.doc not in live_entries:
            live_entries[entry.doc] = set(entry.doc.entries)
        if (entry not in live_entries[entry.doc] or entry.kind != "name"
                or entry.span is None or entry.name != edit.before):
            raise ValueError("A name changed after the preview. Refresh the batch rename preview.")
        problem = name_problem(edit.after)
        if problem:
            raise ValueError(problem)
        if entry in chosen and chosen[entry] != edit.after:
            raise ValueError("The preview contains competing changes to the same line.")
        chosen[entry] = edit.after
    operation = Operation("batch rename")
    try:
        with operation:
            for entry, after in chosen.items():
                entry.set_name(after, reason="batch_rename")
    except Exception:
        operation.undo()
        raise
    return len(chosen)


class TerminologyCluster:
    """A term family with at least two spellings in the loaded text names."""

    __slots__ = ("label", "variants")

    def __init__(self, label, variants):
        self.label = label
        self.variants = tuple((term, tuple(entities)) for term, entities in variants)


def harmonisation_pattern(source: str) -> str:
    """Match the chosen spelling without treating St. as the separate form St."""
    ending = r"(?![\w.])" if source.casefold() == "st" else r"(?!\w)"
    return r"(?<!\w)" + re.escape(source) + ending


# Built-in terminology groups: used by find_naming_inconsistencies and to
# reject a pinned pair that would duplicate one of them. Dotted and undotted
# forms stay distinct (St vs St.), the way harmonisation_pattern uses them.
BUILTIN_TERM_GROUPS = (
    ("United", "Utd"), ("City", "Cty"), ("Town", "Twn"),
    ("Athletic", "Ath"), ("Association", "Assoc"),
    ("International", "Intl"), ("Saint", "St.", "St"),
    ("Sporting", "Sp"), ("Wanderers", "Wand"), ("FC", "F.C."),
)


def find_naming_inconsistencies(entities) -> list[TerminologyCluster]:
    """Count entities using each spelling, without guessing preferred forms."""
    groups = BUILTIN_TERM_GROUPS
    terms = {term.casefold(): (number, term)
             for number, group in enumerate(groups) for term in group}
    expression = re.compile(r"(?<!\w)(?:" + "|".join(
        re.escape(term) for term in sorted(terms, key=len, reverse=True)) + r")(?!\w)", re.I)
    counts = [{term: [] for term in group} for group in groups]
    for entity in entities:
        found = set()
        for slot, entries in entity.slots.items():
            if slot not in TEXT_SLOTS:
                continue
            for entry in entries:
                for match in expression.finditer(entry.name):
                    found.add(terms[match.group().casefold()])
        for number, term in found:
            counts[number][term].append(entity)
    return [TerminologyCluster(" / ".join(group),
                               [(term, counts[number][term]) for term in group
                                if counts[number][term]])
            for number, group in enumerate(groups)
            if sum(bool(items) for items in counts[number].values()) > 1]


def builtin_pair_folds() -> frozenset:
    """Every unordered pair of case-folded sides inside a built-in group.

    A pair the user tries to pin is refused when its two sides match one of
    these pairs: those spellings are already Harmonise's offer. Dotted and
    undotted forms stay distinct, so {"st", "st."} is here as a built-in but
    {"st", "saint"} and {"st.", "saint"} are too.
    """
    pairs = set()
    for group in BUILTIN_TERM_GROUPS:
        for first in range(len(group)):
            for second in range(first + 1, len(group)):
                pairs.add(frozenset({group[first].casefold(),
                                     group[second].casefold()}))
    return frozenset(pairs)


BUILTIN_PAIR_FOLDS = builtin_pair_folds()
# A side of a pinned pair is one whole word: no whitespace, no double quote,
# and no control character (any of these would split or break a .lnc line).
_PINNED_PAIR_SIDE = re.compile(r"^[^\s\"\r\n\t]+$")


def _pair_fold(full: str, short: str) -> frozenset:
    return frozenset({full.casefold(), short.casefold()})


def pinned_pair_problem(full: str, short: str, pinned_pairs=(),
                        built_ins: "frozenset | None" = None) -> str:
    """Return a plain reason the pair cannot be pinned, or "" if it can.

    Both sides must be non-empty text, with no internal whitespace, no
    double quote, and no control character. A pair is refused when it would
    duplicate a built-in pair or an existing pinned pair. Dotted and
    undotted forms stay distinct, so "St" and "St." could be a legal pair
    if they were not already one of the built-ins.
    """
    full_stripped, short_stripped = full.strip(), short.strip()
    if not full_stripped or not short_stripped:
        return "Both spellings must be filled in."
    for side in (full_stripped, short_stripped):
        if not _PINNED_PAIR_SIDE.match(side):
            return (f"A pinned pair is one whole word on each side: "
                    f"'{side}' is not.")
    if not name_is_legal(full_stripped) or not name_is_legal(short_stripped):
        return ("A pinned pair cannot contain a double quote, a line break, "
                "or another control character.")
    if full_stripped.casefold() == short_stripped.casefold():
        return "The two spellings are the same."
    fold = _pair_fold(full_stripped, short_stripped)
    if built_ins is None:
        built_ins = BUILTIN_PAIR_FOLDS
    if fold in built_ins:
        return "That pair is already one of the built-in pairs."
    for existing_full, existing_short in pinned_pairs:
        if _pair_fold(existing_full, existing_short) == fold:
            return "That pair is already pinned."
    return ""


def find_pinned_pair_for_token(token: str, pinned_pairs
                               ) -> "tuple[str, str] | None":
    """Return ``(source, target)`` if the token matches one side of a pin."""
    fold = token.casefold()
    for full, short in pinned_pairs:
        if full.casefold() == fold:
            return full, short
        if short.casefold() == fold:
            return short, full
    return None


def count_pair_matches(full: str, short: str, entities
                       ) -> "tuple[list, list]":
    """Return ``(entities_using_full, entities_using_short)`` for one pair.

    One entity using both forms is counted under both; the two lists are
    not disjoint totals of clubs. Matching uses harmonisation_pattern, so
    "St" does not match the "St" inside "St.".
    """
    full_expression = re.compile(harmonisation_pattern(full), re.IGNORECASE)
    short_expression = re.compile(harmonisation_pattern(short), re.IGNORECASE)
    full_matches, short_matches = [], []
    for entity in entities:
        full_found = False
        short_found = False
        for slot, entries in entity.slots.items():
            if slot not in TEXT_SLOTS:
                continue
            for entry in entries:
                if not full_found and full_expression.search(entry.name):
                    full_found = True
                if not short_found and short_expression.search(entry.name):
                    short_found = True
                if full_found and short_found:
                    break
            if full_found and short_found:
                break
        if full_found:
            full_matches.append(entity)
        if short_found:
            short_matches.append(entity)
    return full_matches, short_matches


def pinned_pair_clusters(pairs, entities) -> list[TerminologyCluster]:
    """A TerminologyCluster per pinned pair, with both forms kept.

    Unlike find_naming_inconsistencies, a cluster with only one side used is
    still returned, so the user sees every pinned pair under Harmonise. The
    count of clubs on each side is not a total: a club using both forms is
    counted under both.
    """
    clusters = []
    for full, short in pairs:
        full_matches, short_matches = count_pair_matches(full, short, entities)
        clusters.append(TerminologyCluster(
            f"{full} / {short}",
            [(full, tuple(full_matches)), (short, tuple(short_matches))]))
    return clusters


def list_version_dirs(db_root: Path) -> list[Path]:
    """Numeric database folders, oldest first."""
    if not db_root.is_dir():
        return []
    found = [path for path in db_root.iterdir() if path.is_dir() and path.name.isdigit()]
    return sorted(found, key=lambda path: int(path.name))


def version_has_names(version_dir: Path) -> bool:
    folder = version_dir / "lnc" / "all"
    return all((folder / name).is_file() for name in NAME_FILES)


def name_paths(version_dir: Path) -> list[Path]:
    folder = version_dir / "lnc" / "all"
    return [folder / name for name in NAME_FILES]


class DatabaseIdentity:
    """The name and version a database folder's own XML file reports.

    ``<folder>\\<folder>_fm\\<folder>_fm.xml`` sits beside the ``lnc`` folder.
    FM27 writes it as ``<string id="name" value="Football Manager 27"/>`` and
    ``<string id="version" value="27.0.0"/>``. A missing or malformed file
    gives ``None``; the label then falls back to the folder name.
    """

    __slots__ = ("name", "version")

    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version


def read_database_identity(version_dir) -> "DatabaseIdentity | None":
    """Returns ``DatabaseIdentity`` for a version folder, or ``None``.

    Reads ``<folder>_fm/<folder>_fm.xml`` with the standard library's
    ElementTree parser. Returns ``None`` when the file is missing, cannot
    be parsed, or does not carry both a name and a version. Never raises
    for the caller. The file is from the game's installation folder (a
    trusted source); Python 3.7.1 onwards rejects external entities in
    ElementTree, and the file has none anyway.
    """
    folder = Path(version_dir)
    xml_path = folder / f"{folder.name}_fm" / f"{folder.name}_fm.xml"
    try:
        tree = ElementTree.parse(xml_path)
    except (OSError, ElementTree.ParseError):
        return None
    name = version = None
    for element in tree.getroot().findall("string"):
        if element.get("id") == "name":
            name = element.get("value")
        elif element.get("id") == "version":
            version = element.get("value")
    if not name or not version:
        return None
    return DatabaseIdentity(name, version)


def short_database_name(full: str) -> str:
    """A compact badge for a database name.

    "Football Manager 27" -> "FM27". The first letter of each word is kept;
    digit runs are kept whole. Empty text, or text with no letters or
    digits, gives the original back so the selector always shows something.
    """
    out = []
    for token in re.findall(r"[A-Za-z]+|\d+", full):
        out.append(token if token[0].isdigit() else token[0].upper())
    return "".join(out) or full


def version_label(version_dir) -> str:
    """The database selector's label for one version folder.

    Reads the XML identity when present: "FM27 27.0.0 (2700)". Falls back
    to the folder name alone. A folder without the FM27 name-file pair
    gets a " (no name files)" trailer, as before.
    """
    folder = Path(version_dir)
    identity = read_database_identity(folder)
    if identity is not None:
        base = f"{short_database_name(identity.name)} {identity.version} ({folder.name})"
    else:
        base = folder.name
    return base if version_has_names(folder) else f"{base} (no name files)"


def find_overrides(family: str, id_: str, version_dir) -> list["Override"]:
    """Every ``.lnc`` line in a database folder whose entity key matches.

    Scans every ``.lnc`` under ``<version>/lnc/`` (``lnc/all``, ``lnc/greek``,
    and any other subfolders) and returns the lines whose command belongs
    to ``family``'s set and whose id matches ``id_``. Lines are grouped by
    (command, language); within a group, a line's state is ``identical``
    when its value equals every other value in that group, or ``competing``
    when the group holds more than one distinct value. The tool shows the
    overlap and does not claim to know the game's load order (note 05, C).
    A file that cannot be read or decoded is skipped; its absence from the
    list does not mean the file has nothing to say.
    """
    commands = {cmd for _slot, _label, cmd in FAMILY_FIELDS.get(family, [])}
    if not commands:
        return []
    folder = Path(version_dir) / "lnc"
    if not folder.is_dir():
        return []
    overrides: list[Override] = []
    groups: dict[tuple[str, str], list[str]] = {}
    paths = sorted(folder.rglob("*.lnc"),
                   key=lambda p: (p.parent.name.casefold(), p.name.casefold()))
    for path in paths:
        try:
            doc = LncDoc(path)
        except (OSError, UnicodeError):
            continue
        for entry in doc.names():
            if entry.cmd not in commands or entry.id != id_:
                continue
            key = (entry.cmd, entry.lang)
            groups.setdefault(key, []).append(entry.name)
            overrides.append(Override(
                file=path, line=entry.lineno, command=entry.cmd,
                id_=entry.id, language=entry.lang, name=entry.name,
                state="identical"))             # settled by the second pass
    for override in overrides:
        values = groups[(override.command, override.language)]
        if len(set(values)) > 1:
            override.state = "competing"
    return overrides


RULES_FORMAT = "fm-name-rules"
RULES_VERSION = 1
RULES_FILE = "rules.json"


CASING_MODES = ("capitals", "words")
BULK_SCOPES = ("shown", "family", "selected")
DEFAULT_CASING = "capitals"
DEFAULT_SCOPE = "shown"


class Rules:
    """Reusable bulk-tool preferences, kept in ``state/rules.json``.

    ``sponsors`` is the sponsor cleanser's list; ``affixes`` the affix
    stripper's set; ``small_words`` the words the title-caser keeps lower case;
    ``casing`` is "capitals" (re-case names written wholly in capitals) or
    "words" (also re-case single long capital words); ``scope`` is where a run
    starts: "shown" (the entities in the current filter), "family" (every
    entity of the family shown), or "selected" (the selected rows);
    ``exceptions`` are (family, id, language) keys no bulk run ever changes.
    ``pinned_pairs`` are ``(full, short)`` whole-word spellings Harmonise
    and Select similar know about beside the built-ins; the editor never
    invents one.
    A missing file loads the built-in defaults; a damaged file is named in the
    status bar and left alone, as with ``state/settings.json`` (decision 38).
    """

    __slots__ = ("sponsors", "small_words", "affixes", "casing", "scope",
                 "exceptions", "pinned_pairs")

    def __init__(self, sponsors=None, small_words=None, affixes=None,
                 casing=DEFAULT_CASING, scope=DEFAULT_SCOPE, exceptions=None,
                 pinned_pairs=None):
        self.sponsors = (list(sponsors) if sponsors is not None
                         else list(STARTER_SPONSORS))
        self.small_words = (list(small_words) if small_words is not None
                            else sorted(SMALL_WORDS))
        self.affixes = list(affixes) if affixes is not None else list(AFFIXES)
        self.casing = casing if casing in CASING_MODES else DEFAULT_CASING
        self.scope = scope if scope in BULK_SCOPES else DEFAULT_SCOPE
        self.exceptions = sorted({tuple(key) for key in (exceptions or ())},
                                 key=_key_order)
        self.pinned_pairs = [(str(full), str(short))
                             for full, short in (pinned_pairs or ())]

    def exception_keys(self) -> frozenset:
        return frozenset(self.exceptions)

    def to_bytes(self) -> bytes:
        payload = {
            "format": RULES_FORMAT,
            "version": RULES_VERSION,
            "sponsors": self.sponsors,
            "affixes": self.affixes,
            "small_words": self.small_words,
            "casing": self.casing,
            "scope": self.scope,
            "exceptions": [{"family": family, "id": id_, "language": lang}
                           for family, id_, lang in self.exceptions],
            "pinned_pairs": [{"full": full, "short": short}
                             for full, short in self.pinned_pairs],
        }
        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def add_pinned_pair(self, full: str, short: str) -> None:
        """Validate the pair against built-ins and this list, then append it.

        Raises ``ValueError`` with the reason when a pair cannot be pinned:
        empty, multi-word, a repeat of a built-in or an existing pin, or
        containing a character .lnc cannot carry.
        """
        problem = pinned_pair_problem(full, short, self.pinned_pairs)
        if problem:
            raise ValueError(problem)
        self.pinned_pairs.append((full.strip(), short.strip()))

    def remove_pinned_pair(self, full: str, short: str) -> bool:
        """Drop the pair matching the two sides (case-insensitive).

        Returns True when a pair was removed; False when nothing matched.
        Removing a pair never renames any club.
        """
        fold = _pair_fold(full, short)
        for position, (existing_full, existing_short) in enumerate(self.pinned_pairs):
            if _pair_fold(existing_full, existing_short) == fold:
                self.pinned_pairs.pop(position)
                return True
        return False


def _text_list(raw, name: str):
    """A list of non-empty texts from ``raw[name]``, or None when absent or not a list."""
    value = raw.get(name)
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str) and item]


def _clean_exceptions(value) -> list[tuple]:
    """The usable (family, id, language) keys in a saved list; anything else is dropped."""
    keys = []
    if not isinstance(value, list):
        return keys
    for item in value:
        if not isinstance(item, dict):
            continue
        family, id_, lang = item.get("family"), item.get("id"), item.get("language", "")
        if (isinstance(family, str) and family in FAMILY_FIELDS
                and isinstance(id_, str) and id_is_legal(id_)
                and isinstance(lang, str)):
            keys.append((family, id_, lang))
    return keys


def _clean_pinned_pairs(value) -> list[tuple[str, str]]:
    """The usable ``(full, short)`` pairs in a saved list; bad entries drop.

    A wrongly typed or blank pair, a pair that repeats a built-in, and a
    pair that repeats one already read earlier all drop. The rest of the
    list is kept, as the other ``state/rules.json`` fields are (decision 58).
    """
    pairs: list[tuple[str, str]] = []
    if not isinstance(value, list):
        return pairs
    for item in value:
        if not isinstance(item, dict):
            continue
        full, short = item.get("full"), item.get("short")
        if not isinstance(full, str) or not isinstance(short, str):
            continue
        if pinned_pair_problem(full, short, pairs):
            continue
        pairs.append((full.strip(), short.strip()))
    return pairs


def read_rules(root) -> tuple["Rules", str]:
    """Returns (rules, problem). A missing file is not damaged.

    Shape is the same as ``read_state``: ({built-in defaults}, "") when the
    file is missing, (defaults, named problem) when it exists but cannot be
    used, and (parsed rules, "") on success. A byte-order mark is accepted. A
    field that is missing or of the wrong type takes its default; one bad
    exception is dropped, not the file.
    """
    path = Path(root) / RULES_FILE
    if not path.exists():
        return Rules(), ""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return Rules(), f"{path} could not be read: {exc}."
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return Rules(), f"{path} is not UTF-8 text."
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return Rules(), f"{path} is not readable JSON: {exc.msg}."
    if not isinstance(raw, dict):
        return Rules(), f"{path} does not hold rules: it should be one JSON object."
    casing, scope = raw.get("casing"), raw.get("scope")
    return Rules(
        sponsors=_text_list(raw, "sponsors"),
        small_words=_text_list(raw, "small_words"),
        affixes=_text_list(raw, "affixes"),
        casing=casing if isinstance(casing, str) else DEFAULT_CASING,
        scope=scope if isinstance(scope, str) else DEFAULT_SCOPE,
        exceptions=_clean_exceptions(raw.get("exceptions")),
        pinned_pairs=_clean_pinned_pairs(raw.get("pinned_pairs")),
    ), ""


def save_rules(rules: "Rules", root) -> None:
    """Save the rules file. Refuses to write over a damaged one (decision 38).

    Raises ``DamagedFileError`` with the path of the damaged file; the window
    shows the problem and leaves the file as it is. The caller created the
    ``state`` folder for other files, so this helper only writes to it.
    """
    root_path = Path(root)
    _rules, problem = read_rules(root_path)
    if problem:
        raise DamagedFileError(root_path / RULES_FILE, problem)
    root_path.mkdir(parents=True, exist_ok=True)
    write_file_atomically(root_path / RULES_FILE, rules.to_bytes())


def under_game_tree(path: Path, game_root: Path | None) -> bool:
    """True when path sits inside the Football Manager database root."""
    if game_root is None:
        return False
    try:
        file_path = str(path.resolve()).casefold()
        root = str(game_root.resolve()).casefold().rstrip("\\/")
    except OSError:
        return False
    return file_path == root or file_path.startswith(root + "\\") or file_path.startswith(root + "/")


def _path_key(path) -> str:
    """A comparable spelling of a path: absolute, and case-folded as Windows compares."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(os.path.abspath(path))
    return os.path.normcase(str(resolved))


def same_path(first, second) -> bool:
    """True when two paths name the same file."""
    return _path_key(first) == _path_key(second)


def database_folder_of(path) -> str:
    """The numbered database folder a path sits in, such as "2700", or "" if none."""
    for parent in Path(path).parents:
        if parent.name.isascii() and parent.name.isdigit():
            return parent.name
    return ""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- writing one file ----------------------------------------------------

def _discard(path) -> bool:
    """Remove a staging file if it is still there. False when it could not be removed."""
    if path is None:
        return True
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _stage_bytes(path: Path, payload: bytes) -> Path:
    """Write payload to a new temporary file beside path and return its name.

    The file sits in the destination's own folder, so the os.replace that
    follows stays on one volume. Its name ends in ``.writing``, so the game
    never reads it as a name file. The bytes are flushed to disk before
    this returns. On failure the file is removed and the error is raised.
    """
    handle, name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".writing", dir=str(path.parent))
    staged = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        _discard(staged)
        raise
    return staged


def write_file_atomically(path, payload: bytes, times=None) -> None:
    """Replace one file with payload in a single step.

    The bytes go to a unique temporary sibling and are flushed to disk, then
    os.replace swaps that sibling in. If anything fails, the file at path is
    left as it was, and the temporary file is removed in ``finally``.
    ``times`` (access and modification time in nanoseconds) is applied to
    the new file, so a backup copy keeps its original's date. This covers
    one file. Several files written this way are not one atomic step; see
    write_documents for how a set of files is handled.
    """
    path = Path(path)
    staged = _stage_bytes(path, payload)
    try:
        if times is not None:
            os.utime(staged, ns=times)
        os.replace(staged, path)
    finally:
        _discard(staged)


def _times_of(stat):
    return None if stat is None else (stat.st_atime_ns, stat.st_mtime_ns)


# ---- backup folders and their manifests ----------------------------------

def new_archive_dir(archive_root: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    dest = archive_root / stamp
    suffix = 0
    while dest.exists():
        suffix += 1
        dest = archive_root / f"{stamp}-{suffix}"
    dest.mkdir(parents=True)
    return dest


def _unique_name(folder: Path, name: str, taken: set) -> str:
    """name, or name-2, name-3 and so on, so no two copies share a file name."""
    stem, suffix = os.path.splitext(name)
    candidate = name
    count = 1
    while candidate.casefold() in taken or (folder / candidate).exists():
        count += 1
        candidate = f"{stem}-{count}{suffix}"
    taken.add(candidate.casefold())
    return candidate


def _describe_encoding(path: Path, data: bytes):
    """Encoding and BOM of a name file's bytes. (None, None) for other files."""
    if path.suffix.casefold() != ".lnc":
        return None, None
    try:
        _text, encoding, has_bom = decode_lnc_bytes(data)
    except UnicodeError:
        return "unreadable", None
    return encoding, has_bom


def write_manifest(folder: Path, manifest: dict) -> None:
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    write_file_atomically(Path(folder) / MANIFEST_NAME, text.encode("utf-8"))


def read_manifest(folder: Path) -> dict | None:
    """Return a backup folder's manifest, or None for a folder made before 2.2.

    Raises:
        ValueError: manifest.json is there but cannot be read as a manifest.
    """
    folder = Path(folder)
    path = folder / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"The manifest in {folder.name} could not be read: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != ARCHIVE_FORMAT:
        raise ValueError(f"{MANIFEST_NAME} in {folder.name} is not a backup manifest.")
    if data.get("version") != ARCHIVE_VERSION:
        raise ValueError(
            f"The manifest in {folder.name} is version {data.get('version')}. "
            f"This editor reads version {ARCHIVE_VERSION}.")
    files = data.get("files")
    if not isinstance(files, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("original"), str)
            and isinstance(item.get("archived"), str)
            for item in files):
        raise ValueError(f"The manifest in {folder.name} has no usable list of files.")
    return data


def manifest_entry(manifest: dict | None, archived_name: str) -> dict | None:
    """The manifest's record for one copy, found by its name in the backup folder."""
    if not manifest:
        return None
    wanted = archived_name.casefold()
    for item in manifest["files"]:
        if item["archived"].casefold() == wanted:
            return item
    return None


def _store_copies(sources, archive_root: Path, operation: str,
                  database: str | None = None) -> tuple[Path, list[Path]]:
    """Copy file contents into a new backup folder and describe them in manifest.json.

    ``sources`` lists (original path, bytes, os.stat_result or None). The
    bytes are what the file held when it was read, so the copy and any check
    made on that reading are of the same contents. Each copy is written
    through a temporary file and keeps its original's dates. Two sources
    with one name get separate copies (``name-2.lnc`` and so on), and the
    manifest records which original each copy came from. The manifest is
    written last, so a folder that has one holds every copy it lists. Its
    ``result`` stays "pending" until finish_manifest records the outcome.
    Returns the folder and the copies, in the order of ``sources``.
    """
    now = datetime.now()
    folder = new_archive_dir(archive_root, now)
    taken: set = set()
    files, copies = [], []
    for original, data, stat in sources:
        original = Path(original)
        name = _unique_name(folder, original.name, taken)
        write_file_atomically(folder / name, data, _times_of(stat))
        encoding, has_bom = _describe_encoding(original, data)
        modified = None
        if stat is not None:
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        files.append({
            "original": str(original),
            "archived": name,
            "size": len(data),
            "sha256": sha256_hex(data),
            "encoding": encoding,
            "bom": has_bom,
            "modified": modified,
        })
        copies.append(folder / name)
    if database is None:
        found = {database_folder_of(original) for original, _data, _stat in sources}
        database = ", ".join(sorted(found - {""}))
    write_manifest(folder, {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "operation": operation,
        "timestamp": now.isoformat(timespec="seconds"),
        "database": database,
        "editor_version": VERSION,
        "result": "pending",
        "files": files,
    })
    return folder, copies


def archive_files(paths, archive_root: Path, operation: str = "Backup",
                  database: str | None = None) -> Path:
    """Copy existing files into a new backup folder with a manifest. Missing paths are skipped."""
    sources = []
    for path in paths:
        path = Path(path)
        if path.is_file():
            stat = path.stat()
            sources.append((path, path.read_bytes(), stat))
    return _store_copies(sources, archive_root, operation, database)[0]


def finish_manifest(folder: Path, result: str, outcomes: dict | None = None) -> bool:
    """Record in a backup folder's manifest how its operation ended.

    ``result`` is a key of ARCHIVE_RESULTS. ``outcomes`` maps an original
    path, as the manifest spells it, to that file's state. This is best
    effort: the files are already where they are, so a failure here returns
    False and is not reported as a failed write.
    """
    try:
        manifest = read_manifest(folder)
        if manifest is None:
            return False
        manifest["result"] = result
        for item in manifest["files"]:
            state = (outcomes or {}).get(item["original"])
            if state:
                item["outcome"] = state
        write_manifest(folder, manifest)
    except (OSError, ValueError):
        return False
    return True


def _beside_copy(path: Path, data: bytes, stat) -> Path:
    """Write a ``.bak-<date>`` copy of data next to path and return its name."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak-{stamp}")
    count = 1
    while target.exists():
        count += 1
        target = path.with_name(f"{path.name}.bak-{stamp}-{count}")
    write_file_atomically(target, data, _times_of(stat))
    return target


# ---- writing several files -------------------------------------------------

class WriteError(OSError):
    """A write stopped. The message says where each file stands.

    ``files`` holds a FileWrite for every destination once replacing had
    begun, and is empty when the write stopped before touching anything.
    ``archive`` is the backup folder, if one was made.
    """

    def __init__(self, message: str, files=(), archive=None):
        super().__init__(message)
        self.files = list(files)
        self.archive = archive


class ExternalChangeError(WriteError):
    """Files changed on disk after the editor read them, so nothing was replaced."""

    def __init__(self, paths):
        self.paths = [Path(path) for path in paths]
        listed = "\n".join(str(path) for path in self.paths)
        super().__init__(
            "These files changed on disk, or were removed, after the editor read them:\n"
            f"{listed}\n\nNothing was written, so the files on disk are kept as they are. "
            "To carry your edits across, export them as a name pack, open the files "
            "again, and import the pack.")


class FileWrite:
    """One destination in a write, and where it stands.

    ``state`` is "pending" until the write runs, then one of: "written";
    "not written" (an earlier file failed, so this one was not tried);
    "failed" (its replacement failed, so the file is as it was); "restored"
    (it was replaced, then put back from the bytes read before); "removed"
    (it was created, then removed again); or "left written" (it was
    replaced and could not be put back, ``detail`` says why).
    """

    __slots__ = ("doc", "dest", "payload", "backup_mode", "before", "stat",
                 "backup", "staged", "state", "detail", "lines")

    def __init__(self, doc, dest, payload: bytes, backup_mode: str, lines=None):
        self.doc = doc
        self.dest = Path(dest)
        self.payload = payload
        self.lines = lines                # payload_lines record of a partial write, or None
        self.backup_mode = backup_mode    # "archive", "beside", or "none"
        self.before = None                # bytes on disk before the write; None if no file
        self.stat = None
        self.backup = None                # where the copy of ``before`` went
        self.staged = None                # temporary file waiting to be swapped in
        self.state = "pending"
        self.detail = ""

    @property
    def existed(self) -> bool:
        return self.before is not None

    def describe(self) -> str:
        if self.state == "written":
            return "written"
        if self.state == "not written":
            return "not written, so it is unchanged (an earlier file failed)"
        if self.state == "failed":
            return f"could not be replaced, so it is unchanged ({self.detail})"
        if self.state == "restored":
            return "put back as it was, from the copy taken before the write"
        if self.state == "removed":
            return "removed again (it did not exist before)"
        if self.state == "left written":
            if not self.existed:
                return f"was created and could not be removed ({self.detail})"
            where = f" The previous version is in {self.backup}." if self.backup else ""
            return f"holds the new version, because putting it back failed ({self.detail}).{where}"
        return self.state


def _read_current(path: Path):
    """The bytes and stat of a file as it is now, or (None, None) when there is no file."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None, None
    return path.read_bytes(), stat


def _put_back(write: FileWrite) -> None:
    """Undo one replacement: write the earlier bytes back, or remove a new file."""
    try:
        if write.before is None:
            write.dest.unlink()
            write.state = "removed"
        else:
            write_file_atomically(write.dest, write.before, _times_of(write.stat))
            write.state = "restored"
    except OSError as exc:
        write.state = "left written"
        write.detail = str(exc)


def _write_report(operation: str, writes, leftovers) -> str:
    touched = any(w.state in ("restored", "removed", "left written") for w in writes)
    if touched:
        head = (f"{operation} stopped part-way. Files are replaced one at a time, per "
                "file, not as one batch. This is where each file stands now:")
    else:
        head = f"{operation} stopped before any file was replaced:"
    lines = [head, ""]
    for write in writes:
        lines.append(f"{write.dest}\n    {write.describe()}")
    if leftovers:
        lines += ["", "These temporary files could not be removed:"]
        lines += [str(path) for path in leftovers]
    lines += ["", "Your edits are still open in the editor."]
    return "\n".join(lines)


def _settle(writes) -> None:
    """Settle every document whose destination now holds its payload.

    A whole working copy marks the document clean. A partial write keeps
    the changes it left out pending against the bytes now on disk.
    """
    for write in writes:
        if write.state in ("written", "left written"):
            write.doc.path = write.dest
            if write.lines is None:
                write.doc.mark_clean(write.payload)
            else:
                write.doc.settle_written(write.lines, write.payload)


def _end_result(writes) -> str:
    states = {write.state for write in writes}
    if "left written" in states:
        return "partly written"
    if states & {"restored", "removed"}:
        return "rolled back"
    return "stopped"


def write_documents(operation: str, plan, archive_root: Path | None = None) -> Path | None:
    """Write documents to their destinations one file at a time, with a way back.

    ``plan`` lists (doc, destination, backup), where backup is "archive"
    (copy the current file into a new folder under ``archive_root``, with a
    manifest), "beside" (a ``.bak-<date>`` copy next to it), or "none". An
    item may carry a fourth element, a Payload from build_payload: its bytes
    are written instead of the whole working copy, and the changes it left
    out stay pending in memory.

    1. Every payload is encoded. An encoding error stops the write here.
    2. Every destination is read. One that its document was opened from
       must still hold the bytes read then. If it changed or went,
       ExternalChangeError is raised and nothing is written.
    3. Payloads are staged as temporary files beside their destinations.
    4. Backups are written from the bytes read in step 2.
    5. Each destination is read again. A change since step 2 stops the
       write before any file is replaced.
    6. Destinations are replaced one at a time with os.replace. If one
       fails, the files already replaced get their earlier bytes back, or
       are removed when they did not exist, and WriteError says where each
       file stands. Several files are never described as one atomic step.

    Staging files are removed in ``finally``. A document whose destination
    now holds its payload is settled with those bytes (see _settle), and
    its path becomes that destination. Returns the backup folder, or None.

    Raises:
        UnicodeEncodeError: a payload could not be encoded (step 1).
        ExternalChangeError: a destination changed on disk (steps 2 and 5).
        WriteError: a replacement failed (step 6), or two documents would
            write the same file.
        OSError: reading, staging, or backing up failed. No file was
            replaced then.
    """
    writes = []
    for item in plan:
        doc, dest, backup = item[0], item[1], item[2]
        prepared = item[3] if len(item) > 3 else None
        if prepared is None:
            writes.append(FileWrite(doc, dest, doc.to_bytes(), backup))
        else:
            writes.append(FileWrite(doc, dest, prepared.data, backup, prepared.lines))
    if not writes:
        return None
    seen: set = set()
    for write in writes:
        key = _path_key(write.dest)
        if key in seen:
            raise WriteError(
                f"Two open files would both be written to {write.dest}. "
                "Close one of them first. Nothing was written.")
        seen.add(key)
    changed = []
    for write in writes:
        write.before, write.stat = _read_current(write.dest)
        if same_path(write.doc.path, write.dest) and write.before != write.doc.baseline_bytes:
            changed.append(write.dest)
    if changed:
        raise ExternalChangeError(changed)

    archive = None
    try:
        for write in writes:
            write.dest.parent.mkdir(parents=True, exist_ok=True)
            write.staged = _stage_bytes(write.dest, write.payload)
        archived = [w for w in writes if w.backup_mode == "archive" and w.existed]
        if archived:
            if archive_root is None:
                raise ValueError("This write needs a backup folder.")
            archive, copies = _store_copies(
                [(w.dest, w.before, w.stat) for w in archived], archive_root, operation)
            for write, copy in zip(archived, copies):
                write.backup = copy
        for write in writes:
            if write.backup_mode == "beside" and write.existed:
                write.backup = _beside_copy(write.dest, write.before, write.stat)
        moved = [w.dest for w in writes if _read_current(w.dest)[0] != w.before]
        if moved:
            if archive is not None:
                finish_manifest(archive, "stopped")
            raise ExternalChangeError(moved)
        for index, write in enumerate(writes):
            try:
                os.replace(write.staged, write.dest)
            except OSError as exc:
                write.state = "failed"
                write.detail = str(exc)
                for done in reversed(writes[:index]):
                    _put_back(done)
                for later in writes[index + 1:]:
                    later.state = "not written"
                leftovers = []
                for other in writes:
                    if other.staged is not None and not _discard(other.staged):
                        leftovers.append(other.staged)
                    other.staged = None
                _settle(writes)
                if archive is not None:
                    finish_manifest(archive, _end_result(writes),
                                    {str(w.dest): w.state for w in writes})
                raise WriteError(
                    _write_report(operation, writes, leftovers), writes, archive) from exc
            write.staged = None
            write.state = "written"
    finally:
        for write in writes:
            _discard(write.staged)
    _settle(writes)
    if archive is not None:
        finish_manifest(archive, "complete", {str(w.dest): w.state for w in writes})
    return archive


def save_documents(docs, game_root: Path | None, archive_root: Path) -> Path | None:
    """Write documents back to their own paths, see write_documents.

    Files under game_root are copied into one new folder under archive_root,
    with a manifest. Other files keep a ``.bak-<date>`` copy beside them.
    Returns the backup folder, or None when no game file was copied.
    """
    plan = [
        (doc, doc.path, "archive" if under_game_tree(doc.path, game_root) else "beside")
        for doc in docs
    ]
    return write_documents("Save", plan, archive_root)


def deploy_documents(pairs, archive_root: Path) -> Path | None:
    """Write each document to its game destination, see write_documents.

    The current game files are copied into a new folder under archive_root,
    with a manifest, before anything is replaced. A failed encode leaves the
    game files untouched and creates no backup folder. Each document's path
    becomes its destination once that file is written.

    pairs: list of (LncDoc, destination Path).
    """
    return write_documents(
        "Deploy", [(doc, dest, "archive") for doc, dest in pairs], archive_root)


def process_names_from_tasklist(text: str) -> list[str]:
    """Pick Football Manager executables out of `tasklist /FO CSV` text."""
    found = []
    for line in text.splitlines():
        if not line.startswith('"'):
            continue
        exe = line.split('"', 2)[1]
        stem = exe.casefold()
        if stem == "fm.exe" or stem.startswith("football manager"):
            found.append(exe)
    return found


def football_manager_running() -> list[str] | None:
    """Return matching process names, or None when the list could not be read.

    An empty list means the game is not running. None means the process
    list is unknown: tasklist was missing, failed, or took more than ten
    seconds. Callers must not read None as "closed". This never stops a
    process.
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return process_names_from_tasklist(out.stdout)


class Preflight:
    """What one write into the game tree would touch, and whether it may start.

    ``running`` lists the Football Manager processes found. ``check_failed``
    is True when the process list could not be read, which is not the same
    as the game being closed.
    """

    __slots__ = ("operation", "paths", "game_paths", "running", "check_failed")

    def __init__(self, operation: str, paths, game_paths, running, check_failed: bool):
        self.operation = operation
        self.paths = list(paths)
        self.game_paths = list(game_paths)
        self.running = list(running)
        self.check_failed = check_failed

    @property
    def blocked(self) -> bool:
        return bool(self.running)

    def blocked_message(self) -> str:
        return (
            "Football Manager is running: " + ", ".join(self.running)
            + "\nClose the game before writing game files.")

    def unknown_message(self) -> str:
        return (
            "The check for a running copy of Football Manager could not be made. "
            "Make sure the game is closed before you continue.")


def game_write_preflight(operation: str, paths, game_root: Path | None = None,
                         check=None) -> Preflight:
    """Check one write before it starts. Shared by Save, Deploy, and licensing.

    ``paths`` are the files the operation would write. With a ``game_root``,
    only paths under it count as game writes. With ``None``, every path is
    a game write: Deploy and the licensing toggle only ever touch the game
    tree. The process check runs only when there is a game write to make.
    ``check`` replaces the process lookup in tests.
    """
    paths = [Path(path) for path in paths]
    if game_root is None:
        game_paths = list(paths)
    else:
        game_paths = [path for path in paths if under_game_tree(path, game_root)]
    running: list[str] = []
    check_failed = False
    if game_paths:
        found = (check or football_manager_running)()
        if found is None:
            check_failed = True
        else:
            running = list(found)
    return Preflight(operation, paths, game_paths, running, check_failed)


# ---- the Changes view and the review before a write ------------------------

CHANGE_STATES = {
    "edited": "Edited",
    "added": "Added",
    "restored": "Restored",
    "removed": "Removed",
    "other": "Other lines",
}
OTHER_LINES_TEXT = "Comments, blank lines, or line endings differ from the file on disk"


def _row_text(entry: Entry, name: str, source: str) -> str:
    """How a name line or a person rule reads in the Changes view."""
    if entry.kind == "person":
        return f"{source} → {name}"
    return name


class ChangeRow:
    """One difference between an open file and its file on disk.

    ``state`` is a key of CHANGE_STATES. ``entry`` is the line in memory;
    for a removed row it is the line on disk that a restored backup lacks;
    for the "other" row it is None, which stands for differences outside
    name lines and person rules. The include tick is kept on the entry, or
    on the document when its changes are written together (LncDoc.grouped),
    so the Changes tab and the review dialog always agree.
    """

    __slots__ = ("doc", "entry", "state")

    def __init__(self, doc: LncDoc, entry, state: str):
        self.doc = doc
        self.entry = entry
        self.state = state

    @property
    def included(self) -> bool:
        if self.entry is None or self.doc.grouped:
            return not self.doc.whole_excluded
        return not self.entry.excluded

    def set_included(self, value: bool) -> None:
        if self.entry is None or self.doc.grouped:
            self.doc.whole_excluded = not value
        else:
            self.entry.excluded = not value

    @property
    def command(self) -> str:
        return self.entry.cmd if self.entry is not None else ""

    @property
    def id(self) -> str:
        return self.entry.id if self.entry is not None else ""

    @property
    def language(self) -> str:
        return self.entry.lang if self.entry is not None else ""

    @property
    def line(self) -> int | None:
        """The line number in memory; for a removed row, its number on disk."""
        return self.entry.lineno if self.entry is not None else None

    @property
    def on_disk(self) -> str:
        if self.state in ("edited", "restored"):
            return _row_text(self.entry, self.entry.orig_name, self.entry.orig_source)
        if self.state == "removed":
            return _row_text(self.entry, self.entry.name, self.entry.source)
        if self.state == "added":
            return "no line"
        return ""

    @property
    def proposed(self) -> str:
        if self.state in ("edited", "restored", "added"):
            return _row_text(self.entry, self.entry.name, self.entry.source)
        if self.state == "removed":
            return "no line"
        return OTHER_LINES_TEXT

    @property
    def reason(self) -> str:
        """The operation that made this difference, in words."""
        if self.entry is None:
            return CHANGE_REASONS["restore"] if self.doc.restore_pending else ""
        if self.state == "removed":
            # A disk line missing from memory comes from a restore, or from an
            # undo that took out a line a write had already put on disk.
            return CHANGE_REASONS["restore" if self.doc.restore_pending else "undo"]
        return line_reason(self.entry)

    @property
    def detail(self) -> str:
        """A longer note for a tooltip: where a restore came from, or why rows go together."""
        if self.doc.restore_pending:
            where = f" {self.doc.restored_from}" if self.doc.restored_from else " a backup"
            return (f"Restored from{where}. A restored file is written whole: tick or "
                    "untick it as one.")
        if self.doc.grouped:
            return "These changes can only be written together, as one file."
        return ""


def collect_changes(docs) -> list[ChangeRow]:
    """Every difference between the open files and their files on disk, in file order.

    An edited or restored line differs in text, an added line is not on
    disk, and a removed line is on disk but a restored backup lacks it. A
    file that differs from disk only outside name lines and person rules
    gets one "other" row, so nothing a write would change is hidden.
    """
    rows: list[ChangeRow] = []
    for doc in docs:
        found = []
        for entry in doc.entries:
            if entry.kind not in ROW_KINDS or not entry.changed:
                continue
            if entry.imported:
                state = "added"
            elif entry.reason == "restore":
                state = "restored"
            else:
                state = "edited"
            found.append(ChangeRow(doc, entry, state))
        found.extend(ChangeRow(doc, entry, "removed") for entry in doc.removed_rows)
        if not found and doc.dirty:
            found.append(ChangeRow(doc, None, "other"))
        rows.extend(found)
    return rows


def pending_restores(docs) -> str:
    """The footer note for restored backups not written yet, or "" when there are none."""
    names = []
    for doc in docs:
        if doc.restore_pending and doc.dirty:
            where = f" (backup {doc.restored_from.parent.name})" if doc.restored_from else ""
            names.append(doc.path.name + where)
    if not names:
        return ""
    return "Restore pending, not written yet: " + ", ".join(names)


class Payload:
    """What a write would put in one file: the bytes, and which changes they hold.

    ``lines`` is the payload_lines record when some changes are left out,
    or None when the bytes are the whole working copy. ``included`` and
    ``left_out`` count the file's changes (ChangeRow) each way.
    """

    __slots__ = ("data", "lines", "included", "left_out")

    def __init__(self, data: bytes, lines, included: int, left_out: int):
        self.data = data
        self.lines = lines
        self.included = included
        self.left_out = left_out


def build_payload(doc: LncDoc, rows=None) -> Payload:
    """The bytes a reviewed write would put in doc's file, from the include ticks.

    With every change ticked, that is the whole working copy. With some
    left out, it is the file on disk plus the ticked changes; the others
    stay pending in memory after the write. A grouped document (a restored
    backup, see LncDoc.grouped) is all or nothing. ``rows`` are the file's
    changes from collect_changes, when already known.

    Raises:
        UnicodeEncodeError: a ticked change cannot be written in the file's encoding.
    """
    if rows is None:
        rows = collect_changes([doc])
    left_out = sum(1 for row in rows if not row.included)
    included = len(rows) - left_out
    if doc.grouped and left_out:
        return Payload(doc.baseline_bytes, [], 0, left_out)
    if doc.grouped or not left_out:
        return Payload(doc.to_bytes(), None, included, 0)
    lines = payload_lines(doc, lambda entry: not entry.excluded)
    return Payload(doc.encode_text(lines_text(lines)), lines, included, left_out)


class ReviewFile:
    """One file in a reviewed write: where it goes, what is there now, and what it would get."""

    __slots__ = ("doc", "dest", "game", "rows", "current", "read_error", "payload",
                 "encode_error")

    def __init__(self, doc: LncDoc, dest, game: bool):
        self.doc = doc
        self.dest = Path(dest)
        self.game = game                # a game file: archived first, game check applies
        self.rows: list[ChangeRow] = []
        self.current = None             # bytes at dest when reviewed; None if no file
        self.read_error = ""
        self.payload = None             # Payload, or None when it could not be encoded
        self.encode_error = ""

    @property
    def own(self) -> bool:
        """True when the destination is the file the document was read from."""
        return same_path(self.doc.path, self.dest)

    @property
    def backup(self) -> str:
        return "archive" if self.game else "beside"

    @property
    def external(self) -> str:
        """"changed" or "removed" when the file the document came from is not as it was read."""
        if not self.own or self.read_error:
            return ""
        if self.current is None:
            return "removed"
        return "" if self.current == self.doc.baseline_bytes else "changed"

    @property
    def writes(self) -> bool:
        """True when the write would change this file's bytes.

        The document's own file is compared with the bytes it was read as,
        so a file whose changes are all left out is not written at all.
        """
        if self.payload is None:
            return False
        if self.own:
            return self.payload.data != self.doc.baseline_bytes
        return self.read_error != "" or self.payload.data != self.current

    def disk_state(self) -> str:
        """What is at the destination now, in words."""
        if self.read_error:
            return f"could not be read: {self.read_error}"
        if self.own:
            return {
                "": "as the editor read it",
                "changed": "changed on disk since the editor read it",
                "removed": "removed since the editor read it",
            }[self.external]
        if self.current is None:
            return "not there yet; it will be created"
        return "a file the editor did not open; it is replaced whole"

    def write_state(self) -> str:
        """What the write would do to this file, in words."""
        if self.payload is None:
            return "its text cannot be written in its encoding"
        payload = self.payload
        if not self.writes:
            if payload.left_out and not payload.included:
                return f"not written: all {payload.left_out:,} change(s) left out"
            return "not written: it already holds these bytes"
        text = f"{payload.included:,} change(s)"
        if payload.left_out:
            text += f", {payload.left_out:,} left out"
        if self.doc.grouped and payload.included:
            text += ", written together"
        return text


class WriteReview:
    """What a Save or Deploy would write, worked out before anything is written.

    The Review changes dialog shows it. ``pairs`` lists (document,
    destination). ``game_root`` decides which destinations are game files;
    None makes every destination one, as for Deploy. The game check runs
    here, once, when a game file is in the review, and again with
    ``recheck`` just before the write. Every destination is read once, so
    the review can name a file that changed on disk since the editor read
    it, which write_documents refuses. Each file's bytes are built from the
    include ticks (build_payload); a change left out stays pending in
    memory. ``left_alone`` names open documents the operation does not
    write.
    """

    def __init__(self, operation: str, pairs, game_root: Path | None = None,
                 check=None, left_alone=()):
        self.operation = operation
        self.game_root = game_root
        self.left_alone = list(left_alone)
        self.files: list[ReviewFile] = []
        for doc, dest in pairs:
            game = game_root is None or under_game_tree(Path(dest), game_root)
            self.files.append(ReviewFile(doc, dest, game))
        self.preflight = game_write_preflight(
            operation, [item.dest for item in self.files if item.game], None, check)
        self.rows = collect_changes([item.doc for item in self.files])
        for item in self.files:
            item.rows = [row for row in self.rows if row.doc is item.doc]
        self.written = None             # (files, changes, left out) once write() has run
        self.read_disk()
        self.refresh()

    def read_disk(self) -> None:
        """Read every destination as it is now."""
        for item in self.files:
            item.read_error = ""
            try:
                item.current = item.dest.read_bytes()
            except FileNotFoundError:
                item.current = None
            except OSError as exc:
                item.current = None
                item.read_error = str(exc)

    def refresh(self) -> None:
        """Build each file's bytes again from the include ticks."""
        for item in self.files:
            item.encode_error = ""
            try:
                item.payload = build_payload(item.doc, item.rows)
            except UnicodeError as exc:
                item.payload = None
                item.encode_error = str(exc)

    def recheck(self, check=None) -> None:
        """Look for a running copy of the game again, for the game files about to be written."""
        self.preflight = game_write_preflight(
            self.operation, [item.dest for item in self.to_write if item.game], None, check)

    @property
    def to_write(self) -> list[ReviewFile]:
        return [item for item in self.files if item.writes]

    @property
    def included(self) -> int:
        """Ticked changes in the files that would be written."""
        return sum(item.payload.included for item in self.to_write)

    @property
    def left_out(self) -> int:
        return sum(item.payload.left_out for item in self.files if item.payload is not None)

    @property
    def title(self) -> str:
        if self.operation == "Deploy":
            return "Review changes: Deploy to the game folder"
        game = [item for item in self.files if item.game]
        if not game:
            return "Review changes: Save"
        if len(game) == len(self.files):
            return "Review changes: Save into the game folder, the same as Deploy"
        return "Review changes: Save, with the game files handled the same as Deploy"

    def summary(self) -> str:
        files = self.to_write
        if files and self.included:
            text = (f"{self.included:,} change(s) ticked, to be written to "
                    f"{len(files):,} file(s).")
        elif files:
            text = (f"{len(files):,} file(s) to be written as they are open, each replacing "
                    "the file at its destination whole.")
        else:
            text = "Nothing would be written."
        if self.left_out:
            text += f" {self.left_out:,} left out, still pending in memory."
        return text

    def nothing_message(self) -> str:
        if self.rows and not any(row.included for row in self.rows):
            return ("Nothing is ticked, so nothing would be written. Unticked changes stay "
                    "pending in memory.")
        return "The destination files already hold these bytes, so there is nothing to write."

    def problems(self) -> list[str]:
        """Why the write cannot go ahead as it stands; empty when it can."""
        found = []
        writing = self.to_write
        if self.preflight.blocked and any(item.game for item in writing):
            found.append(self.preflight.blocked_message())
        unreadable = [item for item in writing if item.read_error]
        for item in unreadable:
            found.append(f"{item.dest} could not be read: {item.read_error}\n"
                         "Nothing is written until it can be.")
        changed = [item.dest for item in writing if item.external]
        if changed:
            found.append(str(ExternalChangeError(changed)))
        for item in self.files:
            if item.encode_error:
                found.append(f"{item.doc.path.name} holds text that cannot be written as "
                             f"{item.doc.encoding}: {item.encode_error}")
        if not found and not writing:
            found.append(self.nothing_message())
        return found

    def game_check(self) -> tuple[str, str]:
        """The game check as a sentence, and its level: ok, warning, blocked, or muted."""
        if not self.preflight.game_paths:
            return "No game file is written, so the game is not checked.", "muted"
        if self.preflight.blocked:
            return self.preflight.blocked_message(), "blocked"
        if self.preflight.check_failed:
            return self.preflight.unknown_message(), "warning"
        return "Football Manager is not running.", "ok"

    def disk_check(self) -> tuple[str, str]:
        """Changes on disk since the editor read each file, as a sentence and a level."""
        writing = self.to_write
        bad = [item for item in writing if item.external or item.read_error]
        if bad:
            names = ", ".join(f"{item.dest.name} ({item.disk_state()})" for item in bad)
            return (f"{names}. Nothing can be written until the file is as the editor "
                    "read it. Export your edits as a name pack, open the files again, "
                    "and import the pack."), "blocked"
        idle = [item for item in self.files if item.external and item not in writing]
        if idle:
            names = ", ".join(item.dest.name for item in idle)
            return (f"{names} changed on disk since the editor read it, but nothing in it "
                    "is written."), "warning"
        return "No file has changed on disk since the editor read it.", "ok"

    def problem_lines(self) -> list[Entry]:
        return [entry for item in self.files for entry in item.doc.problems()]

    def problem_check(self) -> tuple[str, str]:
        found = self.problem_lines()
        if not found:
            return "No problem lines.", "ok"
        names = sorted({entry.doc.path.name for entry in found})
        return (f"{len(found):,} problem line(s) in {', '.join(names)}. They are written "
                "back exactly as they are."), "warning"

    def repeated_keys(self) -> list[list[Entry]]:
        """Name lines that share a command, ID, and language, across the files reviewed."""
        groups = index_all([item.doc for item in self.files])
        return [rows for rows in groups.values() if len(rows) > 1]

    def repeated_check(self) -> tuple[str, str]:
        groups = self.repeated_keys()
        if not groups:
            return "No command, ID, and language is on more than one line.", "ok"
        competing = sum(1 for rows in groups if len({row.name for row in rows}) > 1)
        text = f"{len(groups):,} command, ID, and language key(s) are on more than one line"
        if competing:
            text += (f"; {competing:,} with different names. The game's order between such "
                     "lines is not known")
        return text + ".", "warning"

    def backup_text(self, archive_root) -> str:
        """Where copies of the files about to be replaced will go."""
        writing = self.to_write
        parts = []
        if any(item.game and item.current is not None for item in writing):
            parts.append(
                f"Backup folder: {Path(archive_root)}{os.sep}YYYYMMDD-HHMMSS, a new folder "
                "named for the time of the write. Each game file is copied there, with a "
                "manifest, before it is replaced.")
        if any(not item.game and item.current is not None for item in writing):
            parts.append("Each file outside the game folder keeps a .bak-<date> copy beside it.")
        if not parts:
            parts.append("No existing file is replaced, so nothing is backed up.")
        return " ".join(parts)

    def plan(self) -> list:
        """The write_documents plan for the files that would change."""
        return [(item.doc, item.dest, item.backup, item.payload) for item in self.to_write]

    def write(self, archive_root) -> Path | None:
        """Write the ticked changes, see write_documents.

        Raises:
            WriteError: the review has a problem (see ``problems``), or a
                write failed; ExternalChangeError and the errors
                write_documents raises pass through.
        """
        problems = self.problems()
        if problems:
            raise WriteError("\n\n".join(problems))
        writing = self.to_write
        beside = any(not item.game and item.current is not None for item in writing)
        self.written = (len(writing), self.included, self.left_out, beside)
        return write_documents(self.operation, self.plan(), archive_root)

    def outcome(self, archive) -> str:
        """The status line after a successful write."""
        files, changes, left_out, beside = self.written or (0, 0, 0, False)
        verb = "Deployed" if self.operation == "Deploy" else "Saved"
        text = f"{verb} {files:,} file(s)"
        text += f" with {changes:,} change(s)." if changes else "."
        if left_out:
            text += f" {left_out:,} left out, still pending in memory."
        if archive is not None:
            text += f" Game files were copied to {archive} first."
        if beside:
            text += " Files outside the game folder kept a .bak-<date> copy beside them."
        return text


def licence_inventory(version_dir: Path) -> list[dict]:
    """Status of each known licensing file. Binary files are not opened."""
    rows = []
    for rel, toggle in (
        *((path, True) for path in MASK_FILES),
        *((path, False) for path in REPORT_FILES),
    ):
        src = version_dir / rel
        disabled = src.with_name(src.name + ".disabled")
        if src.is_file() and disabled.is_file():
            state = "both"
        elif src.is_file():
            state = "present"
        elif disabled.is_file():
            state = "disabled"
        else:
            state = "missing"
        rows.append({
            "rel": rel,
            "name": rel.as_posix(),
            "toggle": toggle,
            "state": state,
            "path": src,
        })
    return rows


LICENCE_INTENTS = ("disable", "restore")


def licence_intent(state: str) -> str:
    """What a toggle of a name-mask file in this state would do: "disable", "restore",
    or "" when the state cannot be toggled (missing, or both names present)."""
    return {"present": "disable", "disabled": "restore"}.get(state, "")


def toggle_licence(version_dir: Path, rel: Path, archive_root: Path, intent: str) -> str:
    """Disable a name-mask file (rename it to `.disabled`), or restore it.

    ``intent`` is what the person confirmed, "disable" or "restore". The
    folder is looked at again here, just before anything happens, and the
    file must still be in the state that intent starts from: a file renamed
    in between is refused, never renamed back the other way. The current
    file is copied into a new backup folder first, with a manifest, through
    write_file_atomically. No bytes are written into the game tree: the
    change is one rename inside one folder, which never replaces a file.
    When both names exist it refuses, because choosing between them is the
    user's call. Nothing is deleted.

    Raises:
        ValueError: not a name-mask file, or an intent other than those two.
        FileExistsError: the file and its ``.disabled`` copy both exist.
        FileNotFoundError: the file the intent would rename is not there.
    """
    if rel not in MASK_FILES:
        raise ValueError(f"Not a name-mask file: {rel}")
    if intent not in LICENCE_INTENTS:
        raise ValueError(f"Not a licensing change: {intent!r}")
    src = version_dir / rel
    disabled = src.with_name(src.name + ".disabled")
    if src.exists() and disabled.exists():
        raise FileExistsError(
            f"Both {src.name} and {disabled.name} are in {src.parent}. The editor will "
            "not choose between them. Move or rename one of them yourself.")
    if intent == "disable":
        current, target, operation, result = src, disabled, "Disable licensing file", "disabled"
    else:
        current, target, operation, result = disabled, src, "Restore licensing file", "restored"
    if not current.is_file():
        raise FileNotFoundError(
            f"{current.name} is not in {current.parent} now, so there is nothing to "
            f"{intent}. It was renamed or moved after the list was read. Nothing was renamed.")
    archive = archive_files([current], archive_root, operation, version_dir.name)
    try:
        os.rename(current, target)
    except OSError:
        finish_manifest(archive, "stopped")
        raise
    finish_manifest(archive, "complete", {str(current): "renamed"})
    return result


def preview_replace(docs, pattern: str, replacement: str, section: str = "",
                    ignore_case: bool = False):
    """Preview a regular-expression replace on name lines.

    Returns ``(edits, skipped, error)``. ``error`` is set when the pattern
    is empty or illegal, and ``edits`` is then empty. ``skipped`` counts
    substitutions that would not be a legal name. An empty ``section``
    covers every section. A section matches the whole heading, ignoring
    accents and capitals. Nothing is written.
    """
    if not pattern:
        return [], 0, "Enter a pattern."
    flags = re.IGNORECASE if ignore_case else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return [], 0, f"That pattern is not a valid regular expression: {exc}"
    wanted = fold(section)
    edits = []
    skipped = 0
    for doc in docs:
        for entry in doc.names():
            if wanted and fold(entry.section) != wanted:
                continue
            try:
                after = compiled.sub(replacement, entry.name)
            except re.error as exc:
                return [], 0, f"That replacement is not valid: {exc}"
            if after == entry.name:
                continue
            if not name_is_legal(after):
                skipped += 1
                continue
            edits.append(BulkEdit(None, "", entry, entry.name, after))
    return edits, skipped, ""


def pack_document(docs, changed_only: bool = True) -> dict:
    """Build a name pack from database-id name lines.

    Person-name rules are not included. They are not keyed by database id.
    """
    names = []
    for doc in docs:
        for entry in doc.names():
            if changed_only and not entry.changed:
                continue
            names.append({
                "command": entry.cmd,
                "id": entry.id,
                "language": entry.lang,
                "name": entry.name,
            })
    return {"format": PACK_FORMAT, "version": PACK_VERSION, "names": names}


def pack_to_json(pack: dict) -> str:
    return json.dumps(pack, ensure_ascii=False, indent=2) + "\n"


def pack_to_csv(pack: dict) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=["command", "id", "language", "name"],
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in pack["names"]:
        writer.writerow({key: row[key] for key in writer.fieldnames})
    return buffer.getvalue()


def _pack_row(raw: dict) -> dict | None:
    """Return a clean pack row, or None when the row cannot be applied.

    Every field is checked, the language included, so a pack cannot write
    a second record into the file through a quote or a line break.
    """
    cmd = str(raw.get("command", "")).strip()
    id_ = str(raw.get("id", "")).strip()
    lang = str(raw.get("language", "")).strip()
    name = str(raw.get("name", "")).strip()
    if (
        not is_name_command(cmd)
        or not id_is_legal(id_)
        or not name_is_legal(name)
        or not field_is_legal(lang)
    ):
        return None
    return {"command": cmd, "id": id_, "language": lang, "name": name}


def parse_pack(text: str, kind: str) -> tuple[list[dict], int, str]:
    """Read a JSON or CSV name pack.

    Returns ``(rows, skipped, error)``. ``skipped`` counts rows that are
    not legal name lines. ``error`` is set when the file is not a pack.
    """
    if kind == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return [], 0, f"That JSON pack could not be read: {exc}"
        if not isinstance(payload, dict):
            return [], 0, "A JSON name pack must be an object with a names list."
        if payload.get("format") != PACK_FORMAT:
            return [], 0, f"This file is not an {PACK_FORMAT} pack."
        version = payload.get("version")
        if version != PACK_VERSION:
            return [], 0, (
                f"This pack is version {version}. This editor reads version {PACK_VERSION}.")
        raw_rows = payload.get("names")
        if not isinstance(raw_rows, list):
            return [], 0, "The pack has no names list."
    elif kind == "csv":
        try:
            reader = csv.DictReader(io.StringIO(text))
        except csv.Error as exc:
            return [], 0, f"That CSV pack could not be read: {exc}"
        fieldnames = reader.fieldnames or []
        mapped = {}
        for field in fieldnames:
            if field is None:
                continue
            mapped[field.strip().lstrip("\ufeff").casefold()] = field
        required = {"command", "id", "language", "name"}
        if not required <= set(mapped):
            return [], 0, "A CSV pack needs the columns command, id, language, and name."
        raw_rows = []
        try:
            for record in reader:
                raw_rows.append({
                    "command": record.get(mapped["command"], ""),
                    "id": record.get(mapped["id"], ""),
                    "language": record.get(mapped["language"], ""),
                    "name": record.get(mapped["name"], ""),
                })
        except csv.Error as exc:
            return [], 0, f"That CSV pack could not be read: {exc}"
    else:
        return [], 0, "Choose a JSON or CSV name pack."
    rows = []
    skipped = 0
    for raw in raw_rows:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        cleaned = _pack_row(raw)
        if cleaned is None:
            skipped += 1
            continue
        rows.append(cleaned)
    return rows, skipped, ""


def proposals_from_pack(docs, rows: list[dict]):
    """Turn pack rows into the same proposals the older-file import uses.

    Differing names are pre-ticked. Rows that are not in the open files
    stay unticked. A repeated key keeps the last spelling.
    """
    targets = index_all(docs)
    changes, missing = [], []
    stats = {"rows": len(rows), "same": 0, "skipped": 0, "duplicate": 0}
    seen: dict = {}
    order: list = []
    for raw in rows:
        cleaned = raw if "command" in raw else None
        if cleaned is None:
            stats["skipped"] += 1
            continue
        key = (cleaned["command"], cleaned["id"], cleaned["language"].casefold())
        if key in seen:
            stats["duplicate"] += 1
        else:
            order.append(key)
        seen[key] = cleaned
    for key in order:
        row = seen[key]
        found = targets.get(key, [])
        current = found[-1] if found else None
        note = "From name pack"
        if current is None:
            missing.append(Proposal(
                row["command"], row["id"], row["language"], row["name"],
                None, "", False, "", note))
            continue
        if all(entry.name == row["name"] for entry in found):
            stats["same"] += 1
            continue
        if len(found) > 1:
            note = f"{note}; Duplicate id ({len(found)} rows)"
        changes.append(Proposal(
            row["command"], row["id"], row["language"], row["name"],
            current, current.section, True, "", note, found))
    return changes, missing, stats


# ---- spelling profiles -----------------------------------------------------

_RESERVED_STEMS = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)])


def profile_key(command: str, id_: str, language: str) -> tuple:
    """The identity of a profile row. It matches Entry.key."""
    return (command, id_, language.casefold())


def _profile_row_order(row: dict):
    return (row["command"], int(row["id"]), row["language"].casefold())


class Profile:
    """A named set of preferred spellings that outlives Save and Deploy.

    ``rows`` maps profile_key to a row: command, id, language, the preferred
    ``name``, the ``baseline`` (the name the file on disk had when the
    preference was recorded, or None when it had no such line), the
    ``source`` file, the SHA-256 of that file as it was then, and when it
    was recorded. The baseline lets Apply tell an unchanged file from one
    the game has changed since. A profile is not a name pack: packs are for
    exchange and keep their own format.
    """

    __slots__ = ("name", "note", "rows", "path", "created", "updated")

    def __init__(self, name: str, note: str = "", path=None, created: str = "",
                 updated: str = ""):
        now = datetime.now().isoformat(timespec="seconds")
        self.name = name
        self.note = note
        self.rows: dict = {}
        self.path = Path(path) if path is not None else None
        self.created = created or now
        self.updated = updated or self.created

    def copy(self) -> "Profile":
        twin = Profile(self.name, self.note, self.path, self.created, self.updated)
        twin.rows = {key: dict(row) for key, row in self.rows.items()}
        return twin

    def to_bytes(self) -> bytes:
        """UTF-8 JSON, rows in a fixed order, so an unchanged profile writes the same bytes."""
        payload = {
            "format": PROFILE_FORMAT,
            "version": PROFILE_VERSION,
            "name": self.name,
            "note": self.note,
            "created": self.created,
            "updated": self.updated,
            "rows": sorted(self.rows.values(), key=_profile_row_order),
        }
        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def label_problem(name: str, existing=(), own=None, kind: str = "profile") -> str:
    """Why ``name`` cannot name a profile, collection, or saved search; "" when it can.

    ``existing`` holds things with a ``name``; a name must differ from
    theirs, ignoring case. ``own`` is the one being renamed, which may keep
    its name. ``kind`` words the message.
    """
    cleaned = name.strip()
    if not cleaned:
        return f"Give the {kind} a name."
    if len(cleaned) > 80:
        return "Keep the name to 80 characters or fewer."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return f"A {kind} name cannot contain control characters."
    for other in existing:
        if other is not own and other.name.casefold() == cleaned.casefold():
            return f"There is already a {kind} called {other.name}."
    return ""


def profile_name_problem(name: str, existing=(), own=None) -> str:
    """Why ``name`` cannot name a profile, or "" when it can (see label_problem)."""
    return label_problem(name, existing, own, "profile")


def _check_profile_row(where: str, raw) -> dict:
    """A clean copy of one stored row. Raises ValueError, naming ``where``, when it cannot be used."""
    if not isinstance(raw, dict):
        raise ValueError(f"{where} is not a row of names.")
    cmd = raw.get("command")
    id_ = raw.get("id")
    if isinstance(id_, int) and not isinstance(id_, bool):
        id_ = str(id_)
    lang = raw.get("language", "")
    name = raw.get("name")
    baseline = raw.get("baseline")
    if not (isinstance(cmd, str) and is_name_command(cmd)):
        raise ValueError(f"{where}: {cmd!r} is not a name command.")
    if not (isinstance(id_, str) and id_is_legal(id_)):
        raise ValueError(f"{where}: {id_!r} is not a database id.")
    if not (isinstance(lang, str) and field_is_legal(lang)):
        raise ValueError(f"{where}: the language cannot sit in one quoted field.")
    if not (isinstance(name, str) and name_is_legal(name)):
        raise ValueError(f"{where}: the name cannot sit in one quoted field.")
    if baseline is not None and not (isinstance(baseline, str) and field_is_legal(baseline)):
        raise ValueError(f"{where}: the baseline cannot sit in one quoted field.")
    return {
        "command": cmd,
        "id": id_,
        "language": lang,
        "name": name,
        "baseline": baseline,
        "source": str(raw.get("source", "")),
        "source_sha256": str(raw.get("source_sha256", "")),
        "recorded": str(raw.get("recorded", "")),
    }


def load_profile(path) -> Profile:
    """Read one profile file.

    Raises:
        OSError: the file could not be read.
        ValueError: it is not a profile this editor can use; the message says why.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:       # bad UTF-8 or bad JSON
        raise ValueError(f"{path.name} could not be read as a profile: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
        raise ValueError(f"{path.name} is not a spelling profile.")
    if data.get("version") != PROFILE_VERSION:
        raise ValueError(
            f"{path.name} is profile version {data.get('version')}. "
            f"This editor reads version {PROFILE_VERSION}.")
    name, note = data.get("name"), data.get("note", "")
    if not isinstance(name, str) or profile_name_problem(name):
        raise ValueError(f"{path.name} has no usable profile name.")
    if not isinstance(note, str):
        raise ValueError(f"{path.name} has a note that is not text.")
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{path.name} has no list of rows.")
    profile = Profile(name.strip(), note, path, str(data.get("created", "")),
                      str(data.get("updated", "")))
    for number, raw in enumerate(rows, 1):
        row = _check_profile_row(f"{path.name}, row {number}", raw)
        key = profile_key(row["command"], row["id"], row["language"])
        if key in profile.rows:
            raise ValueError(
                f"{path.name}, row {number}: an earlier row has the same command, "
                "id, and language.")
        profile.rows[key] = row
    return profile


def list_profiles(root) -> tuple[list, list]:
    """Read every profile in ``root``. Returns (profiles sorted by name, problems).

    A file that cannot be read is described in ``problems`` and left alone.
    Only the folder itself is read, so profiles in ``deleted`` are not listed.
    """
    root = Path(root)
    if not root.is_dir():
        return [], []
    profiles, problems = [], []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            profiles.append(load_profile(path))
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    profiles.sort(key=lambda item: (item.name.casefold(), item.path.name.casefold()))
    return profiles, problems


def _profile_slug(name: str) -> str:
    """A safe file-name stem for a profile: plain letters and digits joined by hyphens."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.casefold()).strip("-")[:60].strip("-")
    if not slug:
        slug = "profile"
    if slug in _RESERVED_STEMS:
        slug += "-profile"
    return slug


def _free_profile_path(root: Path, name: str, own=None) -> Path:
    """Where a profile called ``name`` should live: a file no other profile uses."""
    stem = _profile_slug(name)
    candidate = Path(root) / f"{stem}.json"
    count = 1
    while candidate.exists() and not (own is not None and same_path(candidate, own)):
        count += 1
        candidate = Path(root) / f"{stem}-{count}.json"
    return candidate


def save_profile(profile: Profile, root) -> Path:
    """Write a profile through write_file_atomically and return its path.

    A profile without a path gets a new file in ``root``, named after it.
    ``updated`` becomes now, but only once the write has succeeded.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = profile.path if profile.path is not None else _free_profile_path(root, profile.name)
    previous = profile.updated
    profile.updated = datetime.now().isoformat(timespec="seconds")
    try:
        write_file_atomically(path, profile.to_bytes())
    except BaseException:
        profile.updated = previous
        raise
    profile.path = path
    return path


def create_profile(name: str, note: str, root, existing=()) -> Profile:
    """Make and save a new, empty profile.

    Raises:
        ValueError: the name cannot be used (see profile_name_problem).
        OSError: the file could not be written.
    """
    problem = profile_name_problem(name, existing)
    if problem:
        raise ValueError(problem)
    profile = Profile(name.strip(), note.strip())
    save_profile(profile, root)
    return profile


def rename_profile(profile: Profile, new_name: str, note, root, existing=()) -> Profile:
    """Give a profile a new name, and a new note unless ``note`` is None.

    The renamed copy is written to a file that matches its new name first,
    and only then is the old file removed, so a failure part-way leaves at
    least one whole copy. Returns the renamed profile.

    Raises:
        ValueError: the name cannot be used.
        OSError: a file could not be written or removed.
    """
    problem = profile_name_problem(new_name, existing, own=profile)
    if problem:
        raise ValueError(problem)
    twin = profile.copy()
    twin.name = new_name.strip()
    if note is not None:
        twin.note = note.strip()
    old_path = profile.path
    twin.path = _free_profile_path(Path(root), twin.name, own=old_path)
    save_profile(twin, root)
    if old_path is not None and not same_path(old_path, twin.path):
        old_path.unlink(missing_ok=True)
    return twin


def delete_profile(profile: Profile, root) -> Path:
    """Move a profile's file into ``root/deleted``, where it can be recovered by hand.

    Nothing is erased. Returns where the file went.
    """
    if profile.path is None:
        raise FileNotFoundError(f"The profile {profile.name} has no file.")
    bin_folder = Path(root) / "deleted"
    bin_folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = bin_folder / f"{profile.path.stem}-{stamp}.json"
    count = 1
    while target.exists():
        count += 1
        target = bin_folder / f"{profile.path.stem}-{stamp}-{count}.json"
    os.rename(profile.path, target)     # one step; never replaces a file on Windows
    return target


def record_edits(profile: Profile, docs) -> dict:
    """Copy the open files' unsaved name edits into ``profile``, with their baselines.

    A name line is recorded when it differs from the file on disk
    (``Entry.changed``): an edited name, whose baseline is the text on
    disk, or an added line, whose baseline is None because the file has no
    such line. The newer spelling replaces a row the profile already has.
    Edits that were saved are part of the file on disk now, so they are not
    edits any more: record before Save or Deploy. Person rules are not keyed
    by database id, and rows a restore left out are not spellings, so
    neither is recorded; both are counted. A row with a field that could
    not be written as one line is skipped and counted. When a key is on
    several edited lines, the last is recorded.

    Only memory changes; save the profile afterwards. Returns counts for
    "added", "updated", "same", "persons", "removed", "skipped", "repeated".
    """
    counts = dict.fromkeys(
        ("added", "updated", "same", "persons", "removed", "skipped", "repeated"), 0)
    stamp = datetime.now().isoformat(timespec="seconds")
    latest: dict = {}
    for doc in docs:
        counts["persons"] += sum(1 for entry in doc.persons() if entry.changed)
        counts["removed"] += len(doc.removed_rows)
        source_hash = sha256_hex(doc.baseline_bytes)
        for entry in doc.names():
            if not entry.changed:
                continue
            baseline = None if entry.imported else entry.orig_name
            if (not is_name_command(entry.cmd) or not id_is_legal(entry.id)
                    or not name_is_legal(entry.name) or not field_is_legal(entry.lang)
                    or (baseline is not None and not field_is_legal(baseline))):
                counts["skipped"] += 1
                continue
            if entry.key in latest:
                counts["repeated"] += 1
            latest[entry.key] = {
                "command": entry.cmd,
                "id": entry.id,
                "language": entry.lang,
                "name": entry.name,
                "baseline": baseline,
                "source": str(doc.path),
                "source_sha256": source_hash,
                "recorded": stamp,
            }
    for key, row in latest.items():
        old = profile.rows.get(key)
        if old is not None and (old["name"], old["baseline"]) == (row["name"], row["baseline"]):
            counts["same"] += 1
            continue
        counts["updated" if old is not None else "added"] += 1
        profile.rows[key] = row
    return counts


def _shown(text) -> str:
    return "no line" if text is None else text


def apply_profile(profile: Profile, docs):
    """Turn a profile into proposals for the open files, for the usual preview.

    A row's open baseline is the text on disk for its key, or None when no
    line on disk has it. A proposal is ticked only when that still equals
    the baseline the row was recorded with, so a spelling the game has
    changed since is looked at before it is replaced. It is left unticked,
    with a note, when the baseline differs, when the line has an unsaved
    edit of its own, or when another profile set it in this session. When
    a key is on several lines, Apply writes the preferred name into each,
    so every line it would change is looked at, whatever their order, and
    the note says which file and line each finding is on; lines that
    already read the preferred name are left as they are. A row the open
    files lack becomes an added line in the open file it was recorded
    from; when no open file has that name it is counted under "elsewhere"
    and left out. Rows that already read the preferred name are counted
    as "same".

    Nothing changes yet. Returns (changes, missing, stats); apply the
    ticked ones with apply_profile_proposals.
    """
    targets = index_all(docs)
    by_file: dict = {}
    for doc in docs:
        by_file.setdefault(doc.path.name.casefold(), doc)
    changes, missing = [], []
    stats = dict.fromkeys(("rows", "same", "ticked", "review", "elsewhere"), 0)
    stats["rows"] = len(profile.rows)
    for row in sorted(profile.rows.values(), key=_profile_row_order):
        cmd, id_, lang = row["command"], row["id"], row["language"]
        preferred, recorded = row["name"], row["baseline"]
        found = targets.get(profile_key(cmd, id_, lang), [])
        if not found:
            doc = by_file.get(Path(row["source"]).name.casefold())
            if doc is None:
                stats["elsewhere"] += 1
                continue
            ticked = recorded is None
            if ticked:
                note = "Added line; the file still has no line for it"
            else:
                note = (f"Baseline changed: the file has no line for it now; when "
                        f"recorded it said {recorded}")
            stats["ticked" if ticked else "review"] += 1
            missing.append(Proposal(
                cmd, id_, lang, preferred, None, "", ticked, recorded or "", note, doc=doc))
            continue
        if all(entry.name == preferred for entry in found):
            stats["same"] += 1
            continue
        # Every line Apply would change counts, not only the last: one with an
        # unsaved edit, another profile's spelling, or a name the game changed
        # since leaves the whole proposal unticked (note 05, finding 3).
        changing = [entry for entry in found if entry.name != preferred]
        current = changing[-1]
        notes = []
        for entry in changing:
            where = f" ({describe_lines([entry])})" if len(found) > 1 else ""
            mark = entry.profile_mark
            if mark is not None and mark[0] != profile.name and entry.name == mark[1]:
                notes.append(f"Competes with profile {mark[0]}, which set {mark[1]} in this "
                             f"session{where}")
            elif entry.changed:
                notes.append(f"Unsaved edit {entry.name} would be replaced{where}")
            on_disk = None if entry.imported else entry.orig_name
            if on_disk != recorded:
                notes.append(f"Baseline changed: the file says {_shown(on_disk)}; when "
                             f"recorded it said {_shown(recorded)}{where}")
        ticked = not notes
        if len(found) > 1:
            notes.append(f"Duplicate id ({len(found)} rows)")
        stats["ticked" if ticked else "review"] += 1
        changes.append(Proposal(
            cmd, id_, lang, preferred, current, current.section, ticked,
            recorded or "", "; ".join(notes) or "Baseline unchanged", found))
    return changes, missing, stats


def describe_profile_apply(profile: Profile, stats: dict) -> str:
    """The summary line for the Apply preview."""
    parts = [
        f"{stats['rows']:,} spelling(s) in {profile.name}.",
        f"{stats['same']:,} already match.",
        f"{stats['ticked']:,} ticked: the file still has the name they were recorded against.",
    ]
    if stats["review"]:
        parts.append(f"{stats['review']:,} left unticked for you to check; the note says why.")
    if stats["elsewhere"]:
        parts.append(
            f"{stats['elsewhere']:,} belong to a file that is not open, so they are left out.")
    parts.append("Nothing is written until you Save or Deploy.")
    return " ".join(parts)


MIGRATION_STATES = {
    "eligible": "Carries forward",
    "already_preferred": "Already the new spelling",
    "conflict": "Upstream changed since recorded",
    "missing": "Not present in the new files",
    "blocked": "Unsaved edit or competing profile",
}


def migrate_profile(profile: Profile, docs):
    """Three-way migration: compare the profile baseline, the preference, and the new files.

    For each profile row (command, id, language):

    - The key is not on any open line: the new files lack it. A row that
      was recorded as a *new line* (``baseline is None``) stays an addition,
      pre-ticked. A row that was recorded against a baseline is left
      unticked with "Not present in the new files".
    - All matching open lines already read the preference: counted as
      already-preferred; nothing to do.
    - At least one matching open line has a different name: the proposal
      asks to replace them with the preference. It is ticked only when
      every line Apply would change still reads the recorded baseline on
      disk, has no unsaved edit, and is not held by another profile.
      Otherwise it is unticked and the note says what the new files now
      say, or which blocker (unsaved edit, competing profile, duplicate)
      stops it; the proposal is counted as a conflict when the new files
      disagree with the recorded baseline, or blocked when it is held by
      a line's own state.

    Rows belonging to a file that is not open are counted as elsewhere.
    Nothing is changed yet; apply the ticked ones with
    ``apply_profile_proposals``.
    """
    targets = index_all(docs)
    by_file: dict = {}
    for doc in docs:
        by_file.setdefault(doc.path.name.casefold(), doc)
    changes, missing = [], []
    stats = dict.fromkeys(
        ("rows", "eligible", "already_preferred", "conflict", "missing",
         "blocked", "elsewhere"), 0)
    stats["rows"] = len(profile.rows)
    for row in sorted(profile.rows.values(), key=_profile_row_order):
        cmd, id_, lang = row["command"], row["id"], row["language"]
        preferred, recorded = row["name"], row["baseline"]
        found = targets.get(profile_key(cmd, id_, lang), [])
        if not found:
            doc = by_file.get(Path(row["source"]).name.casefold())
            if doc is None:
                stats["elsewhere"] += 1
                continue
            if recorded is None:
                stats["eligible"] += 1
                missing.append(Proposal(
                    cmd, id_, lang, preferred, None, "", True,
                    "", "Added line; the new files still have no line for it", doc=doc))
            else:
                stats["missing"] += 1
                missing.append(Proposal(
                    cmd, id_, lang, preferred, None, "", False,
                    recorded,
                    f"Not present in the new files; when recorded it said {_shown(recorded)}",
                    doc=doc))
            continue
        if all(entry.name == preferred for entry in found):
            stats["already_preferred"] += 1
            continue
        changing = [entry for entry in found if entry.name != preferred]
        current = changing[-1]
        blockers: list[str] = []
        drift = False
        for entry in changing:
            where = f" ({describe_lines([entry])})" if len(found) > 1 else ""
            mark = entry.profile_mark
            if mark is not None and mark[0] != profile.name and entry.name == mark[1]:
                blockers.append(
                    f"Competes with profile {mark[0]}, which set {mark[1]} in this session{where}")
            elif entry.changed:
                blockers.append(f"Unsaved edit {entry.name} would be replaced{where}")
            on_disk = None if entry.imported else entry.orig_name
            if on_disk != recorded:
                drift = True
                blockers.append(
                    f"Upstream changed since recorded: the new files say {_shown(on_disk)}; "
                    f"when recorded it said {_shown(recorded)}{where}")
        ticked = not blockers
        if len(found) > 1:
            blockers.append(f"Duplicate id ({len(found)} rows)")
        if ticked:
            stats["eligible"] += 1
            note = "Carries forward: the new files still have the recorded baseline"
        else:
            stats["conflict" if drift else "blocked"] += 1
            note = "; ".join(blockers)
        changes.append(Proposal(
            cmd, id_, lang, preferred, current, current.section, ticked,
            recorded or "", note, found))
    return changes, missing, stats


def describe_profile_migration(profile: Profile, stats: dict) -> str:
    """The summary line for the Migrate preview."""
    parts = [f"{stats['rows']:,} spelling(s) in {profile.name}."]
    if stats["already_preferred"]:
        parts.append(f"{stats['already_preferred']:,} already match the new files.")
    parts.append(
        f"{stats['eligible']:,} ticked to carry forward: the new files still have the "
        "recorded baseline.")
    if stats["conflict"]:
        parts.append(
            f"{stats['conflict']:,} unticked because the new files changed those spellings; "
            "the note says what they now say.")
    if stats["missing"]:
        parts.append(
            f"{stats['missing']:,} unticked because the key is not present in the new files.")
    if stats["blocked"]:
        parts.append(
            f"{stats['blocked']:,} unticked because of an unsaved edit or another profile; "
            "the note says why.")
    if stats["elsewhere"]:
        parts.append(
            f"{stats['elsewhere']:,} belong to a file that is not open, so they are left out.")
    parts.append("Nothing is written until you Save or Deploy.")
    return " ".join(parts)


def apply_profile_proposals(profile_name: str, changes, missing, docs):
    """Apply the ticked profile proposals in memory and note which profile set each line.

    The note lets a later Apply of another profile show the competing
    spelling. Returns what apply_proposals returns.
    """
    count, added = apply_proposals(changes, missing, docs, "profile")
    for proposal in changes:
        if not proposal.checked:
            continue
        for entry in proposal.target_rows:
            if entry.name == proposal.new:
                entry.profile_mark = (profile_name, proposal.new)
    for entry in added:
        entry.profile_mark = (profile_name, entry.name)
    return count, added


class DamagedFileError(OSError):
    """A local file the editor keeps is damaged, so it is not written over.

    ``path`` is the file and the message says what is wrong with it. The
    file is left exactly as it is, for the person to put right or move away.
    """

    def __init__(self, path, problem: str):
        super().__init__(problem)
        self.path = Path(path)


def read_state(root) -> tuple[dict, str]:
    """The editor's local settings, and what is wrong with the file, if anything.

    Returns (settings, problem). A missing file holds no settings: ({}, "").
    A file that cannot be read, is not UTF-8 JSON, or does not hold one
    JSON object is damaged: ({}, a sentence naming the file and what is
    wrong). A damaged file is left alone: save_state will not write over it.
    """
    path = Path(root) / STATE_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, ""
    except OSError as exc:
        return {}, f"{path} could not be read: {exc.strerror or exc}."
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeError:
        return {}, f"{path} is not UTF-8 text."
    except ValueError as exc:
        return {}, f"{path} is not readable JSON: {exc}."
    if not isinstance(data, dict):
        return {}, f"{path} does not hold settings: it should be one JSON object."
    return data, ""


def load_state(root) -> dict:
    """The editor's local settings. A missing or damaged file reads as empty (see read_state)."""
    return read_state(root)[0]


def save_state(state: dict, root) -> None:
    """Write the local settings through write_file_atomically.

    Raises:
        DamagedFileError: the settings file on disk is damaged (see
            read_state). It is left exactly as it is, never written over.
        OSError: the file could not be written.
    """
    root = Path(root)
    _settings, problem = read_state(root)
    if problem:
        raise DamagedFileError(root / STATE_FILE, problem)
    root.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_file_atomically(root / STATE_FILE, text.encode("utf-8"))


# ---- collections, saved searches, and the remembered view (Session 8) ------

COLLECTIONS_FILE = "collections.json"
COLLECTIONS_FORMAT = "fm-name-collections"
COLLECTIONS_VERSION = 1
# The entity grid's status filters. The keys are what the settings file stores.
STATUS_FILTERS = {
    "all": "All",
    "edited": "Edited",
    "missing_short": "No short-name override",
    "missing_code": "No code override",
    "health": "Name health",        # Session 21: names with something to check
}
# The All lines columns, as the line model and the settings file name them.
LINE_COLUMNS = ("section", "type", "id", "name", "lang", "file", "status")


def _entity_columns(family: str) -> tuple:
    return ("section", "id", *(slot for slot, _label, _cmd in FAMILY_FIELDS[family]),
            *(("lang",) if family == "award" else ()), "status")


def entity_key(entity: NameEntity) -> tuple:
    """(family, id, language): how a collection names an entity."""
    return (entity.family, entity.id, entity.lang)


def _key_order(key: tuple):
    return (key[0], _id_number(key[1]), key[1], key[2])


class Collection:
    """A set of entities the user named, such as "My save" or "Names to review".

    Collections are kept in ``state\\collections.json``, never in the name
    files, and the window lists them apart from file sections, which are
    only the comment headings in the files.
    """

    __slots__ = ("name", "keys", "created", "updated")

    def __init__(self, name: str, keys=(), created: str = "", updated: str = ""):
        self.name = name
        self.keys: set = set(keys)
        self.created = created or datetime.now().isoformat(timespec="seconds")
        self.updated = updated or self.created

    def add(self, keys) -> int:
        """Add entity keys. Returns how many were not in the collection already."""
        new = set(keys) - self.keys
        if new:
            self.keys |= new
            self.updated = datetime.now().isoformat(timespec="seconds")
        return len(new)

    def remove(self, keys) -> int:
        """Take entity keys out. Returns how many were in the collection."""
        gone = self.keys & set(keys)
        if gone:
            self.keys -= gone
            self.updated = datetime.now().isoformat(timespec="seconds")
        return len(gone)

    def count_in(self, family: str) -> int:
        return sum(1 for key in self.keys if key[0] == family)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "created": self.created,
            "updated": self.updated,
            "members": [{"family": family, "id": id_, "language": lang}
                        for family, id_, lang in sorted(self.keys, key=_key_order)],
        }


class CollectionFile:
    """What ``state\\collections.json`` holds: the collections in name order, and the
    deleted ones, kept so they can be recovered by hand."""

    def __init__(self, collections=(), deleted=()):
        self.collections: list[Collection] = sorted(collections, key=lambda c: fold(c.name))
        self.deleted: list[dict] = list(deleted)

    def find(self, name: str):
        for collection in self.collections:
            if collection.name.casefold() == name.casefold():
                return collection
        return None

    def add(self, collection: Collection) -> None:
        self.collections.append(collection)
        self.collections.sort(key=lambda c: fold(c.name))

    def delete(self, collection: Collection) -> None:
        """Move a collection into the deleted list, with the time it went."""
        self.collections.remove(collection)
        kept = collection.to_json()
        kept["deleted"] = datetime.now().isoformat(timespec="seconds")
        self.deleted.append(kept)

    def to_bytes(self) -> bytes:
        data = {
            "format": COLLECTIONS_FORMAT,
            "version": COLLECTIONS_VERSION,
            "collections": [c.to_json() for c in sorted(self.collections,
                                                         key=lambda c: fold(c.name))],
            "deleted": self.deleted,
        }
        return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def collection_name_problem(name: str, store: CollectionFile, own=None) -> str:
    return label_problem(name, store.collections, own, "collection")


def load_collection_file(root) -> CollectionFile:
    """Read ``collections.json``. A missing file is an empty one.

    Raises:
        ValueError: the file cannot be read or is not a collections file;
            the message names the file and, where it can, the collection.
            The window then leaves the file alone.
    """
    path = Path(root) / COLLECTIONS_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return CollectionFile()
    except OSError as exc:
        raise ValueError(f"{path} could not be read: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"{path} is not readable JSON: {exc}") from exc
    if (not isinstance(data, dict) or data.get("format") != COLLECTIONS_FORMAT
            or data.get("version") != COLLECTIONS_VERSION):
        raise ValueError(f"{path} is not a version {COLLECTIONS_VERSION} collections file.")
    # Every value is checked for its type before it is used, so a hand-edited
    # file with a number or a list in the wrong place is a damaged file
    # (ValueError, named in the panel), never a crash when the window opens.
    listed = data.get("collections") or []
    if not isinstance(listed, list):
        raise ValueError(f"{path} has a damaged list of collections.")
    found = []
    for number, item in enumerate(listed, 1):
        where = f"{path}, collection {number}"
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError(f"{where} has no name.")
        name = item["name"].strip()
        problem = label_problem(name, found, None, "collection")
        if problem:
            raise ValueError(f"{where}: {problem}")
        members = item.get("members") or []
        if not isinstance(members, list):
            raise ValueError(f"{where} ({name}) has a damaged list of members.")
        keys = []
        for member in members:
            family = member.get("family") if isinstance(member, dict) else None
            id_ = member.get("id") if isinstance(member, dict) else None
            lang = member.get("language", "") if isinstance(member, dict) else None
            if (not isinstance(family, str) or family not in FAMILY_FIELDS
                    or not isinstance(id_, str) or not id_is_legal(id_)
                    or not isinstance(lang, str) or not field_is_legal(lang)):
                raise ValueError(f"{where} ({name}) has a member that is not a family, "
                                 f"an ID, and a language: {member!r}")
            keys.append((family, id_, lang))
        found.append(Collection(name, keys, str(item.get("created") or ""),
                                str(item.get("updated") or "")))
    deleted = data.get("deleted") or []
    if not isinstance(deleted, list) or not all(isinstance(item, dict) for item in deleted):
        raise ValueError(f"{path} has a damaged list of deleted collections.")
    return CollectionFile(found, deleted)


def save_collection_file(store: CollectionFile, root) -> None:
    """Write ``collections.json`` through write_file_atomically. The same collections
    write the same bytes."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    write_file_atomically(root / COLLECTIONS_FILE, store.to_bytes())


class SavedSearch:
    """A named entity search: the family, the words, the status filter, and the file
    section or collection shown. Kept in the settings file under "saved_searches"."""

    __slots__ = ("name", "family", "text", "status", "section", "collection")
    FIELDS = ("family", "text", "status", "section", "collection")

    def __init__(self, name: str, family: str = "club", text: str = "", status: str = "all",
                 section: str = "", collection: str = ""):
        self.name = name
        self.family = family
        self.text = text
        self.status = status
        self.section = section
        self.collection = collection

    def to_json(self) -> dict:
        return {"name": self.name, **{field: getattr(self, field) for field in self.FIELDS}}


def clean_saved_searches(raw) -> list[SavedSearch]:
    """The saved searches in the settings file that the window can use, in their order.

    One with a name that is empty, too long, or already used, an unknown
    family or status filter, or a field that is not text (a number, a
    list, null) is left out. A missing field takes its default (Clubs, All,
    no words). Types are checked before anything else, so no value in a
    hand-edited file can stop the window opening.
    """
    found: list[SavedSearch] = []
    defaults = {"family": "club", "text": "", "status": "all", "section": "", "collection": ""}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"].strip()
        values = {field: item.get(field, defaults[field]) for field in SavedSearch.FIELDS}
        if (not all(isinstance(value, str) for value in values.values())
                or label_problem(name, found, None, "saved search")
                or values["family"] not in FAMILY_FIELDS
                or values["status"] not in STATUS_FILTERS):
            continue
        found.append(SavedSearch(name, **values))
    return found


def _clean_sort(raw, allowed) -> dict | None:
    if (isinstance(raw, dict) and isinstance(raw.get("key"), str)
            and isinstance(raw.get("descending"), bool)
            and (raw["key"] == "" or raw["key"] in allowed)):
        return {"key": raw["key"], "descending": raw["descending"]}
    return None


def _clean_widths(raw, allowed) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {key: width for key, width in raw.items()
            if key in allowed and isinstance(width, int) and not isinstance(width, bool)
            and 20 <= width <= 2000}


def clean_view(raw) -> dict:
    """The remembered view from the settings file, keeping only what the window can use.

    Keys: "tab", "family", "status", "entity_sort" and "line_sort" (key and
    descending), "entity_widths" (per family, per column key), "line_widths",
    "inspector" and "id_column" (shown or hidden; the entity grid's ID column
    since Session 19), and "geometry", "window_state", and "splitter" (base64 text from Qt). A
    value of the wrong type or out of range is dropped, so an older or
    hand-edited settings file cannot stop the window opening. Each type is
    checked before the value is looked up: a list or an object cannot be.
    """
    view: dict = {}
    if not isinstance(raw, dict):
        return view
    tab = raw.get("tab")
    if isinstance(tab, int) and not isinstance(tab, bool) and 0 <= tab <= 2:
        view["tab"] = tab
    for name, allowed in (("family", FAMILY_FIELDS), ("status", STATUS_FILTERS)):
        value = raw.get(name)
        if isinstance(value, str) and value in allowed:
            view[name] = value
    every_entity_column = {key for family in FAMILY_FIELDS for key in _entity_columns(family)}
    for name, allowed in (("entity_sort", every_entity_column), ("line_sort", LINE_COLUMNS)):
        sort = _clean_sort(raw.get(name), allowed)
        if sort is not None:
            view[name] = sort
    entity_widths = raw.get("entity_widths")
    if isinstance(entity_widths, dict):
        kept = {family: _clean_widths(widths, _entity_columns(family))
                for family, widths in entity_widths.items() if family in FAMILY_FIELDS}
        kept = {family: widths for family, widths in kept.items() if widths}
        if kept:
            view["entity_widths"] = kept
    line_widths = _clean_widths(raw.get("line_widths"), LINE_COLUMNS)
    if line_widths:
        view["line_widths"] = line_widths
    for name in ("inspector", "id_column"):
        shown = raw.get(name)
        if isinstance(shown, bool):
            view[name] = shown
    for name in ("geometry", "window_state", "splitter"):
        text = raw.get(name)
        if isinstance(text, str) and text.isascii() and 0 < len(text) < 20000:
            view[name] = text
    return view


# ---- where the file pickers open, and three favourite folders (Session 19) ----

MAX_FAVOURITES = 3


def _folder_key(folder: str) -> str:
    return os.path.normcase(os.path.normpath(folder))


def _usable_folder(text) -> str:
    """``text`` as a folder path in Windows form, or "" when it is not an existing folder.

    Only text that names a whole path (a drive or share, then folders) and
    is a folder now counts; anything else from a hand-edited settings file
    is ignored rather than guessed at.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    folder = os.path.normpath(text.strip())
    try:
        return folder if Path(folder).is_absolute() and Path(folder).is_dir() else ""
    except (OSError, ValueError):
        return ""


def clean_folders(raw, limit: int = MAX_FAVOURITES) -> list[str]:
    """The favourite folders from the settings file that can be used, in their order.

    An entry that is not text, is empty, is not a folder, or repeats one
    already kept is dropped; at most ``limit`` are kept. A bad entry never
    stops the window opening, and the file is only rewritten when the
    favourites are changed in File > Favourite folders.
    """
    found: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        folder = _usable_folder(item)
        if folder and _folder_key(folder) not in {_folder_key(kept) for kept in found}:
            found.append(folder)
            if len(found) >= limit:
                break
    return found


def add_favourite(favourites: list[str], folder: str) -> tuple[list[str], str]:
    """The favourites with ``folder`` added at the end, and "" when it was added.

    Otherwise the list comes back as it was, with why not: there are
    already three (a fourth is refused), the folder is not there, or it is
    a favourite already.
    """
    favourites = list(favourites)
    if len(favourites) >= MAX_FAVOURITES:
        return favourites, ("You can keep up to three favourite folders. "
                            "Remove one first.")
    usable = _usable_folder(folder)
    if not usable:
        return favourites, f"{folder or 'That'} is not a folder that can be opened."
    if _folder_key(usable) in {_folder_key(kept) for kept in favourites}:
        return favourites, f"{usable} is already a favourite."
    return [*favourites, usable], ""


def names_folder(version) -> Path | None:
    """lnc\\all of a database folder: where Quick load reads the name files. None without one."""
    return Path(version) / "lnc" / "all" if version else None


def picker_folder(remembered, version) -> tuple[str, str]:
    """Where a file picker opens, and what to say when the database's folder is missing.

    The last folder File > Open used comes first, then lnc\\all of the
    selected database (``version``, the folder Quick load uses). With
    neither, the picker opens in the user's own folder and the sentence
    names the folder that was looked for: no other drive is guessed.
    """
    folder = _usable_folder(remembered)
    if folder:
        return folder, ""
    names = names_folder(version)
    if names is not None and names.is_dir():
        return str(names), ""
    looked = names if names is not None else GAME_DB_ROOT
    home = str(Path.home())
    return home, (f"No name files folder was found for the selected database (looked for "
                  f"{looked}), so the file picker opens in {home}. A Steam library on "
                  "another drive can be added under File > Favourite folders.")


def inside_folder(path, folder) -> bool:
    """True when ``path`` is ``folder`` or lies anywhere under it (letter case ignored)."""
    try:
        target = os.path.normcase(os.path.abspath(path))
        root = os.path.normcase(os.path.abspath(folder))
        return os.path.commonpath([target, root]) == root
    except ValueError:                  # another drive
        return False


def in_game_tree(path) -> bool:
    """True for a path in the game's database folder or anywhere in a Steam library.

    The file pickers may open in lnc\\all (Session 19), but a name pack is
    never saved there: only Save and Deploy write into the game's folders,
    after a backup.
    """
    parts = {part.casefold() for part in Path(os.path.abspath(path)).parts}
    return inside_folder(path, GAME_DB_ROOT) or "steamapps" in parts


def list_archives(archive_root: Path) -> list[Path]:
    """Timestamped backup folders, newest name first."""
    if not archive_root.is_dir():
        return []
    folders = [path for path in archive_root.iterdir() if path.is_dir()]
    return sorted(folders, key=lambda path: path.name.casefold(), reverse=True)


def _diff_key(entry: Entry):
    if entry.kind == "person":
        return ("person", entry.cmd, entry.source, entry.id, entry.lang.casefold())
    return ("name", entry.cmd, entry.id, entry.lang.casefold())


def diff_documents(working: LncDoc, archived: LncDoc) -> list[dict]:
    """Name and person-rule differences between two loaded files.

    Each row has command, id, language, source, working, archived, and note.
    Matching rows are omitted.
    """
    def grouped(doc: LncDoc) -> dict:
        found: dict = {}
        for entry in doc.editable():
            found.setdefault(_diff_key(entry), []).append(entry)
        return found

    current = grouped(working)
    previous = grouped(archived)
    rows = []
    for key in sorted(set(current) | set(previous)):
        now = current.get(key, [])
        then = previous.get(key, [])
        now_names = [entry.name for entry in now]
        then_names = [entry.name for entry in then]
        if now_names == then_names:
            continue
        sample = (now or then)[0]
        if not then:
            note = "Only in the open file"
        elif not now:
            note = "Only in the backup"
        elif len(now) != len(then):
            note = "Different (duplicate count)"
        else:
            note = "Different"
        rows.append({
            "command": sample.cmd,
            "id": sample.id,
            "language": sample.lang,
            "source": sample.source,
            "working": " | ".join(now_names),
            "archived": " | ".join(then_names),
            "note": note,
        })
    return rows


def bytes_match(doc: LncDoc, data: bytes) -> bool | None:
    """True when the open document would write exactly ``data``.

    None when its text cannot be encoded, so no byte comparison is possible.
    """
    try:
        return doc.to_bytes() == data
    except UnicodeError:
        return None


def compare_with_backup(doc: LncDoc, archive_file: Path) -> tuple[list[dict], bool | None]:
    """Compare an open file with a backed-up copy, in two separate ways.

    Returns the supported-name differences (see diff_documents) and whether
    the files are byte-identical (see bytes_match). A comment, a blank line,
    an unsupported command, a line ending, or the encoding can differ while
    every supported name matches; the second value catches that.

    Raises:
        OSError, UnicodeError: the backup could not be read.
    """
    archived = LncDoc(archive_file)
    return diff_documents(doc, archived), bytes_match(doc, archived.baseline_bytes)


def describe_backup_match(differences: int, identical: bool | None) -> str:
    """One plain sentence on how an open file compares with a backup."""
    if differences:
        return (f"{differences:,} difference(s) in supported names, so the files are "
                "not byte-identical either.")
    if identical is None:
        return ("Supported names match. A byte-for-byte check could not be made, because "
                "the open text cannot be written in its file's encoding.")
    if identical:
        return "Supported names match, and the files are byte-identical."
    return ("Supported names match, but the files are not byte-identical: comments, blank "
            "lines, other commands, line endings, or the encoding differ.")


def match_open_document(archive_file: Path, docs, manifest: dict | None = None):
    """Find the open document a backed-up file belongs to.

    Returns ``(doc, how)``. When the manifest lists the copy, the original
    path decides and ``how`` is "path", so two open files with one name are
    told apart. Otherwise (a backup from before 2.2, or the original is not
    open) the one open file with the original's name is used and ``how`` is
    "name", so the window can say so. ``(None, "")`` means no match, or
    more than one file with that name.
    """
    entry = manifest_entry(manifest, archive_file.name)
    name = archive_file.name
    if entry is not None:
        for doc in docs:
            if same_path(doc.path, entry["original"]):
                return doc, "path"
        name = Path(entry["original"]).name
    found = [doc for doc in docs if doc.path.name.casefold() == name.casefold()]
    if len(found) == 1:
        return found[0], "name"
    return None, ""


def restore_into(doc: LncDoc, archive_file: Path) -> None:
    """Replace the open document's lines with a backup. The path is kept.

    Nothing is written to ``doc.path``. The caller saves or deploys later.
    The disk baseline stays as it was, so the restored lines count as
    pending changes until they are written, and the document remembers
    which copy they came from. A bad backup raises before anything in
    memory changes.
    """
    doc.apply_working(prepare_restore(doc, archive_file))


def prepare_restore(doc: LncDoc, archive_file: Path) -> PreparedLines:
    """Read and parse a backup for ``doc`` without changing it: the slow half of a
    restore, which a worker thread may run. restore_into does both halves."""
    archive_file = Path(archive_file)
    if not archive_file.is_file():
        raise FileNotFoundError(archive_file)
    return doc.prepare_working(archive_file.read_bytes(), archive_file)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

# Slow work (opening files, reading a backup, the check for a running game)
# runs on a worker thread; see run_gui's Jobs. The tests set this so a job
# runs at once on the calling thread instead: the window behaves the same,
# minus the thread. Tests of the threads themselves set it back.
JOBS_INLINE = False


def run_gui(paths):
    from PySide6.QtCore import (QAbstractTableModel, QByteArray, QEvent, QEventLoop,
                                QItemSelection, QItemSelectionModel, QModelIndex, QObject, QPointF, QRectF,
                                QRegularExpression, QSize, QSortFilterProxyModel, Qt, QTimer, Signal,
                                QPropertyAnimation, QEasingCurve, QParallelAnimationGroup)
    from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QIcon, QKeySequence,
                               QPainter, QPen, QRegularExpressionValidator, QUndoCommand,
                               QUndoStack)
    from PySide6.QtWidgets import (
        QAbstractItemDelegate, QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
        QComboBox, QDialog,
        QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
        QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
        QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
        QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
        QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
        QToolButton)

    FILTER = "FM name files (*.lnc);;All files (*)"
    GAME_WRITE_NOTE = (
        "A copy of each existing game file is stored under backups first. Files are "
        "replaced one at a time; if one fails, the files already replaced are put back "
        "from that copy.")
    GAME_CHECK = "Checking whether Football Manager is running..."
    SETTINGS_LEFT_ALONE = (
        "The editor leaves the file as it is. Until it is put right or moved away and the "
        "editor started again, the chosen profile, saved searches, and the window's layout "
        "are not saved.")
    DISPLAY, EDIT, FONT = Qt.DisplayRole, Qt.EditRole, Qt.FontRole
    FOREGROUND, TOOLTIP = Qt.ForegroundRole, Qt.ToolTipRole
    # The theme's colours as Qt colours, made once (see THEME). State text in
    # the grids is coloured as well as worded (STATE_COLOUR_NAMES).
    COLOURS = {name: QColor(value) for name, value in THEME.items()}
    BADGE_ROLE = Qt.UserRole + 20       # a type cell's badge family (see badge_family)
    BADGE_SPACE = 18                    # the room a badge takes before the type's words

    def state_colour(text: str):
        """The colour for a status cell: a repeated key first, then added, then edited."""
        name = state_colour_name(text)
        return COLOURS[name] if name else None

    def reorder_rows(model, rows) -> None:
        """Give a model's rows a new order, keeping each selection on the same row.

        The grids sort in Python like this rather than through the proxy, which
        would ask data() for every comparison: seconds with both FM27 files open.
        """
        model.layoutAboutToBeChanged.emit()
        old = model.persistentIndexList()
        held = [(model.rows[index.row()], index.column()) for index in old]
        model.rows = rows
        where = {id(row): number for number, row in enumerate(rows)}
        model.changePersistentIndexList(
            old, [model.index(where[id(row)], column) if id(row) in where else QModelIndex()
                  for row, column in held])
        model.layoutChanged.emit()

    def text_width(metrics: QFontMetrics, texts, sample: int = 24) -> int:
        """The widest of some texts, measuring only the longest few by character count."""
        longest = sorted({text for text in texts if text}, key=len, reverse=True)[:sample]
        return max((metrics.horizontalAdvance(text) for text in longest), default=0)

    def fit_columns(view: QTableView, texts_by_column: dict, caps: dict | None = None,
                    extra: dict | None = None) -> None:
        """Size columns from their texts without asking the model for every cell.

        resizeColumnToContents asks data() for a thousand rows per column,
        which took seconds with both FM27 files open. Bold is measured, since
        edited rows are bold. Each column is at least as wide as its header.
        """
        view.ensurePolished()
        font = QFont(view.font())
        font.setBold(True)
        metrics = QFontMetrics(font)
        header = view.horizontalHeader()
        for column, texts in texts_by_column.items():
            width = max(header.sectionSizeHint(column), text_width(metrics, texts) + 16
                        + (extra or {}).get(column, 0))
            if caps and column in caps:
                width = min(width, caps[column])
            view.setColumnWidth(column, width)

    class EditCommand(QUndoCommand):
        """A recorded Operation on the undo stack.

        The change is already made when the command is pushed, so the redo()
        that QUndoStack.push runs straight away does nothing; later redos and
        every undo go to the Operation, and the window is refreshed.
        """

        def __init__(self, window, operation: Operation):
            super().__init__(operation.label)
            self.window = window
            self.operation = operation
            self.pushed = False

        def redo(self):
            if not self.pushed:
                self.pushed = True
                return
            self.operation.redo()
            self.window.after_undo(self.operation, "Redone")

        def undo(self):
            self.operation.undo()
            self.window.after_undo(self.operation, "Undone")

    class TickDelegate(QStyledItemDelegate):
        """An include tick drawn plainly: a box with a light border, filled with the accent
        and ticked when the row is in.

        The style's own box takes its border from the panel colour, which on the
        slate theme is nearly black. The box sits where the style puts it, so a
        click toggles it as before.
        """

        def paint(self, painter, option, index):
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            widget = opt.widget
            style = widget.style() if widget is not None else QApplication.style()
            if not opt.features & QStyleOptionViewItem.HasCheckIndicator:
                super().paint(painter, option, index)
                return
            box = style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, widget)
            checked = opt.checkState == Qt.Checked
            opt.features = opt.features & ~QStyleOptionViewItem.HasCheckIndicator
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
            side = max(10.0, min(box.width(), box.height(), 16) - 1.0)
            square = QRectF(box.center().x() - side / 2 + 0.5, box.center().y() - side / 2 + 0.5,
                            side, side)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(COLOURS["edited" if checked else "muted"], 1.2))
            painter.setBrush(COLOURS["accent" if checked else "window"])
            painter.drawRoundedRect(square, 3, 3)
            if checked:
                tick = QPen(COLOURS["on_accent"], max(1.6, side / 8))
                tick.setCapStyle(Qt.RoundCap)
                tick.setJoinStyle(Qt.RoundJoin)
                painter.setPen(tick)
                x, y, s = square.x(), square.y(), square.width()
                painter.drawPolyline([QPointF(x + s * 0.24, y + s * 0.52),
                                      QPointF(x + s * 0.43, y + s * 0.71),
                                      QPointF(x + s * 0.77, y + s * 0.31)])
            painter.restore()

    class BadgeDelegate(QStyledItemDelegate):
        """A line's type with its family's badge before it: a small rounded square
        in the family's theme colour, then the type's own words ("Club - short
        name"), so the colour never stands alone. Painted, never a widget per cell;
        a cell with no badge family is drawn as usual.
        """

        ROLE = BADGE_ROLE

        def paint(self, painter, option, index):
            family = index.data(BADGE_ROLE)
            if not family:
                super().paint(painter, option, index)
                return
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            widget = opt.widget
            style = widget.style() if widget is not None else QApplication.style()
            words = opt.text
            opt.text = ""
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
            rect = opt.rect
            side = max(6.0, min(10.0, rect.height() - 10.0))
            chip = QRectF(rect.x() + 6, rect.center().y() - side / 2 + 0.5, side, side)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(COLOURS.get(f"badge_{family}", COLOURS["muted"]))
            painter.drawRoundedRect(chip, 2.5, 2.5)
            painter.restore()
            opt.text = words
            opt.rect = rect.adjusted(BADGE_SPACE - 4, 0, 0, 0)
            opt.state &= ~QStyle.State_HasFocus
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

        def sizeHint(self, option, index):
            size = super().sizeHint(option, index)
            if index.data(BADGE_ROLE):
                size.setWidth(size.width() + BADGE_SPACE)
            return size

    class IllustrativePreviewCard(QWidget):
        """A collapsible card showing the selected entity's spellings in three illustrative formats.

        Table row: like the entity grid, with long, short, and code side by side.
        Scoreboard: large text for the primary name, with short and code below.
        Ticker: a scrolling marquee showing the names in sequence.

        Absent overrides are shown honestly using the existing "No X override" text.
        Updates only from selection/edits; no file I/O during paint. Collapsible at small sizes.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("illustrative_card")
            self._expanded = True
            self._auto_collapsed = False    # collapsed by lack of room, not by the user
            self._user_override = False     # the user toggled it while space was short
            self._animation = None
            self._content_height = 0
            self._entity = None

            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)

            # Header with toggle button
            header = QWidget()
            header.setObjectName("illustrative_header")
            header_lay = QHBoxLayout(header)
            header_lay.setContentsMargins(8, 6, 8, 6)
            self.title_label = QLabel("Illustrative")
            self.title_label.setObjectName("heading")
            self.toggle_btn = QToolButton()
            self.toggle_btn.setArrowType(Qt.DownArrow)
            self.toggle_btn.setCheckable(True)
            self.toggle_btn.setChecked(True)
            self.toggle_btn.setToolTip("Collapse/expand illustrative previews")
            self.toggle_btn.clicked.connect(self._on_toggle)
            header_lay.addWidget(self.title_label)
            header_lay.addStretch(1)
            header_lay.addWidget(self.toggle_btn)
            lay.addWidget(header)

            # Content area (will be animated)
            self.content = QWidget()
            self.content_lay = QVBoxLayout(self.content)
            self.content_lay.setContentsMargins(8, 4, 8, 8)
            self.content_lay.setSpacing(8)

            # Three preview widgets
            self.table_preview = self._make_table_preview()
            self.scoreboard_preview = self._make_scoreboard_preview()
            self.ticker_preview = self._make_ticker_preview()

            self.content_lay.addWidget(self.table_preview)
            self.content_lay.addWidget(self.scoreboard_preview)
            self.content_lay.addWidget(self.ticker_preview)
            # Session 20: said only while a name is shown cut at its typical guide.
            self.cut_note = QLabel(
                "A name longer than its typical guide is shown cut with an ellipsis, as a skin "
                "might show it. Skins differ: this is illustrative, not exact. The name itself "
                "is kept whole.")
            self.cut_note.setObjectName("muted")
            self.cut_note.setWordWrap(True)
            self.content_lay.addWidget(self.cut_note)
            self.cut_note.hide()

            lay.addWidget(self.content)

            # Set initial size
            self.content.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

        def _make_table_preview(self) -> QWidget:
            """Create the table row preview: long | short | code side by side."""
            frame = QFrame()
            frame.setObjectName("preview_frame")
            frame.setFrameShape(QFrame.StyledPanel)
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(4)

            title = QLabel("Table row")
            title.setObjectName("muted")
            title.setFont(QFont(title.font().family(), title.font().pointSize(), QFont.Bold))
            lay.addWidget(title)

            row = QHBoxLayout()
            row.setSpacing(8)

            self.table_long = QLabel()
            self.table_long.setObjectName("preview_cell")
            self.table_long.setWordWrap(True)
            self.table_long.setTextInteractionFlags(Qt.TextSelectableByMouse)

            self.table_short = QLabel()
            self.table_short.setObjectName("preview_cell")
            self.table_short.setWordWrap(True)
            self.table_short.setTextInteractionFlags(Qt.TextSelectableByMouse)

            self.table_code = QLabel()
            self.table_code.setObjectName("preview_cell")
            self.table_code.setWordWrap(True)
            self.table_code.setTextInteractionFlags(Qt.TextSelectableByMouse)

            for lbl, widget in (("Long", self.table_long), ("Short", self.table_short), ("Code", self.table_code)):
                col = QVBoxLayout()
                col.setSpacing(2)
                cap = QLabel(lbl)
                cap.setObjectName("muted")
                cap.setFont(QFont(cap.font().family(), max(7, cap.font().pointSize() - 1)))
                col.addWidget(cap)
                col.addWidget(widget)
                row.addLayout(col, 1)

            lay.addLayout(row)
            return frame

        def _make_scoreboard_preview(self) -> QWidget:
            """Create the scoreboard preview: large primary name with short/code below."""
            frame = QFrame()
            frame.setObjectName("preview_frame")
            frame.setFrameShape(QFrame.StyledPanel)
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(6)

            title = QLabel("Scoreboard")
            title.setObjectName("muted")
            title.setFont(QFont(title.font().family(), title.font().pointSize(), QFont.Bold))
            lay.addWidget(title)

            self.scoreboard_name = QLabel()
            self.scoreboard_name.setObjectName("scoreboard_name")
            self.scoreboard_name.setWordWrap(True)
            self.scoreboard_name.setAlignment(Qt.AlignHCenter)
            self.scoreboard_name.setFont(QFont(self.scoreboard_name.font().family(), 18, QFont.Bold))
            self.scoreboard_name.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(self.scoreboard_name)

            detail_row = QHBoxLayout()
            detail_row.setSpacing(16)

            self.scoreboard_short = QLabel()
            self.scoreboard_short.setObjectName("muted")
            self.scoreboard_short.setAlignment(Qt.AlignHCenter)
            self.scoreboard_short.setTextInteractionFlags(Qt.TextSelectableByMouse)

            self.scoreboard_code = QLabel()
            self.scoreboard_code.setObjectName("muted")
            self.scoreboard_code.setAlignment(Qt.AlignHCenter)
            self.scoreboard_code.setTextInteractionFlags(Qt.TextSelectableByMouse)

            detail_row.addStretch(1)
            detail_row.addWidget(self.scoreboard_short)
            detail_row.addWidget(self.scoreboard_code)
            detail_row.addStretch(1)
            lay.addLayout(detail_row)

            return frame

        def _make_ticker_preview(self) -> QWidget:
            """Create the ticker preview: a scrolling marquee of the names."""
            frame = QFrame()
            frame.setObjectName("preview_frame")
            frame.setFrameShape(QFrame.StyledPanel)
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(4)

            title = QLabel("Ticker")
            title.setObjectName("muted")
            title.setFont(QFont(title.font().family(), title.font().pointSize(), QFont.Bold))
            lay.addWidget(title)

            self.ticker_label = QLabel()
            self.ticker_label.setObjectName("ticker_label")
            self.ticker_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.ticker_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.ticker_label.setMinimumHeight(28)
            self.ticker_label.setFont(QFont(self.ticker_label.font().family(), 12))
            lay.addWidget(self.ticker_label)

            # Simple timer-based scrolling (no complex animation needed for MVP)
            self._ticker_timer = QTimer(self)
            self._ticker_timer.setInterval(3000)  # Change every 3 seconds
            self._ticker_timer.timeout.connect(self._advance_ticker)
            self._ticker_texts = []
            self._ticker_index = 0

            return frame

        def _advance_ticker(self) -> None:
            if not self._ticker_texts:
                return
            self._ticker_index = (self._ticker_index + 1) % len(self._ticker_texts)
            self.ticker_label.setText(self._ticker_texts[self._ticker_index])

        # Below these the card would crowd the inspector's fields, so it folds itself away.
        MIN_WIDTH = 240
        MIN_WINDOW_HEIGHT = 560

        def _on_toggle(self, checked: bool) -> None:
            self._set_expanded(checked)
            self._auto_collapsed = False
            self._user_override = self._too_small()

        def _set_expanded(self, expanded: bool) -> None:
            self._expanded = expanded
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(expanded)
            self.toggle_btn.blockSignals(False)
            self.toggle_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            self._animate_content(expanded)
            self._sync_ticker()

        def _too_small(self) -> bool:
            return self.width() < self.MIN_WIDTH or self.window().height() < self.MIN_WINDOW_HEIGHT

        def fit_to_space(self) -> None:
            """Fold away when the inspector or window is small; open again when room returns."""
            if self._too_small():
                if self._expanded and not self._user_override:
                    self._set_expanded(False)
                    self._auto_collapsed = True
            else:
                self._user_override = False
                if self._auto_collapsed:
                    self._set_expanded(True)
                    self._auto_collapsed = False

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            self.fit_to_space()

        def _ticker_wanted(self) -> bool:
            return self._expanded and self._entity is not None and not self.isHidden()

        def stop_ticker(self) -> None:
            """Stop the ticker for good, as the window closes."""
            self._entity = None
            self._ticker_timer.stop()

        def _sync_ticker(self) -> None:
            """The ticker runs only while it can be seen: expanded, shown, and something selected."""
            if self._ticker_wanted():
                if not self._ticker_timer.isActive():
                    self._ticker_timer.start()
            else:
                self._ticker_timer.stop()

        def showEvent(self, event) -> None:
            super().showEvent(event)
            self._sync_ticker()

        def hideEvent(self, event) -> None:
            super().hideEvent(event)
            self._ticker_timer.stop()

        def _animate_content(self, expand: bool) -> None:
            if self._animation and self._animation.state() == QPropertyAnimation.Running:
                self._animation.stop()

            if expand:
                self.content.show()
                # Calculate the content's preferred height
                self.content_lay.activate()
                target_height = self.content.sizeHint().height()
                self._animation = QPropertyAnimation(self.content, b"maximumHeight")
                self._animation.setDuration(150)
                self._animation.setEasingCurve(QEasingCurve.OutCubic)
                self._animation.setStartValue(0)
                self._animation.setEndValue(target_height)
                self._animation.start()
            else:
                self._animation = QPropertyAnimation(self.content, b"maximumHeight")
                self._animation.setDuration(150)
                self._animation.setEasingCurve(QEasingCurve.InCubic)
                self._animation.setStartValue(self.content.maximumHeight())
                self._animation.setEndValue(0)
                self._animation.finished.connect(lambda: self.content.hide())
                self._animation.start()

        def update_from_entity(self, entity) -> None:
            """Update all three previews from the given entity."""
            self._entity = entity
            if entity is None:
                self._clear_all()
                return

            family = entity.family
            # Get names for each slot
            long_name = entity.name_in("long") if "long" in [s for s, _, _ in FAMILY_FIELDS[family]] else ""
            short_name = entity.name_in("short") if "short" in [s for s, _, _ in FAMILY_FIELDS[family]] else ""
            code_name = entity.name_in("code") if "code" in [s for s, _, _ in FAMILY_FIELDS[family]] else ""

            # For families without certain slots (e.g., stadium only has long), use honest "No override" text
            if not long_name and "long" in [s for s, _, _ in FAMILY_FIELDS[family]]:
                long_name = no_override_text(family, "long")
            if not short_name and "short" in [s for s, _, _ in FAMILY_FIELDS[family]]:
                short_name = no_override_text(family, "short")
            if not code_name and "code" in [s for s, _, _ in FAMILY_FIELDS[family]]:
                code_name = no_override_text(family, "code")

            # Session 20: a name past its typical guide is shown cut, with an ellipsis.
            def cut(slot, text):
                if not text or text == no_override_text(family, slot):
                    return text
                return cut_to_guide(text, length_guide(family, slot))

            names = {"long": long_name, "short": short_name, "code": code_name}
            shown = {slot: cut(slot, text) for slot, text in names.items()}
            for slot, label in (("long", self.table_long), ("short", self.table_short),
                                ("code", self.table_code)):
                label.setText(shown[slot])
                label.setToolTip(names[slot] if shown[slot] != names[slot] else "")
            self.cut_note.setVisible(shown != names)

            # Scoreboard preview - use long name as primary, or first available
            primary = "long" if long_name != no_override_text(family, "long") else (
                "short" if short_name != no_override_text(family, "short") else "code")
            self.scoreboard_name.setText(shown[primary])
            self.scoreboard_short.setText(f"Short: {shown['short']}")
            self.scoreboard_code.setText(f"Code: {shown['code']}")

            # Ticker preview - cycle through available names
            self._ticker_texts = []
            if long_name and long_name != no_override_text(family, "long"):
                self._ticker_texts.append(f"Long: {shown['long']}")
            if short_name and short_name != no_override_text(family, "short"):
                self._ticker_texts.append(f"Short: {shown['short']}")
            if code_name and code_name != no_override_text(family, "code"):
                self._ticker_texts.append(f"Code: {shown['code']}")
            if not self._ticker_texts:
                # All are "No override" - show one message
                self._ticker_texts = [f"No overrides for {ENTITY_KINDS.get(family, family).lower()}"]
            self._ticker_index = 0
            self.ticker_label.setText(self._ticker_texts[0])
            self._sync_ticker()

        def _clear_all(self) -> None:
            """Clear all previews when no entity is selected."""
            for lbl in (self.table_long, self.table_short, self.table_code,
                        self.scoreboard_name, self.scoreboard_short, self.scoreboard_code):
                lbl.setText("")
                lbl.setToolTip("")
            self.cut_note.hide()
            self._ticker_texts = []
            self.ticker_label.setText("")
            self._sync_ticker()

        def set_expanded(self, expanded: bool) -> None:
            """Programmatically set expanded state."""
            if self._expanded != expanded:
                self._on_toggle(expanded)

    def report_write_failure(parent, operation: str, exc: Exception) -> None:
        """Tell the user why a write stopped and where each file stands."""
        if isinstance(exc, ExternalChangeError):
            QMessageBox.warning(parent, APP_NAME, str(exc))
        elif isinstance(exc, WriteError):
            QMessageBox.critical(parent, APP_NAME, str(exc))
        else:
            QMessageBox.critical(
                parent, APP_NAME,
                f"{operation} failed:\n{exc}\n\nNo file was replaced.")

    # ---------------- main table ----------------
    class EntryModel(QAbstractTableModel):
        """Every name line and person rule, in file order until a column is sorted.

        Sorting happens here, in Python (sort_by), not in the proxy.
        """

        COLS = ["File section or ending", "Type", "ID", "Name", "Language", "File", "Status"]
        KEYS = list(LINE_COLUMNS)
        TYPE_COL = 1
        NAME_COL = 3
        STATUS_COL = 6
        operation_done = Signal(object)     # an edit made here, for the undo stack
        rejected = Signal(str)              # why a typed name or ending was not used

        def __init__(self):
            super().__init__()
            self.rows: list[Entry] = []
            self.base_rows: list[Entry] = []    # file order
            self.sort_key = ""                  # "" keeps file order
            self.sort_descending = False
            self.bold = QFont()
            self.bold.setBold(True)

        def set_docs(self, docs):
            self.beginResetModel()
            self.base_rows = [e for d in docs for e in d.editable()]
            self.rows = sort_entries(self.base_rows, self.sort_key, self.sort_descending)
            self.endResetModel()

        def sort_by(self, column: int, descending: bool) -> None:
            """Sort by a column, or go back to file order when ``column`` is -1."""
            self.sort_key = self.KEYS[column] if 0 <= column < len(self.KEYS) else ""
            self.sort_descending = descending
            reorder_rows(self, sort_entries(self.base_rows, self.sort_key, descending))

        def sort_column(self) -> int:
            return self.KEYS.index(self.sort_key) if self.sort_key in self.KEYS else -1

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return len(self.COLS)

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if orientation != Qt.Horizontal:
                return None
            if role == DISPLAY:
                return self.COLS[section]
            if role == TOOLTIP and section == 0:
                return FILE_SECTION_HINT
            if role == Qt.InitialSortOrderRole:
                return Qt.AscendingOrder        # the first click on a header sorts A to Z
            if role == FONT and section == self.sort_column():
                return self.bold                # the sorted heading, beside its small arrow
            return None

        def flags(self, index):
            f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if not index.isValid():
                return f
            entry = self.rows[index.row()]
            if index.column() == self.NAME_COL:
                f |= Qt.ItemIsEditable
            elif index.column() == 0 and entry.kind == "person":
                f |= Qt.ItemIsEditable
            return f

        def data(self, index, role=Qt.DisplayRole):
            if role == DISPLAY or role == EDIT:
                return entry_text(self.rows[index.row()], self.KEYS[index.column()])
            if role == FONT:
                return self.bold if self.rows[index.row()].changed else None
            if role == FOREGROUND and index.column() == self.STATUS_COL:
                return state_colour(entry_status(self.rows[index.row()]))
            if role == BADGE_ROLE and index.column() == self.TYPE_COL:
                return badge_family(self.rows[index.row()].cmd)
            if role == TOOLTIP:
                e = self.rows[index.row()]
                if e.kind == "person":
                    return f"Ending was: {e.orig_source}. Replacement was: {e.orig_name}."
                if e.changed and not e.imported:
                    return f"Was: {e.orig_name}"
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if role != Qt.EditRole:
                return False
            entry = self.rows[index.row()]
            text = str(value).strip()
            if index.column() == 0 and entry.kind == "person":
                noun, current = "ending", entry.source
            elif index.column() == self.NAME_COL:
                noun = "replacement" if entry.kind == "person" else "name"
                current = entry.name
            else:
                return False
            if text == current:
                return False
            problem = name_problem(text, noun)
            if problem:
                self.rejected.emit(problem)     # the window says why, instead of nothing
                return False
            with Operation(f"edit {noun}: {text}") as operation:
                if noun == "ending":
                    changed = try_set_source(entry, text)
                else:
                    changed = try_set_name(entry, text)
            if not changed:
                return False
            self.row_changed(index.row())
            self.operation_done.emit(operation)
            return True

        def row_changed(self, row):
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.COLS) - 1))

    class EntryProxy(QSortFilterProxyModel):
        """Filters the line table. The model sorts; this keeps the model's order."""

        def __init__(self):
            super().__init__()
            self.words = []
            self.cmd = ""
            self.changed_only = False
            self.setDynamicSortFilter(False)   # edited rows stay put until re-filtered

        def configure(self, text, cmd, changed_only) -> None:
            """Set the filter without running it: a model reset that follows runs it once."""
            self.words = fold(text).split()
            self.cmd = cmd
            self.changed_only = changed_only

        def set_filter(self, text, cmd, changed_only):
            self.configure(text, cmd, changed_only)
            self.invalidate()

        def filterAcceptsRow(self, row, parent):
            e = self.sourceModel().rows[row]
            if self.cmd and e.cmd != self.cmd:
                return False
            if self.changed_only and not e.changed:
                return False
            if self.words:
                hay = e.search_text()
                return all(w in hay for w in self.words)
            return True

    # ---------------- import dialog ----------------
    class ProposalModel(QAbstractTableModel):
        def __init__(self, cols):
            super().__init__()
            self.cols = cols
            self.items: list[Proposal] = []
            self.view_rows: list[Proposal] = []

        def set_items(self, items):
            self.items = items
            self.apply_filter("")

        def apply_filter(self, text):
            words = fold(text).split()
            self.beginResetModel()
            if words:
                def hay(p):
                    cur = p.target.name if p.target else ""
                    return fold(f"{p.new} {cur} {p.id} {p.section} {friendly(p.cmd)} "
                                f"{p.base} {p.note}")
                self.view_rows = [p for p in self.items if all(w in hay(p) for w in words)]
            else:
                self.view_rows = list(self.items)
            self.endResetModel()

        def set_all(self, state):
            self.beginResetModel()
            for p in self.view_rows:
                p.checked = state
            self.endResetModel()

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.view_rows)

        def columnCount(self, parent=QModelIndex()):
            return len(self.cols)

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                return self.cols[section]
            return None

        def flags(self, index):
            f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if index.column() == 0:
                f |= Qt.ItemIsUserCheckable
            return f

        def data(self, index, role=Qt.DisplayRole):
            p = self.view_rows[index.row()]
            c = index.column()
            if role == Qt.CheckStateRole and c == 0:
                return Qt.Checked if p.checked else Qt.Unchecked
            if role == Qt.DisplayRole:
                name = self.cols[c]
                if name == "Use": return ""
                if name == "Type": return friendly(p.cmd)
                if name == "ID": return p.id
                if name == "Current name": return p.target.name if p.target else ""
                if name in ("Your older name", "Profile spelling"): return p.new
                if name == "Language": return p.lang
                if name == "File section": return p.section
                if name in ("Older original", "Baseline when recorded"): return p.base
                if name == "Note": return p.note
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if role == Qt.CheckStateRole and index.column() == 0:
                p = self.view_rows[index.row()]
                p.checked = (Qt.CheckState(value) == Qt.Checked)
                self.dataChanged.emit(index, index)
                return True
            return False

    class ImportDialog(QDialog):
        def __init__(self, parent, docs):
            super().__init__(parent)
            self.setWindowTitle("Import edits from older files")
            self.resize(1050, 680)
            self.docs = docs
            self.old_paths, self.base_paths = [], []
            self.result_counts = None
            self.jobs = getattr(parent, "jobs", None)
            # Where the pickers open: File > Open's folder rule (Session 19), never "".
            self.start_folder = getattr(parent, "start_folder", lambda: str(Path.home()))
            lay = QVBoxLayout(self)

            self.old_label = QLabel("No files chosen")
            self.base_label = QLabel("None (optional)")
            for text, label, slot in (
                ("1. Your edited older files...", self.old_label, self.pick_old),
                ("2. Unedited originals of those files...", self.base_label, self.pick_base),
            ):
                row = QHBoxLayout()
                b = QPushButton(text)
                b.setMinimumWidth(280)
                b.clicked.connect(slot)
                row.addWidget(b)
                row.addWidget(label, 1)
                lay.addLayout(row)
            hint = QLabel(
                "Step 2 is optional. With the originals, only the names you personally "
                "changed are listed. Without them, every difference is listed, including "
                "names that are simply newer in the current file, so nothing is ticked "
                "for you.")
            hint.setWordWrap(True)
            lay.addWidget(hint)

            row = QHBoxLayout()
            self.compare_btn = QPushButton("3. Compare")
            self.compare_btn.clicked.connect(self.compare)
            self.compare_btn.setEnabled(False)
            row.addWidget(self.compare_btn)
            self.search = QLineEdit()
            self.search.setPlaceholderText("Filter this list (name, ID, section, note)...")
            self.search.textChanged.connect(self.refilter)
            row.addWidget(self.search, 1)
            for text, state in (("Tick all shown", True), ("Untick all shown", False)):
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, s=state: self.current_model().set_all(s))
                row.addWidget(b)
            lay.addLayout(row)

            self.tabs = QTabWidget()
            self.change_model = ProposalModel(
                ["Use", "File section", "Type", "ID", "Current name", "Your older name",
                 "Older original", "Note", "Language"])
            self.missing_model = ProposalModel(
                ["Use", "File section", "Type", "ID", "Your older name", "Older original", "Note",
                 "Language"])
            for model, title in ((self.change_model, "Different names"),
                                 (self.missing_model, "Not in current files")):
                view = QTableView()
                view.setModel(model)
                view.setItemDelegateForColumn(0, TickDelegate(view))   # the Use tick
                view.setSelectionBehavior(QTableView.SelectRows)
                view.setAlternatingRowColors(True)
                view.verticalHeader().setVisible(False)
                view.horizontalHeader().setStretchLastSection(True)
                self.tabs.addTab(view, title)
            lay.addWidget(self.tabs, 1)

            self.summary = QLabel("")
            self.summary.setWordWrap(True)
            lay.addWidget(self.summary)

            box = QDialogButtonBox()
            self.apply_btn = box.addButton("Apply ticked", QDialogButtonBox.AcceptRole)
            box.addButton(QDialogButtonBox.Cancel)
            self.apply_btn.setEnabled(False)
            box.accepted.connect(self.apply)
            box.rejected.connect(self.reject)
            lay.addWidget(box)

        def current_model(self):
            return self.tabs.currentWidget().model()

        def pick_old(self):
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Your edited older files", self.start_folder(), FILTER)
            if paths:
                self.old_paths = paths
                self.old_label.setText(", ".join(Path(p).name for p in paths))
                self.compare_btn.setEnabled(True)

        def pick_base(self):
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Unedited originals", self.start_folder(), FILTER)
            self.base_paths = paths
            self.base_label.setText(", ".join(Path(p).name for p in paths) or "None (optional)")

        def compare(self):
            """Read the older files and build proposals. The reading and the
            comparison run on the window's worker when one is available (the
            live files time 773 ms end-to-end on this PC); the dialog fills
            in when the job finishes, and the Compare button stays off
            meanwhile."""
            self.compare_btn.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self.summary.setText("Reading the older files and comparing...")
            old_paths = list(self.old_paths)
            base_paths = list(self.base_paths)
            docs = self.docs

            def work():
                old = [LncDoc(p) for p in old_paths]
                base = [LncDoc(p) for p in base_paths] or None
                changes, missing, stats = build_proposals(docs, old, base)
                bad = sum(len(d.problems()) for d in old)
                return changes, missing, stats, bad

            if self.jobs is None:
                try:
                    result = work()
                except (OSError, UnicodeError) as exc:
                    self._compare_failed(exc)
                    return
                self._compare_done(result)
            else:
                self.jobs.start("Reading older files...", work,
                                self._compare_done, self._compare_failed)

        def _compare_done(self, result) -> None:
            changes, missing, stats, bad = result
            self.compare_btn.setEnabled(True)
            key = lambda p: (fold(p.section), p.cmd, p.new)
            self.change_model.set_items(sorted(changes, key=key))
            self.missing_model.set_items(sorted(missing, key=key))
            self.tabs.setTabText(0, f"Different names ({len(changes)})")
            self.tabs.setTabText(1, f"Not in current files ({len(missing)})")
            for i in range(2):
                self.tabs.widget(i).resizeColumnsToContents()
            text = (f"{stats['old']} names read from the older files. "
                    f"{stats['same']} already match the current files.")
            if self.base_paths:
                text += (f" {stats['stock']} were never edited by you and are skipped."
                         " 'Renamed since' in the Note column means the stock name has"
                         " also changed between versions, so your older name may be out"
                         " of date; type 'renamed' in the filter to review just those.")
            if bad:
                text += f" {bad} malformed lines in the older files were ignored."
            if stats.get("skipped"):
                text += (f" {stats['skipped']} older name(s) were skipped because the "
                         "name was blank, or the name, id, or language could not be "
                         "written as one line.")
            text += (" Entries under 'Not in current files' are added to the end of the "
                     "file if ticked; their IDs may no longer exist in the game.")
            self.summary.setText(text)
            self.apply_btn.setEnabled(True)
            self.search.clear()

        def _compare_failed(self, exc: Exception) -> None:
            self.compare_btn.setEnabled(True)
            self.summary.setText("")
            if not isinstance(exc, (OSError, UnicodeError)):
                raise exc
            QMessageBox.critical(self, APP_NAME, f"Could not read file:\n{exc}")

        def refilter(self, text):
            self.change_model.apply_filter(text)
            self.missing_model.apply_filter(text)

        def apply(self):
            n, added = apply_proposals(self.change_model.items, self.missing_model.items,
                                       self.docs)
            self.result_counts = (n, len(added))
            self.accept()

    DARK_QSS = theme_style_sheet()

    def field_label(family: str, slot: str) -> str:
        """"long name", "3-letter code": a field as an undo label names it."""
        for key, label, _cmd in FAMILY_FIELDS[family]:
            if key == slot:
                return label[:1].lower() + label[1:]
        return slot

    def cell_operation(entity: NameEntity, slot: str, text: str) -> str:
        """The undo label for writing one cell: an edit, or an added line when it was empty."""
        verb = "edit" if entity.slots.get(slot) else "add"
        return f"{verb} {field_label(entity.family, slot)}: {text.strip()}"

    class EntityModel(QAbstractTableModel):
        """Side-by-side rows. Column set follows the selected family.

        The column list is worked out once per family, not on every call, and
        the rows are sorted here, in Python (sort_by), by the long name until
        another column header is clicked. The ID and File section columns
        stay in the model; the window hides File section while one section
        is chosen, and ID when View > Show ID column is off (see
        MainWindow.show_columns). The sorted column's heading is bold, since
        the arrow beside it is small and far from the words (Session 19).
        """

        operation_done = Signal(object)     # an edit made here, for the undo stack
        rejected = Signal(str)              # why a typed name was not used

        def __init__(self, docs):
            super().__init__()
            self.docs = docs
            self.family = "club"
            self.rows: list[NameEntity] = []
            self.base_rows: list[NameEntity] = []   # build_entities order: section, then ID
            self.sort_key = "long"                  # "" keeps base_rows order
            self.sort_descending = False
            self.health: dict = {}                  # name_health result; the window's (Session 21)
            self.bold = QFont()
            self.bold.setBold(True)
            self._structure = False
            self._set_columns()

        def _set_columns(self) -> None:
            fields = FAMILY_FIELDS[self.family]
            keys = ["section", "id", *(slot for slot, _label, _cmd in fields)]
            if self.family == "award":
                keys.append("lang")
            keys.append("status")
            self._keys = keys
            self._slots = frozenset(slot for slot, _label, _cmd in fields)
            self._titles = {"section": "File section", "id": "ID", "lang": "Language",
                            "status": "Status"}
            self._titles.update((slot, label) for slot, label, _cmd in fields)

        def columns(self) -> list[str]:
            return list(self._keys)

        def set_family_rows(self, family: str, rows: list[NameEntity]) -> None:
            self.beginResetModel()
            self.family = family
            self._set_columns()
            self.base_rows = list(rows)
            if self.sort_key and self.sort_key not in self._keys:
                self.sort_key, self.sort_descending = "long", False
            self.rows = sort_entities(self.base_rows, self.sort_key, self.sort_descending,
                                      self.health)
            self.endResetModel()

        def sort_by(self, column: int, descending: bool) -> None:
            """Sort by a column, or go back to file-section order when ``column`` is -1."""
            self.sort_key = self._keys[column] if 0 <= column < len(self._keys) else ""
            self.sort_descending = descending
            reorder_rows(self, sort_entities(self.base_rows, self.sort_key, descending,
                                             self.health))

        def sort_column(self) -> int:
            return self._keys.index(self.sort_key) if self.sort_key in self._keys else -1

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self._keys)

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if orientation != Qt.Horizontal or not 0 <= section < len(self._keys):
                return None
            key = self._keys[section]
            if role == DISPLAY:
                return self._titles[key]
            if role == TOOLTIP and key == "section":
                return FILE_SECTION_HINT
            if role == Qt.InitialSortOrderRole:
                return Qt.AscendingOrder        # the first click on a header sorts A to Z
            if role == FONT and key == self.sort_key:
                return self.bold                # the sorted heading, beside its small arrow
            return None

        def flags(self, index):
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if index.isValid() and self._keys[index.column()] in self._slots:
                flags |= Qt.ItemIsEditable
            return flags

        def data(self, index, role=Qt.DisplayRole):
            if role == DISPLAY or role == EDIT:
                key = self._keys[index.column()]
                entity = self.rows[index.row()]
                if key in self._slots:
                    return entity.name_in(key)
                return entity_text(entity, key, self.health)
            if role == FONT:
                return self.bold if self.rows[index.row()].changed() else None
            key = self._keys[index.column()]
            if role == FOREGROUND and key == "status":
                return state_colour(entity_status(self.rows[index.row()], self.health))
            if role == TOOLTIP and key == "status":
                issues = self.health.get(entity_key(self.rows[index.row()]))
                if issues:
                    return "Name health\n" + "\n".join(issue.text for issue in issues)
            if role == TOOLTIP and key in self._slots:
                group = self.rows[index.row()].slots.get(key) or []
                if len(group) > 1:
                    return "Duplicate lines: " + " | ".join(entry.name for entry in group)
                if group and group[0].changed and not group[0].imported:
                    return f"Was: {group[0].orig_name}"
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if role != Qt.EditRole:
                return False
            key = self._keys[index.column()]
            if key not in self._slots:
                return False
            entity = self.rows[index.row()]
            text = str(value).strip()
            problem = name_problem(text)
            if problem:
                if text or entity.slots.get(key):   # an empty cell left empty is no change
                    self.rejected.emit(problem)
                return False
            was_empty = not entity.slots.get(key)
            with Operation(cell_operation(entity, key, text)) as operation:
                changed = set_entity_field(entity, key, text, self.docs)
            if not changed:
                return False
            self._structure = was_empty
            self.row_changed(index.row())
            self.operation_done.emit(operation)
            return True

        def row_changed(self, row):
            self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

    class EntityProxy(QSortFilterProxyModel):
        """Filters the entity grid. The model sorts; this keeps the model's order."""

        def __init__(self):
            super().__init__()
            self.words: list[str] = []
            self.section = ""
            self.mode = "all"
            self.keys = None                    # a collection's members, or None for all
            self.alias = ""                     # a club's formal name, when an alias matched
            self.health = None                  # name_health result for the "health" mode
            self.setDynamicSortFilter(False)

        def configure(self, text: str, section: str, mode: str, keys=None) -> None:
            """Set the filter without running it: a model reset that follows runs it once.

            It searches the words typed; MainWindow.settle_search tries an alias after.
            """
            self.words = fold(text).split()
            self.section = section
            self.mode = mode
            self.keys = keys
            self.alias = ""

        def set_filter(self, text: str, section: str, mode: str, keys=None) -> None:
            self.configure(text, section, mode, keys)
            self.invalidate()

        def set_alias(self, alias: str) -> None:
            """Search a club's formal name instead of the words typed, or go back with ""."""
            self.alias = alias
            self.invalidate()

        def filterAcceptsRow(self, row, parent):
            return entity_shown(self.sourceModel().rows[row], self.words, self.section,
                                self.mode, self.keys, self.alias, self.health)

    class BulkDialog(QDialog):
        """Preview a bulk rename, then apply it in memory.

        The saved rules (affix set, sponsors, small words, casing, scope,
        never-change keys) start the dialog; Save as default rules keeps what
        is on screen. Every preview row has a tick, and only ticked rows are
        applied.
        """

        SCOPE_TEXT = {
            "shown": "Entities in the current filter",
            "family": "Every entity in this family",
            "selected": "Selected rows",
        }
        CASING_TEXT = {
            "capitals": "Only names written wholly in capitals",
            "words": "Also single long capital words (four letters or more)",
        }
        USE, SECTION, ID, FIELD, BEFORE, AFTER = range(6)

        def __init__(self, parent, entities, docs, scopes=None):
            super().__init__(parent)
            self.setWindowTitle("Bulk transformer")
            self.resize(960, 640)
            self.docs = docs
            self.scopes = dict(scopes) if scopes else {"shown": list(entities)}
            self.edits: list[BulkEdit] = []
            self.applied = 0
            self._filling = False
            rules = getattr(parent, "rules", None)
            if rules is None:
                rules = Rules()
            self.exceptions: set = set(rules.exceptions)
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(
                "Preview comes first, and each row has a tick. Apply changes only the "
                "ticked rows and only marks the files as unsaved."))
            row = QHBoxLayout()
            self.mode_group = QButtonGroup(self)
            for kind, label in (
                ("affix", "Affix stripper"),
                ("sponsor", "Sponsor cleanser"),
                ("title", "Title casing"),
            ):
                button = QRadioButton(label)
                button.setProperty("kind", kind)
                self.mode_group.addButton(button)
                row.addWidget(button)
                if kind == "affix":
                    button.setChecked(True)
            row.addStretch(1)
            lay.addLayout(row)
            scope_row = QHBoxLayout()
            scope_row.addWidget(QLabel("Scope:"))
            self.scope_box = QComboBox()
            for key in BULK_SCOPES:
                if key not in self.scopes:
                    continue
                count = len(self.scopes[key])
                self.scope_box.addItem(f"{self.SCOPE_TEXT[key]} ({count})", key)
                if not count:
                    self.scope_box.model().item(self.scope_box.count() - 1).setEnabled(False)
            wanted = self.scope_box.findData(rules.scope)
            if wanted < 0 or not self.scopes.get(rules.scope):
                wanted = self.scope_box.findData("shown")
            self.scope_box.setCurrentIndex(max(wanted, 0))
            scope_row.addWidget(self.scope_box, 1)
            lay.addLayout(scope_row)
            # One options area per mode; only the chosen mode's is shown.
            self.affix_box = QTextEdit()
            self.affix_box.setPlaceholderText("One affix per line, such as FC or AFC")
            self.affix_box.setPlainText("\n".join(rules.affixes))
            self.affix_box.setMaximumHeight(96)
            lay.addWidget(self.affix_box)
            self.sponsor_box = QTextEdit()
            self.sponsor_box.setPlaceholderText("One sponsor phrase per line")
            self.sponsor_box.setPlainText("\n".join(rules.sponsors))
            self.sponsor_box.setMaximumHeight(110)
            lay.addWidget(self.sponsor_box)
            self.casing_widget = QWidget()
            casing_lay = QVBoxLayout(self.casing_widget)
            casing_lay.setContentsMargins(0, 0, 0, 0)
            casing_row = QHBoxLayout()
            casing_row.addWidget(QLabel("Re-case:"))
            self.casing_box = QComboBox()
            for key in CASING_MODES:
                self.casing_box.addItem(self.CASING_TEXT[key], key)
            self.casing_box.setCurrentIndex(max(self.casing_box.findData(rules.casing), 0))
            casing_row.addWidget(self.casing_box, 1)
            casing_lay.addLayout(casing_row)
            self.small_words_box = QTextEdit()
            self.small_words_box.setPlaceholderText(
                "Small words kept in lower case after the first word, one per line")
            self.small_words_box.setPlainText("\n".join(rules.small_words))
            self.small_words_box.setMaximumHeight(96)
            casing_lay.addWidget(self.small_words_box)
            lay.addWidget(self.casing_widget)
            exception_row = QHBoxLayout()
            self.exceptions_label = QLabel()
            exception_row.addWidget(self.exceptions_label, 1)
            self.never_btn = QPushButton("Never change selected rows")
            self.never_btn.setToolTip(
                "Add the entities of the selected preview rows to the never-change list. "
                "Save as default rules keeps the list for later runs.")
            self.never_btn.clicked.connect(self.never_change_selected)
            exception_row.addWidget(self.never_btn)
            self.clear_never_btn = QPushButton("Clear the list")
            self.clear_never_btn.clicked.connect(self.clear_exceptions)
            exception_row.addWidget(self.clear_never_btn)
            lay.addLayout(exception_row)
            buttons = QHBoxLayout()
            preview = QPushButton("Preview")
            preview.clicked.connect(self.preview)
            buttons.addWidget(preview)
            self.tick_all_btn = QPushButton("Tick all")
            self.tick_all_btn.clicked.connect(lambda: self.set_all_ticks(True))
            buttons.addWidget(self.tick_all_btn)
            self.untick_all_btn = QPushButton("Untick all")
            self.untick_all_btn.clicked.connect(lambda: self.set_all_ticks(False))
            buttons.addWidget(self.untick_all_btn)
            # A Save-as-default button writes the rules on screen to
            # state/rules.json, so the next run starts from them. It is on for
            # parents that have keep_rules (the live window).
            self.save_rules_btn = QPushButton("Save as default rules")
            self.save_rules_btn.setToolTip(
                "Write the affixes, sponsors, small words, casing, scope, and never-change "
                "list to state\\rules.json, so they load next time. Nothing in the name "
                "files is written.")
            self.save_rules_btn.clicked.connect(self._save_rules)
            self.save_rules_btn.setEnabled(hasattr(parent, "keep_rules"))
            buttons.addWidget(self.save_rules_btn)
            buttons.addStretch(1)
            lay.addLayout(buttons)
            self.preview_label = QLabel(self.PREVIEW_HINT)
            self.preview_label.setWordWrap(True)
            lay.addWidget(self.preview_label)
            self.table = QTableWidget(0, 6)
            self.table.setHorizontalHeaderLabels(
                ["Use", "File section", "ID", "Field", "Before", "After"])
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.setSelectionBehavior(QTableWidget.SelectRows)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setItemDelegateForColumn(self.USE, TickDelegate(self.table))
            self.table.itemChanged.connect(self.on_tick)
            lay.addWidget(self.table, 1)
            box = QDialogButtonBox()
            self.apply_btn = box.addButton("Apply", QDialogButtonBox.AcceptRole)
            box.addButton(QDialogButtonBox.Cancel)
            self.apply_btn.setEnabled(False)
            box.accepted.connect(self.apply_edits)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.mode_group.buttonClicked.connect(lambda _button: self.invalidate())
            self.scope_box.currentIndexChanged.connect(lambda _index: self.invalidate())
            self.casing_box.currentIndexChanged.connect(lambda _index: self.invalidate())
            for editor_box in (self.sponsor_box, self.affix_box, self.small_words_box):
                editor_box.textChanged.connect(self.invalidate)
            self.refresh_exceptions()
            self.sync_options()

        PREVIEW_HINT = "Choose Preview to see the changes. Nothing is written yet."

        @property
        def entities(self) -> list:
            """The entities the chosen scope covers."""
            return self.scopes.get(self.scope_key(), [])

        def kind(self) -> str:
            button = self.mode_group.checkedButton()
            return button.property("kind") if button else "affix"

        def scope_key(self) -> str:
            return self.scope_box.currentData() or "shown"

        @staticmethod
        def _lines(box) -> list[str]:
            return [line.strip() for line in box.toPlainText().splitlines() if line.strip()]

        def current_rules(self) -> "Rules":
            """The rules as they stand on screen."""
            return Rules(
                sponsors=self._lines(self.sponsor_box),
                small_words=self._lines(self.small_words_box),
                affixes=self._lines(self.affix_box),
                casing=self.casing_box.currentData(),
                scope=self.scope_key(),
                exceptions=self.exceptions,
            )

        def sync_options(self) -> None:
            kind = self.kind()
            self.affix_box.setVisible(kind == "affix")
            self.sponsor_box.setVisible(kind == "sponsor")
            self.casing_widget.setVisible(kind == "title")

        def sync_sponsor(self) -> None:         # the name Session 13 gave it
            self.sync_options()

        def refresh_exceptions(self) -> None:
            count = len(self.exceptions)
            self.exceptions_label.setText(
                f"Never changed by any bulk run: {count_of(count, 'entity', 'entities')}."
                if count else "No entity is on the never-change list.")
            self.clear_never_btn.setEnabled(bool(count))

        def invalidate(self) -> None:
            self.edits = []
            self.apply_btn.setEnabled(False)
            self.apply_btn.setText("Apply")
            self._filling = True
            self.table.setRowCount(0)
            self._filling = False
            self.preview_label.setText(self.PREVIEW_HINT)
            self.sync_options()

        def preview(self) -> None:
            rules = self.current_rules()
            entities = self.entities
            self.edits = preview_bulk(entities, self.kind(), rules.sponsors, rules)
            self._filling = True
            self.table.setRowCount(len(self.edits))
            for row, edit in enumerate(self.edits):
                labels = {slot: label for slot, label, _cmd in FAMILY_FIELDS[edit.entity.family]}
                tick = QTableWidgetItem()
                tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                tick.setCheckState(Qt.Checked if edit.included else Qt.Unchecked)
                self.table.setItem(row, self.USE, tick)
                values = [edit.entity.section, edit.entity.id,
                          labels.get(edit.slot, edit.slot), edit.before, edit.after]
                for col, value in enumerate(values, start=self.SECTION):
                    self.table.setItem(row, col, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            self._filling = False
            if self.kind() == "sponsor" and any(e.family != "comp" for e in entities):
                note = " The sponsor cleanser only changes competitions."
            else:
                note = ""
            if not entities:
                note += " Nothing is in this scope."
            self.preview_label.setText(f"{len(self.edits)} line(s) would change.{note}")
            self.update_apply()

        def on_tick(self, item) -> None:
            if self._filling or item.column() != self.USE:
                return
            row = item.row()
            if 0 <= row < len(self.edits):
                self.edits[row].included = item.checkState() == Qt.Checked
                self.update_apply()

        def set_all_ticks(self, on: bool) -> None:
            self._filling = True
            for row, edit in enumerate(self.edits):
                edit.included = on
                item = self.table.item(row, self.USE)
                if item is not None:
                    item.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self._filling = False
            self.update_apply()

        def ticked(self) -> int:
            return sum(1 for edit in self.edits if edit.included)

        def update_apply(self) -> None:
            ticked = self.ticked()
            self.apply_btn.setEnabled(ticked > 0)
            self.apply_btn.setText(f"Apply {ticked} ticked" if self.edits else "Apply")

        def never_change_selected(self) -> None:
            rows = {index.row() for index in self.table.selectionModel().selectedRows()}
            keys = {entity_key(self.edits[row].entity) for row in rows if row < len(self.edits)}
            if not keys:
                return
            self.exceptions |= keys
            self.refresh_exceptions()
            self.preview()          # those entities drop out of the list

        def clear_exceptions(self) -> None:
            self.exceptions.clear()
            self.refresh_exceptions()
            self.invalidate()

        def apply_edits(self) -> None:
            if not self.ticked():
                return
            self.applied = apply_bulk(self.edits, self.docs)
            self.accept()

        def _save_rules(self) -> None:
            new_rules = self.current_rules()
            parent = self.parent()
            problem = parent.keep_rules(new_rules)
            if problem:
                QMessageBox.warning(self, APP_NAME,
                                    f"The default rules were not saved.\n\n{problem}")
                return
            parent.rules = new_rules
            QMessageBox.information(
                self, APP_NAME,
                f"Saved the rules to {STATE_ROOT / RULES_FILE}: "
                f"{count_of(len(new_rules.affixes), 'affix', 'affixes')}, "
                f"{count_of(len(new_rules.sponsors), 'sponsor')}, "
                f"{count_of(len(new_rules.exceptions), 'never-change entity', 'never-change entities')}. "
                "The next run starts from them.")

    class BatchPreviewModel(QAbstractTableModel):
        """The batch preview keeps ticks on the edits, including hidden rows."""

        ticks_changed = Signal()
        HEADERS = ("Use", "ID", "Entity name", "Field", "Current value", "Proposed value")

        def __init__(self, parent=None):
            super().__init__(parent)
            self.rows = []
            self.bold = QFont()
            self.bold.setBold(True)

        def set_rows(self, edits):
            self.beginResetModel()
            self.rows = list(edits)
            self.endResetModel()

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.HEADERS)

        def headerData(self, section, orientation, role=DISPLAY):
            if orientation == Qt.Horizontal and role == DISPLAY:
                return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None
            return None

        def flags(self, index):
            if not index.isValid():
                return Qt.NoItemFlags
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            edit = self.rows[index.row()]
            if index.column() == 0 and edit.before != edit.after:
                flags |= Qt.ItemIsUserCheckable
            return flags

        def data(self, index, role=DISPLAY):
            if not index.isValid() or not 0 <= index.row() < len(self.rows):
                return None
            edit = self.rows[index.row()]
            column = index.column()
            changed = edit.before != edit.after
            reason = getattr(edit, "reason", "")
            if role == Qt.CheckStateRole and column == 0:
                return Qt.Checked if changed and edit.included else Qt.Unchecked
            if role == DISPLAY:
                entity = edit.entity
                labels = {slot: label for slot, label, _cmd in FAMILY_FIELDS[entity.family]}
                after_text = (edit.after if changed
                              else (f"(unticked: {reason})" if reason else "(No change)"))
                values = ("", entity.id, entity.name_in("long") or entity.name_in("name")
                          or entity.name_in("short"), labels.get(edit.slot, edit.slot),
                          edit.before, after_text)
                return values[column]
            if role == FONT and column == 5 and changed:
                return self.bold
            if role == FOREGROUND and column == 5 and changed:
                return COLOURS["edited"]
            if role == TOOLTIP:
                if reason:
                    return reason
                if column == 5 and changed:
                    start = 0
                    while (start < min(len(edit.before), len(edit.after))
                           and edit.before[start] == edit.after[start]):
                        start += 1
                    end_before, end_after = len(edit.before), len(edit.after)
                    while (end_before > start and end_after > start
                           and edit.before[end_before - 1] == edit.after[end_after - 1]):
                        end_before -= 1
                        end_after -= 1
                    return (f"Changed text: {edit.before[start:end_before]!r} → "
                            f"{edit.after[start:end_after]!r}")
                return f"{edit.entry.doc.path.name}, line {edit.entry.lineno}"
            return None

        def setData(self, index, value, role=EDIT):
            if (not index.isValid() or index.column() != 0
                    or role != Qt.CheckStateRole):
                return False
            edit = self.rows[index.row()]
            if edit.before == edit.after:
                return False
            edit.included = value == Qt.Checked or value == Qt.Checked.value
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.ticks_changed.emit()
            return True

        def refresh_ticks(self):
            if self.rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0),
                                      [Qt.CheckStateRole])
            self.ticks_changed.emit()

    class BatchRenameDialog(QDialog):
        """Preview selected name lines; the window records and applies the accepted edit."""

        MODES = (("Replace text", "replace"), ("Add prefix", "add_prefix"),
                 ("Remove prefix", "remove_prefix"), ("Add suffix", "add_suffix"),
                 ("Remove suffix", "remove_suffix"), ("Regular expression", "regex"))
        PRESETS = tuple((label, source, target, mode)
                        for label, mode, source, target in BATCH_RENAME_PRESETS)

        def __init__(self, parent, entities, docs, initial_token="", replacement="",
                     regex=False, suggestion=None, pinned_pairs=()):
            super().__init__(parent)
            self.entities = list(entities)
            self.docs = list(docs)
            self.edits = []
            self.applied = 0
            self._ready = False
            # The selection suggestion (basis, count, total, source, target), or
            # None; the label states it in plain words, the preview takes the
            # preset when one exists but Apply still requires a tick.
            self.suggestion = suggestion
            self.setWindowTitle("Batch rename selected names")
            self.setStyleSheet(theme_style_sheet())
            self.resize(920, 620)
            layout = QVBoxLayout(self)
            documents = {entry.doc for entity in self.entities for entry in entity.entries()}
            lines = sum(1 for entity in self.entities for _entry in entity.entries())
            families = {entity.family for entity in self.entities}
            family = (FAMILY_LABELS[next(iter(families))].lower() if len(families) == 1
                      else "entities")
            self.scope_label = QLabel(
                f"Targeting {len(self.entities):,} selected {family} "
                f"({lines:,} total lines across {count_of(len(documents), 'document')})")
            self.scope_label.setWordWrap(True)
            layout.addWidget(self.scope_label)
            self.suggestion_label = QLabel()
            self.suggestion_label.setObjectName("muted")
            self.suggestion_label.setWordWrap(True)
            self.suggestion_label.setVisible(bool(self.suggestion))
            if self.suggestion is not None:
                basis, count, total, source, target = self.suggestion
                if target:
                    detail = f"suggested {source} → {target}"
                else:
                    detail = "no built-in preset; type a replacement to continue"
                scope = (f"in all {total} selected names" if count == total
                         else f"in {count} of {total} selected names")
                self.suggestion_label.setText(
                    f"Based on '{basis}' {scope} — {detail}. Clear or type your own below.")
            layout.addWidget(self.suggestion_label)
            note = QLabel("Preview first. Apply changes only in memory; Save or Deploy writes "
                          "the reviewed changes. Existing overrides only; no fields are added.")
            note.setWordWrap(True)
            layout.addWidget(note)
            form = QGridLayout()
            self.mode_box = QComboBox()
            for label, key in self.MODES:
                self.mode_box.addItem(label, key)
            self.mode_box.setCurrentIndex(self.mode_box.findData("regex" if regex else "replace"))
            self.preset_box = QComboBox()
            self.preset_box.addItem("Choose a football preset…", None)
            for label, source, target, mode in self.PRESETS:
                self.preset_box.addItem(label, (source, target, mode))
            form.addWidget(QLabel("Mode:"), 0, 0)
            form.addWidget(self.mode_box, 0, 1)
            form.addWidget(QLabel("Quick preset:"), 0, 2)
            form.addWidget(self.preset_box, 0, 3)
            self.find_edit = QLineEdit(initial_token)
            self.replace_edit = QLineEdit(replacement)
            self.find_label = QLabel("Find:")
            self.replace_label = QLabel("Replace with:")
            form.addWidget(self.find_label, 1, 0)
            form.addWidget(self.find_edit, 1, 1)
            form.addWidget(self.replace_label, 1, 2)
            form.addWidget(self.replace_edit, 1, 3)
            # Pin the current Replace pair, so Harmonise and Select similar
            # can offer it next time. Enabled only when the preview shows
            # both forms: Replace mode with non-empty Find and Replace with.
            self.pinned_pairs = tuple(pinned_pairs)
            self.pin_pair_btn = QPushButton("Pin this pair…")
            self.pin_pair_btn.setToolTip(
                "Save Find → Replace with as a pinned pair for later "
                "selections and Harmonise.")
            self.pin_pair_btn.clicked.connect(self._pin_current_pair)
            form.addWidget(self.pin_pair_btn, 2, 3)
            layout.addLayout(form)
            fields = QHBoxLayout()
            fields.addWidget(QLabel("Fields:"))
            self.target_long = QCheckBox("Long name / name")
            self.target_short = QCheckBox("Short name")
            self.target_code = QCheckBox("Code")
            self.target_long.setChecked(True)
            self.target_short.setChecked(True)
            self.target_code.setToolTip("Change existing code overrides only.")
            for check in (self.target_long, self.target_short, self.target_code):
                fields.addWidget(check)
            fields.addStretch(1)
            layout.addLayout(fields)
            options = QHBoxLayout()
            self.whole_word = QCheckBox("Whole word only")
            self.whole_word.setChecked(True)
            self.case_sensitive = QCheckBox("Case sensitive")
            self.match_accents = QCheckBox("Match accents")
            self.match_accents.setChecked(True)
            self.preserve_case = QCheckBox("Preserve capitalisation")
            self.preserve_case.setChecked(True)
            self.preserve_case.setToolTip("Use capitals for an all-capital match and lower case "
                                         "for a lower-case match.")
            for check in (self.whole_word, self.case_sensitive, self.match_accents,
                          self.preserve_case):
                options.addWidget(check)
            options.addStretch(1)
            layout.addLayout(options)
            self.auto_sync_short = QCheckBox("Also transform short names with no unsaved edits")
            self.auto_sync_short.setToolTip("Transform an existing short name only when every "
                                           "line for it still matches the disk baseline.")
            layout.addWidget(self.auto_sync_short)
            self.problem_label = QLabel()
            self.problem_label.setObjectName("warning")
            self.problem_label.setWordWrap(True)
            layout.addWidget(self.problem_label)
            controls = QHBoxLayout()
            self.tick_all_btn = QPushButton("Tick all")
            self.untick_all_btn = QPushButton("Untick all")
            self.invert_ticks_btn = QPushButton("Invert ticks")
            self.tick_all_btn.clicked.connect(lambda: self.set_all_ticks(True))
            self.untick_all_btn.clicked.connect(lambda: self.set_all_ticks(False))
            self.invert_ticks_btn.clicked.connect(self.invert_ticks)
            for button in (self.tick_all_btn, self.untick_all_btn, self.invert_ticks_btn):
                controls.addWidget(button)
            self.hide_unchanged = QCheckBox("Hide unchanged rows")
            self.hide_unchanged.setChecked(True)
            self.hide_unchanged.toggled.connect(self.show_preview_rows)
            controls.addWidget(self.hide_unchanged)
            controls.addStretch(1)
            layout.addLayout(controls)
            self.counter_label = QLabel()
            layout.addWidget(self.counter_label)
            self.table = QTableView()
            self.preview_model = BatchPreviewModel(self)
            self.table.setModel(self.preview_model)
            self.table.setItemDelegateForColumn(0, TickDelegate(self.table))
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setAlternatingRowColors(True)
            self.table.setWordWrap(False)
            self.table.verticalHeader().setVisible(False)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.preview_model.ticks_changed.connect(self.update_apply)
            layout.addWidget(self.table, 1)
            buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.apply_btn = buttons.addButton("Apply changes", QDialogButtonBox.AcceptRole)
            self.apply_btn.setObjectName("review")
            self.apply_btn.setAutoDefault(False)
            buttons.accepted.connect(self.accept_edits)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self.apply_shortcut = QAction(self)
            self.apply_shortcut.setShortcuts(
                [QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter")])
            self.apply_shortcut.triggered.connect(self.accept_edits)
            self.addAction(self.apply_shortcut)
            self.preview_timer = QTimer(self)
            self.preview_timer.setSingleShot(True)
            self.preview_timer.setInterval(120)
            self.preview_timer.timeout.connect(self.refresh_preview)
            for check in (self.target_long, self.target_short, self.target_code,
                          self.whole_word, self.case_sensitive, self.match_accents,
                          self.preserve_case, self.auto_sync_short):
                check.toggled.connect(self.queue_preview)
            self.mode_box.currentIndexChanged.connect(self.queue_preview)
            self.find_edit.textChanged.connect(self.queue_preview)
            self.replace_edit.textChanged.connect(self.queue_preview)
            self.preset_box.activated.connect(self.choose_preset)
            self._ready = True
            self.refresh_preview()
            screen = self.screen().availableGeometry()
            self.resize(min(920, screen.width() - 40), min(620, screen.height() - 40))

        @property
        def description(self):
            mode = self.mode_box.currentData()
            if mode in ("replace", "regex"):
                return f"{self.find_edit.text()} → {self.replace_edit.text()}"
            return f"{self.mode_box.currentText().lower()}: " + (
                self.replace_edit.text() if mode.startswith("add_") else self.find_edit.text())

        def current_rule(self):
            return BatchRenameRule(
                mode=self.mode_box.currentData(), find=self.find_edit.text(),
                replacement=self.replace_edit.text(), whole_word=self.whole_word.isChecked(),
                case_sensitive=self.case_sensitive.isChecked(),
                match_accents=self.match_accents.isChecked(),
                preserve_case=self.preserve_case.isChecked())

        def sync_options(self):
            mode = self.mode_box.currentData()
            regex = mode == "regex"
            add = mode in ("add_prefix", "add_suffix")
            remove = mode in ("remove_prefix", "remove_suffix")
            self.find_edit.setEnabled(not add)
            self.replace_edit.setEnabled(not remove)
            self.find_label.setText("Remove:" if remove else "Find:")
            self.replace_label.setText("Add:" if add else "Replace with:")
            self.whole_word.setEnabled(not regex and not add)
            self.match_accents.setEnabled(not regex and not add)
            self.preserve_case.setEnabled(not regex and not add and not remove)
            self.auto_sync_short.setEnabled(not self.target_short.isChecked())
            self.find_edit.setToolTip("Python regular expression; replacements accept \\1 and "
                                     "\\g<name>." if regex else "Text to match.")
            # Pin is only meaningful when the preview shows both forms: a
            # Replace with two non-empty sides. Everything else is refused.
            full = self.find_edit.text().strip()
            short = self.replace_edit.text().strip()
            self.pin_pair_btn.setEnabled(
                mode == "replace" and bool(full) and bool(short))

        def _pin_current_pair(self) -> None:
            """Ask the window to pin the current Replace pair.

            The parent window is the holder of the ``Rules`` and ``state/rules.json``;
            it writes the file and shows the result. Save and Deploy do not
            touch the pin list (brief acceptance for Stage 1).
            """
            parent = self.parent()
            full = self.find_edit.text().strip()
            short = self.replace_edit.text().strip()
            if not hasattr(parent, "pin_pair_requested"):
                return
            if parent.pin_pair_requested(full, short, source=self):
                self.pinned_pairs = tuple(parent.rules.pinned_pairs)

        def queue_preview(self, *_args):
            if not self._ready:
                return
            self.sync_options()
            self.apply_btn.setEnabled(False)
            self.apply_shortcut.setEnabled(False)
            self.preview_timer.start()

        def refresh_preview(self):
            self.preview_timer.stop()
            self.sync_options()
            slots = []
            if self.target_long.isChecked():
                slots.extend(("long", "name"))
            if self.target_short.isChecked():
                slots.append("short")
            if self.target_code.isChecked():
                slots.append("code")
            try:
                self.edits = preview_batch_rename(
                    self.entities, self.current_rule(), slots=slots,
                    auto_sync_short=(self.auto_sync_short.isChecked()
                                     and not self.target_short.isChecked()),
                    include_unchanged=True)
                self._mark_short_already_target()
                self.problem_label.setText("")
            except (ValueError, re.error) as exc:
                self.edits = []
                self.problem_label.setText(f"Preview unavailable: {exc}")
            self.show_preview_rows()

        def _mark_short_already_target(self):
            """Flag short-name rows that already read the Replace target.

            When the long-name of an entity is being transformed and its
            short-name already uses the other form of the pair, show the
            short-name row unticked with a reason ("short name already
            reads Utd"). The row stays visible when "Hide unchanged" is on.
            A different-wording short (Man Utd) is left alone: it has no
            match for the needle as a whole word.
            """
            rule = self.current_rule()
            if rule.mode != "replace" or not rule.find or not rule.replacement:
                return
            needle = rule.replacement.strip()
            if not needle:
                return
            changed_long = {id(edit.entity) for edit in self.edits
                            if edit.slot in {"long", "name"}
                            and edit.before != edit.after}
            if not changed_long:
                return
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            pattern = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", flags)
            # Mark existing no-change short-name edits that already read the target.
            seen_entries = set()
            for edit in self.edits:
                seen_entries.add(id(edit.entry))
                if (edit.slot == "short" and edit.before == edit.after
                        and id(edit.entity) in changed_long
                        and pattern.search(edit.before)):
                    edit.included = False
                    edit.reason = f"short name already reads {needle}"
            # If the short slot was not in the preview, add informational rows.
            for entity in self.entities:
                if id(entity) not in changed_long:
                    continue
                for entry in entity.slots.get("short") or []:
                    if id(entry) in seen_entries:
                        continue
                    if pattern.search(entry.name):
                        info = BulkEdit(entity, "short", entry, entry.name, entry.name)
                        info.included = False
                        info.reason = f"short name already reads {needle}"
                        self.edits.append(info)
                        seen_entries.add(id(entry))

        def show_preview_rows(self, *_args):
            rows = [edit for edit in self.edits
                    if not self.hide_unchanged.isChecked()
                    or edit.before != edit.after
                    or getattr(edit, "reason", "")]
            self.preview_model.set_rows(rows)
            fit_columns(self.table, {
                0: ["Use"], 1: [edit.entity.id for edit in rows],
                2: [edit.entity.name_in("long") or edit.entity.name_in("name") for edit in rows],
                3: ["Long name", "Short name", "Code"],
                4: [edit.before for edit in rows], 5: [edit.after for edit in rows]},
                {0: 52, 1: 96, 2: 210, 3: 125, 4: 240, 5: 240})
            self.update_apply()

        def ticked(self):
            return sum(edit.included and edit.before != edit.after for edit in self.edits)

        def update_apply(self):
            ticked = self.ticked()
            total = sum(edit.before != edit.after for edit in self.edits)
            self.counter_label.setText(f"{ticked:,} of {total:,} changes selected")
            self.apply_btn.setText(f"Apply {ticked:,} ticked edits")
            enabled = bool(ticked) and not self.preview_timer.isActive()
            self.apply_btn.setEnabled(enabled)
            self.apply_shortcut.setEnabled(enabled)

        def set_all_ticks(self, on):
            for edit in self.edits:
                edit.included = bool(on) and edit.before != edit.after
            self.preview_model.refresh_ticks()

        def invert_ticks(self):
            for edit in self.edits:
                edit.included = not edit.included and edit.before != edit.after
            self.preview_model.refresh_ticks()

        def choose_preset(self, index):
            preset = self.preset_box.itemData(index)
            if preset:
                source, target, mode = preset
                self.apply_preset(source, target, mode)

        def apply_preset(self, source, target, mode="replace"):
            self.mode_box.setCurrentIndex(self.mode_box.findData(mode))
            self.find_edit.setText(source)
            self.replace_edit.setText(target)
            self.whole_word.setChecked(True)
            self.refresh_preview()

        def accept_edits(self):
            if self.preview_timer.isActive():
                self.refresh_preview()
            if self.ticked():
                self.accept()

        def apply_edits(self):
            self.applied = apply_batch_rename(self.edits, self.docs)
            return self.applied

    class HarmoniseDialog(QDialog):
        """Choose a terminology direction, then review it in the batch preview.

        The built-in pairs (United/Utd, City/Cty, Saint/St./St and so on) are
        shown first; pinned pairs the user keeps in ``state/rules.json`` are
        listed under them, with counts for each form. The pin list is managed
        from this dialog: Pin new pair… and Delete pinned pair.
        """

        def __init__(self, parent, entities, findings=None, pinned_pairs=()):
            super().__init__(parent)
            self.setWindowTitle("Harmonise terminology")
            self.resize(720, 520)
            self.choice = None
            self.entities = list(entities)
            self.pinned_pairs = tuple(pinned_pairs)
            # built-ins first, then pinned pairs (always shown even with a zero
            # count so the user sees every pin).
            if findings is None:
                self.builtin_findings = find_naming_inconsistencies(self.entities)
            else:
                self.builtin_findings = list(findings)
            self.pinned_findings = pinned_pair_clusters(self.pinned_pairs, self.entities)
            self.findings = self.builtin_findings + self.pinned_findings
            layout = QVBoxLayout(self)
            note = QLabel("Mixed full and abbreviated forms in loaded club names. "
                          "Pinned pairs are shown under the built-ins, with counts "
                          "for each form. One club using both forms is counted "
                          "under both: the numbers are not a total of clubs.")
            note.setWordWrap(True)
            layout.addWidget(note)
            self.opportunities = QListWidget()
            self._fill_opportunities()
            layout.addWidget(self.opportunities, 1)
            self.direction_box = QComboBox()
            layout.addWidget(self.direction_box)
            self.hint = QLabel("" if self.findings
                               else "No mixed terminology or pinned pairs were found.")
            self.hint.setWordWrap(True)
            layout.addWidget(self.hint)
            manage = QHBoxLayout()
            self.pin_new_btn = QPushButton("Pin new pair…")
            self.pin_new_btn.setToolTip(
                "Add a whole-word pair the editor will remember.")
            self.pin_new_btn.clicked.connect(self._pin_new_pair)
            self.delete_pin_btn = QPushButton("Delete pinned pair")
            self.delete_pin_btn.setToolTip(
                "Remove the selected pinned pair. No club is renamed.")
            self.delete_pin_btn.setEnabled(False)
            self.delete_pin_btn.clicked.connect(self._delete_selected_pin)
            manage.addWidget(self.pin_new_btn)
            manage.addWidget(self.delete_pin_btn)
            manage.addStretch(1)
            layout.addLayout(manage)
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            self.review_btn = buttons.addButton("Review this standardisation…",
                                               QDialogButtonBox.AcceptRole)
            self.review_btn.setEnabled(False)
            buttons.rejected.connect(self.reject)
            buttons.accepted.connect(self.choose_direction)
            layout.addWidget(buttons)
            self.opportunities.currentRowChanged.connect(self._on_row)
            if self.findings:
                self.opportunities.setCurrentRow(0)

        def _fill_opportunities(self) -> None:
            """Fill the list widget with built-in and pinned clusters."""
            self.opportunities.clear()
            pinned_offset = len(self.builtin_findings)
            for row, cluster in enumerate(self.findings):
                prefix = "Pinned: " if row >= pinned_offset else ""
                detail = "; ".join(f"{term}: {len(matches):,} clubs"
                                   for term, matches in cluster.variants)
                self.opportunities.addItem(f"{prefix}{cluster.label} — {detail}")

        def _on_row(self, row: int) -> None:
            """Fill the direction box and update the Delete button for the row."""
            self.fill_directions(row)
            pinned_offset = len(self.builtin_findings)
            self.delete_pin_btn.setEnabled(row >= pinned_offset
                                           and row < len(self.findings))

        def fill_directions(self, row):
            self.direction_box.clear()
            if not 0 <= row < len(self.findings):
                self.review_btn.setEnabled(False)
                return
            variants = self.findings[row].variants
            for source, entities in variants:
                if not entities:    # a pinned pair with no club on this side
                    continue
                for target, _matches in variants:
                    if source != target:
                        self.direction_box.addItem(
                            f"Standardise {len(entities):,} '{source}' clubs to '{target}'",
                            (harmonisation_pattern(source) if source == "St" else source,
                             target, list(entities), source == "St"))
            self.review_btn.setEnabled(self.direction_box.count() > 0)

        def choose_direction(self):
            choice = self.direction_box.currentData()
            if choice:
                self.choice = choice
                self.accept()

        def _pin_new_pair(self) -> None:
            """Ask the window to open the pair-input dialog and pin the result."""
            parent = self.parent()
            if not hasattr(parent, "pin_new_pair_via_dialog"):
                return
            if parent.pin_new_pair_via_dialog(self):
                self._refresh_pinned()

        def _delete_selected_pin(self) -> None:
            """Remove the selected pinned pair from the list."""
            row = self.opportunities.currentRow()
            offset = len(self.builtin_findings)
            if row < offset or row >= len(self.findings):
                return
            full, short = self.pinned_pairs[row - offset]
            parent = self.parent()
            if not hasattr(parent, "delete_pinned_pair"):
                return
            if parent.delete_pinned_pair(full, short, source=self):
                self._refresh_pinned()

        def _refresh_pinned(self) -> None:
            """Re-read the parent's pin list and refill the opportunity list."""
            parent = self.parent()
            self.pinned_pairs = tuple(parent.rules.pinned_pairs)
            self.pinned_findings = pinned_pair_clusters(self.pinned_pairs, self.entities)
            self.findings = self.builtin_findings + self.pinned_findings
            previous = self.opportunities.currentRow()
            self._fill_opportunities()
            if self.findings:
                row = min(previous, len(self.findings) - 1) if previous >= 0 else 0
                self.opportunities.setCurrentRow(row)
            else:
                self.delete_pin_btn.setEnabled(False)
                self.review_btn.setEnabled(False)

    class PinPairDialog(QDialog):
        """Ask for a whole-word pair and validate it against the rules.

        ``check`` returns why the pair cannot be used, or "". The problem is
        shown under the fields and the dialog stays open, so the text the
        user typed is never thrown away. Dotted and undotted forms stay
        distinct, so "St" and "St." are refused only when they would
        duplicate a built-in or an existing pin.
        """

        def __init__(self, parent, check):
            super().__init__(parent)
            self.setWindowTitle("Pin a spelling pair")
            self.check = check
            lay = QVBoxLayout(self)
            note = QLabel(
                "Pin a pair of whole-word spellings. Harmonise lists them "
                "under the built-ins, Select similar offers the other form, "
                "and Batch rename may suggest them from the selection. "
                "Applying a pair still goes through Batch rename.")
            note.setWordWrap(True)
            lay.addWidget(note)
            form = QFormLayout()
            self.full_edit = QLineEdit()
            self.full_edit.setPlaceholderText("Rovers")
            self.short_edit = QLineEdit()
            self.short_edit.setPlaceholderText("Rvrs")
            for widget in (self.full_edit, self.short_edit):
                widget.setMaxLength(80)
            form.addRow("Full spelling", self.full_edit)
            form.addRow("Short spelling", self.short_edit)
            lay.addLayout(form)
            self.problem = QLabel("")
            self.problem.setObjectName("warning")
            self.problem.setWordWrap(True)
            lay.addWidget(self.problem)
            box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            box.accepted.connect(self.try_accept)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.resize(480, self.sizeHint().height())

        def try_accept(self) -> None:
            full, short = self.full_edit.text(), self.short_edit.text()
            problem = self.check(full, short)
            if problem:
                self.problem.setText(problem)
                self.full_edit.setFocus()
                return
            self.accept()

        def values(self) -> tuple[str, str]:
            return self.full_edit.text().strip(), self.short_edit.text().strip()

    class CommandPaletteDialog(QDialog):
        """Search the available commands; one extra choice selects a name word."""

        def __init__(self, parent, commands):
            super().__init__(parent)
            self.setWindowTitle("Command palette")
            self.resize(720, 440)
            self.commands = list(commands)
            self.matches = []
            self.chosen = None
            layout = QVBoxLayout(self)
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("Type a command, saved search, collection or name word…")
            layout.addWidget(self.search_edit)
            self.list_widget = QListWidget()
            layout.addWidget(self.list_widget, 1)
            hint = QLabel("Enter runs the highlighted command. Escape closes this window.")
            layout.addWidget(hint)
            buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.run_btn = buttons.addButton("Run", QDialogButtonBox.AcceptRole)
            buttons.accepted.connect(self.run_selected)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self.search_edit.textChanged.connect(self.refresh_matches)
            self.search_edit.returnPressed.connect(self.run_selected)
            self.list_widget.itemActivated.connect(lambda _item: self.run_selected())
            self.search_edit.installEventFilter(self)
            self.refresh_matches()
            self.search_edit.setFocus()

        @staticmethod
        def search_score(query, label):
            query, label = query.casefold(), label.casefold()
            if not query:
                return 0
            if query in label:
                return label.index(query)
            if all(word in label for word in query.split()):
                return 100
            position = 0
            for letter in query.replace(" ", ""):
                position = label.find(letter, position)
                if position < 0:
                    return None
                position += 1
            return 200 + position

        def refresh_matches(self, *_args):
            query = self.search_edit.text().strip()
            ranked = []
            for command in self.commands:
                label, shortcut, callback, enabled = command
                score = self.search_score(query, label)
                if score is not None:
                    ranked.append((score, label.casefold(), command))
            ranked.sort(key=lambda row: (row[0], row[1]))
            self.matches = [row[2] for row in ranked]
            parent = self.parent()
            if query and hasattr(parent, "select_entities_by_token"):
                self.matches.append((f"Select visible names containing '{query}'", "",
                                     lambda word=query: parent.select_entities_by_token(word),
                                     not getattr(parent, "busy", False)))
            self.list_widget.clear()
            for label, shortcut, _callback, enabled in self.matches:
                item = QListWidgetItem(label + (f"    {shortcut}" if shortcut else ""))
                if not enabled:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.list_widget.addItem(item)
            first = next((row for row, command in enumerate(self.matches) if command[3]), -1)
            self.list_widget.setCurrentRow(first)
            self.run_btn.setEnabled(first >= 0)

        def run_selected(self):
            row = self.list_widget.currentRow()
            if 0 <= row < len(self.matches) and self.matches[row][3]:
                self.chosen = self.matches[row][2]
                self.accept()

        def eventFilter(self, watched, event):
            if (watched is self.search_edit and event.type() == event.Type.KeyPress
                    and event.key() in (Qt.Key_Down, Qt.Key_Up)):
                step = 1 if event.key() == Qt.Key_Down else -1
                row = self.list_widget.currentRow() + step
                while 0 <= row < len(self.matches):
                    if self.matches[row][3]:
                        self.list_widget.setCurrentRow(row)
                        return True
                    row += step
                return True
            return super().eventFilter(watched, event)

    def confirm_game_write(parent, preflight: Preflight, question: str, note: str = "") -> bool:
        """Show a preflight result and ask once. True means the write may go ahead.

        A running game is refused outright, with the same message for Save,
        Deploy, and the licensing toggle. An unknown process state is stated
        in the question, with No as the default answer. The question lists
        the exact game files the operation would write.
        """
        if preflight.blocked:
            QMessageBox.warning(parent, APP_NAME, preflight.blocked_message())
            return False
        listed = preflight.game_paths or preflight.paths
        text = question + "\n\n" + "\n".join(str(path) for path in listed)
        if note:
            text += "\n\n" + note
        default = QMessageBox.Yes
        if preflight.check_failed:
            text += "\n\n" + preflight.unknown_message()
            default = QMessageBox.No
        answer = QMessageBox.question(
            parent, APP_NAME, text, QMessageBox.Yes | QMessageBox.No, default)
        return answer == QMessageBox.Yes

    class LicenceDialog(QDialog):
        """Report licensing files, and set aside the name-mask set.

        A toggle goes in steps: a game check on the window's worker, the
        confirmation, a fresh game check (a game started while the question
        was open still stops it), then the rename the person confirmed,
        disable or restore, never whatever the file's state then suggests.
        One toggle runs at a time, and closing the dialog by any route
        (Close, Esc, the title bar) drops a toggle that is still waiting.
        """

        def __init__(self, parent, version: Path):
            super().__init__(parent)
            self.version = version
            self.rows: list[dict] = []
            self.pending = 0            # the number of the toggle under way; 0 when none
            self.serial = 0
            self.closed = False
            self.setWindowTitle("Licensing health")
            self.resize(760, 460)
            lay = QVBoxLayout(self)
            note = QLabel(
                "Name-mask files can be renamed to .disabled so your .lnc spellings "
                "are not overridden in the game. A copy is stored in the backups "
                "folder first. Nothing is deleted, and the file contents are not edited. "
                "Report-only files are shown and left alone.")
            note.setWordWrap(True)
            lay.addWidget(note)
            self.table = QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["File", "Role", "State"])
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.setSelectionBehavior(QTableWidget.SelectRows)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table, 1)
            row = QHBoxLayout()
            self.toggle_btn = QPushButton("Toggle selected name mask")
            self.toggle_btn.clicked.connect(self.toggle_selected)
            row.addWidget(self.toggle_btn)
            row.addStretch(1)
            self.close_btn = QPushButton("Close")
            self.close_btn.clicked.connect(self.reject)
            row.addWidget(self.close_btn)
            lay.addLayout(row)
            self.refresh()

        def done(self, result: int) -> None:
            """Every way of closing ends here: a toggle still waiting is dropped."""
            self.closed = True
            super().done(result)

        def current(self, request: int) -> bool:
            """True while ``request`` is the toggle under way and the dialog is open."""
            return not self.closed and request == self.pending

        def end_toggle(self, request: int) -> None:
            """A toggle is over, however it ended: another may start."""
            if request == self.pending:
                self.pending = 0
            self.toggle_btn.setEnabled(True)

        def check_game(self, then) -> None:
            """Look for a running game on the window's worker, then call ``then(found)``.

            A check that breaks counts as unknown (None), never as closed.
            """
            jobs = getattr(self.parent(), "jobs", None)
            if jobs is None:
                try:
                    found = football_manager_running()
                except Exception:           # unknown, as on the worker
                    found = None
                then(found)
                return
            jobs.start(GAME_CHECK, football_manager_running, then, lambda _error: then(None))

        def refresh(self) -> None:
            self.rows = licence_inventory(self.version)
            labels = {
                "present": "Present",
                "disabled": "Disabled",
                "missing": "Missing",
                "both": "Present, and a .disabled copy too",
            }
            self.table.setRowCount(len(self.rows))
            for index, row in enumerate(self.rows):
                role = "Name mask" if row["toggle"] else "Report only"
                self.table.setItem(index, 0, QTableWidgetItem(row["name"]))
                self.table.setItem(index, 1, QTableWidgetItem(role))
                self.table.setItem(index, 2, QTableWidgetItem(labels[row["state"]]))
            self.table.resizeColumnsToContents()

        def toggle_selected(self) -> None:
            if self.pending or self.closed:
                return                      # one toggle at a time, and none once closed
            selected = self.table.currentRow()
            if selected < 0:
                return
            row = self.rows[selected]
            if not row["toggle"] or row["state"] == "missing":
                QMessageBox.information(
                    self, APP_NAME,
                    "Only a present or disabled name-mask file can be toggled.")
                return
            if row["state"] == "both":
                QMessageBox.information(
                    self, APP_NAME,
                    f"{row['name']} and its .disabled copy are both in the folder. The "
                    "editor will not choose between them. Move or rename one of them "
                    "yourself, then try again.")
                return
            intent = licence_intent(row["state"])
            current = row["path"]
            if intent == "restore":
                current = current.with_name(current.name + ".disabled")
            self.serial += 1
            request = self.pending = self.serial
            self.toggle_btn.setEnabled(False)
            self.check_game(lambda found: self.confirm_toggle(request, row, intent, current,
                                                              found))

        def confirm_toggle(self, request: int, row: dict, intent: str, current: Path,
                           found) -> None:
            """The first game check is back: refuse a running game, or ask."""
            if not self.current(request):
                return                      # closed, or not this toggle: nothing more
            preflight = game_write_preflight(
                f"{intent} a licensing file", [current], check=lambda: found)
            if not confirm_game_write(
                    self, preflight, f"This will {intent} the file below.",
                    "A copy is stored in the backups folder first. The file is renamed "
                    "in one step and its contents are not changed."):
                self.end_toggle(request)
                return
            if not self.current(request):
                return
            # The answer may have taken a while: look again before renaming.
            self.check_game(lambda again: self.commit_toggle(request, row, intent, current,
                                                             again))

        def commit_toggle(self, request: int, row: dict, intent: str, current: Path,
                          found) -> None:
            """The game check after Yes is back: rename only while the game is closed."""
            if not self.current(request):
                return
            preflight = game_write_preflight(
                f"{intent} a licensing file", [current], check=lambda: found)
            if preflight.blocked:
                QMessageBox.warning(self, APP_NAME,
                                    preflight.blocked_message() + "\n\nNothing was renamed.")
                self.end_toggle(request)
                return
            if preflight.check_failed:
                # An earlier answer is not reused: this check failed, so ask again.
                answer = QMessageBox.question(
                    self, APP_NAME,
                    "Just before renaming, the check for a running copy of Football Manager "
                    f"could not be made. Rename {current.name} only if the game is closed."
                    "\n\nHave you closed Football Manager?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes or not self.current(request):
                    self.end_toggle(request)
                    return
            try:
                result = toggle_licence(self.version, row["rel"], BACKUP_ROOT, intent)
            except (OSError, ValueError) as exc:
                self.end_toggle(request)
                self.refresh()              # show the folder as it is now
                QMessageBox.critical(self, APP_NAME, f"Could not change the file:\n{exc}")
                return
            self.end_toggle(request)
            self.refresh()
            parent = self.parent()
            if parent is not None:
                parent.statusBar().showMessage(
                    f"Licensing file {result}: {row['name']}", 8000)

    # ---------------- main window ----------------
    class ReplaceDialog(QDialog):
        """Preview a section-scoped regular-expression replace, then apply it."""

        def __init__(self, parent, docs):
            super().__init__(parent)
            self.setWindowTitle("Replace")
            self.resize(860, 560)
            self.docs = docs
            self.edits: list[BulkEdit] = []
            self.applied = 0
            lay = QVBoxLayout(self)
            form = QHBoxLayout()
            form.addWidget(QLabel("File section"))
            self.section_box = QComboBox()
            self.section_box.addItem("All sections", "")
            seen = set()
            for doc in docs:
                for entry in doc.names():
                    if entry.section and entry.section not in seen:
                        seen.add(entry.section)
                        self.section_box.addItem(entry.section, entry.section)
            form.addWidget(self.section_box, 1)
            self.ignore_case = QCheckBox("Ignore capitals")
            form.addWidget(self.ignore_case)
            lay.addLayout(form)
            self.pattern = QLineEdit()
            self.pattern.setPlaceholderText("Find (regular expression)")
            self.replacement = QLineEdit()
            self.replacement.setPlaceholderText("Replacement. \\1 keeps a bracketed part.")
            lay.addWidget(self.pattern)
            lay.addWidget(self.replacement)
            row = QHBoxLayout()
            preview = QPushButton("Preview")
            preview.clicked.connect(self.preview)
            row.addWidget(preview)
            self.summary = QLabel("Preview before anything changes.")
            self.summary.setWordWrap(True)
            row.addWidget(self.summary, 1)
            lay.addLayout(row)
            self.table = QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(
                ["File section", "Type", "ID", "Before", "After"])
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table, 1)
            box = QDialogButtonBox()
            self.apply_btn = box.addButton("Apply preview", QDialogButtonBox.AcceptRole)
            box.addButton(QDialogButtonBox.Cancel)
            self.apply_btn.setEnabled(False)
            box.accepted.connect(self.apply)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.pattern.textChanged.connect(self._stale)
            self.replacement.textChanged.connect(self._stale)
            self.section_box.currentIndexChanged.connect(lambda _index: self._stale())
            self.ignore_case.toggled.connect(lambda _state: self._stale())

        def _stale(self, *_args):
            self.edits = []
            self.apply_btn.setEnabled(False)

        def preview(self):
            edits, skipped, error = preview_replace(
                self.docs,
                self.pattern.text(),
                self.replacement.text(),
                self.section_box.currentData() or "",
                self.ignore_case.isChecked(),
            )
            self.table.setRowCount(0)
            if error:
                self.edits = []
                self.apply_btn.setEnabled(False)
                self.summary.setText(error)
                return
            self.edits = edits
            self.table.setRowCount(len(edits))
            for row, edit in enumerate(edits):
                values = [
                    edit.entry.section,
                    friendly(edit.entry.cmd),
                    edit.entry.id,
                    edit.before,
                    edit.after,
                ]
                for column, value in enumerate(values):
                    self.table.setItem(row, column, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            text = f"{len(edits)} name(s) would change."
            if skipped:
                text += f" {skipped} result(s) were not legal names and were left out."
            if not edits:
                text = "Nothing would change."
                if skipped:
                    text += f" {skipped} result(s) were not legal names and were left out."
            self.summary.setText(text)
            self.apply_btn.setEnabled(bool(edits))

        def apply(self):
            if not self.edits:
                return
            self.applied = apply_bulk(self.edits, self.docs, "replace")
            self.accept()

    class PackDialog(QDialog):
        """Tick proposed rows, then apply them to the open files.

        Name packs and spelling profiles both use it. ``new_label`` names the
        proposed-name column, ``base_label`` adds a column for Proposal.base,
        and ``apply_func`` replaces apply_proposals.
        """

        def __init__(self, parent, changes, missing, summary: str,
                     title: str = "Import name pack", new_label: str = "Your older name",
                     base_label: str = "", apply_func=None):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.resize(980, 620)
            self.changes = changes
            self.missing = missing
            self.apply_func = apply_func or apply_proposals
            self.result_counts = None
            lay = QVBoxLayout(self)
            self.summary = QLabel(summary)
            self.summary.setWordWrap(True)
            lay.addWidget(self.summary)
            self.tabs = QTabWidget()
            extra = [base_label] if base_label else []
            self.change_model = ProposalModel(
                ["Use", "File section", "Type", "ID", "Current name", new_label,
                 *extra, "Note", "Language"])
            self.missing_model = ProposalModel(
                ["Use", "File section", "Type", "ID", new_label, *extra, "Note", "Language"])
            key = lambda proposal: (fold(proposal.section), proposal.cmd, proposal.new)
            self.change_model.set_items(sorted(changes, key=key))
            self.missing_model.set_items(sorted(missing, key=key))
            for model, title in (
                (self.change_model, f"Different names ({len(changes)})"),
                (self.missing_model, f"Not in current files ({len(missing)})"),
            ):
                view = QTableView()
                view.setModel(model)
                view.setItemDelegateForColumn(0, TickDelegate(view))   # the Use tick
                view.setSelectionBehavior(QTableView.SelectRows)
                view.setAlternatingRowColors(True)
                view.verticalHeader().setVisible(False)
                view.horizontalHeader().setStretchLastSection(True)
                # Fit names and headers, measuring a sample so a large pack stays quick.
                view.horizontalHeader().setResizeContentsPrecision(200)
                view.resizeColumnsToContents()
                self.tabs.addTab(view, title)
            lay.addWidget(self.tabs, 1)
            box = QDialogButtonBox()
            apply_btn = box.addButton("Apply ticked", QDialogButtonBox.AcceptRole)
            box.addButton(QDialogButtonBox.Cancel)
            apply_btn.setEnabled(bool(changes or missing))
            box.accepted.connect(self.apply)
            box.rejected.connect(self.reject)
            lay.addWidget(box)

        def apply(self):
            self.result_counts = self.apply_func(self.changes, self.missing, self.parent().docs)
            self.accept()

    class ProfileDialog(QDialog):
        """Name a spelling profile and give it a note; or, with ``note=None``, name a
        collection or a saved search, which have no note.

        ``check`` returns why a name cannot be used, or "". The problem is
        shown under the fields and the dialog stays open, so the text the
        user typed is never thrown away.
        """

        def __init__(self, parent, title: str, check, name: str = "", note: str | None = ""):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.check = check
            lay = QVBoxLayout(self)
            form = QFormLayout()
            self.name_edit = QLineEdit(name)
            self.name_edit.setMaxLength(80)
            self.note_edit = QLineEdit(note or "")
            self.note_edit.setPlaceholderText("Optional, for example: traditional English names")
            form.addRow("Name", self.name_edit)
            if note is not None:
                form.addRow("Note", self.note_edit)
            lay.addLayout(form)
            self.problem = QLabel("")
            self.problem.setObjectName("warning")
            self.problem.setWordWrap(True)
            lay.addWidget(self.problem)
            box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            box.accepted.connect(self.try_accept)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.resize(480, self.sizeHint().height())

        def try_accept(self) -> None:
            problem = self.check(self.name_edit.text())
            if problem:
                self.problem.setText(problem)
                self.name_edit.setFocus()
                return
            self.accept()

        def values(self) -> tuple[str, str]:
            return self.name_edit.text().strip(), self.note_edit.text().strip()

    class FavouritesDialog(QDialog):
        """File > Favourite folders: up to three folders the File menu lists (Session 19).

        Picking one in the menu opens the normal Windows file picker there;
        the folders are only ever read from. ``start`` gives the folder the
        Add folder picker opens in. A fourth folder is refused with the
        reason under the list, and the folders already chosen stay.
        """

        def __init__(self, parent, folders: list[str], start):
            super().__init__(parent)
            self.setWindowTitle("Favourite folders")
            self.start = start
            lay = QVBoxLayout(self)
            note = QLabel(
                "Keep up to three folders here. The File menu lists them, with the name files "
                "folder of the selected database, which does not count towards the three. "
                "Picking one opens the Windows file picker in that folder. Opening files never "
                "writes to them.")
            note.setWordWrap(True)
            lay.addWidget(note)
            self.folder_list = QListWidget()
            lay.addWidget(self.folder_list, 1)
            row = QHBoxLayout()
            self.add_btn = QPushButton("Add folder...")
            self.add_btn.clicked.connect(lambda _checked=False: self.add_folder())
            self.remove_btn = QPushButton("Remove")
            self.remove_btn.clicked.connect(lambda _checked=False: self.remove_selected())
            row.addWidget(self.add_btn)
            row.addWidget(self.remove_btn)
            row.addStretch(1)
            lay.addLayout(row)
            self.problem = QLabel("")
            self.problem.setObjectName("warning")
            self.problem.setWordWrap(True)
            lay.addWidget(self.problem)
            box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            box.accepted.connect(self.accept)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.fill(folders)
            self.resize(560, 300)

        def fill(self, folders: list[str]) -> None:
            self.folder_list.clear()
            self.folder_list.addItems(folders)
            self.remove_btn.setEnabled(bool(folders))

        def folders(self) -> list[str]:
            return [self.folder_list.item(row).text() for row in range(self.folder_list.count())]

        def add_folder(self) -> None:
            """Choose a folder in the Windows folder picker and add it, unless three are kept."""
            folders = self.folders()
            chosen = ""                         # with three kept, add_favourite refuses
            if len(folders) < MAX_FAVOURITES:
                chosen = QFileDialog.getExistingDirectory(
                    self, "Add a favourite folder", self.start())
                if not chosen:
                    return
            folders, problem = add_favourite(folders, chosen)
            self.problem.setText(problem)
            if not problem:
                self.fill(folders)

        def remove_selected(self) -> None:
            row = self.folder_list.currentRow()
            if row >= 0:
                folders = self.folders()
                del folders[row]
                self.fill(folders)
                self.problem.setText("")

    class AddNameDialog(QDialog):
        """Edit > Add name: name lines for an ID the game already uses (Session 19, note 08).

        It does not create a club and does not look IDs up; the ID is typed
        by the person. The name fields follow the family chosen (a club has
        a long name, a short name, and a 3-letter code). ``check`` returns
        why the fields cannot be used, or ""; the problem is shown under the
        fields and the dialog stays open, so nothing typed is lost.
        """

        def __init__(self, parent, check, family: str = "club"):
            super().__init__(parent)
            self.setWindowTitle("Add name")
            self.check = check
            lay = QVBoxLayout(self)
            note = QLabel(
                "This adds a name line for an ID the game already uses. It does not create a "
                "club, and the editor does not look IDs up: a wrong ID renames another record, "
                "or nothing at all. Use it only when the open files have no line for the ID. "
                "The lines go at the end of the file, under #Imported by FM Name Editor, and "
                "nothing is written until you Save or Deploy.")
            note.setWordWrap(True)
            lay.addWidget(note)
            self.form = QFormLayout()
            self.family_box = QComboBox()
            for key, kind in ENTITY_KINDS.items():
                self.family_box.addItem(kind, key)
            self.id_edit = QLineEdit()
            self.id_edit.setMaxLength(12)
            self.id_edit.setValidator(
                QRegularExpressionValidator(QRegularExpression("[0-9]*"), self.id_edit))
            self.id_edit.setPlaceholderText("Digits only, such as 740")
            self.form.addRow("Family", self.family_box)
            self.form.addRow("ID", self.id_edit)
            self.name_edits: list[QLineEdit] = []
            for _row in range(max(len(fields) for fields in FAMILY_FIELDS.values())):
                edit = QLineEdit()
                edit.setMaxLength(200)
                self.name_edits.append(edit)
                self.form.addRow("Name", edit)
            self.lang_edit = QLineEdit()
            self.lang_edit.setMaxLength(40)
            self.lang_edit.setPlaceholderText("Blank means English")
            self.form.addRow("Language", self.lang_edit)
            lay.addLayout(self.form)
            self.problem = QLabel("")
            self.problem.setObjectName("warning")
            self.problem.setWordWrap(True)
            lay.addWidget(self.problem)
            box = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.add_btn = box.addButton("Add", QDialogButtonBox.AcceptRole)
            box.accepted.connect(self.try_accept)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.family_box.currentIndexChanged.connect(lambda _index: self.show_fields())
            self.family_box.setCurrentIndex(max(0, self.family_box.findData(family)))
            self.show_fields()
            self.resize(520, self.sizeHint().height())

        def family(self) -> str:
            return self.family_box.currentData() or "club"

        def show_fields(self) -> None:
            """Label the name fields for the family chosen; hide the ones it does not have."""
            fields = FAMILY_FIELDS[self.family()]
            for number, edit in enumerate(self.name_edits):
                shown = number < len(fields)
                self.form.setRowVisible(edit, shown)
                if shown:
                    self.form.labelForField(edit).setText(fields[number][1])
                    edit.setPlaceholderText("Required" if number == 0 else "Optional")

        def values(self) -> tuple[str, str, dict, str]:
            """(family, ID, {field key: text}, language), as add_name_problem takes them."""
            fields = FAMILY_FIELDS[self.family()]
            names = {slot: edit.text().strip()
                     for (slot, _label, _cmd), edit in zip(fields, self.name_edits)}
            return (self.family(), self.id_edit.text().strip(), names,
                    self.lang_edit.text().strip())

        def try_accept(self) -> None:
            problem = self.check(*self.values())
            if problem:
                self.problem.setText(problem)
                return
            self.accept()

    class BackupDialog(QDialog):
        """List backup folders, diff a name file, and restore it into memory."""

        def __init__(self, parent, docs):
            super().__init__(parent)
            self.setWindowTitle("Backups")
            self.resize(980, 640)
            self.docs = docs
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(
                "Restore replaces the open file in memory only. "
                "Save or Deploy writes it. Nothing in the backup folder is deleted."))
            lists = QHBoxLayout()
            self.archive_list = QListWidget()
            self.file_list = QListWidget()
            lists.addWidget(self.archive_list, 1)
            lists.addWidget(self.file_list, 1)
            lay.addLayout(lists)
            self.origin = QLabel("")
            self.origin.setObjectName("muted")
            self.origin.setWordWrap(True)
            self.origin.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(self.origin)
            self.summary = QLabel("")
            self.summary.setWordWrap(True)
            lay.addWidget(self.summary)
            self.table = QTableWidget(0, 7)
            self.table.setHorizontalHeaderLabels(
                ["Restore", "Type", "ID", "Language", "Open file", "Backup", "Note"])
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table, 1)
            box = QDialogButtonBox(QDialogButtonBox.Close)
            self.close_btn = box.button(QDialogButtonBox.Close)
            self.restore_btn = QPushButton("Restore into open file")
            self.restore_btn.setEnabled(False)
            box.addButton(self.restore_btn, QDialogButtonBox.ActionRole)
            self.restore_btn.clicked.connect(self.restore)
            self.restore_selected_btn = QPushButton("Restore selected names")
            self.restore_selected_btn.setEnabled(False)
            self.restore_selected_btn.setToolTip(
                "Restore only the ticked names from the backup into the open file. "
                "Each restored name is marked as a pending restore until Save or Deploy.")
            box.addButton(self.restore_selected_btn, QDialogButtonBox.ActionRole)
            self.restore_selected_btn.clicked.connect(self.restore_selected_names)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.archive_list.currentRowChanged.connect(self.show_archive)
            self.file_list.currentRowChanged.connect(lambda _row: self.show_diff())
            self.archives = list_archives(BACKUP_ROOT)
            self.manifests: dict = {}
            if not self.archives:
                self.summary.setText("No backups yet. Save or Deploy a game file to create one.")
            for folder in self.archives:
                try:
                    found, problem = read_manifest(folder), ""
                except ValueError as exc:
                    found, problem = None, str(exc)
                self.manifests[folder] = (found, problem)
                item = QListWidgetItem(self.archive_label(folder, found, problem))
                if found is not None:
                    result = found.get("result", "pending")
                    item.setToolTip(f"{found.get('operation', 'Backup')}: "
                                    f"{ARCHIVE_RESULTS.get(result, result)}")
                self.archive_list.addItem(item)
            if self.archives:
                self.archive_list.setCurrentRow(0)

        @staticmethod
        def archive_label(folder: Path, manifest, problem: str) -> str:
            """Folder name, operation, and file count. The outcome in a word or two."""
            if problem:
                return f"{folder.name}    (manifest unreadable)"
            if manifest is None:
                return folder.name
            label = (f"{folder.name}    {manifest.get('operation', 'Backup')}, "
                     f"{len(manifest['files'])} file(s)")
            result = manifest.get("result", "pending")
            if result == "pending":
                label += "    (outcome not recorded)"
            elif result != "complete":
                label += f"    ({result})"
            return label

        def manifest_for(self, path: Path):
            return self.manifests.get(path.parent, (None, ""))

        def describe_origin(self, path: Path) -> str:
            manifest, problem = self.manifest_for(path)
            if problem:
                return f"{problem} Files in this folder are matched to open files by name."
            if manifest is None:
                return ("This backup was made before version 2.2 and has no manifest, "
                        "so it is matched to an open file by name.")
            when = str(manifest.get("timestamp", "")).replace("T", " ")
            text = f"{manifest.get('operation', 'Backup')} on {when}"
            if manifest.get("database"):
                text += f", database {manifest['database']}"
            result = manifest.get("result", "pending")
            text += f": {ARCHIVE_RESULTS.get(result, result)}."
            entry = manifest_entry(manifest, path.name)
            if entry is None:
                return text + " The manifest does not list this file."
            text += f" This copy came from {entry['original']}."
            outcome = entry.get("outcome")
            if result != "complete" and outcome:
                text += f" Afterwards that file was {FILE_OUTCOMES.get(outcome, outcome)}."
            return text

        def show_archive(self, row: int):
            self.file_list.clear()
            self.table.setRowCount(0)
            self.restore_btn.setEnabled(False)
            self.origin.setText("")
            if row < 0 or row >= len(self.archives):
                return
            folder = self.archives[row]
            manifest, _problem = self.manifests.get(folder, (None, ""))
            files = sorted(
                (path for path in folder.iterdir()
                 if path.is_file() and path.name.casefold() != MANIFEST_NAME),
                key=lambda path: path.name.casefold())
            for path in files:
                item = QListWidgetItem(f"{path.name}  ({path.stat().st_size:,} bytes)")
                item.setData(Qt.UserRole, str(path))
                entry = manifest_entry(manifest, path.name)
                if entry is not None:
                    item.setToolTip(f"Copied from {entry['original']}")
                self.file_list.addItem(item)
            if files:
                self.file_list.setCurrentRow(0)
            else:
                self.summary.setText("That backup folder is empty.")

        def selected_file(self) -> Path | None:
            item = self.file_list.currentItem()
            if item is None:
                return None
            return Path(item.data(Qt.UserRole))

        def matching_doc(self, path: Path):
            """The open document for a backed-up file, and how it was matched."""
            manifest, _problem = self.manifest_for(path)
            return match_open_document(path, self.docs, manifest)

        def show_diff(self):
            self.table.setRowCount(0)
            self.restore_btn.setEnabled(False)
            self.restore_selected_btn.setEnabled(False)
            path = self.selected_file()
            if path is None:
                self.origin.setText("")
                return
            self.origin.setText(self.describe_origin(path))
            if path.suffix.casefold() != ".lnc":
                self.summary.setText(
                    "That backup is not a name file. It is listed so you can see it "
                    "was archived. Restore it from Licensing, not from here.")
                return
            doc, how = self.matching_doc(path)
            if doc is None:
                entry = manifest_entry(self.manifest_for(path)[0], path.name)
                if entry is not None:
                    wanted = entry["original"]
                    self.summary.setText(
                        f"Open {wanted} before comparing or restoring this copy.")
                else:
                    self.summary.setText(
                        f"Open one file named {path.name} before comparing or restoring it.")
                return
            try:
                rows, identical = compare_with_backup(doc, path)
            except (OSError, UnicodeError) as exc:
                self.summary.setText(f"Could not read the backup:\n{exc}")
                return
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                # Column 0: checkbox for per-name restore
                checkbox = QTableWidgetItem()
                checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                checkbox.setCheckState(Qt.Unchecked)
                checkbox.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(index, 0, checkbox)
                # Columns 1-6: diff data
                values = [
                    friendly(row["command"]),
                    row["id"],
                    row["language"],
                    row["working"],
                    row["archived"],
                    row["note"],
                ]
                for column, value in enumerate(values):
                    self.table.setItem(index, column + 1, QTableWidgetItem(value))
                # The Type column shows the friendly label; the raw command rides along.
                self.table.item(index, 1).setData(Qt.UserRole, row["command"])
            self.table.resizeColumnsToContents()
            text = describe_backup_match(len(rows), identical)
            if doc.dirty:
                text += " The open file has unsaved changes, and the comparison includes them."
            if how == "name" and manifest_entry(self.manifest_for(path)[0], path.name):
                text += (f" It is compared with {doc.path}, which has the same name but is "
                         "not the file this copy came from.")
            self.summary.setText(text)
            self.restore_btn.setEnabled(True)
            self.restore_selected_btn.setEnabled(True)

        def restore(self):
            path = self.selected_file()
            doc = None if path is None else self.matching_doc(path)[0]
            if path is None or doc is None:
                return
            answer = QMessageBox.question(
                self, APP_NAME,
                f"Replace the open {doc.path} with the copy {path.name} from "
                f"{path.parent.name}?\n\nNothing is written until you Save or Deploy.",
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            jobs = getattr(self.parent(), "jobs", None)
            if jobs is None:
                try:
                    prepared = prepare_restore(doc, path)
                except (OSError, UnicodeError) as exc:
                    self.restore_failed(exc)
                    return
                self.finish_restore(doc, path, prepared)
                return
            # Reading and parsing the copy is the slow part: a worker does it, and
            # the dialog's buttons wait. The lines are taken on the GUI thread.
            for button in (self.restore_btn, self.close_btn):
                button.setEnabled(False)
            self.summary.setText(f"Reading {path.name}...")
            jobs.start(f"Reading {path.name} from {path.parent.name}...",
                       lambda: prepare_restore(doc, path),
                       lambda prepared: self.finish_restore(doc, path, prepared),
                       self.restore_failed)

        def restore_selected_names(self):
            """Restore only the ticked names from the backup into the open file.

            Each restored name is marked as a pending restore until Save or Deploy.
            This is one Operation/undo step. The original backup is never modified.
            A stale diff (open file changed since diff was shown) is refused.
            """
            path = self.selected_file()
            doc = None if path is None else self.matching_doc(path)[0]
            if path is None or doc is None:
                return

            # Collect ticked rows
            ticked_rows = []
            for row in range(self.table.rowCount()):
                checkbox = self.table.item(row, 0)
                if checkbox and checkbox.checkState() == Qt.Checked:
                    # Get the diff data for this row
                    cmd = self.table.item(row, 1).data(Qt.UserRole)
                    id_ = self.table.item(row, 2).text()
                    lang = self.table.item(row, 3).text()
                    working = self.table.item(row, 4).text()
                    archived = self.table.item(row, 5).text()
                    note = self.table.item(row, 6).text()
                    ticked_rows.append({
                        "command": cmd,
                        "id": id_,
                        "language": lang,
                        "working": working,
                        "archived": archived,
                        "note": note,
                    })

            if not ticked_rows:
                QMessageBox.information(self, APP_NAME, "No names selected for restore.")
                return

            # Check for stale diff: compare the current open file with the backup again
            # If the diff has changed, refuse the restore
            try:
                current_rows, _ = compare_with_backup(doc, path)
            except (OSError, UnicodeError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not re-read the backup:\n{exc}")
                return

            # Build a set of keys from the current diff
            current_keys = set()
            for r in current_rows:
                key = (r["command"], r["id"], r["language"])
                current_keys.add(key)

            # Build a set of keys from the ticked rows
            ticked_keys = set()
            for r in ticked_rows:
                key = (r["command"], r["id"], r["language"])
                ticked_keys.add(key)

            # If any ticked key is not in the current diff, the diff is stale
            if not ticked_keys.issubset(current_keys):
                QMessageBox.warning(
                    self, APP_NAME,
                    "The comparison has changed since it was shown. "
                    "Please refresh the diff before restoring.")
                self.show_diff()
                return

            # Confirm the restore
            count = len(ticked_rows)
            answer = QMessageBox.question(
                self, APP_NAME,
                f"Restore {count} selected name(s) from {path.name} into the open file?\n\n"
                "Each restored name is marked as a pending restore. "
                "Nothing is written until you Save or Deploy.",
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return

            # Perform the restore as one Operation
            operation = Operation(f"restore {count} name(s) from {path.parent.name}")
            with operation:
                self._apply_selected_restore(doc, path, ticked_rows)

            parent = self.parent()
            if parent is not None:
                parent.push_operation(operation)
                parent.reload_views()
            self.docs = parent.docs if parent is not None else self.docs
            self.show_diff()
            self.summary.setText(
                f"Restored {count} name(s) from {path.name}. Save or Deploy to write them.")

        def _apply_selected_restore(self, doc: LncDoc, backup_path: Path, ticked_rows: list[dict]) -> None:
            """Apply the selected restore by updating the open document with archived values.

            This marks the changed lines with reason "restore" and sets restore_pending.
            """
            # Read the backup file to get the archived entries
            backup_doc = LncDoc(backup_path)

            # Build a lookup: (command, id, language) -> list of archived entries
            archived_lookup: dict[tuple, list[Entry]] = {}
            for entry in backup_doc.editable():
                key = (entry.cmd, entry.id, entry.lang.casefold())
                archived_lookup.setdefault(key, []).append(entry)

            # For each ticked row, find the matching entry in the open document and update it
            for row in ticked_rows:
                cmd = row["command"]
                id_ = row["id"]
                lang = row["language"]
                archived_name = row["archived"]

                # Find the matching entry in the open document
                key = (cmd, id_, lang.casefold())
                archived_entries = archived_lookup.get(key, [])
                if not archived_entries:
                    continue

                # Find the corresponding entry in the open document
                for entry in doc.editable():
                    if entry.cmd == cmd and entry.id == id_ and entry.lang.casefold() == lang.casefold():
                        # Update the entry with the archived name
                        entry.set_name(archived_name, "restore")
                        break

            # Mark the document as having pending restores
            doc.restore_pending = True
            doc.restored_from = backup_path
            doc.whole_excluded = False
            doc.touch()

        def finish_restore(self, doc, path: Path, prepared) -> None:
            self.close_btn.setEnabled(True)
            operation = Operation(f"restore {doc.path.name} from {path.parent.name}")
            with operation:
                doc.apply_working(prepared)
            parent = self.parent()
            if parent is not None:
                parent.push_operation(operation)
                parent.reload_views()
            self.docs = parent.docs if parent is not None else self.docs
            self.show_diff()
            self.summary.setText(
                f"Restored {path.name} into the open file. Save or Deploy to write it.")

        def restore_failed(self, exc: Exception) -> None:
            self.close_btn.setEnabled(True)
            self.restore_btn.setEnabled(True)
            if not isinstance(exc, (OSError, UnicodeError)):
                raise exc
            QMessageBox.critical(self, APP_NAME, f"Could not restore:\n{exc}")
            self.summary.setText("Nothing was restored. The open file is unchanged.")

    class OverrideDialog(QDialog):
        """Session 13: the cross-file conflict inspector.

        Lists every ``.lnc`` line in the chosen database folder that matches
        the selected entity's family and ID, grouped by (command, language),
        with the state saying whether a group's values agree. The tool shows
        the overlap and does not claim to know the game's load order
        (note 05, C). Reads run through the window's ``Jobs`` so the scan
        does not freeze the GUI.
        """

        COLUMNS = ("File", "Line", "Type", "Language", "Name", "State")

        def __init__(self, parent, entity, version_dir):
            super().__init__(parent)
            self.entity = entity
            self.version_dir = Path(version_dir)
            self.setWindowTitle(
                f"Overrides across files: {ENTITY_KINDS[entity.family]} ID {entity.id}")
            self.resize(880, 520)
            lay = QVBoxLayout(self)
            self.summary = QLabel(
                f"Scanning {self.version_dir}\\lnc for every line that matches this entity...")
            self.summary.setWordWrap(True)
            lay.addWidget(self.summary)
            self.table = QTableWidget(0, len(self.COLUMNS))
            self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.setSelectionMode(QTableWidget.NoSelection)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table, 1)
            self.note = QLabel(
                "The editor shows every matching line and whether the values agree. "
                "It does not claim to know the game's load order; a single file may "
                "override another at run-time in ways this list cannot tell.")
            self.note.setObjectName("muted")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            box = QDialogButtonBox(QDialogButtonBox.Close)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.jobs = parent.jobs
            self._scan()

        def _scan(self) -> None:
            family = self.entity.family
            id_ = self.entity.id
            version = self.version_dir

            def work():
                return find_overrides(family, id_, version)

            self.jobs.start(
                f"Scanning {version.name} for overrides...", work, self._filled, self._failed)

        def _filled(self, overrides: list) -> None:
            self.table.setRowCount(len(overrides))
            competing = 0
            for row, override in enumerate(overrides):
                state_text = OVERRIDE_STATES.get(override.state, override.state)
                if override.state == "competing":
                    competing += 1
                try:
                    rel = override.file.relative_to(self.version_dir)
                    file_text = str(rel)
                except ValueError:
                    file_text = str(override.file)
                values = [
                    file_text,
                    str(override.line),
                    friendly(override.command),
                    override.language or "",
                    override.name,
                    state_text,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if override.state == "competing" and column == len(values) - 1:
                        item.setForeground(COLOURS["warning"])    # competing: worded too
                    self.table.setItem(row, column, item)
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setStretchLastSection(True)
            if not overrides:
                self.summary.setText(
                    f"No matching lines found under {self.version_dir}\\lnc.")
            elif competing:
                self.summary.setText(
                    f"{len(overrides):,} line(s) found; {competing:,} disagree with the others. "
                    f"Hover a value to compare.")
            else:
                self.summary.setText(
                    f"{len(overrides):,} line(s) found; all values agree.")

        def _failed(self, exc: Exception) -> None:
            self.summary.setText(f"Could not scan the database folder:\n{exc}")

    # ---------------- changes and the review before a write ----------------
    def show_lines(parent, title: str, intro: str, lines: list[str],
                   empty: str = "None.") -> None:
        """A read-only list of lines in a dialog of its own."""
        dlg = QDialog(parent)
        dlg.setWindowTitle(title)
        dlg.resize(900, 400)
        lay = QVBoxLayout(dlg)
        intro_label = QLabel(intro)
        intro_label.setWordWrap(True)
        lay.addWidget(intro_label)
        box = QPlainTextEdit("\n".join(lines) or empty)
        box.setReadOnly(True)
        box.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(box)
        dlg.exec()

    def set_level(label: QLabel, text: str, level: str) -> None:
        """Show a check's sentence in the colour of its level."""
        label.setText(text)
        if label.objectName() != level:
            label.setObjectName(level)
            label.style().unpolish(label)
            label.style().polish(label)

    class ChangeModel(QAbstractTableModel):
        """One row per difference from disk, with an include tick.

        The ticks live on the lines and documents (see ChangeRow), so the
        Changes tab and the review dialog always show the same choice.
        ``destinations`` maps a document to where a write would put it; by
        default that is the file it was read from.
        """

        COLS = ["Include", "State", "Reason", "Type", "ID", "Language", "On disk",
                "To write", "File", "Line", "Destination"]
        INCLUDE, STATE, REASON, TYPE, ID, LANGUAGE, ON_DISK, PROPOSED, FILE, LINE, DEST = \
            range(11)
        ticks_changed = Signal()

        def __init__(self, destinations=None):
            super().__init__()
            self.rows: list[ChangeRow] = []
            self.destinations = dict(destinations or {})
            self.muted = COLOURS["muted"]

        def set_rows(self, rows) -> None:
            self.beginResetModel()
            self.rows = list(rows)
            self.endResetModel()

        def destination(self, row: ChangeRow) -> Path:
            return self.destinations.get(row.doc, row.doc.path)

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.COLS)

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if orientation != Qt.Horizontal:
                return None
            if role == Qt.DisplayRole:
                return self.COLS[section]
            if role == Qt.ToolTipRole and section == self.INCLUDE:
                return ("Ticked changes are written by the next Save or Deploy. Unticked "
                        "changes are left out and stay pending in memory.")
            if role == Qt.ToolTipRole and section == self.LINE:
                return "The line in memory. For a removed row, the line it has on disk."
            return None

        def flags(self, index):
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if index.isValid() and index.column() == self.INCLUDE:
                flags |= Qt.ItemIsUserCheckable
            return flags

        def data(self, index, role=Qt.DisplayRole):
            if not index.isValid():
                return None
            row = self.rows[index.row()]
            column = index.column()
            if role == Qt.CheckStateRole and column == self.INCLUDE:
                return Qt.Checked if row.included else Qt.Unchecked
            if role == BADGE_ROLE:
                return badge_family(row.command) if column == self.TYPE and row.command else ""
            if role in (Qt.DisplayRole, Qt.EditRole):
                if column == self.INCLUDE:
                    return "" if role == Qt.DisplayRole else int(row.included)
                if column == self.STATE:
                    return CHANGE_STATES[row.state]
                if column == self.REASON:
                    return row.reason
                if column == self.TYPE:
                    return friendly(row.command) if row.command else ""
                if column == self.ID:
                    if role == Qt.EditRole and row.id.isdigit():
                        return int(row.id)
                    return row.id
                if column == self.LANGUAGE:
                    return row.language
                if column == self.ON_DISK:
                    return row.on_disk
                if column == self.PROPOSED:
                    return row.proposed
                if column == self.FILE:
                    return row.doc.path.name
                if column == self.LINE:
                    if role == Qt.EditRole:
                        return row.line or 0
                    return str(row.line) if row.line else ""
                if column == self.DEST:
                    return str(self.destination(row))
            if role == Qt.ToolTipRole:
                if column in (self.INCLUDE, self.STATE, self.REASON) and row.detail:
                    return row.detail
                if column == self.DEST:
                    return str(self.destination(row))
            if role == Qt.ForegroundRole:
                if not row.included:
                    return self.muted       # a left-out row reads quieter as well as unticked
                if column == self.ON_DISK and row.state == "added":
                    return self.muted
                if column == self.PROPOSED and row.state in ("removed", "other"):
                    return self.muted
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if role != Qt.CheckStateRole or index.column() != self.INCLUDE:
                return False
            self.rows[index.row()].set_included(Qt.CheckState(value) == Qt.Checked)
            self._ticks_moved()
            return True

        def set_included(self, rows, value: bool) -> None:
            for row in rows:
                row.set_included(value)
            self._ticks_moved()

        def _ticks_moved(self) -> None:
            # A restored file ticks as one, so every row may have moved.
            if self.rows:
                self.dataChanged.emit(self.index(0, self.INCLUDE),
                                      self.index(len(self.rows) - 1, self.INCLUDE))
            self.ticks_changed.emit()

    class ChangeProxy(QSortFilterProxyModel):
        """Filters the changes by the words typed, ignoring accents and capitals."""

        def __init__(self):
            super().__init__()
            self.words: list[str] = []
            self.setSortRole(Qt.EditRole)
            self.setDynamicSortFilter(False)
            self.setSortCaseSensitivity(Qt.CaseInsensitive)

        def set_filter(self, text: str) -> None:
            self.words = fold(text).split()
            self.invalidate()

        def filterAcceptsRow(self, source_row, parent):
            if not self.words:
                return True
            row = self.sourceModel().rows[source_row]
            hay = fold(" ".join([
                CHANGE_STATES[row.state], row.reason, friendly(row.command) if row.command else "",
                row.id, row.language, row.on_disk, row.proposed, row.doc.path.name]))
            return all(word in hay for word in self.words)

        def shown_rows(self) -> list[ChangeRow]:
            model = self.sourceModel()
            return [model.rows[self.mapToSource(self.index(number, 0)).row()]
                    for number in range(self.rowCount())]

    class MiddleElide(QStyledItemDelegate):
        """Shortens long text in the middle, so a path keeps its folder and its file name."""

        def initStyleOption(self, option, index):
            super().initStyleOption(option, index)
            option.textElideMode = Qt.ElideMiddle

    def change_table(proxy) -> QTableView:
        """A table for the changes: one row each, sortable, sized to its contents."""
        view = QTableView()
        view.setModel(proxy)
        view.setSortingEnabled(True)
        view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        view.setSelectionBehavior(QTableView.SelectRows)
        view.setAlternatingRowColors(True)
        view.setWordWrap(False)     # a path has no spaces; wrapping would cut it after "C:"
        view.verticalHeader().setVisible(False)
        view.verticalHeader().setDefaultSectionSize(24)
        view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        view.setItemDelegateForColumn(ChangeModel.DEST, MiddleElide(view))
        view.setItemDelegateForColumn(ChangeModel.INCLUDE, TickDelegate(view))
        view.setItemDelegateForColumn(ChangeModel.TYPE, BadgeDelegate(view))
        header = view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setResizeContentsPrecision(200)
        return view

    def fit_change_columns(view: QTableView, model) -> None:
        """Size a changes table from its rows' text (see fit_columns); the last column stretches."""
        rows = model.rows
        texts = {
            ChangeModel.STATE: {CHANGE_STATES[row.state] for row in rows},
            ChangeModel.REASON: {row.reason for row in rows},
            ChangeModel.TYPE: {friendly(row.command) for row in rows if row.command},
            ChangeModel.ID: {row.id for row in rows},
            ChangeModel.LANGUAGE: {row.language for row in rows},
            ChangeModel.ON_DISK: {row.on_disk for row in rows},
            ChangeModel.PROPOSED: {row.proposed for row in rows},
            ChangeModel.FILE: {row.doc.path.name for row in rows},
            ChangeModel.LINE: {str(row.line) for row in rows if row.line},
            ChangeModel.INCLUDE: set(),
        }
        if not view.isColumnHidden(ChangeModel.DEST):
            texts[ChangeModel.DEST] = {str(model.destination(row)) for row in rows}
        fit_columns(view, texts, {ChangeModel.ON_DISK: 320, ChangeModel.PROPOSED: 320,
                                  ChangeModel.DEST: 420}, {ChangeModel.TYPE: BADGE_SPACE})

    def describe_ticks(rows) -> str:
        """The line under the Changes tab's filter."""
        if not rows:
            return "No changes: the open files match their files on disk."
        ticked = sum(1 for row in rows if row.included)
        text = (f"{len(rows):,} change(s): {ticked:,} ticked for the next Save or Deploy, "
                f"{len(rows) - ticked:,} left out. Unticked changes are not written and stay "
                "pending in memory.")
        if any(row.doc.grouped for row in rows):
            text += " A restored file is written whole, so its rows tick and untick together."
        return text

    class ReviewDialog(QDialog):
        """Review the changes a Save or Deploy would write, then write them.

        Built from a WriteReview. The rows are the Changes tab's rows for
        the files in this write, with the same ticks: unticking one here
        unticks it there. Write looks for a running game once more first.
        When that check cannot be made, "I have closed Football Manager"
        must be ticked before Write is allowed.
        """

        def __init__(self, parent, review: WriteReview):
            super().__init__(parent)
            self.review = review
            self.jobs = getattr(parent, "jobs", None)   # the window's worker, for the check at Write
            self.cancelled = False
            self.setWindowTitle(review.title)
            screen = self.screen().availableGeometry() if self.screen() else None
            width, height = 1180, 740
            if screen is not None:
                width, height = min(width, screen.width() - 40), min(height, screen.height() - 40)
            self.resize(width, height)
            lay = QVBoxLayout(self)

            self.summary = QLabel("")
            self.summary.setObjectName("heading")
            self.summary.setWordWrap(True)
            lay.addWidget(self.summary)

            self.files_table = QTableWidget(len(review.files), 4)
            self.files_table.setHorizontalHeaderLabels(
                ["File", "Destination", "This write", "On disk now"])
            self.files_table.verticalHeader().setVisible(False)
            self.files_table.verticalHeader().setDefaultSectionSize(24)
            self.files_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.files_table.setSelectionMode(QTableWidget.NoSelection)
            self.files_table.setWordWrap(False)
            self.files_table.setItemDelegateForColumn(1, MiddleElide(self.files_table))
            self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            for number, item in enumerate(review.files):
                self.files_table.setItem(number, 0, QTableWidgetItem(item.doc.path.name))
                dest = QTableWidgetItem(str(item.dest))
                dest.setToolTip(str(item.dest))
                self.files_table.setItem(number, 1, dest)
            lay.addWidget(self.files_table)

            self.backup_label = QLabel("")
            self.backup_label.setWordWrap(True)
            self.backup_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(self.backup_label)

            grid = QGridLayout()
            grid.setColumnStretch(1, 1)
            self.game_label, self.disk_label, self.problem_label, self.repeat_label = (
                QLabel(""), QLabel(""), QLabel(""), QLabel(""))
            self.problem_btn = QPushButton("Show...")
            self.problem_btn.clicked.connect(self.show_problem_lines)
            self.repeat_btn = QPushButton("Show...")
            self.repeat_btn.clicked.connect(self.show_repeated_keys)
            for number, (caption, label, button) in enumerate((
                    ("Game", self.game_label, None),
                    ("Files on disk", self.disk_label, None),
                    ("Problem lines", self.problem_label, self.problem_btn),
                    ("Repeated keys", self.repeat_label, self.repeat_btn))):
                title = QLabel(caption)
                title.setObjectName("muted")
                label.setWordWrap(True)
                grid.addWidget(title, number, 0, Qt.AlignTop)
                grid.addWidget(label, number, 1)
                if button is not None:
                    grid.addWidget(button, number, 2, Qt.AlignTop)
            lay.addLayout(grid)
            self.closed_box = QCheckBox("I have closed Football Manager")
            self.closed_box.setVisible(False)
            lay.addWidget(self.closed_box)
            if review.left_alone:
                alone = QLabel(f"Not part of this {review.operation}, so left as they are: "
                               + ", ".join(review.left_alone) + ".")
                alone.setObjectName("muted")
                alone.setWordWrap(True)
                lay.addWidget(alone)

            row = QHBoxLayout()
            self.search = QLineEdit()
            self.search.setPlaceholderText("Filter these changes...")
            self.search.setClearButtonEnabled(True)
            row.addWidget(self.search, 1)
            for text, state in (("Tick all shown", True), ("Untick all shown", False)):
                button = QPushButton(text)
                button.clicked.connect(
                    lambda _=False, s=state: self.model.set_included(self.proxy.shown_rows(), s))
                row.addWidget(button)
            lay.addLayout(row)
            self.model = ChangeModel({item.doc: item.dest for item in review.files})
            self.model.set_rows(review.rows)
            self.proxy = ChangeProxy()
            self.proxy.setSourceModel(self.model)
            self.table = change_table(self.proxy)
            self.table.setColumnHidden(ChangeModel.DEST, True)   # the files table names it
            fit_change_columns(self.table, self.model)
            lay.addWidget(self.table, 1)
            self.search.textChanged.connect(self.proxy.set_filter)

            self.note = QLabel("")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            box = QDialogButtonBox()
            self.write_btn = box.addButton(review.operation, QDialogButtonBox.AcceptRole)
            box.addButton(QDialogButtonBox.Cancel)
            box.accepted.connect(self.try_write)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.model.ticks_changed.connect(self.update_state)
            self.closed_box.toggled.connect(lambda _state: self.update_state())
            self.update_state()

        def update_state(self) -> None:
            """Work the files out again from the ticks and show where things stand."""
            review = self.review
            review.refresh()
            self.summary.setText(review.summary())
            for number, item in enumerate(review.files):
                self.files_table.setItem(number, 2, QTableWidgetItem(item.write_state()))
                self.files_table.setItem(number, 3, QTableWidgetItem(item.disk_state()))
            self.files_table.resizeColumnToContents(0)
            self.files_table.resizeColumnToContents(2)
            self.files_table.resizeColumnToContents(3)
            frame = 2 * self.files_table.frameWidth()
            self.files_table.setFixedHeight(
                self.files_table.horizontalHeader().height() + frame
                + sum(self.files_table.rowHeight(n) for n in range(self.files_table.rowCount())))
            self.backup_label.setText(review.backup_text(BACKUP_ROOT))
            set_level(self.game_label, *review.game_check())
            set_level(self.disk_label, *review.disk_check())
            set_level(self.problem_label, *review.problem_check())
            set_level(self.repeat_label, *review.repeated_check())
            self.problem_btn.setVisible(bool(review.problem_lines()))
            self.repeat_btn.setVisible(bool(review.repeated_keys()))
            unknown = review.preflight.check_failed and any(
                item.game for item in review.to_write)
            self.closed_box.setVisible(unknown)
            problems = review.problems()
            notes = []
            if problems:
                notes.append(problems[0])
            else:
                if unknown and not self.closed_box.isChecked():
                    notes.append("Tick \"I have closed Football Manager\" to write.")
                notes.append(
                    "Unticked rows are left out of this write and stay pending in memory.")
            if any(item.game for item in review.to_write):
                notes.append(GAME_WRITE_NOTE)
            self.note.setText(" ".join(notes))
            self.write_btn.setEnabled(
                not problems and (not unknown or self.closed_box.isChecked()))

        def try_write(self) -> None:
            """Look for a running game once more, on a worker, then close the dialog to write.

            Without a game file in the write there is nothing to look for.
            """
            if not any(item.game for item in self.review.to_write):
                self.finish_write([])
                return
            if self.jobs is None:
                self.finish_write(football_manager_running())
                return
            self.write_btn.setEnabled(False)
            self.note.setText(GAME_CHECK)
            # A check that breaks is a check that could not be made: unknown, not closed.
            self.jobs.start(GAME_CHECK, football_manager_running, self.finish_write,
                            lambda _error: self.finish_write(None))

        def finish_write(self, found) -> None:
            """The check at Write is back: write, or say why not."""
            if self.cancelled:
                return
            self.review.recheck(lambda: found)
            self.update_state()
            if self.review.preflight.blocked:
                QMessageBox.warning(self, APP_NAME, self.review.preflight.blocked_message())
                return
            if self.write_btn.isEnabled():
                self.accept()

        def reject(self) -> None:
            self.cancelled = True           # a check still running then writes nothing
            super().reject()

        def show_problem_lines(self) -> None:
            show_lines(self, "Problem lines",
                       "These lines look malformed. They are written back exactly as they are.",
                       [f"{entry.doc.path.name}  line {entry.lineno}:  {entry.raw}"
                        for entry in self.review.problem_lines()])

        def show_repeated_keys(self) -> None:
            lines = []
            for rows in self.review.repeated_keys():
                first = rows[0]
                where = " | ".join(f"{row.name} ({row.doc.path.name} line {row.lineno})"
                                   for row in rows)
                lines.append(f"{friendly(first.cmd)} {first.id} {first.lang}: {where}")
            show_lines(self, "Repeated keys",
                       "These name lines share a command, ID, and language. The game's order "
                       "between them is not known.", lines)

    def sortable(view: QTableView, handler) -> None:
        """Let a table's headers sort its model in Python, not through the proxy.

        One click sorts A to Z, a second Z to A, a third goes back to the
        model's own order. ``handler(column, order)`` does the sorting.
        """
        header = view.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicatorClearable(True)
        header.sortIndicatorChanged.connect(handler)

    def relayout(model) -> None:
        """Tell the proxy and views that text changed in many rows that did not move."""
        model.layoutAboutToBeChanged.emit()
        model.layoutChanged.emit()

    def restyle(widget, name: str) -> None:
        """Give a widget another style-sheet object name, and repaint it in that style."""
        if widget.objectName() != name:
            widget.setObjectName(name)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    class CadenceDelegate(QStyledItemDelegate):
        """The entity grid's cell editor (Session 20): Tab and Enter move on.

        Tab keeps the cell and edits the next name column on the same row
        (Shift+Tab the one before); Enter keeps it and edits the same column
        on the next row shown. The cell is kept through the usual path
        (commitData, then the model's setData), so a changed cell is one Undo
        step and an unchanged one records nothing. Past the last name column
        or the last row, the editor just closes. ``where()`` names the cell
        being edited before it is kept; ``move(where, how)`` opens the next
        one once the event loop is free, after any reload the edit queued.
        """

        def __init__(self, view, where, move):
            super().__init__(view)
            self.where = where
            self.move = move

        def eventFilter(self, editor, event):
            if event.type() == QEvent.KeyPress:
                key = event.key()
                modifiers = event.modifiers() & ~Qt.KeypadModifier
                how = ""
                if key == Qt.Key_Tab and modifiers == Qt.NoModifier:
                    how = "next"
                elif key == Qt.Key_Backtab:
                    how = "previous"
                elif key in (Qt.Key_Return, Qt.Key_Enter) and modifiers == Qt.NoModifier:
                    how = "down"
                if how:
                    origin = self.where()
                    self.commitData.emit(editor)
                    self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)
                    if origin is not None:
                        QTimer.singleShot(0, lambda: self.move(origin, how))
                    return True
            return super().eventFilter(editor, event)

    class InspectorEdit(QLineEdit):
        """A field in the inspector. Esc puts back the name in memory.

        Session 20: Alt+Down or Shift+Enter asks for the next grid row, and
        Alt+Up for the one before (``step``); the window keeps the field first.
        """

        escaped = Signal()
        step = Signal(int)

        def keyPressEvent(self, event):
            key = event.key()
            modifiers = event.modifiers() & ~Qt.KeypadModifier
            if key == Qt.Key_Escape:
                self.escaped.emit()
                event.accept()
                return
            if modifiers == Qt.AltModifier and key in (Qt.Key_Down, Qt.Key_Up):
                event.accept()
                self.step.emit(1 if key == Qt.Key_Down else -1)
                return
            if modifiers == Qt.ShiftModifier and key in (Qt.Key_Return, Qt.Key_Enter):
                event.accept()
                self.step.emit(1)
                return
            super().keyPressEvent(event)

    class Jobs(QObject):
        """Slow work on a worker thread, with its answer handed back on the GUI thread.

        ``work`` must not touch a widget or a model: it reads files or runs a
        process and returns a value. ``done(result)``, or ``failed(error)``
        when it raised, runs on the GUI thread through a queued signal.
        ``busy(True, text)`` runs when the first job starts, and
        ``busy(False, "")`` when the last one ends, before its ``done`` or
        ``failed``, so whatever those open finds the window ready again. A
        write never runs here: it is short, and it settles the documents the
        views show. With JOBS_INLINE (the tests) a job runs at once on the
        calling thread, in the same order.
        """

        finished = Signal(int, object, object)

        def __init__(self, parent, busy):
            super().__init__(parent)
            self.busy = busy
            self.pending: dict[int, tuple] = {}
            self.serial = 0
            self.finished.connect(self._finish, type=Qt.QueuedConnection)

        def start(self, text: str, work, done, failed=None) -> int:
            self.serial += 1
            number = self.serial
            self.pending[number] = (done, failed)
            if len(self.pending) == 1:
                self.busy(True, text)
            if JOBS_INLINE:
                self._run(number, work, inline=True)
            else:
                threading.Thread(target=self._run, args=(number, work), daemon=True,
                                 name=f"{APP_NAME} job {number}").start()
            return number

        def _run(self, number: int, work, inline: bool = False) -> None:
            try:
                result, error = work(), None
            except Exception as exc:            # handed to failed() on the GUI thread
                result, error = None, exc
            if inline:
                self._finish(number, result, error)
            else:
                self.finished.emit(number, result, error)

        def _finish(self, number: int, result, error) -> None:
            done, failed = self.pending.pop(number)
            if not self.pending:
                self.busy(False, "")
            if error is None:
                done(result)
            elif failed is not None:
                failed(error)
            else:
                raise error

        def wait(self, timeout: float = 30.0) -> bool:
            """Run the event loop until no job is pending, or the time is up. True when idle."""
            deadline = time.monotonic() + timeout
            while self.pending and time.monotonic() < deadline:
                QApplication.processEvents(QEventLoop.AllEvents, 50)
                if self.pending:
                    time.sleep(0.005)
            return not self.pending

    class MainWindow(QMainWindow):
        CHANGES_TAB = 2

        def __init__(self):
            super().__init__()
            self.docs: list[LncDoc] = []
            self.all_entities: list[NameEntity] = []
            # Session 16: per-family whole-word token index, built on reload and
            # refreshed after any edit or undo. Right-click menus read it once.
            self.token_index = FamilyTokenIndex()
            # Session 17: targeted refresh. ``_entry_entity`` maps every open
            # Entry to its NameEntity, rebuilt in reload_views; ``_pending_token_refresh``
            # is the set of entries an edit touched since the last rebuild,
            # or ``None`` for "rebuild everything on the next after_edit". A
            # measurement on 4,300 entities put a full rebuild at 72-100 ms on
            # this PC, so touched-entity refresh keeps the window under the
            # one-second rule.
            self._entry_entity: dict = {}
            self._pending_token_refresh: "set | None" = None
            self.family = "club"
            self.status_mode = "all"
            self.section_filter = ""
            self.inspector_entity = None
            self.inspector_edits: dict = {}
            self._filling = False
            self._updating = False
            self._sizing = False
            self._inspector_family = ""
            # Session 21: name health for every open entity (name_health), shared with the
            # entity model and its filter, and snapshots of the lines, kept in memory only.
            self.health: dict = {}
            self.snapshots: list[Snapshot] = []
            self._snapshots_taken = 0
            # A damaged settings file is named in the status bar and never written
            # over (note 05, finding 5); the window opens with its defaults.
            self.state, self.state_problem = read_state(STATE_ROOT)
            # Session 13: saved bulk-tool rules (state/rules.json). Same shape:
            # a missing file loads built-in defaults, a damaged one is named in
            # the status bar and refused for writes.
            self.rules, self.rules_problem = read_rules(STATE_ROOT)
            self.saved_view = clean_view(self.state.get("view"))
            self.saved_searches = clean_saved_searches(self.state.get("saved_searches"))
            # Session 19: up to three folders for File > Open. A bad entry is left out here
            # and stays in the file until the favourites are changed.
            self.favourites = clean_folders(self.state.get("favourite_folders"))
            self.entity_widths = {family: dict(widths) for family, widths
                                  in self.saved_view.get("entity_widths", {}).items()}
            self.line_widths = dict(self.saved_view.get("line_widths", {}))
            self.collection_filter = ""
            self.remember_on_close = True       # the tests switch this off (see close_window)
            self.profiles: list[Profile] = []
            self.resize(self.default_size())
            self.jobs = Jobs(self, self.set_busy)

            self.undo_stack = QUndoStack(self)
            self.line_model = EntryModel()
            self.model = self.line_model
            self.line_proxy = EntryProxy()
            self.proxy = self.line_proxy
            self.line_proxy.setSourceModel(self.line_model)
            self.line_model.dataChanged.connect(self.on_line_data)
            self.line_model.operation_done.connect(self.push_operation)
            self.line_model.rejected.connect(self.say_refused)

            self.entity_model = EntityModel(self.docs)
            self.entity_proxy = EntityProxy()
            self.entity_proxy.setSourceModel(self.entity_model)
            self.entity_model.dataChanged.connect(self.on_entity_data)
            self.entity_model.operation_done.connect(self.push_operation)
            self.entity_model.rejected.connect(self.say_refused)
            self.entity_model.health = self.health
            self.entity_proxy.health = self.health

            self.build_actions()
            self.build_menus()
            self.build_toolbar()
            central = QWidget()
            outer = QVBoxLayout(central)
            outer.setContentsMargins(8, 6, 8, 2)
            self.tabs = QTabWidget()
            outer.addWidget(self.tabs, 1)
            self.setCentralWidget(central)
            self.build_entity_page()
            self.build_line_page()
            self.build_change_page()

            self.metrics = QLabel()
            self.metrics.setObjectName("metrics")
            self.statusBar().addPermanentWidget(self.metrics)
            # Session 21: how many open names have something to check; its link lists them.
            self.health_label = QLabel("")
            self.health_label.setObjectName("muted")
            self.health_label.setTextFormat(Qt.RichText)
            self.health_label.linkActivated.connect(lambda _link: self.show_name_health())
            self.health_label.hide()
            self.statusBar().addPermanentWidget(self.health_label)
            self.selection_pill = QPushButton()
            self.selection_pill.setObjectName("small")
            self.selection_pill.setToolTip("Batch rename the selected entities (Ctrl+B)")
            self.selection_pill.clicked.connect(lambda: self.open_batch_rename())
            self.selection_pill.hide()
            self.statusBar().insertPermanentWidget(0, self.selection_pill)
            self.copyright_label = QLabel(COPYRIGHT_SHORT)
            self.copyright_label.setObjectName("metrics")
            self.copyright_label.setToolTip(
                f"{COPYRIGHT_FULL}\n{REPOSITORY_URL}\n{COPYRIGHT_NOTE}")
            self.statusBar().addPermanentWidget(self.copyright_label)
            self.pending_label = QLabel("")
            self.pending_label.setObjectName("warning")
            self.statusBar().addPermanentWidget(self.pending_label)
            self.settings_label = QLabel("")
            self.settings_label.setObjectName("warning")
            self.statusBar().addPermanentWidget(self.settings_label)
            self.show_settings_problem()
            self.rules_label = QLabel("")
            self.rules_label.setObjectName("warning")
            self.statusBar().addPermanentWidget(self.rules_label)
            self.show_rules_problem()

            self.entity_timer = QTimer(self)
            self.entity_timer.setSingleShot(True)
            self.entity_timer.setInterval(200)
            self.entity_timer.timeout.connect(self.apply_entity_filter)
            self.entity_search.textChanged.connect(lambda _text: self.entity_timer.start())
            self.line_timer = QTimer(self)
            self.line_timer.setSingleShot(True)
            self.line_timer.setInterval(200)
            self.line_timer.timeout.connect(self.apply_line_filter)
            self.line_search.textChanged.connect(lambda _text: self.line_timer.start())
            self.type_box.currentIndexChanged.connect(lambda _index: self.apply_line_filter())
            self.changed_box.toggled.connect(lambda _state: self.apply_line_filter())
            self.section_list.currentItemChanged.connect(lambda _cur, _prev: self.on_section())
            self.family_group.buttonClicked.connect(self.on_family_clicked)
            self.status_group.buttonClicked.connect(self.on_status_clicked)
            self.entity_view.selectionModel().selectionChanged.connect(
                lambda *_args: self.on_entity_selection())
            self.change_view.doubleClicked.connect(self.go_to_change)
            self.tabs.currentChanged.connect(lambda _index: self.refresh_status())
            self.profile_box.currentIndexChanged.connect(lambda _index: self.on_profile_chosen())
            self.entity_view.horizontalHeader().sectionResized.connect(self.on_entity_resized)
            self.line_view.horizontalHeader().sectionResized.connect(self.on_line_resized)
            self.collection_list.currentItemChanged.connect(
                lambda _cur, _prev: self.on_collection())
            self.section_search.textChanged.connect(lambda _text: self.filter_sections())
            self.entity_view.setContextMenuPolicy(Qt.CustomContextMenu)
            self.entity_view.customContextMenuRequested.connect(self.show_grid_menu)

            self.busy_actions = [
                self.open_act, self.quick_load_act, self.save_act, self.deploy_act,
                self.review_act, self.import_act, self.licensing_act, self.undo_act,
                self.redo_act, self.undo_tool, self.redo_tool, self.edit_cell_act,
                self.revert_act, self.replace_act, self.bulk_act, self.export_act,
                self.import_pack_act, self.backups_act, self.record_act,
                self.apply_profile_act, self.migrate_act, self.new_profile_act,
                self.rename_profile_act, self.delete_profile_act,
                self.add_to_collection_menu.menuAction(),
                self.new_collection_act, self.rename_collection_act,
                self.delete_collection_act, self.remove_from_collection_act,
                self.overrides_act, self.batch_rename_act, self.harmonise_act,
                self.select_word_act, self.select_pattern_act, self.select_section_act,
                self.invert_selection_act, self.clear_selection_act, self.palette_act,
                self.open_db_folder_act, *self.favourite_acts, self.favourites_act,
                self.add_name_act, self.search_all_act, self.copy_long_act,
                self.fill_siblings_act, self.fix_formatting_act, self.snapshot_act,
                self.rollback_menu.menuAction()]
            self.busy_widgets = [self.centralWidget(), self.version_box, self.profile_box]
            self.busy_widgets.append(self.selection_pill)
            self._enabled_before: dict = {}

            self.restore_view()
            self.refresh_versions()
            self.load_collections()
            self.apply_family()
            self.tabs.setCurrentIndex(self.saved_view.get("tab", 0))
            self.refresh_status()
            self.refresh_profiles()

        # ----- building the window -----
        def action(self, text: str, slot, keys=(), tip: str = "") -> QAction:
            """A window action for a menu or the toolbar.

            ``keys`` is a standard key or a list of key texts. A shortcut must
            belong to one action only: Qt runs neither of two that share one.
            """
            made = QAction(text, self)
            made.triggered.connect(slot)
            if isinstance(keys, QKeySequence.StandardKey):
                made.setShortcuts(keys)
            elif keys:
                made.setShortcuts([QKeySequence(key) for key in keys])
            if tip:
                made.setToolTip(tip)
            return made

        def build_actions(self) -> None:
            a = self.action
            self.open_act = a("Open files...", self.open_dialog, QKeySequence.Open,
                              "Open one or more .lnc files")
            self.quick_load_act = a(
                "Quick load", self.quick_load, (),
                "Open the two FM27 name files in the selected database folder")
            # Session 19: where to open files from. Each opens the Windows file picker there.
            self.open_db_folder_act = a(
                "Name files in the selected database", self.open_database_folder, (),
                "Choose files in lnc\\all of the database selected at the top, the folder "
                "Quick load reads")
            self.favourite_acts = []
            for number in range(MAX_FAVOURITES):     # filled by fill_favourite_actions
                self.favourite_acts.append(
                    a("", lambda _checked=False, n=number: self.open_favourite(n)))
            self.favourites_act = a(
                "Favourite folders...", self.edit_favourites, (),
                "Keep up to three folders for the File menu; picking one opens the file "
                "picker there")
            self.add_name_act = a(
                "Add name...", self.add_name, (),
                "Add a name line for an ID the game already uses but the open files do not "
                "mention. It does not create a club or look IDs up.")
            self.save_act = a(
                "Save...", self.save, QKeySequence.Save,
                "Review the changes, then write the ticked ones to the files they came from")
            self.deploy_act = a(
                "Deploy to FM27...", self.deploy, ["Ctrl+Shift+D"],
                "Review the changes, then write the name files into lnc\\all of the selected "
                "database, after a backup")
            self.import_act = a(
                "Import older edits...", self.import_old, (),
                "Carry spellings across from an older game's .lnc files, matched by ID")
            self.problem_act = a(
                "Problem lines...", self.show_problems, (),
                "List the lines that could not be read as names. They are kept as they are.")
            self.licensing_act = a(
                "Licensing files...", self.open_licensing, (),
                "Check the name-mask files; four of them can be disabled or restored")
            self.exit_act = a("Exit", self.close, ["Ctrl+Q"], "Close the editor")

            self.undo_act = self.undo_stack.createUndoAction(self, "Undo")
            self.undo_act.setShortcut(QKeySequence.Undo)
            self.redo_act = self.undo_stack.createRedoAction(self, "Redo")
            self.redo_act.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
            self.edit_cell_act = a(
                "Edit cell", self.edit_current, ["F2"],
                "Edit the selected cell. Double-clicking it does the same.")
            self.revert_act = a(
                "Revert selected", self.revert_selected, (),
                "Put the selected lines back to the text on disk")
            self.find_act = a("Find", self.focus_find, QKeySequence.Find,
                              "Go to the search box of the tab shown")
            # Session 20 (note 09). Alt+A and Ctrl+Shift+L were free: no menu
            # mnemonic uses A, and Ctrl+Shift+D stays Deploy.
            self.search_all_act = a(
                "Search all sections", lambda _checked=False: self.search_all_sections(),
                ["Alt+A"],
                "Show every file section again, and no collection, keeping the words typed")
            self.copy_long_act = a(
                "Copy long name to short name", self.copy_long_to_short, ["Ctrl+Shift+L"],
                "Put the inspector's long name into its Short name field, to trim. Nothing "
                "changes until you press Enter there.")
            # Session 21 (note 09). Ctrl+Alt+D and Ctrl+Alt+K were free.
            self.fill_siblings_act = a(
                "Fill short name and code", self.fill_short_and_code, ["Ctrl+Alt+D"],
                "Add the selected club's missing short name and 3-letter code, suggested from "
                "its long name, as one Undo step. Nothing is written until Save or Deploy.")
            self.fix_formatting_act = a(
                "Fix formatting", self.fix_formatting_selected, (),
                "In the selected rows: trim spaces at the ends and in a row, use plain spaces, "
                "quotes and dashes, and put 3-letter codes in capitals, as one Undo step")
            self.snapshot_act = a(
                "Create snapshot...", self.create_snapshot, ["Ctrl+Alt+K"],
                "Keep the open files' lines as they are now, in memory only, to roll back to "
                "later. Nothing is written to disk.")
            self.rollback_menu = QMenu("Roll back to snapshot", self)
            self.rollback_menu.setToolTipsVisible(True)
            self.rollback_menu.aboutToShow.connect(self.fill_snapshot_menu)
            self.replace_act = a("Replace...", self.open_replace, QKeySequence.Replace,
                                 "Find and replace with a regular expression")
            self.bulk_act = a(
                "Bulk tools...", self.open_bulk, (),
                "Strip affixes, remove sponsors, or title-case the names shown")
            self.batch_rename_act = a(
                "Batch rename selected...", lambda: self.open_batch_rename(), ["Ctrl+B"],
                "Preview transformations of selected names; apply them as one undo step")
            self.select_word_act = a(
                "Select all matching word...", self.prompt_select_word, ["Ctrl+Shift+W"])
            self.select_pattern_act = a(
                "Select by pattern / regex...", self.prompt_select_pattern,
                ["Ctrl+Shift+S", "Ctrl+Shift+F"])
            self.select_section_act = a(
                "Select same file section", self.select_same_section, ["Ctrl+Alt+S"])
            self.invert_selection_act = a(
                "Invert selection", self.invert_entity_selection, ["Ctrl+Shift+I"])
            self.clear_selection_act = a(
                "Clear selection", self.clear_entity_selection, ["Ctrl+D"])
            self.harmonise_act = a(
                "Harmonise terminology...", self.open_harmoniser, (),
                "Find mixed football terms in loaded clubs, then preview a chosen spelling")
            self.palette_act = a(
                "Command palette...", self.open_command_palette, ["Ctrl+Shift+P"],
                "Search menu commands, saved searches, collections and name words")

            self.entities_act = a("Entities", lambda _checked=False: self.tabs.setCurrentIndex(0),
                                  ["Ctrl+1"])
            self.lines_act = a("All lines", lambda _checked=False: self.tabs.setCurrentIndex(1),
                               ["Ctrl+2"])
            self.changes_act = a(
                "Changes", self.show_changes_tab, ["Ctrl+Shift+C", "Ctrl+3"],
                "Every difference between the open files and the files on disk")

            self.inspector_act = a(
                "Inspector", self.set_inspector_shown, ["F4"],
                "Show or hide the inspector beside the entity grid")
            self.inspector_act.setCheckable(True)
            self.inspector_act.setChecked(True)
            # Session 19 revises decision 26: the ID is how a row is matched across
            # versions, so the grid shows it by default; the inspector shows it as well.
            self.id_column_act = a(
                "Show ID column", self.set_id_column_shown, (),
                "Show or hide the ID column of the entity grid. The inspector and All lines "
                "always show the ID.")
            self.id_column_act.setCheckable(True)
            self.id_column_act.setChecked(True)
            self.reset_widths_act = a(
                "Reset column widths", self.reset_column_widths, (),
                "Size every grid column to its text again, forgetting the widths you set")

            self.export_act = a("Export pack...", self.export_pack, (),
                                "Save edited names as JSON or CSV")
            self.import_pack_act = a("Import pack...", self.import_pack, (),
                                     "Apply a JSON or CSV name pack")
            self.backups_act = a(
                "Browse and restore...", self.open_backups, (),
                "Compare a backup with the open files and restore it into memory")

            self.record_act = a(
                "Record edits", self.record_into_profile, (),
                "Copy the unsaved name edits into this profile, with the names on disk as "
                "their baselines. Record before you Save or Deploy.")
            self.apply_profile_act = a(
                "Apply...", self.apply_profile_to_files, (),
                "Preview this profile's spellings against the open files. Nothing is written "
                "until you Save or Deploy.")
            self.migrate_act = a(
                "Migrate from new files...", self.migrate_profile_to_files, (),
                "Carry this profile's spellings forward to a new version of Football Manager. "
                "Open the new files first, then this compares every spelling with them.")
            self.new_profile_act = a("New profile...", self.new_profile)
            self.rename_profile_act = a("Rename profile...", self.rename_current_profile)
            self.delete_profile_act = a("Delete profile...", self.delete_current_profile)

            self.shortcuts_act = a("Keyboard shortcuts", self.show_shortcuts,
                                   QKeySequence.HelpContents, "List the keys the editor knows")
            self.guide_act = a(
                "User guide", self.show_guide, (),
                "What the editor does and in what order: open, edit, review, write")
            self.about_act = a(
                f"About {APP_NAME}", self.show_about, (),
                "Version, copyright, and the licence this software ships under")
            self.overrides_act = a(
                "Show overrides across files...", self.show_overrides, (),
                "List every line in the chosen database folder's .lnc files that "
                "matches the selected entity, and whether the values agree.")

            # Collections: sets of entities you name, kept in state\collections.json.
            self.add_to_collection_menu = QMenu("Add selected to", self)
            self.add_to_collection_menu.setToolTipsVisible(True)
            self.add_to_collection_menu.aboutToShow.connect(self.fill_add_to_menu)
            self.remove_from_collection_act = a(
                "Remove selected from this collection", self.remove_selected_from_collection, (),
                "Take the selected rows out of the collection shown. The names are not changed.")
            self.new_collection_act = a(
                "New collection...", lambda _checked=False: self.new_collection(), (),
                "Make an empty collection; add rows to it from the grid")
            self.rename_collection_act = a("Rename collection...", self.rename_collection)
            self.delete_collection_act = a(
                "Delete collection...", self.delete_collection, (),
                "Delete the collection shown. It is kept in collections.json, so it can be "
                "recovered by hand. The names are not changed.")

            # Toolbar-only actions. Their text stays short and fixed, and they carry
            # no shortcut: the menu actions own Ctrl+S, Ctrl+Z, and Ctrl+Y.
            self.review_act = a(
                "Review changes", self.save, (),
                "Review the changes, then write the ticked ones to the files they came from. "
                "The same as File > Save (Ctrl+S).")
            self.review_act.setEnabled(False)
            self.undo_tool = a("Undo", self.undo_stack.undo, (), "Undo (Ctrl+Z)")
            self.redo_tool = a("Redo", self.undo_stack.redo, (), "Redo (Ctrl+Y)")
            for tool in (self.undo_tool, self.redo_tool):
                tool.setEnabled(False)
            self.undo_stack.canUndoChanged.connect(self.undo_tool.setEnabled)
            self.undo_stack.canRedoChanged.connect(self.redo_tool.setEnabled)
            self.undo_stack.undoTextChanged.connect(
                lambda text: self.undo_tool.setToolTip(
                    f"Undo {text} (Ctrl+Z)" if text else "Undo (Ctrl+Z)"))
            self.undo_stack.redoTextChanged.connect(
                lambda text: self.redo_tool.setToolTip(
                    f"Redo {text} (Ctrl+Y)" if text else "Redo (Ctrl+Y)"))

        def build_menus(self) -> None:
            bar = self.menuBar()
            self.menus: list[QMenu] = []

            def menu(title: str, *items) -> QMenu:
                made = bar.addMenu(title)
                made.setToolTipsVisible(True)
                for item in items:
                    if item is None:
                        made.addSeparator()
                    else:
                        made.addAction(item)
                self.menus.append(made)
                return made

            self.file_menu = menu(
                "&File", self.open_act, self.quick_load_act, None, self.open_db_folder_act,
                *self.favourite_acts, self.favourites_act, None, self.save_act,
                self.deploy_act, None, self.import_act, None, self.problem_act,
                self.licensing_act, None, self.exit_act)
            self.fill_favourite_actions()
            self.edit_menu = menu(
                "&Edit", self.undo_act, self.redo_act, None, self.edit_cell_act,
                self.add_name_act, self.revert_act, self.copy_long_act,
                self.fill_siblings_act, self.fix_formatting_act, None, self.find_act,
                self.search_all_act, self.replace_act, self.bulk_act)
            self.edit_menu.addAction(self.batch_rename_act)
            self.selection_menu = self.edit_menu.addMenu("&Selection")
            for action in (self.select_word_act, self.select_pattern_act,
                           self.select_section_act, self.invert_selection_act,
                           self.clear_selection_act):
                self.selection_menu.addAction(action)
            self.edit_menu.addSeparator()
            self.edit_menu.addAction(self.snapshot_act)
            self.edit_menu.addMenu(self.rollback_menu)
            self.edit_menu.addSeparator()
            self.edit_menu.addAction(self.palette_act)
            self.tools_menu = menu("&Tools", self.harmonise_act)
            self.view_menu = menu("&View", self.entities_act, self.lines_act, self.changes_act,
                                  None, self.inspector_act, self.id_column_act,
                                  self.reset_widths_act)
            self.packs_menu = menu("&Packs", self.export_act, self.import_pack_act)
            self.backups_menu = menu("&Backups", self.backups_act)
            self.profiles_menu = menu(
                "P&rofiles", self.record_act, self.apply_profile_act, self.migrate_act, None,
                self.new_profile_act, self.rename_profile_act, self.delete_profile_act)
            self.collections_menu = menu(
                "&Collections", self.add_to_collection_menu.menuAction(),
                self.remove_from_collection_act, None, self.new_collection_act,
                self.rename_collection_act, self.delete_collection_act)
            self.help_menu = menu("&Help", self.guide_act, self.shortcuts_act, None,
                                  self.about_act)

        def build_toolbar(self) -> None:
            """One row under the menus: the product, the database, the profile, the
            frequent actions, and Review changes, which stays at the right-hand end."""
            tb = self.addToolBar("Main")
            tb.setObjectName("main_toolbar")
            tb.setMovable(False)
            tb.setFloatable(False)
            tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
            tb.toggleViewAction().setVisible(False)    # no right-click way to hide the header
            self.toolbar = tb
            product = QLabel(f"{APP_NAME} {VERSION}")
            product.setObjectName("product")
            self.product_label = product
            tb.addWidget(product)
            tb.addSeparator()
            tb.addWidget(QLabel("Database"))
            self.version_box = QComboBox()
            self.version_box.setToolTip(
                "Quick load and Deploy use the name files in this database folder. The "
                "highest folder that has both is chosen at start; that does not prove a "
                "save uses it.")
            tb.addWidget(self.version_box)
            tb.addSeparator()
            tb.addWidget(QLabel("Profile"))
            self.profile_box = QComboBox()
            self.profile_box.setMinimumWidth(170)
            self.profile_box.setMaximumWidth(260)
            self.profile_box.setToolTip(
                "A spelling profile keeps your preferred names after Save and Deploy, "
                "so they can be applied again when the game's files change.")
            tb.addWidget(self.profile_box)
            tb.addAction(self.record_act)
            tb.addAction(self.apply_profile_act)
            self.record_btn = tb.widgetForAction(self.record_act)
            self.apply_profile_btn = tb.widgetForAction(self.apply_profile_act)
            tb.addSeparator()
            tb.addAction(self.quick_load_act)
            tb.addAction(self.undo_tool)
            tb.addAction(self.redo_tool)
            spacer = QWidget()
            spacer.setObjectName("spacer")
            spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            tb.addWidget(spacer)
            tb.addAction(self.review_act)
            self.review_btn = tb.widgetForAction(self.review_act)
            self.review_btn.setObjectName("review")

        def build_entity_page(self) -> None:
            entity_page = QWidget()
            entity_lay = QVBoxLayout(entity_page)
            entity_lay.setContentsMargins(0, 8, 0, 0)
            family_row = QHBoxLayout()
            self.family_group = QButtonGroup(self)
            self.family_group.setExclusive(True)
            self.family_buttons = []
            for key, label in FAMILY_LABELS.items():
                button = QPushButton(label)
                button.setCheckable(True)
                button.setProperty("family", key)
                self.family_group.addButton(button)
                self.family_buttons.append(button)
                family_row.addWidget(button)
            family_row.addStretch(1)
            entity_lay.addLayout(family_row)

            status_row = QHBoxLayout()
            # Session 20: what the search box searches, while a file section or a
            # collection narrows the grid, and the way out of it (Alt+A).
            self.scope_label = QLabel("")
            self.scope_label.setObjectName("muted")
            self.scope_label.setMaximumWidth(260)
            self.scope_label.hide()
            status_row.addWidget(self.scope_label)
            self.entity_search = QLineEdit()
            self.entity_search.setPlaceholderText(
                "Search names, IDs, and file sections (accents ignored). Ctrl+F")
            self.entity_search.setClearButtonEnabled(True)
            status_row.addWidget(self.entity_search, 1)
            self.search_all_btn = QPushButton("Search all sections")
            self.search_all_btn.setObjectName("small")
            self.search_all_btn.setToolTip(
                "Show every file section again, keeping the words typed (Alt+A)")
            self.search_all_btn.clicked.connect(lambda _checked=False: self.search_all_sections())
            self.search_all_btn.hide()
            status_row.addWidget(self.search_all_btn)
            self.searches_btn = QPushButton("Saved searches")
            self.searches_btn.setToolTip(
                "Keep this search (family, words, filter, and file section or collection) "
                "under a name, and come back to it")
            self.searches_menu = QMenu(self.searches_btn)
            self.searches_menu.aboutToShow.connect(self.fill_searches_menu)
            self.searches_btn.setMenu(self.searches_menu)
            status_row.addWidget(self.searches_btn)
            self.status_group = QButtonGroup(self)
            self.status_group.setExclusive(True)
            self.status_buttons = []
            for mode, label in STATUS_FILTERS.items():
                button = QPushButton(label)
                button.setCheckable(True)
                button.setProperty("mode", mode)
                self.status_group.addButton(button)
                self.status_buttons.append(button)
                status_row.addWidget(button)
            entity_lay.addLayout(status_row)
            # "Matched via alias ...", or "No matches in ... Found N in other sections"
            # as a link that shows every section. Hidden when there is nothing to say.
            self.scope_hint = QLabel("")
            self.scope_hint.setObjectName("muted")
            self.scope_hint.setTextFormat(Qt.RichText)
            self.scope_hint.linkActivated.connect(lambda _link: self.search_all_sections())
            self.scope_hint.hide()
            entity_lay.addWidget(self.scope_hint)

            splitter = QSplitter()
            self.entity_splitter = splitter
            left = QWidget()
            left_lay = QVBoxLayout(left)
            left_lay.setContentsMargins(0, 0, 0, 0)
            heading = QHBoxLayout()
            heading.addWidget(QLabel("Collections"))
            heading.addStretch(1)
            new_button = QPushButton("New...")
            new_button.setObjectName("small")
            new_button.setToolTip(self.new_collection_act.toolTip())
            new_button.clicked.connect(lambda _checked=False: self.new_collection())
            self.new_collection_btn = new_button
            heading.addWidget(new_button)
            left_lay.addLayout(heading)
            self.collection_list = QListWidget()
            self.collection_list.setObjectName("collections")
            self.collection_list.setToolTip(
                "Sets of names you made. They live in your settings, not in the name files, "
                "and are not file sections.")
            self.collection_list.setMaximumHeight(118)
            left_lay.addWidget(self.collection_list)
            self.collection_hint = QLabel("")
            self.collection_hint.setObjectName("muted")
            self.collection_hint.setWordWrap(True)
            left_lay.addWidget(self.collection_hint)
            left_lay.addSpacing(6)
            label = QLabel("File sections")
            label.setToolTip(FILE_SECTION_HINT)
            left_lay.addWidget(label)
            self.section_search = QLineEdit()
            self.section_search.setPlaceholderText("Search file sections")
            self.section_search.setClearButtonEnabled(True)
            left_lay.addWidget(self.section_search)
            self.section_list = QListWidget()
            left_lay.addWidget(self.section_list, 1)
            splitter.addWidget(left)

            self.entity_view = QTableView()
            self.entity_view.setModel(self.entity_proxy)
            self.entity_view.setSelectionBehavior(QTableView.SelectRows)
            self.entity_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.entity_view.setAlternatingRowColors(True)
            self.entity_view.setWordWrap(False)
            self.entity_view.verticalHeader().setVisible(False)
            self.entity_view.verticalHeader().setDefaultSectionSize(24)
            self.entity_view.setEditTriggers(
                QTableView.DoubleClicked | QTableView.EditKeyPressed)
            self.entity_view.setItemDelegate(
                CadenceDelegate(self.entity_view, self.grid_edit_origin, self.move_grid_editor))
            sortable(self.entity_view, self.on_entity_sort)
            splitter.addWidget(self.entity_view)

            self.inspector = QWidget()
            self.inspector_lay = QVBoxLayout(self.inspector)
            self.inspector_lay.setContentsMargins(10, 0, 6, 0)
            self.inspector_fields: dict = {}
            inspector_scroll = QScrollArea()
            inspector_scroll.setWidgetResizable(True)
            inspector_scroll.setFrameShape(QFrame.NoFrame)
            inspector_scroll.setMinimumWidth(260)
            inspector_scroll.setWidget(self.inspector)
            self.inspector_scroll = inspector_scroll
            splitter.addWidget(inspector_scroll)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([190, 770, 300])
            entity_lay.addWidget(splitter, 1)
            self.tabs.addTab(entity_page, "Entities")

        def build_line_page(self) -> None:
            line_page = QWidget()
            line_lay = QVBoxLayout(line_page)
            line_lay.setContentsMargins(0, 8, 0, 0)
            row = QHBoxLayout()
            self.line_search = QLineEdit()
            self.search = self.line_search
            self.line_search.setPlaceholderText(
                "Search name, ID or section (accents ignored). Ctrl+F")
            self.line_search.setClearButtonEnabled(True)
            row.addWidget(self.line_search, 1)
            self.type_box = QComboBox()
            row.addWidget(self.type_box)
            self.changed_box = QCheckBox("Changed only")
            row.addWidget(self.changed_box)
            line_lay.addLayout(row)
            self.line_view = QTableView()
            self.view = self.line_view
            self.line_view.setModel(self.line_proxy)
            self.line_view.setSelectionBehavior(QTableView.SelectRows)
            self.line_view.setAlternatingRowColors(True)
            self.line_view.setWordWrap(False)
            self.line_view.verticalHeader().setVisible(False)
            self.line_view.verticalHeader().setDefaultSectionSize(24)
            self.line_view.horizontalHeader().setSectionResizeMode(
                EntryModel.NAME_COL, QHeaderView.Stretch)
            self.line_view.setItemDelegateForColumn(EntryModel.TYPE_COL,
                                                    BadgeDelegate(self.line_view))
            sortable(self.line_view, self.on_line_sort)
            self.line_view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
            line_lay.addWidget(self.line_view, 1)
            self.tabs.addTab(line_page, "All lines")

        def build_change_page(self) -> None:
            change_page = QWidget()
            change_lay = QVBoxLayout(change_page)
            change_lay.setContentsMargins(0, 8, 0, 0)
            row = QHBoxLayout()
            self.change_search = QLineEdit()
            self.change_search.setPlaceholderText(
                "Filter changes (name, ID, file, reason; accents ignored)")
            self.change_search.setClearButtonEnabled(True)
            row.addWidget(self.change_search, 1)
            for text, state in (("Tick all shown", True), ("Untick all shown", False)):
                button = QPushButton(text)
                button.clicked.connect(
                    lambda _=False, s=state: self.change_model.set_included(
                        self.change_proxy.shown_rows(), s))
                row.addWidget(button)
            change_lay.addLayout(row)
            self.change_summary = QLabel("")
            self.change_summary.setObjectName("muted")
            self.change_summary.setWordWrap(True)
            change_lay.addWidget(self.change_summary)
            self.change_model = ChangeModel()
            self.change_proxy = ChangeProxy()
            self.change_proxy.setSourceModel(self.change_model)
            self.change_view = change_table(self.change_proxy)
            self.change_view.setToolTip("Double-click a row to go to its line on All lines.")
            change_lay.addWidget(self.change_view, 1)
            self.tabs.addTab(change_page, "Changes")
            self.change_search.textChanged.connect(self.change_proxy.set_filter)
            self.change_model.ticks_changed.connect(
                lambda: self.change_summary.setText(describe_ticks(self.change_model.rows)))

        def open_dialog(self):
            if not self.confirm_discard():
                return
            self.pick_and_open(self.start_folder())

        # ----- where the file pickers open, and the favourite folders (Session 19) -----
        def start_folder(self) -> str:
            """Where a file picker opens, never "": the last folder File > Open used, else
            lnc\\all of the selected database (see picker_folder). The status bar says so
            when that folder is missing."""
            folder, problem = picker_folder(self.state.get("open_folder"),
                                            self.selected_version())
            if problem:
                self.statusBar().showMessage(problem, 15000)
            return folder

        def remember_open_folder(self, paths) -> None:
            """Keep the folder files were opened from, for the next File > Open.

            It is kept in the settings file through keep_settings, so a damaged
            file is left as it is; this run still opens there next time.
            """
            folder = os.path.normpath(os.path.dirname(paths[0]))
            if self.state.get("open_folder") != folder:
                self.state = {**self.state, "open_folder": folder}
                self.keep_settings(self.state)

        def pick_and_open(self, folder: str) -> None:
            """Open the .lnc files chosen in the Windows file picker, which opens in ``folder``."""
            paths, _ = QFileDialog.getOpenFileNames(self, "Open .lnc files", folder, FILTER)
            if paths:
                self.remember_open_folder(paths)
                self.load_in_background(paths)

        def open_database_folder(self) -> None:
            """File > Name files in the selected database: the file picker, in its lnc\\all."""
            folder = names_folder(self.selected_version())
            if folder is None or not folder.is_dir():
                QMessageBox.warning(
                    self, APP_NAME,
                    "The name files folder of the selected database was not found.\n"
                    f"Looked for {folder if folder is not None else GAME_DB_ROOT}")
                return
            if self.confirm_discard():
                self.pick_and_open(str(folder))

        def open_favourite(self, number: int) -> None:
            """File > one of the favourite folders: the file picker, in that folder."""
            if not 0 <= number < len(self.favourites):
                return
            folder = self.favourites[number]
            if not _usable_folder(folder):
                QMessageBox.warning(
                    self, APP_NAME,
                    f"The favourite folder {folder} is not there now; a drive may be missing. "
                    "File > Favourite folders can change it.")
                return
            if self.confirm_discard():
                self.pick_and_open(folder)

        def fill_favourite_actions(self) -> None:
            """List the favourite folders in the File menu; a place without one is hidden."""
            for number, action in enumerate(self.favourite_acts):
                folder = self.favourites[number] if number < len(self.favourites) else ""
                shown = folder if len(folder) <= 72 else f"{folder[:34]}…{folder[-36:]}"
                action.setText(f"&{number + 1}  {shown.replace('&', '&&')}" if folder else "")
                action.setToolTip(f"Choose files in {folder}" if folder else "")
                action.setVisible(bool(folder))

        def edit_favourites(self) -> None:
            """File > Favourite folders: up to three, kept in the settings file."""
            dialog = FavouritesDialog(self, self.favourites, self.start_folder)
            if not dialog.exec():
                return
            folders = dialog.folders()
            if folders == self.favourites:
                return
            state = {**self.state, "favourite_folders": folders}
            problem = self.keep_settings(state)
            if problem:
                QMessageBox.warning(self, APP_NAME,
                                    f"The favourite folders were not changed.\n\n{problem}")
                return
            self.state = state
            self.favourites = folders
            self.fill_favourite_actions()
            self.statusBar().showMessage(
                f"Favourite folders kept: {len(folders)} of {MAX_FAVOURITES}. The File menu "
                "lists them.", 8000)

        def load(self, paths) -> bool:
            """Open the files as the new workspace, here and now (files dropped on the
            launcher, and the tests). Open and Quick load use load_in_background.

            Every file is read and decoded first. If any one fails, a message
            names it and the files that were already open are left alone.
            Returns True when the new files replaced the old ones.
            """
            paths = list(paths)
            if not paths:
                return False
            try:
                docs = open_documents(paths)
            except LoadError as exc:
                self.load_failed(exc)
                return False
            self.adopt_documents(docs)
            return True

        def load_in_background(self, paths) -> None:
            """Open files with the reading and parsing on a worker thread.

            The window stays drawn, with everything that could change files
            switched off, until the files are in; a failure leaves the files
            that were open as they were.
            """
            paths = list(paths)
            if not paths:
                return
            names = ", ".join(Path(path).name for path in paths)
            self.jobs.start(f"Opening {names}...", lambda: open_documents(paths),
                            self.adopt_documents, self.load_failed)

        def load_failed(self, exc: Exception) -> None:
            reason = str(exc) if isinstance(exc, LoadError) else f"Could not open the files:\n{exc}"
            QMessageBox.critical(
                self, APP_NAME, f"{reason}\n\nNothing was opened. The current files are unchanged.")

        def adopt_documents(self, docs) -> None:
            """Make freshly read documents the workspace, with a new history.

            The family shown stays (it is part of the remembered view); the
            file section, collection, and status filter start again at all.
            """
            self.docs.clear()
            self.docs.extend(docs)
            self.undo_stack.clear()     # its steps belong to the files that were open
            self.snapshots.clear()      # and so do the snapshots (Session 21)
            self.section_filter = ""
            self.collection_filter = ""
            self.status_mode = "all"
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "all")
            self.reload_views(keep_place=False)
            self.tabs.setCurrentIndex(0)

        def save(self):
            """Write every document with changes back to its own file, after a review.

            A file inside the game tree is handled exactly as Deploy handles
            it: refused while the game runs, reviewed with its backup folder
            named, and copied into that folder first. Only the ticked changes
            are written; the rest stay pending.
            """
            dirty = [doc for doc in self.docs if doc.dirty]
            if not dirty:
                self.statusBar().showMessage("Nothing to save.", 4000)
                return
            self.review_and_write("Save", [(doc, doc.path) for doc in dirty], GAME_DB_ROOT)

        def review_and_write(self, operation: str, pairs, game_root, left_alone=()) -> None:
            """Check for a running game on a worker, then review the Save or Deploy and write.

            The check is made only when a game file is among the destinations;
            the window waits with its actions off until it comes back.
            """
            pairs = list(pairs)
            if any(game_root is None or under_game_tree(Path(dest), game_root)
                   for _doc, dest in pairs):
                self.jobs.start(GAME_CHECK, football_manager_running,
                                lambda found: self.open_review(
                                    operation, pairs, game_root, left_alone, found),
                                lambda _error: self.open_review(   # unknown, not closed
                                    operation, pairs, game_root, left_alone, None))
            else:
                self.open_review(operation, pairs, game_root, left_alone, [])

        def open_review(self, operation: str, pairs, game_root, left_alone, found) -> bool:
            """Show the Review changes dialog, then write. ``found`` is the game check's answer.

            A running game refuses the write before the review opens, with
            the same message for Save and Deploy. Returns True when files
            were written.
            """
            review = WriteReview(operation, pairs, game_root, check=lambda: found,
                                 left_alone=left_alone)
            if review.preflight.blocked:
                QMessageBox.warning(self, APP_NAME, review.preflight.blocked_message())
                return False
            if not review.rows and not review.to_write:
                QMessageBox.information(self, APP_NAME, review.nothing_message())
                return False
            dialog = ReviewDialog(self, review)
            accepted = dialog.exec()
            if not accepted:
                self.refresh_status()       # ticks changed in the review show in Changes
                return False
            try:
                archive = review.write(BACKUP_ROOT)
            except (OSError, UnicodeError) as exc:
                if isinstance(exc, WriteError) and exc.files:
                    self.reload_views()     # a file left written is now settled
                report_write_failure(self, operation, exc)
                return False
            self.undo_stack.setClean()      # a label for the state just written; dirty stays the bytes
            self.reload_views()
            self.statusBar().showMessage(review.outcome(archive), 10000)
            return True

        # ----- undo and redo -----
        @contextlib.contextmanager
        def recording(self, label: str):
            """Record the changes made in the block as one step on the undo stack.

            Set ``label`` on the yielded Operation inside the block when it
            depends on what happened. Nothing is pushed when nothing changed.
            """
            operation = Operation(label)
            with operation:
                yield operation
            self.push_operation(operation)

        def push_operation(self, operation: Operation) -> None:
            if operation.changed:
                self._queue_token_refresh(operation)
                self.undo_stack.push(EditCommand(self, operation))

        def _queue_token_refresh(self, operation: Operation) -> None:
            """Note which entries ``after_edit`` has to refresh in the token index.

            A structural operation (a line added, removed, or swapped) may
            have moved a name across entities, so the whole family is rebuilt
            and the pending set goes back to ``None``. A non-structural
            operation touches only the entries it recorded; those are added
            to the pending set so after_edit refreshes just their entities.
            """
            if operation.structural:
                self._pending_token_refresh = None
                return
            if self._pending_token_refresh is None:
                self._pending_token_refresh = set()
            self._pending_token_refresh.update(operation.touched_entries)

        def _queue_token_refresh_for_entries(self, entries) -> None:
            """Queue refresh for a list of entries that bypassed recording.

            Revert paths change line names directly without an ``Operation``
            around them; they still need the token index to catch up before
            the next right-click reads it.
            """
            if self._pending_token_refresh is None:
                self._pending_token_refresh = set()
            self._pending_token_refresh.update(entries)

        def after_undo(self, operation: Operation, verb: str) -> None:
            """Show the files as an undo or redo left them."""
            self._queue_token_refresh(operation)
            if operation.structural:
                self.reload_views()
            else:
                self.after_edit()           # as after a cell edit
            self.statusBar().showMessage(f"{verb}: {operation.label}.", 8000)

        def after_edit(self) -> None:
            """Show a change of names that moved no lines.

            A view is filtered again only when its filter reads the names (a
            search, Changed only, Edited); otherwise repainting it is enough.
            Then the counts, and the inspector, are brought up to date, and
            the token index is refreshed for any entity whose names changed.
            Name health is checked again first, for the grid, its filter, and
            the count (Session 21).
            """
            self.refresh_health()
            if self.line_proxy.words or self.line_proxy.changed_only:
                relayout(self.line_model)
            else:
                self.line_view.viewport().update()
            proxy = self.entity_proxy
            if proxy.words or proxy.mode != "all":
                if proxy.alias:     # the words typed may find the row now: they come first
                    proxy.configure(self.entity_search.text(), self.section_filter,
                                    self.status_mode, self.collection_keys())
                proxy.invalidate()
                self.settle_search()
            else:
                self.entity_view.viewport().update()
            self.refresh_status()
            self._refresh_token_index()
            if self.inspector_entity is not None:
                self.show_inspector(self.inspector_entity)

        def _refresh_token_index(self) -> None:
            """Refresh the token index for the entities an edit touched.

            When the pending set covers every touched entry, each unique
            entity is refreshed in place; the rest of the family is left as
            it is. ``None`` (the default, and the post-structural state)
            rebuilds the whole index, and so does an unknown entry (one
            whose entity the map does not hold yet, for example after a
            structural change the caller forgot to flag).
            """
            pending = self._pending_token_refresh
            self._pending_token_refresh = None
            if pending is None:
                self.token_index.rebuild(self.all_entities)
                return
            entities: list = []
            seen = set()
            for entry in pending:
                entity = self._entry_entity.get(entry)
                if entity is None:
                    # An entry that was not in the map on the last reload:
                    # safest to rebuild the whole index.
                    self.token_index.rebuild(self.all_entities)
                    return
                key = id(entity)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(entity)
            for entity in entities:
                self.token_index.refresh(entity)

        def say_refused(self, problem: str) -> None:
            """A typed name or ending was not used: say why, instead of nothing."""
            self.statusBar().showMessage(f"Not changed. {problem}", 12000)

        def confirm_discard(self) -> bool:
            if not any(d.dirty for d in self.docs):
                return True
            r = QMessageBox.question(
                self, APP_NAME, "You have unsaved changes. Save them first?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Save:
                self.save()
                self.jobs.wait()            # the review may be waiting for the game check
                return not any(d.dirty for d in self.docs)
            return r == QMessageBox.Discard

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if hasattr(self, "illustrative_card"):
                self.illustrative_card.fit_to_space()

        def closeEvent(self, event):
            self.jobs.wait(15)              # let a job end before the window goes
            if not self.confirm_discard():
                event.ignore()
                return
            self.illustrative_card.stop_ticker()
            if self.remember_on_close:
                self.remember_view()
            event.accept()

        def set_busy(self, busy: bool, text: str) -> None:
            """A job started, or the last one ended: switch off, or back on, what it could clash with.

            While a job runs, the grids, the inspector, the database and
            profile choices, and every action that opens, changes, or writes
            files are off, so nothing can change under it. Afterwards each
            action is as it was; Undo and Redo follow the undo stack again.
            """
            if busy:
                self._enabled_before = {action: action.isEnabled()
                                        for action in self.busy_actions}
                for action in self.busy_actions:
                    action.setEnabled(False)
                for widget in self.busy_widgets:
                    widget.setEnabled(False)
                self.update_selection_actions()
                QApplication.setOverrideCursor(Qt.BusyCursor)
                self.statusBar().showMessage(text)
                return
            for action, enabled in self._enabled_before.items():
                action.setEnabled(enabled)
            for widget in self.busy_widgets:
                widget.setEnabled(True)
            self.update_selection_actions()
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

        @staticmethod
        def default_size() -> QSize:
            """1280 by 820, or less to fit the screen's free area with room for the title bar.

            At 150% scaling a 1920 by 1080 screen is 1280 by 720 to Qt, and a
            window 820 tall would run off its bottom.
            """
            screen = QApplication.primaryScreen()
            if screen is None:
                return QSize(1280, 820)
            free = screen.availableGeometry()
            return QSize(min(1280, free.width()), min(820, free.height() - 48))

        # ----- the remembered view -----
        def restore_view(self) -> None:
            """Put back the view kept in the settings file (see clean_view)."""
            view = self.saved_view
            self.family = view.get("family", "club")
            self.status_mode = view.get("status", "all")
            for button in self.family_buttons:
                button.setChecked(button.property("family") == self.family)
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == self.status_mode)
            for name, model in (("entity_sort", self.entity_model),
                                ("line_sort", self.line_model)):
                if name in view:
                    model.sort_key = view[name]["key"]
                    model.sort_descending = view[name]["descending"]
            for name, restore in (("geometry", self.restoreGeometry),
                                  ("window_state", self.restoreState),
                                  ("splitter", self.entity_splitter.restoreState)):
                if name in view:
                    restore(QByteArray.fromBase64(view[name].encode("ascii")))
            shown = view.get("inspector", True)
            self.inspector_act.setChecked(shown)
            self.set_inspector_shown(shown)
            self.id_column_act.setChecked(view.get("id_column", True))  # apply_family shows it

        def remember_view(self) -> None:
            """Keep the view in the settings file for next time. The window calls it on close."""
            def text(data) -> str:
                return data.toBase64().data().decode("ascii")

            self.state["view"] = clean_view({
                "tab": self.tabs.currentIndex(),
                "family": self.family,
                "status": self.status_mode,
                "entity_sort": {"key": self.entity_model.sort_key,
                                "descending": self.entity_model.sort_descending},
                "line_sort": {"key": self.line_model.sort_key,
                              "descending": self.line_model.sort_descending},
                "entity_widths": self.entity_widths,
                "line_widths": self.line_widths,
                "geometry": text(self.saveGeometry()),
                "window_state": text(self.saveState()),
                "splitter": text(self.entity_splitter.saveState()),
                "inspector": self.inspector_act.isChecked(),
                "id_column": self.id_column_act.isChecked(),
            })
            # The window is closing: when the file cannot be written, the next run
            # starts with the view before, and a damaged file stays as it is.
            self.keep_settings(self.state)

        def set_inspector_shown(self, shown: bool) -> None:
            """Show or hide the inspector (View > Inspector, F4). Shown again, it
            gets its width back if the splitter had squeezed it to nothing."""
            shown = bool(shown)
            if self.inspector_act.isChecked() != shown:
                self.inspector_act.setChecked(shown)
            self.inspector_scroll.setVisible(shown)
            if shown:
                sizes = self.entity_splitter.sizes()
                if len(sizes) == 3 and sizes[2] < self.inspector_scroll.minimumWidth():
                    sizes[1] = max(200, sizes[1] - 300)
                    sizes[2] = 300
                    self.entity_splitter.setSizes(sizes)

        def reset_column_widths(self) -> None:
            """Forget the widths set by hand and size every grid column to its text."""
            self.entity_widths = {}
            self.line_widths = {}
            self._size_line_columns()
            self._sizing = True
            try:
                self._size_entity_columns()
            finally:
                self._sizing = False
            fit_change_columns(self.change_view, self.change_model)
            self.statusBar().showMessage(
                "Column widths reset to fit their text. The new widths are kept when the "
                "window closes.", 8000)

        def keep_settings(self, state: dict) -> str:
            """Write the settings file. Returns "" when it was written, or why it was not.

            A damaged settings file is never written over (see read_state). Once
            one is found, no settings are written for the rest of the run, so a
            file put right by hand meanwhile is not replaced by this window's
            defaults either.
            """
            if not self.state_problem:
                try:
                    save_state(state, STATE_ROOT)
                    return ""
                except DamagedFileError as exc:     # damaged after the window opened
                    self.state_problem = str(exc)
                    self.show_settings_problem()
                except OSError as exc:
                    return f"Could not write the settings file:\n{exc}"
            return f"{self.state_problem} {SETTINGS_LEFT_ALONE}"

        def show_settings_problem(self) -> None:
            """Name a damaged settings file in the status bar for as long as the window runs."""
            problem = self.state_problem
            self.settings_label.setVisible(bool(problem))
            if problem:
                self.settings_label.setText(
                    f"Settings not saved: {STATE_ROOT / STATE_FILE} could not be read")
                self.settings_label.setToolTip(f"{problem} {SETTINGS_LEFT_ALONE}")

        def keep_rules(self, rules: "Rules") -> str:
            """Write the saved rules file. Returns "" when it was written, or why it was not.

            Mirrors ``keep_settings``: a damaged rules file is never written
            over, and once one is found no rules are written for the rest of
            the run, so a file put right by hand meanwhile is not replaced by
            this window's defaults either.
            """
            if not self.rules_problem:
                try:
                    save_rules(rules, STATE_ROOT)
                    return ""
                except DamagedFileError as exc:     # damaged after the window opened
                    self.rules_problem = str(exc)
                    self.show_rules_problem()
                except OSError as exc:
                    return f"Could not write the rules file:\n{exc}"
            return f"{self.rules_problem} {SETTINGS_LEFT_ALONE}"

        def show_rules_problem(self) -> None:
            """Name a damaged rules file in the status bar for as long as the window runs."""
            problem = self.rules_problem
            self.rules_label.setVisible(bool(problem))
            if problem:
                self.rules_label.setText(
                    f"Rules not saved: {STATE_ROOT / RULES_FILE} could not be read")
                self.rules_label.setToolTip(f"{problem} {SETTINGS_LEFT_ALONE}")

        def on_entity_resized(self, column: int, _old: int, new: int) -> None:
            """Remember a width the user gave a grid column, per family."""
            header = self.entity_view.horizontalHeader()
            keys = self.entity_model.columns()
            if (self._sizing or new <= 0 or not 0 <= column < len(keys)
                    or header.sectionResizeMode(column) != QHeaderView.Interactive
                    or self.entity_view.isColumnHidden(column)):
                return
            self.entity_widths.setdefault(self.family, {})[keys[column]] = new

        def on_line_resized(self, column: int, _old: int, new: int) -> None:
            header = self.line_view.horizontalHeader()
            if (self._sizing or new <= 0 or not 0 <= column < len(EntryModel.KEYS)
                    or header.sectionResizeMode(column) != QHeaderView.Interactive):
                return
            self.line_widths[EntryModel.KEYS[column]] = new

        # ----- actions -----
        def apply_filter(self):
            """Kept for the line-view timer. The entity tab has its own filter."""
            self.apply_line_filter()

        def apply_line_filter(self):
            self.line_proxy.set_filter(
                self.line_search.text(),
                self.type_box.currentData() or "",
                self.changed_box.isChecked())
            self.refresh_status()

        def apply_entity_filter(self):
            self.entity_proxy.set_filter(self.entity_search.text(), self.section_filter,
                                         self.status_mode, self.collection_keys())
            self.settle_search()
            self.refresh_status()

        def settle_search(self) -> None:
            """After the grid is filtered: try a club alias, check other sections, and say so.

            The words typed come first. Only when they find nothing in the
            scope is a club alias tried (CLUB_ALIASES), among the clubs open.
            When the scope still shows nothing, the other sections are counted,
            and the hint offers to show them: a check, never a wider search on
            its own. Each pass is one loop over the family in Python.
            """
            proxy = self.entity_proxy
            text = self.entity_search.text().strip()
            alias = ""
            elsewhere = 0
            if proxy.words and proxy.rowCount() == 0:
                target = alias_for(text) if self.family == "club" else ""
                if target:
                    proxy.set_alias(target)
                    if proxy.rowCount():
                        alias = text
                    else:
                        proxy.set_alias("")
                if not alias and (self.section_filter or self.collection_filter):
                    rows = self.entity_model.rows
                    elsewhere = count_shown(rows, proxy.words, self.status_mode,
                                            health=self.health)
                    if not elsewhere and target:
                        elsewhere = count_shown(rows, [], self.status_mode, target,
                                                self.health)
            self.show_search_scope(alias, elsewhere)

        def search_scope(self) -> tuple[str, int]:
            """The scope the search box is limited to, and how many of the family it holds.

            ("", 0) when every section is searched.
            """
            if self.collection_filter:
                collection = self.shown_collection()
                count = collection.count_in(self.family) if collection is not None else 0
                return f"★ {self.collection_filter}", count
            if self.section_filter:
                return self.section_filter, sum(
                    1 for entity in self.entity_model.rows
                    if entity.section == self.section_filter)
            return "", 0

        def show_search_scope(self, alias: str = "", elsewhere: int = 0) -> None:
            """Show the scope beside the search box, and the alias or elsewhere hint under it."""
            scope, count = self.search_scope()
            if scope:
                label = scope_label(scope, count)
                metrics = QFontMetrics(self.scope_label.font())
                self.scope_label.setText(metrics.elidedText(label, Qt.ElideMiddle, 250))
                self.scope_label.setToolTip(
                    f"The search box searches {scope} only. Search all sections (Alt+A) "
                    "shows every section again.")
                self.search_all_btn.setText(
                    f"Search all sections ({len(self.entity_model.rows):,})")
            self.scope_label.setVisible(bool(scope))
            self.search_all_btn.setVisible(bool(scope))
            if alias:
                self.scope_hint.setText(
                    html.escape(f"Matched via alias '{alias}'", quote=False))
                self.scope_hint.setToolTip(
                    "The words typed found nothing, so a common short name for a club was "
                    "tried. It lists only clubs in the open files.")
            elif elsewhere:
                where = ("outside this collection" if self.collection_filter
                         else "in other sections")
                words = f"No matches in {scope}. Found {elsewhere:,} {where}"
                self.scope_hint.setText(
                    f'<a href="all" style="color:{THEME["focus_text"]}">'
                    f"{html.escape(words, quote=False)}</a> (Alt+A)")
                self.scope_hint.setToolTip(
                    "Click to search every file section, keeping the words typed")
            self.scope_hint.setVisible(bool(alias or elsewhere))

        def search_all_sections(self) -> None:
            """Edit > Search all sections (Alt+A): every section, no collection, same words."""
            self.tabs.setCurrentIndex(0)
            if not (self.section_filter or self.collection_filter):
                self.statusBar().showMessage("Every file section is already searched.", 5000)
                return
            self.section_filter = ""
            self.collection_filter = ""
            for widget, row in ((self.section_list, 0), (self.collection_list, -1)):
                widget.blockSignals(True)
                widget.setCurrentRow(row)
                widget.blockSignals(False)
            self.update_collection_actions()
            self.show_columns()
            self.entity_timer.stop()
            self.apply_entity_filter()

        def import_old(self):
            if not self.docs:
                QMessageBox.information(self, APP_NAME,
                                        "Open the current version's .lnc files first.")
                return
            dlg = ImportDialog(self, self.docs)
            with self.recording("import older edits") as operation:
                accepted = dlg.exec()
                if dlg.result_counts:
                    operation.label = (f"import older edits: {dlg.result_counts[0]:,} changed, "
                                       f"{dlg.result_counts[1]:,} added")
            if accepted and dlg.result_counts:
                self.reload_views()
                changed, added = dlg.result_counts
                self.statusBar().showMessage(
                    f"Imported: {changed} names changed, {added} entries added. "
                    "Nothing is written until you press Save.", 10000)

        def add_name(self) -> None:
            """Edit > Add name: name lines for an ID the open files do not mention (Session 19).

            When the family and ID are already in the open files nothing is
            added: the window says so and selects that row instead. The new
            lines go in as one operation, so one Undo takes them all back,
            with the heading. Nothing is written until Save or Deploy.
            """
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open a name file first.")
                return
            dialog = AddNameDialog(self, add_name_problem)
            if not dialog.exec():
                return
            family, id_, names, lang = dialog.values()
            kind = ENTITY_KINDS[family]
            existing = find_entity(self.all_entities, family, id_)
            if existing is not None:
                self.show_entity(entity_key(existing))
                QMessageBox.information(
                    self, APP_NAME,
                    f"{kind} {existing.id} is already in the open files, so nothing was added. "
                    "Its row is selected: type a missing name in its cell or in the inspector.")
                return
            with self.recording(f"add name: {kind.lower()} {int(id_)}"):
                added = add_entity_lines(self.docs, family, id_, names, lang)
            self.reload_views()
            self.show_entity((family, added[0].id, added[0].lang if family == "award" else ""))
            self.statusBar().showMessage(
                f"Added {count_of(len(added), 'name line', 'name lines')} for {kind.lower()} "
                f"{added[0].id} to {added[0].doc.path.name}. Nothing is written until you press "
                "Save or Deploy.", 10000)

        def show_entity(self, key: tuple) -> bool:
            """Select one entity on the Entities tab and show it in the inspector.

            ``key`` is (family, ID, language), as entity_key gives it. The
            family is switched to, and filters that hide the row are cleared,
            as the Changes tab does for All lines. False when no row has it.
            """
            self.tabs.setCurrentIndex(0)
            if key[0] != self.family:
                self.family = key[0]
                self.section_filter = ""
                for button in self.family_buttons:
                    button.setChecked(button.property("family") == self.family)
                self.apply_family()
                self.refresh_status()
            row = next((number for number, entity in enumerate(self.entity_model.rows)
                        if entity_key(entity) == key), None)
            if row is None:
                return False
            source = self.entity_model.index(row, 0)
            if not self.entity_proxy.mapFromSource(source).isValid():
                self.clear_entity_filters()     # hidden by the words, a filter, or a section
            target = self.entity_proxy.mapFromSource(source)
            self.entity_view.selectRow(target.row())
            self.entity_view.scrollTo(target, QAbstractItemView.PositionAtCenter)
            self.show_inspector(self.entity_model.rows[row])
            return True

        def clear_entity_filters(self) -> None:
            """Show every row of the family: no words, All, every file section, no collection."""
            self.entity_timer.stop()
            self.entity_search.blockSignals(True)
            self.entity_search.clear()
            self.entity_search.blockSignals(False)
            self.status_mode = "all"
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "all")
            self.section_filter = ""
            self.collection_filter = ""
            for widget, row in ((self.section_list, 0), (self.collection_list, -1)):
                widget.blockSignals(True)
                widget.setCurrentRow(row)
                widget.blockSignals(False)
            self.update_collection_actions()
            self.show_columns()
            self.apply_entity_filter()

        def revert_selected(self):
            """Restore orig_name on selected edits, as one step Undo can take back.

            Imported rows are left in place.
            """
            with self.recording("revert") as operation:
                if self.tabs.currentIndex() == 0:
                    counts = self._revert_entities()
                elif self.tabs.currentIndex() == self.CHANGES_TAB:
                    counts = self._revert_changes()
                else:
                    counts = self._revert_lines()
                operation.label = "revert: " + count_of(counts["name"], "name")
                if counts["rule"]:
                    operation.label += " and " + count_of(counts["rule"], "person rule")

        def _revert_changes(self):
            """Revert the lines selected in the Changes tab.

            A removed row, or the row for other lines, belongs to a restored
            backup as a whole and is left as it is.
            """
            rows = {self.change_proxy.mapToSource(index).row()
                    for index in self.change_view.selectionModel().selectedIndexes()}
            entries = [self.change_model.rows[row].entry for row in sorted(rows)
                       if self.change_model.rows[row].state in ("edited", "restored", "added")]
            counts = revert_entries(entries)
            self._queue_token_refresh_for_entries(entries)
            self.after_edit()
            self._revert_message(counts)
            return counts

        def _revert_lines(self):
            rows = {self.line_proxy.mapToSource(index).row()
                    for index in self.line_view.selectionModel().selectedIndexes()}
            # One refresh for the lot: a refresh per reverted line took seconds for hundreds.
            entries = [self.line_model.rows[row] for row in sorted(rows)]
            counts = revert_entries(entries)
            self._queue_token_refresh_for_entries(entries)
            self.after_edit()
            self._revert_message(counts)
            return counts

        def _revert_entities(self):
            rows = {self.entity_proxy.mapToSource(index).row()
                    for index in self.entity_view.selectionModel().selectedIndexes()}
            entries = [entry for row in sorted(rows)
                       for entry in self.entity_model.rows[row].entries()]
            counts = revert_entries(entries)
            self._queue_token_refresh_for_entries(entries)
            self.after_edit()
            self._revert_message(counts)
            return counts

        def _revert_message(self, counts: dict) -> None:
            message = f"Reverted {counts['name']} name(s)"
            if counts["rule"]:
                message += f" and {counts['rule']} person rule(s)"
            message += "."
            if counts["added"]:
                message += f" Left {counts['added']} added row(s) unchanged."
            self.statusBar().showMessage(message, 5000)

        def show_problems(self):
            show_lines(
                self, "Problem lines",
                "These lines look malformed (usually a missing or doubled quote). "
                "They are left exactly as they are when saving.",
                [f"{e.doc.path.name}  line {e.lineno}:  {e.raw}"
                 for d in self.docs for e in d.problems()],
                "No problem lines found.")

        def refresh_status(self, *_):
            self.update_selection_actions()
            total = len(self.line_model.rows)
            changed = sum(1 for entry in self.line_model.rows if entry.changed)
            changed += sum(len(doc.removed_rows) for doc in self.docs)
            dirty = any(doc.dirty for doc in self.docs)
            if changed or not dirty:
                unsaved = f"{changed:,} unsaved"
                unsaved_long = f"{changed:,} unsaved change(s)"
            else:
                unsaved = unsaved_long = "file differs from disk"
            names = ", ".join(doc.path.name for doc in self.docs) or "no files open"
            self.setWindowTitle(f"{'* ' if dirty else ''}{APP_NAME} {VERSION} - {names}")
            clubs = sum(1 for entity in self.all_entities if entity.family == "club")
            comps = sum(1 for entity in self.all_entities if entity.family == "comp")
            self.metrics.setText(f"{clubs:,} clubs    {comps:,} competitions    {unsaved}")
            self.show_health_count()
            changes = collect_changes(self.docs)
            self.tabs.setTabText(
                self.CHANGES_TAB, f"Changes ({len(changes):,})" if changes else "Changes")
            self.review_act.setText(
                f"Review changes ({len(changes):,})" if changes else "Review changes")
            self.review_act.setEnabled(dirty)
            self.pending_label.setText(pending_restores(self.docs))
            if self.tabs.currentIndex() == 0:
                shown = self.entity_proxy.rowCount()
                self.statusBar().showMessage(
                    f"{shown:,} entities shown    |    {total:,} name lines    |    "
                    "double-click a cell to edit")
            elif self.tabs.currentIndex() == self.CHANGES_TAB:
                self.show_changes(changes)
                self.statusBar().showMessage(
                    f"{len(changes):,} change(s)    |    untick a row to leave it out of the "
                    "next Save or Deploy")
            else:
                self.statusBar().showMessage(
                    f"{self.line_proxy.rowCount():,} shown of {total:,} names    |    "
                    f"{unsaved_long}    |    double-click a name to edit")

        def show_changes(self, rows=None) -> None:
            """Fill the Changes tab from the open files."""
            if rows is None:
                rows = collect_changes(self.docs)
            self.change_model.set_rows(rows)
            self.change_proxy.set_filter(self.change_search.text())
            fit_change_columns(self.change_view, self.change_model)
            self.change_summary.setText(describe_ticks(rows))

        def focus_find(self):
            box = {0: self.entity_search, self.CHANGES_TAB: self.change_search}.get(
                self.tabs.currentIndex(), self.line_search)
            box.setFocus()
            box.selectAll()

        def selected_version(self) -> Path | None:
            data = self.version_box.currentData()
            return Path(data) if data else None

        def refresh_versions(self) -> None:
            self.version_box.blockSignals(True)
            self.version_box.clear()
            chosen = None
            for path in list_version_dirs(GAME_DB_ROOT):
                has_names = version_has_names(path)
                # version_label reads <folder>_fm\<folder>_fm.xml and labels as
                # "FM27 27.0.0 (2700)", with "(no name files)" for empty folders
                # and a plain folder name for a missing or malformed XML.
                self.version_box.addItem(version_label(path), str(path))
                self.version_box.setItemData(
                    self.version_box.count() - 1, str(path), Qt.ToolTipRole)
                if has_names:
                    chosen = path
            if chosen is not None:
                index = self.version_box.findData(str(chosen))
                if index >= 0:
                    self.version_box.setCurrentIndex(index)
            self.version_box.blockSignals(False)

        def rebuild_type_filter(self) -> None:
            """Refill the type combo from the name lines and person rules in the open files.

            The current command filter is kept when that command is still present.
            Signals are blocked so refilling does not run the filter.
            """
            current = self.type_box.currentData() or ""
            self.type_box.blockSignals(True)
            self.type_box.clear()
            self.type_box.addItem("All types", "")
            commands = {entry.cmd for doc in self.docs for entry in doc.entries
                        if entry.kind in ROW_KINDS}
            for cmd in sorted(commands, key=friendly):
                self.type_box.addItem(friendly(cmd), cmd)
            restored = self.type_box.findData(current)
            self.type_box.setCurrentIndex(restored if restored >= 0 else 0)
            self.type_box.blockSignals(False)

        def reload_views(self, keep_place: bool = True) -> None:
            """Fill every view from the open files again.

            Each model is reset once, and each proxy filters once, during that
            reset. Columns are sized from their texts. With ``keep_place`` the
            entity shown in the inspector is selected again and both tables
            keep their scroll position, so adding a field does not lose it.
            """
            if self._updating:
                return
            place = self.remember_place() if keep_place else None
            self._updating = True
            try:
                self.all_entities = build_entities(self.docs)
                self.refresh_health()
                self.token_index.rebuild(self.all_entities)
                self._entry_entity = {entry: entity
                                      for entity in self.all_entities
                                      for entry in entity.entries()}
                self._pending_token_refresh = None  # the rebuild above is fresh
                self.rebuild_type_filter()
                self.line_proxy.configure(self.line_search.text(),
                                          self.type_box.currentData() or "",
                                          self.changed_box.isChecked())
                self.line_model.set_docs(self.docs)
                self.show_sort(self.line_view, self.line_model)
                self.family_group.blockSignals(True)
                for button in self.family_buttons:
                    button.setChecked(button.property("family") == self.family)
                self.family_group.blockSignals(False)
                self.apply_family()
                self._size_line_columns()
            finally:
                self._updating = False
            if place is not None:
                self.return_to_place(place)
            self.refresh_status()

        def remember_place(self) -> dict:
            entity = self.inspector_entity
            return {
                "entity": (entity.family, entity.id, entity.lang) if entity is not None else None,
                "drafts": self.inspector_drafts() if entity is not None else {},
                "entities": self.entity_view.verticalScrollBar().value(),
                "lines": self.line_view.verticalScrollBar().value(),
            }

        def return_to_place(self, place: dict) -> None:
            key = place["entity"]
            if key is not None and key[0] == self.family:
                for row, entity in enumerate(self.entity_model.rows):
                    if (entity.family, entity.id, entity.lang) == key:
                        index = self.entity_proxy.mapFromSource(self.entity_model.index(row, 0))
                        if index.isValid():
                            self.entity_view.selectRow(index.row())
                            self.show_inspector(entity)
                            self.put_drafts(place.get("drafts", {}))   # refused text stays
                        break
            self.entity_view.verticalScrollBar().setValue(place["entities"])
            self.line_view.verticalScrollBar().setValue(place["lines"])

        def show_sort(self, view: QTableView, model) -> None:
            """Show a model's sort on its header without sorting again."""
            header = view.horizontalHeader()
            column = model.sort_column()
            order = Qt.DescendingOrder if model.sort_descending else Qt.AscendingOrder
            header.blockSignals(True)
            header.setSortIndicator(column, order)
            header.blockSignals(False)

        def on_entity_sort(self, column: int, order) -> None:
            self.entity_model.sort_by(column, order == Qt.DescendingOrder)

        def on_line_sort(self, column: int, order) -> None:
            self.line_model.sort_by(column, order == Qt.DescendingOrder)

        def show_columns(self) -> None:
            """Hide File section while one section is chosen, so the names get the width,
            and the ID column when View > Show ID column is off.

            Decision 26 (Session 7) hid the ID always, since the inspector shows
            it. Session 19 revises it: the ID is how a row is matched across
            versions, so it is shown by default and the choice is remembered.
            """
            for column, key in enumerate(self.entity_model.columns()):
                hidden = ((key == "id" and not self.id_column_act.isChecked())
                          or (key == "section" and bool(self.section_filter)))
                self.entity_view.setColumnHidden(column, hidden)

        def set_id_column_shown(self, shown: bool) -> None:
            """View > Show ID column: show or hide the entity grid's ID column (Session 19)."""
            shown = bool(shown)
            if self.id_column_act.isChecked() != shown:
                self.id_column_act.setChecked(shown)
            self.show_columns()
            if shown:                           # its width, from its text, like the others
                self._sizing = True
                try:
                    self._size_entity_columns()
                finally:
                    self._sizing = False

        def _size_line_columns(self) -> None:
            rows = self.line_model.base_rows
            texts = {
                column: {entry_text(entry, key) for entry in rows}
                for column, key in enumerate(EntryModel.KEYS)
                if column != EntryModel.NAME_COL
            }
            texts[EntryModel.STATUS_COL] = {"Added", "Edited"}
            self._sizing = True                 # these widths are the program's, not the user's
            try:
                fit_columns(self.line_view, texts, {0: 240}, {EntryModel.TYPE_COL: BADGE_SPACE})
                for column, key in enumerate(EntryModel.KEYS):
                    if key in self.line_widths and column != EntryModel.NAME_COL:
                        self.line_view.setColumnWidth(column, self.line_widths[key])
            finally:
                self._sizing = False

        def apply_family(self) -> None:
            """Show the chosen family: its sections and collections, rows, columns, inspector."""
            if self._inspector_family != self.family:
                self.rebuild_inspector()
                self._inspector_family = self.family
            rows = [entity for entity in self.all_entities if entity.family == self.family]
            self.refill_sections()
            self.refill_collections()
            self.entity_proxy.configure(self.entity_search.text(), self.section_filter,
                                        self.status_mode, self.collection_keys())
            self._sizing = True
            try:
                self.entity_model.set_family_rows(self.family, rows)
                self.show_columns()
                self.show_sort(self.entity_view, self.entity_model)
                self._size_entity_columns()
            finally:
                self._sizing = False
            self.settle_search()                # the scope, and an alias, after the reset
            self.show_inspector(None)

        def _size_entity_columns(self) -> None:
            """The long name takes the width that is left; the other columns fit their text."""
            header = self.entity_view.horizontalHeader()
            columns = self.entity_model.columns()
            stretch = "long" if "long" in columns else columns[2]
            rows = self.entity_model.base_rows
            texts, caps = {}, {}
            for column, key in enumerate(columns):
                header.setSectionResizeMode(
                    column, QHeaderView.Stretch if key == stretch else QHeaderView.Interactive)
                if key == stretch:
                    continue
                if key == "status":
                    texts[column] = ({entity_status(entity, self.health) for entity in rows}
                                     | {"Added, Edited", "Check, Edited"})
                else:
                    texts[column] = {entity_text(entity, key) for entity in rows}
                caps[column] = (200 if key in ("section", "lang")
                                else 140 if key == "id" else 280)
            fit_columns(self.entity_view, texts, caps)
            for column, key in enumerate(columns):      # widths the user set win
                width = self.entity_widths.get(self.family, {}).get(key)
                if width and key != stretch:
                    self.entity_view.setColumnWidth(column, width)

        def refill_sections(self) -> None:
            rows = [entity for entity in self.all_entities if entity.family == self.family]
            counts: dict[str, int] = {}
            for entity in rows:
                counts[entity.section] = counts.get(entity.section, 0) + 1
            self.section_list.blockSignals(True)
            self.section_list.clear()
            all_item = QListWidgetItem(f"All sections ({len(rows)})")
            all_item.setData(Qt.UserRole, "")
            self.section_list.addItem(all_item)
            chosen = 0
            for section in sorted(counts, key=fold):
                item = QListWidgetItem(f"{section} ({counts[section]})")
                item.setData(Qt.UserRole, section)
                self.section_list.addItem(item)
                if section == self.section_filter:
                    chosen = self.section_list.count() - 1
            if chosen == 0:
                self.section_filter = ""
            self.section_list.setCurrentRow(chosen)
            self.section_list.blockSignals(False)
            self.filter_sections()          # the search box still applies to the new list

        def on_section(self) -> None:
            if self._updating:
                return
            item = self.section_list.currentItem()
            self.section_filter = (item.data(Qt.UserRole) if item is not None else "") or ""
            if self.collection_filter:          # a file section and a collection do not mix
                self.collection_filter = ""
                self.collection_list.blockSignals(True)
                self.collection_list.setCurrentRow(-1)
                self.collection_list.blockSignals(False)
                self.update_collection_actions()
            self.show_columns()
            self.apply_entity_filter()

        def filter_sections(self) -> None:
            """Show only the file sections whose names hold the words typed (accents ignored)."""
            words = fold(self.section_search.text()).split()
            for row in range(self.section_list.count()):
                item = self.section_list.item(row)
                section = item.data(Qt.UserRole) or ""
                item.setHidden(bool(words and section)
                               and not all(word in fold(section) for word in words))

        # ----- collections -----
        def load_collections(self) -> None:
            """Read collections.json. A damaged file is named and left alone, with
            collections off until it is put right or moved."""
            try:
                self.collections = load_collection_file(STATE_ROOT)
                self.collections_problem = ""
            except ValueError as exc:
                self.collections = CollectionFile()
                self.collections_problem = str(exc)

        def shown_collection(self):
            if not self.collection_filter:
                return None
            return self.collections.find(self.collection_filter)

        def collection_keys(self):
            collection = self.shown_collection()
            return frozenset(collection.keys) if collection is not None else None

        def refill_collections(self) -> None:
            """List the collections, each with how many of the family shown it holds."""
            self.collection_list.blockSignals(True)
            self.collection_list.clear()
            chosen = -1
            family = FAMILY_LABELS[self.family].lower()
            for collection in self.collections.collections:
                count = collection.count_in(self.family)
                item = QListWidgetItem(f"★ {collection.name} ({count:,})")
                item.setData(Qt.UserRole, collection.name)
                item.setForeground(COLOURS["focus"])
                item.setToolTip(f"Collection {collection.name}: {count:,} {family} of "
                                f"{len(collection.keys):,} in all. Collections are yours; "
                                "they are not file sections.")
                self.collection_list.addItem(item)
                if collection.name == self.collection_filter:
                    chosen = self.collection_list.count() - 1
            if chosen < 0:
                self.collection_filter = ""
            self.collection_list.setCurrentRow(chosen)
            self.collection_list.blockSignals(False)
            self.collection_list.setVisible(bool(self.collections.collections))
            if self.collections_problem:
                set_level(self.collection_hint,
                          f"{self.collections_problem} The file is left alone, and "
                          "collections are off until it is put right or moved.", "warning")
            elif not self.collections.collections:
                set_level(self.collection_hint,
                          "None yet. Select rows in the grid, then Collections > Add selected "
                          "to, or press New.", "muted")
            else:
                set_level(self.collection_hint, "", "muted")
            self.collection_hint.setVisible(bool(self.collection_hint.text()))
            self.update_collection_actions()

        def update_collection_actions(self) -> None:
            usable = not self.collections_problem
            shown = self.shown_collection() is not None
            for item in (self.new_collection_act, self.new_collection_btn,
                         self.add_to_collection_menu):
                item.setEnabled(usable)
            for action in (self.rename_collection_act, self.delete_collection_act,
                           self.remove_from_collection_act):
                action.setEnabled(usable and shown)

        def on_collection(self) -> None:
            if self._updating:
                return
            item = self.collection_list.currentItem()
            self.collection_filter = (item.data(Qt.UserRole) if item is not None else "") or ""
            if self.collection_filter:          # a collection replaces the file section
                self.section_filter = ""
                self.section_list.blockSignals(True)
                self.section_list.setCurrentRow(0)
                self.section_list.blockSignals(False)
            self.update_collection_actions()
            self.show_columns()
            self.apply_entity_filter()

        def selected_entities(self) -> list[NameEntity]:
            rows = {self.entity_proxy.mapToSource(self.entity_proxy.index(row, 0)).row()
                    for row in self.selected_entity_rows()}
            return [self.entity_model.rows[row] for row in sorted(rows)]

        def selected_entity_rows(self) -> list[int]:
            """Read row ranges without asking Qt to check every selected cell's flags."""
            return sorted({row for block in self.entity_view.selectionModel().selection()
                           for row in range(block.top(), block.bottom() + 1)})

        def select_entities_matching(self, predicate) -> int:
            """Replace the selection with matching visible entities in one update."""
            self.tabs.setCurrentIndex(0)
            selection = QItemSelection()
            first = last = None
            count = 0
            columns = self.entity_proxy.columnCount()
            for row in range(self.entity_proxy.rowCount()):
                index = self.entity_proxy.index(row, 0)
                source = self.entity_proxy.mapToSource(index)
                if predicate(self.entity_model.rows[source.row()]):
                    count += 1
                    if first is None:
                        first = row
                    last = row
                elif first is not None:
                    selection.select(self.entity_proxy.index(first, 0),
                                     self.entity_proxy.index(last, columns - 1))
                    first = last = None
            if first is not None:
                selection.select(self.entity_proxy.index(first, 0),
                                 self.entity_proxy.index(last, columns - 1))
            model = self.entity_view.selectionModel()
            model.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            if not selection.isEmpty():
                model.setCurrentIndex(selection.first().topLeft(), QItemSelectionModel.NoUpdate)
            else:
                model.setCurrentIndex(QModelIndex(), QItemSelectionModel.NoUpdate)
            self.update_selection_actions()
            self.statusBar().showMessage(
                f"Selected {count_of(count, 'visible entity', 'visible entities')}. "
                "Existing filters are kept.", 8000)
            return count

        def select_entities_by_token(self, token: str, case_sensitive: bool = False) -> int:
            return self.select_entities_matching(
                lambda entity: entity_matches_token(entity, token, case_sensitive))

        def select_by_pattern(self, pattern: str, regex: bool = False) -> int:
            if not pattern.strip():
                raise ValueError("Enter a name pattern first.")
            try:
                compiled = re.compile(pattern if regex else fnmatch.translate(pattern), re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid regular expression: {exc}") from exc
            return self.select_entities_matching(
                lambda entity: any(compiled.search(entry.name)
                                   for slot in TEXT_SLOTS
                                   for entry in entity.slots.get(slot, ())))

        def prompt_selection(self, pattern: bool = False) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Select by name pattern" if pattern else "Select matching word")
            layout = QVBoxLayout(dialog)
            hint = ("Wildcards match a whole name: *United* or Manchester ?. "
                    "Regular expressions search within names." if pattern else
                    "Match a whole word in long or short names.")
            label = QLabel(hint + " Only visible rows are selected.")
            label.setWordWrap(True)
            layout.addWidget(label)
            text = QLineEdit()
            layout.addWidget(text)
            regex = QCheckBox("Regular expression")
            regex.setVisible(pattern)
            layout.addWidget(regex)
            problem = QLabel()
            problem.setObjectName("warning")
            problem.setWordWrap(True)
            layout.addWidget(problem)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText("Select")
            layout.addWidget(buttons)

            def choose():
                try:
                    if not text.text().strip():
                        raise ValueError("Enter a word or pattern first.")
                    if pattern:
                        self.select_by_pattern(text.text(), regex.isChecked())
                    else:
                        self.select_entities_by_token(text.text().strip())
                except ValueError as exc:
                    problem.setText(str(exc))
                    return
                dialog.accept()

            buttons.accepted.connect(choose)
            buttons.rejected.connect(dialog.reject)
            dialog.resize(520, 200)
            text.setFocus()
            dialog.exec()

        def prompt_select_word(self) -> None:
            self.prompt_selection()

        def prompt_select_pattern(self) -> None:
            self.prompt_selection(True)

        def select_same_section(self) -> int:
            index = self.entity_view.currentIndex()
            source = self.entity_proxy.mapToSource(index)
            entity = (self.entity_model.rows[source.row()] if source.isValid()
                      else self.inspector_entity)
            if entity is None:
                return 0
            return self.select_entities_matching(lambda candidate: candidate.section == entity.section)

        def invert_entity_selection(self) -> int:
            chosen = {entity_key(entity) for entity in self.selected_entities()}
            return self.select_entities_matching(lambda entity: entity_key(entity) not in chosen)

        def clear_entity_selection(self) -> None:
            self.entity_view.clearSelection()
            self.update_selection_actions()

        def update_selection_actions(self) -> None:
            if not hasattr(self, "selection_pill"):
                return
            count = len(self.selected_entity_rows())
            available = count > 0 and self.entity_view.isEnabled()
            self.batch_rename_act.setEnabled(available)
            self.selection_pill.setVisible(count > 1 and self.tabs.currentIndex() == 0)
            family = {"club": ("club", "clubs"), "comp": ("competition", "competitions")}
            noun, plural = family.get(self.family, ("entity", "entities"))
            self.selection_pill.setText(
                f"{count_of(count, noun, plural)} selected | Batch rename (Ctrl+B)")

        def open_batch_rename(self, entities=None, initial_token: str = "",
                              replacement: str = "", regex: bool = False) -> None:
            if not self.entity_view.isEnabled():
                return
            entities = self.selected_entities() if entities is None else list(entities)
            if not entities:
                self.statusBar().showMessage("Select one or more entity rows first.", 6000)
                return
            suggestion = None
            # Pick up a suggestion from the selection when the caller did not
            # pass one of its own (Harmonise, saved search, etc. still win).
            # Built-in presets win first; pinned pairs are consulted next so
            # a word like "Rovers" can suggest "Rvrs" after the user pins it.
            if (not initial_token and not replacement and not regex
                    and len(entities) >= 2):
                fold, count, total = suggest_batch_token(entities, self.token_index)
                if fold and count >= 2:
                    basis = self.token_index.display_for(fold)
                    preset = find_batch_preset_for_token(basis)
                    pinned = (None if preset is not None
                              else find_pinned_pair_for_token(basis, self.rules.pinned_pairs))
                    if preset is not None:
                        initial_token, replacement = preset
                    elif pinned is not None:
                        initial_token, replacement = pinned
                    else:
                        initial_token = basis
                    suggestion = (basis, count, total, initial_token, replacement)
            dialog = BatchRenameDialog(self, entities, self.docs, initial_token, replacement,
                                       regex, suggestion=suggestion,
                                       pinned_pairs=tuple(self.rules.pinned_pairs))
            if not dialog.exec():
                return
            try:
                with self.recording("batch rename") as operation:
                    applied = dialog.apply_edits()
                    operation.label = f"batch rename: {count_of(applied, 'name')} ({dialog.description})"
            except ValueError as exc:
                QMessageBox.warning(self, APP_NAME, str(exc))
                return
            if applied:
                changed_entities = len({entity_key(edit.entity) for edit in dialog.edits
                                        if edit.included and edit.before != edit.after})
                self.reload_views()
                self.statusBar().showMessage(
                    f"Batch rename: updated {count_of(changed_entities, 'entity', 'entities')} "
                    f"({count_of(applied, 'name')}; {dialog.description}). "
                    "Nothing is written until Save or Deploy.", 12000)

        def open_harmoniser(self) -> None:
            entities = [entity for entity in self.all_entities if entity.family == "club"]
            if not entities:
                self.statusBar().showMessage("Open club name files first.", 6000)
                return
            dialog = HarmoniseDialog(self, entities,
                                     pinned_pairs=tuple(self.rules.pinned_pairs))
            if dialog.exec() and dialog.choice is not None:
                source, target, chosen, regex = dialog.choice
                self.open_batch_rename(chosen, source, target, regex)

        # ----- pinned spelling pairs (Session 17) -----
        def pin_pair_requested(self, full: str, short: str, source=None) -> bool:
            """Add a pair to ``state/rules.json``; returns True on success.

            Validation lives in ``Rules.add_pinned_pair`` (whole-word on each
            side, no duplicate of a built-in or existing pin). A damaged
            rules file blocks the write; ``keep_rules`` names it, and no
            rules are written for the rest of the run (decision 38 / 56).
            Save and Deploy never touch the list (brief acceptance).
            """
            holder = source if source is not None else self
            try:
                self.rules.add_pinned_pair(full, short)
            except ValueError as exc:
                QMessageBox.warning(holder, APP_NAME,
                                    f"That pair cannot be pinned.\n\n{exc}")
                return False
            problem = self.keep_rules(self.rules)
            if problem:
                self.rules.remove_pinned_pair(full, short)
                QMessageBox.warning(holder, APP_NAME,
                                    f"The pinned pair was not saved.\n\n{problem}")
                return False
            self.statusBar().showMessage(
                f"Pinned {full} ↔ {short}. Harmonise and Select similar now know about it.",
                8000)
            return True

        def pin_new_pair_via_dialog(self, source) -> bool:
            """Open the pair-input dialog and pin the result. Returns True on success.

            The caller refreshes its own view when True comes back.
            """
            def check(full: str, short: str) -> str:
                return pinned_pair_problem(full, short, self.rules.pinned_pairs)

            dialog = PinPairDialog(source, check)
            if not dialog.exec():
                return False
            full, short = dialog.values()
            return self.pin_pair_requested(full, short, source=source)

        def delete_pinned_pair(self, full: str, short: str, source=None) -> bool:
            """Remove a pinned pair from ``state/rules.json``. Never renames a club."""
            holder = source if source is not None else self
            if not self.rules.remove_pinned_pair(full, short):
                return False
            problem = self.keep_rules(self.rules)
            if problem:
                # Put the pair back so disk and memory stay in step.
                try:
                    self.rules.add_pinned_pair(full, short)
                except ValueError:
                    pass
                QMessageBox.warning(holder, APP_NAME,
                                    f"The pinned pair was not removed.\n\n{problem}")
                return False
            self.statusBar().showMessage(
                f"Deleted the pinned pair {full} ↔ {short}. No club was renamed.",
                8000)
            return True

        def palette_commands(self) -> list:
            commands = []

            def add_menu(menu, path):
                for action in menu.actions():
                    if action.isSeparator() or not action.text():
                        continue
                    label = action.text().replace("&", "")
                    if action.menu() is not None:
                        add_menu(action.menu(), f"{path} > {label}")
                    elif action is not self.palette_act:
                        keys = " / ".join(key.toString(QKeySequence.NativeText)
                                          for key in action.shortcuts())
                        commands.append((f"{path} > {label}", keys, action.trigger,
                                         action.isEnabled()))

            self.fill_add_to_menu()
            self.fill_snapshot_menu()
            for menu in self.menus:
                add_menu(menu, menu.title().replace("&", ""))
            for search in self.saved_searches:
                commands.append((f"Saved search > {search.name}", "",
                                 lambda item=search: self.apply_saved_search(item), True))
            for collection in self.collections.collections:
                commands.append((f"Collection > {collection.name}", "",
                                 lambda name=collection.name: self.show_palette_collection(name), True))
            return commands

        def show_palette_collection(self, name: str) -> None:
            self.tabs.setCurrentIndex(0)
            for row in range(self.collection_list.count()):
                item = self.collection_list.item(row)
                if item.data(Qt.UserRole) == name:
                    self.collection_list.setCurrentItem(item)
                    break

        def open_command_palette(self) -> None:
            dialog = CommandPaletteDialog(self, self.palette_commands())
            if dialog.exec() and dialog.chosen is not None:
                dialog.chosen()

        def store_collections(self, done: str) -> bool:
            """Write collections.json and show the result. A failed write puts the
            collections back as the file has them."""
            try:
                save_collection_file(self.collections, STATE_ROOT)
            except OSError as exc:
                QMessageBox.critical(
                    self, APP_NAME,
                    f"Could not write the collections file:\n{exc}\n\nNothing was changed.")
                self.load_collections()
                done = ""
            self.refill_collections()
            self.apply_entity_filter()
            if done:
                self.statusBar().showMessage(done, 8000)
            return bool(done)

        def fill_add_to_menu(self) -> None:
            menu = self.add_to_collection_menu
            menu.clear()
            chosen = bool(self.selected_entities())
            for collection in self.collections.collections:
                action = menu.addAction(collection.name)
                action.setEnabled(chosen)
                action.triggered.connect(
                    lambda _checked=False, name=collection.name: self.add_selected_to(name))
            if self.collections.collections:
                menu.addSeparator()
            new = menu.addAction("New collection with the selection...")
            new.setEnabled(chosen)
            new.triggered.connect(lambda _checked=False: self.new_collection(True))

        def add_selected_to(self, name: str) -> None:
            collection = self.collections.find(name)
            entities = self.selected_entities()
            if collection is None or not entities or self.collections_problem:
                return
            added = collection.add(entity_key(entity) for entity in entities)
            if not added:
                self.statusBar().showMessage(
                    f"The selected rows are in {collection.name} already.", 6000)
                return
            self.store_collections(
                f"Added {added:,} to {collection.name}, which now holds "
                f"{len(collection.keys):,}.")

        def remove_selected_from_collection(self) -> None:
            collection = self.shown_collection()
            entities = self.selected_entities()
            if collection is None or not entities or self.collections_problem:
                return
            removed = collection.remove(entity_key(entity) for entity in entities)
            self.store_collections(
                f"Took {removed:,} out of {collection.name}, which now holds "
                f"{len(collection.keys):,}. The names are not changed.")

        def new_collection(self, with_selection: bool = False) -> bool:
            if self.collections_problem:
                return False
            dialog = ProfileDialog(
                self, "New collection",
                lambda name: collection_name_problem(name, self.collections), note=None)
            if not dialog.exec():
                return False
            name, _note = dialog.values()
            collection = Collection(name)
            if with_selection:
                collection.add(entity_key(entity) for entity in self.selected_entities())
            self.collections.add(collection)
            return self.store_collections(
                f"Made the collection {collection.name}, holding {len(collection.keys):,}.")

        def rename_collection(self) -> None:
            collection = self.shown_collection()
            if collection is None or self.collections_problem:
                return
            old = collection.name
            dialog = ProfileDialog(
                self, "Rename collection",
                lambda name: collection_name_problem(name, self.collections, own=collection),
                old, note=None)
            if not dialog.exec():
                return
            collection.name = dialog.values()[0]
            self.collections.collections.sort(key=lambda item: fold(item.name))
            self.collection_filter = collection.name
            if (self.store_collections(f"Renamed the collection {old} to {collection.name}.")
                    and any(search.collection == old for search in self.saved_searches)):
                searches = []
                for search in self.saved_searches:     # saved searches follow the new name
                    kept = SavedSearch(search.name, *(getattr(search, field)
                                                      for field in SavedSearch.FIELDS))
                    if kept.collection == old:
                        kept.collection = collection.name
                    searches.append(kept)
                self.store_searches(searches, "")

        def delete_collection(self) -> None:
            collection = self.shown_collection()
            if collection is None or self.collections_problem:
                return
            answer = QMessageBox.question(
                self, APP_NAME,
                f"Delete the collection {collection.name} ({len(collection.keys):,} in all)?"
                f"\n\nIt is kept under \"deleted\" in {STATE_ROOT / COLLECTIONS_FILE}, so it "
                "can be recovered by hand. The name files are not changed.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self.collections.delete(collection)
            self.collection_filter = ""
            self.store_collections(f"Deleted the collection {collection.name}.")

        def grid_menu(self) -> QMenu:
            """Build contextual name selection and editing actions without opening it."""
            menu = QMenu(self)
            index = self.entity_view.currentIndex()
            source = self.entity_proxy.mapToSource(index)
            entity = (self.entity_model.rows[source.row()] if source.isValid()
                      else self.inspector_entity)
            selected = self.selected_entities()
            visible = self.visible_entities()
            similar = QMenu("Select similar names", menu)
            shown_folds: set[str] = set()
            family = (entity.family if entity is not None
                      else (selected[0].family if selected else self.family))
            visible_keys = ({entity_key(item) for item in visible}
                            if len(visible) < len(self.entity_model.rows) else None)
            selected_keys = {entity_key(item) for item in selected}

            def add_item(fold: str, display: str, shared_count: int = 0) -> bool:
                if fold in shown_folds:
                    return False
                matches = self.token_index.entities_with(family, fold)
                total = len(matches)
                if total < 2:
                    return False
                # A word that matches only rows already selected adds no new row.
                if selected and matches.issubset(selected_keys):
                    return False
                visible_count = (total if visible_keys is None
                                 else sum(1 for key in matches if key in visible_keys))
                if shared_count >= 2:
                    scope = f"{shared_count} of {len(selected)} selected, "
                    scope += (f"{total} entities total" if visible_count == total
                              else f"{visible_count} shown of {total}")
                else:
                    scope = (f"{total} entities" if visible_count == total
                             else f"{total} entities; {visible_count} shown")
                action = similar.addAction(f"Select all containing '{display}' ({scope})")
                action.setEnabled(visible_count > 0)
                action.setToolTip("Select matching whole words in visible long or short names")
                action.triggered.connect(
                    lambda _checked=False, word=display: self.select_entities_by_token(word))
                shown_folds.add(fold)
                return True

            # When 2+ rows are selected, lead with the words they share.
            if len(selected) >= 2:
                for fold, selected_count in shared_entity_tokens(selected, self.token_index):
                    display = self.token_index.display_for(fold)
                    add_item(fold, display, selected_count)

            # Then the cursor row's own words, skipping any already shown above.
            if entity is not None:
                for token in extract_name_tokens(
                        " ".join(entity.name_in(slot) for slot in TEXT_SLOTS)):
                    add_item(token.casefold(), token)

            # Pinned pairs: when the context contains one side, offer the
            # other form as an "Also select" item. The user chooses it; the
            # menu never adds it to the selection on its own (brief).
            def add_pinned_other(fold: str, display: str,
                                 label_prefix: str = "") -> bool:
                if fold in shown_folds:
                    return False
                matches = self.token_index.entities_with(family, fold)
                total = len(matches)
                if total < 1:
                    return False
                visible_count = (total if visible_keys is None
                                 else sum(1 for key in matches if key in visible_keys))
                scope = (f"{total} entities" if visible_count == total
                         else f"{total} entities; {visible_count} shown")
                action = similar.addAction(
                    f"{label_prefix}'{display}' ({scope})")
                action.setEnabled(visible_count > 0)
                action.setToolTip(
                    "Pinned pair: select the other form in visible names")
                action.triggered.connect(
                    lambda _checked=False, word=display: self.select_entities_by_token(word))
                shown_folds.add(fold)
                return True

            context_entities = selected if selected else (
                [entity] if entity is not None else [])
            if context_entities:
                for full, short in getattr(self.rules, "pinned_pairs", ()) or ():
                    for side, other in ((full, short), (short, full)):
                        if any(entity_matches_token(e, side) for e in context_entities):
                            add_pinned_other(other.casefold(), other,
                                             label_prefix="Also select the other form: ")
                            break        # one offer per pair, not both

            if not similar.isEmpty():
                menu.addMenu(similar)
            menu.addAction(self.batch_rename_act)
            count = len(self.selected_entities())
            self.fill_add_to_menu()
            collections = menu.addMenu(f"Add selection to collection ({count})")
            collections.addActions(self.add_to_collection_menu.actions())
            menu.addAction(self.remove_from_collection_act)
            menu.addSeparator()
            menu.addAction(self.edit_cell_act)
            menu.addAction(self.revert_act)
            menu.addSeparator()
            menu.addAction(self.overrides_act)
            return menu

        def show_grid_menu(self, point) -> None:
            index = self.entity_view.indexAt(point)
            if index.isValid():
                selection = self.entity_view.selectionModel()
                if not selection.isRowSelected(index.row(), QModelIndex()):
                    selection.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
            self.grid_menu().exec(self.entity_view.viewport().mapToGlobal(point))

        def show_overrides(self) -> None:
            """Open the cross-file override inspector for the selected entity.

            The scan runs on ``self.jobs``, so a folder with many ``.lnc``
            files does not freeze the window; the dialog fills in when it is
            done. Shown from the grid's right-click menu.
            """
            rows = self.selected_entities()
            if not rows:
                rows = [self.inspector_entity] if self.inspector_entity is not None else []
            if not rows:
                QMessageBox.information(
                    self, APP_NAME,
                    "Select a row on the Entities tab first.")
                return
            version = self.selected_version()
            if version is None or not version.is_dir():
                QMessageBox.warning(
                    self, APP_NAME,
                    f"No database folder was found under\n{GAME_DB_ROOT}")
                return
            OverrideDialog(self, rows[0], version).exec()

        # ----- saved searches -----
        def describe_search(self, search: SavedSearch) -> str:
            parts = [FAMILY_LABELS[search.family]]
            if search.text:
                parts.append(f"words: {search.text}")
            if search.status != "all":
                parts.append(f"filter: {STATUS_FILTERS[search.status]}")
            if search.collection:
                parts.append(f"collection: {search.collection}")
            elif search.section:
                parts.append(f"file section: {search.section}")
            return "; ".join(parts)

        def fill_searches_menu(self) -> None:
            menu = self.searches_menu
            menu.clear()
            menu.setToolTipsVisible(True)
            for search in self.saved_searches:
                action = menu.addAction(search.name)
                action.setToolTip(self.describe_search(search))
                action.triggered.connect(
                    lambda _checked=False, chosen=search: self.apply_saved_search(chosen))
            if self.saved_searches:
                menu.addSeparator()
            keep = menu.addAction("Save this search...")
            keep.triggered.connect(lambda _checked=False: self.save_search())
            if self.saved_searches:
                forget = menu.addMenu("Delete a saved search")
                for search in self.saved_searches:
                    action = forget.addAction(search.name)
                    action.triggered.connect(
                        lambda _checked=False, chosen=search: self.delete_saved_search(chosen))

        def store_searches(self, searches: list, done: str) -> bool:
            state = dict(self.state)
            state["saved_searches"] = [search.to_json() for search in searches]
            problem = self.keep_settings(state)
            if problem:
                QMessageBox.warning(self, APP_NAME,
                                    f"The saved searches were not changed.\n\n{problem}")
                return False
            self.state = state
            self.saved_searches = searches
            if done:
                self.statusBar().showMessage(done, 8000)
            return True

        def save_search(self) -> None:
            dialog = ProfileDialog(
                self, "Save this search",
                lambda name: label_problem(name, self.saved_searches, None, "saved search"),
                note=None)
            if not dialog.exec():
                return
            search = SavedSearch(dialog.values()[0], self.family,
                                 self.entity_search.text().strip(), self.status_mode,
                                 self.section_filter, self.collection_filter)
            self.store_searches([*self.saved_searches, search],
                                f"Saved the search {search.name}: {self.describe_search(search)}.")

        def delete_saved_search(self, search: SavedSearch) -> None:
            answer = QMessageBox.question(
                self, APP_NAME, f"Delete the saved search {search.name}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.store_searches([s for s in self.saved_searches if s is not search],
                                    f"Deleted the saved search {search.name}.")

        def apply_saved_search(self, search: SavedSearch) -> None:
            """Show a saved search: its family, filter, words, and file section or collection."""
            self.collection_filter = (search.collection
                                      if self.collections.find(search.collection) else "")
            self.section_filter = "" if self.collection_filter else search.section
            if search.family != self.family:
                self.family = search.family
                for button in self.family_buttons:
                    button.setChecked(button.property("family") == self.family)
            self.status_mode = search.status
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == self.status_mode)
            self.entity_search.blockSignals(True)
            self.entity_search.setText(search.text)
            self.entity_search.blockSignals(False)
            self.entity_timer.stop()
            self.apply_family()             # sections, collections, rows, and the filter
            self.refresh_status()
            missing = search.section and search.section != self.section_filter
            self.statusBar().showMessage(
                f"{search.name}: {self.entity_proxy.rowCount():,} shown."
                + (f" The file section {search.section} is not in the open files."
                   if missing else ""), 8000)

        def on_family_clicked(self, button) -> None:
            if self._updating:
                return
            self.family = button.property("family")
            self.section_filter = ""
            self.apply_family()
            self.refresh_status()

        def on_status_clicked(self, button) -> None:
            self.status_mode = button.property("mode")
            self.apply_entity_filter()

        def on_entity_selection(self) -> None:
            self.update_selection_actions()
            if self._updating or self._filling:
                return
            rows = self.selected_entity_rows()
            if not rows:
                self.show_inspector(None)
                return
            source = self.entity_proxy.mapToSource(self.entity_proxy.index(rows[0], 0))
            if not source.isValid():
                return
            self.show_inspector(self.entity_model.rows[source.row()])

        def on_entity_data(self, *_args) -> None:
            structure = self.entity_model._structure
            self.entity_model._structure = False
            if structure:
                QTimer.singleShot(0, self.reload_views)
                return
            self.after_edit()

        def on_line_data(self, *_args) -> None:
            self.after_edit()

        # ----- the inspector -----
        def rebuild_inspector(self) -> None:
            """Lay out the inspector for the chosen family: a heading, then one block per field.

            Each block shows the field's change marker, its text on disk above
            the proposed text (so a spelling can be compared letter by letter),
            the file and line, and a message when the typed text cannot be used.
            """
            while self.inspector_lay.count():
                item = self.inspector_lay.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.hide()           # deleteLater waits for the event loop; hide now
                    widget.deleteLater()
            self.inspector_edits = {}
            self.inspector_fields = {}
            self.inspector_title = QLabel("Select a row")
            self.inspector_title.setObjectName("title")
            self.inspector_title.setWordWrap(True)
            self.inspector_lay.addWidget(self.inspector_title)
            self.inspector_meta = QLabel("")
            self.inspector_meta.setObjectName("muted")
            self.inspector_meta.setWordWrap(True)
            self.inspector_meta.setToolTip(FILE_SECTION_HINT)
            self.inspector_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.inspector_lay.addWidget(self.inspector_meta)
            # Session 21: what Name health found in this entity's names, and the fix.
            self.health_box = QWidget()
            health_lay = QVBoxLayout(self.health_box)
            health_lay.setContentsMargins(0, 4, 0, 4)
            self.inspector_health = QLabel("")
            self.inspector_health.setObjectName("warning")
            self.inspector_health.setWordWrap(True)
            self.inspector_health.setTextInteractionFlags(Qt.TextSelectableByMouse)
            health_lay.addWidget(self.inspector_health)
            self.inspector_fix = QPushButton("Fix formatting")
            self.inspector_fix.setObjectName("small")
            self.inspector_fix.setToolTip(self.fix_formatting_act.toolTip())
            self.inspector_fix.clicked.connect(
                lambda _checked=False: self.fix_formatting_selected())
            health_lay.addWidget(self.inspector_fix, 0, Qt.AlignLeft)
            self.health_box.hide()
            self.inspector_lay.addWidget(self.health_box)
            for slot, label, _cmd in FAMILY_FIELDS[self.family]:
                rule = QFrame()
                rule.setObjectName("rule")
                rule.setFrameShape(QFrame.HLine)
                self.inspector_lay.addWidget(rule)
                block = QWidget()
                grid = QGridLayout(block)
                grid.setContentsMargins(0, 2, 0, 2)
                grid.setHorizontalSpacing(8)
                grid.setVerticalSpacing(3)
                grid.setColumnStretch(1, 1)
                top = QHBoxLayout()
                caption = QLabel(label)
                caption.setObjectName("heading")
                marker = QLabel("")
                marker.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                top.addWidget(caption)
                top.addStretch(1)
                top.addWidget(marker)
                grid.addLayout(top, 0, 0, 1, 2)
                disk_caption = QLabel("On disk")
                disk_caption.setObjectName("muted")
                disk = QLabel("")
                disk.setWordWrap(True)
                disk.setTextInteractionFlags(Qt.TextSelectableByMouse)
                grid.addWidget(disk_caption, 1, 0)
                grid.addWidget(disk, 1, 1)
                proposed = QLabel("Proposed")
                proposed.setObjectName("muted")
                edit = InspectorEdit()
                edit.editingFinished.connect(
                    lambda slot=slot, edit=edit: self.commit_inspector(slot, edit))
                edit.textEdited.connect(lambda _text, slot=slot: self.check_field(slot))
                edit.escaped.connect(lambda slot=slot: self.put_back_field(slot))
                edit.step.connect(lambda step, slot=slot: self.step_inspector(slot, step))
                grid.addWidget(proposed, 2, 0)
                grid.addWidget(edit, 2, 1)
                # Session 20: the length against its typical guide; a warning only.
                gauge = QLabel("")
                gauge.setObjectName("muted")
                gauge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                edit.textChanged.connect(lambda _text, slot=slot: self.update_gauge(slot))
                grid.addWidget(gauge, 3, 1)
                gauge.setHidden(not length_guide(self.family, slot))
                where = QLabel("")
                where.setObjectName("muted")
                where.setWordWrap(True)
                grid.addWidget(where, 4, 1)
                # Session 14: the line as it stands in memory, command and all.
                raw = QLabel("")
                raw.setObjectName("raw")
                raw.setWordWrap(True)
                raw.setTextInteractionFlags(Qt.TextSelectableByMouse)
                raw.setToolTip("The line as it stands in memory, as Save would write it. "
                               "Tabs between the fields are shown as wide spaces.")
                grid.addWidget(raw, 5, 1)
                problem = QLabel("")
                problem.setObjectName("warning")
                problem.setWordWrap(True)
                problem.hide()
                grid.addWidget(problem, 6, 0, 1, 2)
                # Session 13: the review hint. Local list of suspicious baselines
                # such as "Wolverhamption"; shown, never applied.
                hint = QLabel("")
                hint.setObjectName("warning")
                hint.setWordWrap(True)
                hint.hide()
                grid.addWidget(hint, 7, 0, 1, 2)
                self.inspector_lay.addWidget(block)
                self.inspector_edits[slot] = edit
                self.inspector_fields[slot] = {"marker": marker, "disk": disk, "edit": edit,
                                               "gauge": gauge, "where": where, "raw": raw,
                                               "problem": problem, "hint": hint}

            # Session 21: a short name and code suggested from the long name, for a club
            # missing either. Shown first; Use suggestion adds them as one Undo step.
            self.suggestion_box = QWidget()
            suggestion_lay = QVBoxLayout(self.suggestion_box)
            suggestion_lay.setContentsMargins(0, 4, 0, 4)
            self.inspector_suggestion = QLabel("")
            self.inspector_suggestion.setObjectName("muted")
            self.inspector_suggestion.setWordWrap(True)
            suggestion_lay.addWidget(self.inspector_suggestion)
            self.inspector_use = QPushButton("Use suggestion")
            self.inspector_use.setObjectName("small")
            self.inspector_use.setToolTip(self.fill_siblings_act.toolTip() + " (Ctrl+Alt+D)")
            self.inspector_use.clicked.connect(lambda _checked=False: self.fill_short_and_code())
            suggestion_lay.addWidget(self.inspector_use, 0, Qt.AlignLeft)
            self.suggestion_box.hide()
            self.inspector_lay.addWidget(self.suggestion_box)

            # Illustrative preview card (Session 18)
            self.illustrative_card = IllustrativePreviewCard(self)
            self.inspector_lay.addWidget(self.illustrative_card)

            self.inspector_revert = QPushButton("Revert")
            self.inspector_revert.setToolTip(
                "Put the selected rows' lines back to the text on disk. Added lines stay.")
            self.inspector_revert.clicked.connect(self.revert_selected)
            self.inspector_lay.addWidget(self.inspector_revert)
            self.inspector_lay.addStretch(1)

        def show_inspector(self, entity) -> None:
            """Fill the inspector from an entity, or empty it for None.

            Shown again for the same entity (after an edit to another field or an
            undo), a field holding text that cannot be used keeps that text and
            its message; the rest is brought up to date. Only Esc, a commit of
            that field, or choosing another entity clears it (note 05, finding 6).
            """
            same = (entity is not None and self.inspector_entity is not None
                    and entity_key(entity) == entity_key(self.inspector_entity))
            drafts = self.inspector_drafts() if same else {}
            self._filling = True
            self.inspector_entity = entity
            try:
                if not self.inspector_fields:
                    return
                if entity is None:
                    self.inspector_title.setText("Select a row")
                    self.inspector_meta.setText(
                        "Its fields show here: the text on disk, the proposed text, and "
                        "the file and line.")
                    for widgets in self.inspector_fields.values():
                        for name in ("marker", "disk", "where", "raw", "gauge"):
                            widgets[name].setText("")
                        edit = widgets["edit"]
                        edit.blockSignals(True)
                        edit.clear()
                        edit.setPlaceholderText("")
                        edit.blockSignals(False)
                        edit.setEnabled(False)
                        self.show_field_problem(widgets, "")
                        widgets["hint"].setText("")
                        widgets["hint"].hide()
                    self.show_entity_health(None)
                    if hasattr(self, "illustrative_card"):
                        self.illustrative_card.update_from_entity(None)
                    self.inspector_revert.setEnabled(False)
                    return
                language = entity.lang or next(
                    (entry.lang for entry in entity.entries() if entry.lang), "")
                self.inspector_title.setText(
                    next((entity.name_in(slot) for slot, _label, _cmd
                          in FAMILY_FIELDS[entity.family] if entity.name_in(slot)), ""))
                self.inspector_meta.setText(
                    f"{ENTITY_KINDS[entity.family]}    ID {entity.id}\n"
                    f"File section: {entity.section or 'none'}\n"
                    f"Language: {language or 'none'}")
                for view in describe_fields(entity):
                    widgets = self.inspector_fields[view.slot]
                    if view.state == "none":
                        marker, level = no_override_text(entity.family, view.slot), "muted"
                    else:
                        marker = view.marker
                        level = {"edited": "edited", "added": "added"}.get(view.state, "muted")
                        if view.count > 1:
                            level = "warning"       # a repeated key: worded and coloured
                    set_level(widgets["marker"], marker, level)
                    if view.on_disk is None:
                        set_level(widgets["disk"],
                                  "No line yet" if view.state == "added" else "No line", "muted")
                    else:
                        set_level(widgets["disk"], view.on_disk, "")
                    edit = widgets["edit"]
                    draft = drafts.get(view.slot)
                    edit.blockSignals(True)
                    if draft is None:
                        edit.setText(view.current)
                    edit.setPlaceholderText(
                        "Type a name to add one" if view.state == "none" else "")
                    edit.blockSignals(False)
                    edit.setEnabled(True)
                    self.update_gauge(view.slot)
                    widgets["where"].setText(view.where)
                    widgets["raw"].setText(view.raw.replace("\t", "    "))
                    self.show_field_problem(widgets, draft[1] if draft else "")
                    widgets["hint"].setText(view.hint)
                    widgets["hint"].setVisible(bool(view.hint))
                self.show_entity_health(entity)
                # Update illustrative preview card (Session 18)
                if hasattr(self, "illustrative_card"):
                    self.illustrative_card.update_from_entity(entity)
                self.inspector_revert.setEnabled(entity.changed())
            finally:
                self._filling = False

        def inspector_drafts(self) -> dict:
            """The fields holding text that cannot be used: slot -> (text, message)."""
            return {slot: (widgets["edit"].text(), widgets["problem"].text())
                    for slot, widgets in self.inspector_fields.items()
                    if widgets["edit"].objectName() == "invalid"}

        def put_drafts(self, drafts: dict) -> None:
            """Show refused texts in their fields again, each with its message."""
            for slot, (text, problem) in drafts.items():
                widgets = self.inspector_fields.get(slot)
                if widgets is None:
                    continue
                edit = widgets["edit"]
                edit.blockSignals(True)
                edit.setText(text)
                edit.blockSignals(False)
                self.show_field_problem(widgets, problem)
                self.update_gauge(slot)

        def show_field_problem(self, widgets: dict, problem: str) -> None:
            """Show, or clear, the message under one inspector field."""
            widgets["problem"].setText(problem)
            widgets["problem"].setVisible(bool(problem))
            restyle(widgets["edit"], "invalid" if problem else "")

        def check_field(self, slot: str) -> None:
            """While typing: say at once when the text cannot be a name (emptiness waits for Enter)."""
            widgets = self.inspector_fields.get(slot)
            if widgets is None:
                return
            text = widgets["edit"].text().strip()
            problem = name_problem(text) if text else ""
            if problem:
                problem += " Press Esc to put back the name in memory."
            self.show_field_problem(widgets, problem)

        def put_back_field(self, slot: str) -> None:
            """Esc in an inspector field: show the name in memory again."""
            widgets = self.inspector_fields.get(slot)
            if widgets is None or self.inspector_entity is None:
                return
            edit = widgets["edit"]
            edit.blockSignals(True)
            edit.setText(self.inspector_entity.name_in(slot))
            edit.blockSignals(False)
            self.show_field_problem(widgets, "")
            self.update_gauge(slot)

        def commit_inspector(self, slot: str, edit, reload_now: bool = False) -> bool:
            """Use the text typed in an inspector field, as one step Undo can take back.

            Text that cannot be a name stays in the field with a message beside
            it, so it can be put right; nothing changes until it can be used.
            False when the text was refused, True when it was used or left
            nothing to change (an unchanged field records nothing). A first
            line for a field reloads the views once the event loop is free, or
            at once with ``reload_now`` (a keyboard move does that, so it moves
            on from the reloaded grid).
            """
            if self._filling:
                return True
            entity = self.inspector_entity
            if entity is None:
                return True
            widgets = self.inspector_fields[slot]
            text = edit.text().strip()
            problem = name_problem(text)
            if problem:
                if text or entity.slots.get(slot):      # an empty field left empty is no change
                    self.show_field_problem(
                        widgets, problem + " Press Esc to put back the name in memory.")
                    return False
                self.show_field_problem(widgets, "")
                return True
            self.show_field_problem(widgets, "")
            was_empty = not entity.slots.get(slot)
            with self.recording(cell_operation(entity, slot, text)):
                changed = set_entity_field(entity, slot, text, self.docs)
            if not changed:
                return True
            if was_empty:
                if reload_now:
                    self.reload_views()
                else:
                    QTimer.singleShot(0, self.reload_views)
                return True
            self.after_edit()
            return True

        def update_gauge(self, slot: str) -> None:
            """The counter under a field: its length against the typical guide (Session 20).

            A warning only; it never blocks, trims, or changes a name.
            """
            widgets = self.inspector_fields.get(slot)
            if widgets is None:
                return
            gauge = length_gauge(self.family, slot, widgets["edit"].text())
            if gauge is None or self.inspector_entity is None:
                widgets["gauge"].setText("")
                return
            text, level, tip = gauge
            set_level(widgets["gauge"], text, level)
            widgets["gauge"].setToolTip(tip)

        def entity_row(self, key: tuple) -> int:
            """The grid row that shows the entity with this key, or -1 when none does."""
            proxy = self.entity_proxy
            current = self.entity_view.currentIndex()
            if current.isValid():
                source = proxy.mapToSource(current)
                if (source.isValid()
                        and entity_key(self.entity_model.rows[source.row()]) == key):
                    return current.row()
            for row, entity in enumerate(self.entity_model.rows):
                if entity_key(entity) == key:
                    return proxy.mapFromSource(self.entity_model.index(row, 0)).row()
            return -1

        def next_row(self, key: tuple, row_before: int, step: int) -> int:
            """The visible row ``step`` away from an entity's row, or -1 past the ends.

            The rows the proxy hides are skipped. When the edit itself hid the
            entity (a search it no longer matches), the rows below have moved
            up one, so the next row is where it was.
            """
            row = self.entity_row(key)
            if row >= 0:
                target = row + step
            elif row_before >= 0:
                target = row_before if step > 0 else row_before - 1
            else:
                return -1
            return target if 0 <= target < self.entity_proxy.rowCount() else -1

        def step_inspector(self, slot: str, step: int) -> None:
            """Alt+Down or Shift+Enter (step 1), Alt+Up (step -1), in an inspector field.

            The field is committed as an ordinary edit (one Undo step, or none
            when unchanged), then the next or previous visible grid row is
            selected and the same field takes the focus with its text selected.
            Refused text stays where it is, with its message, and nothing moves.
            The first and last rows do not wrap.
            """
            edit = self.inspector_edits.get(slot)
            entity = self.inspector_entity
            if edit is None or entity is None:
                return
            key = entity_key(entity)
            row_before = self.entity_row(key)
            if not self.commit_inspector(slot, edit, reload_now=True):
                return
            target = self.next_row(key, row_before, step)
            if target < 0:
                self.statusBar().showMessage(
                    "This is the last row shown." if step > 0 else "This is the first row shown.",
                    5000)
            else:
                column = self.entity_model.columns().index(slot)
                index = self.entity_proxy.index(target, column)
                self.entity_view.selectionModel().setCurrentIndex(
                    index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                self.entity_view.scrollTo(index)
            edit = self.inspector_edits.get(slot)
            if edit is not None and edit.isEnabled():
                edit.setFocus()
                edit.selectAll()

        def grid_edit_origin(self):
            """The cell being edited in the entity grid: (entity key, slot, row), or None."""
            index = self.entity_view.currentIndex()
            if not index.isValid():
                return None
            source = self.entity_proxy.mapToSource(index)
            if not source.isValid():
                return None
            entity = self.entity_model.rows[source.row()]
            return entity_key(entity), self.entity_model.columns()[index.column()], index.row()

        def move_grid_editor(self, origin, how: str) -> None:
            """After Tab ("next"), Shift+Tab ("previous") or Enter ("down") in a grid cell
            editor: edit the next name cell on the row, or the cell below (Session 20)."""
            key, slot, row_before = origin
            columns = self.entity_model.columns()
            if key[0] != self.family or slot not in columns:
                return
            if how == "down":
                row, column = self.next_row(key, row_before, 1), columns.index(slot)
            else:
                names = [name for name, _label, _cmd in FAMILY_FIELDS[self.family]]
                if slot not in names:
                    return
                at = names.index(slot) + (1 if how == "next" else -1)
                if not 0 <= at < len(names):
                    return                      # past the first or last name column
                row, column = self.entity_row(key), columns.index(names[at])
            if row < 0:
                return
            index = self.entity_proxy.index(row, column)
            self.entity_view.selectionModel().setCurrentIndex(
                index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            self.entity_view.scrollTo(index)
            self.entity_view.setFocus()
            self.entity_view.edit(index)

        def copy_long_to_short(self) -> None:
            """Edit > Copy long name to short name (Ctrl+Shift+L), for trimming.

            Only the inspector's Short name field is filled; nothing changes
            until Enter there, or a keyboard move, uses it.
            """
            long_edit = self.inspector_edits.get("long")
            short_edit = self.inspector_edits.get("short")
            if self.inspector_entity is None or long_edit is None or short_edit is None:
                self.statusBar().showMessage(
                    "Select a row with a long and a short name in the inspector first.", 6000)
                return
            if not self.inspector_act.isChecked():
                self.statusBar().showMessage("Show the inspector (F4) first.", 6000)
                return
            self.tabs.setCurrentIndex(0)
            short_edit.setText(long_edit.text().strip())
            self.check_field("short")
            short_edit.setFocus()
            short_edit.end(False)
            self.statusBar().showMessage(
                "Long name copied into Short name. Trim it, then press Enter to use it; "
                "Esc puts back the name in memory.", 10000)

        # ----- Session 21: short names and codes, name health, snapshots -----
        def refresh_health(self) -> None:
            """Check every open name again (name_health). The grid, its filter, the count in
            the status bar, and the inspector share the one result."""
            self.health.clear()
            self.health.update(name_health(self.all_entities))

        def show_health_count(self) -> None:
            """The status bar's Name health count: a link that lists the names to check."""
            label = self.health_label
            if not self.docs:
                label.hide()
                return
            label.show()
            count = len(self.health)
            if not count:
                set_level(label, "Name health: clean", "added")
                label.setToolTip(
                    "No spaces at the ends or in a row, no non-breaking or typographic "
                    "characters, no lower-case codes, and no 3-letter code shared in a file "
                    "section.")
                return
            fixable, shared = health_summary(self.health)
            set_level(label, f'Name health: <a href="health">{count:,} to check</a>', "warning")
            label.setToolTip(
                f"{count_of(count, 'entity', 'entities')} to check. Fix formatting can put "
                f"right {fixable:,}; {shared:,} share a 3-letter code in a file section, which "
                "is yours to decide. Click to list them with the Name health filter. "
                "Nothing is changed until you choose.")

        def show_name_health(self) -> None:
            """The Name health link: list the entities to check, in a family that has some."""
            families = {key[0] for key in self.health}
            if not families:
                self.statusBar().showMessage("Nothing to check in the open names.", 6000)
                return
            self.tabs.setCurrentIndex(0)
            if self.family not in families:
                self.family = next(family for family in FAMILY_LABELS if family in families)
                self.section_filter = ""
                for button in self.family_buttons:
                    button.setChecked(button.property("family") == self.family)
                self.apply_family()
            self.clear_entity_filters()
            self.status_mode = "health"
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "health")
            self.apply_entity_filter()

        def show_entity_health(self, entity) -> None:
            """The inspector's Name health notice, and the short name and code suggested from
            the long name. Both are shown only: nothing changes until a button is used."""
            issues = self.health.get(entity_key(entity), []) if entity is not None else []
            if issues:
                self.inspector_health.setText(
                    "Name health\n" + "\n".join(f"\u2022 {issue.text}" for issue in issues))
                self.inspector_fix.setVisible(any(issue.fixable for issue in issues))
            self.health_box.setVisible(bool(issues))
            names = (sibling_suggestion(entity, self.all_entities, self.rules.pinned_pairs)
                     if entity is not None else {})
            if names:
                self.inspector_suggestion.setText(
                    f"Suggested from the long name: {self.describe_siblings(names)}. Nothing "
                    "changes until you use it.")
            self.suggestion_box.setVisible(bool(names))

        @staticmethod
        def describe_siblings(names: dict) -> str:
            """'short name "Man Utd" and 3-letter code "MUN"': a suggestion, in words."""
            return " and ".join(f'{label} "{names[slot]}"' for slot, label
                                in (("short", "short name"), ("code", "3-letter code"))
                                if slot in names)

        def fill_short_and_code(self) -> None:
            """Edit > Fill short name and code (Ctrl+Alt+D), and the inspector's Use suggestion.

            The selected club's empty short name and 3-letter code get the lines
            sibling_suggestion proposes, as one operation; a field that has a
            line is never changed. Nothing is written until Save or Deploy.
            """
            entity = self.inspector_entity
            if entity is None or entity.family != "club":
                self.statusBar().showMessage(
                    "Select a club first: its short name and 3-letter code are suggested from "
                    "its long name.", 8000)
                return
            names = sibling_suggestion(entity, self.all_entities, self.rules.pinned_pairs)
            if not names:
                self.statusBar().showMessage(
                    "Nothing to fill: this club has a short name and a 3-letter code already, "
                    "or no long name to suggest them from.", 8000)
                return
            words = self.describe_siblings(names)
            with self.recording(f"fill {words}"):
                added = fill_siblings(entity, names)
            if not added:
                return
            self.reload_views()
            self.statusBar().showMessage(
                f"Added {words}, suggested from the long name. Undo takes "
                f"{'them' if added > 1 else 'it'} back; nothing is written until Save or "
                "Deploy.", 10000)

        def fix_formatting_selected(self) -> None:
            """Edit > Fix formatting, and the inspector's button: tidy the names of the rows
            selected on the Entities tab (fix_formatting), as one operation. A shared code
            is left for you to decide."""
            if self.tabs.currentIndex() != 0:
                self.statusBar().showMessage(
                    "Fix formatting works on the Entities tab: select the rows there.", 8000)
                return
            entities = self.selected_entities()
            if not entities:
                self.statusBar().showMessage("Select rows on the Entities tab first.", 6000)
                return
            with self.recording("fix formatting") as operation:
                changed = fix_formatting(entities)
                operation.label = "fix formatting: " + count_of(changed, "name")
            if not changed:
                self.statusBar().showMessage(
                    "Nothing to fix in the selected rows. A 3-letter code shared in a file "
                    "section is yours to decide: type another one.", 8000)
                return
            self.after_edit()
            self.statusBar().showMessage(
                f"Fixed formatting in {count_of(changed, 'name')}. Undo takes it back; nothing "
                "is written until Save or Deploy.", 10000)

        def create_snapshot(self) -> None:
            """Edit > Create snapshot... (Ctrl+Alt+K): name a snapshot of the open files' lines."""
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open a name file first.")
                return
            dialog = ProfileDialog(self, "Create snapshot",
                                   lambda name: label_problem(name, kind="snapshot"),
                                   name=f"Snapshot {self._snapshots_taken + 1}", note=None)
            if dialog.exec():
                self.keep_snapshot(dialog.values()[0])

        def keep_snapshot(self, label: str) -> Snapshot:
            """Keep the open files' working lines under ``label``, in memory only.

            Up to SNAPSHOT_LIMIT are kept: taking one more lets the oldest go, and
            says which. They last until files are opened again.
            """
            snapshot = take_snapshot(self.docs, label)
            self.snapshots.append(snapshot)
            self._snapshots_taken += 1
            message = (f"Snapshot '{label}' kept in memory at {snapshot.taken:%H:%M}. Edit > "
                       "Roll back to snapshot puts the lines back; nothing is written to disk.")
            if len(self.snapshots) > SNAPSHOT_LIMIT:
                oldest = self.snapshots.pop(0)
                message += (f" The oldest, '{oldest.label}', was let go: up to "
                            f"{SNAPSHOT_LIMIT} are kept.")
            self.statusBar().showMessage(message, 10000)
            return snapshot

        def fill_snapshot_menu(self) -> None:
            """Edit > Roll back to snapshot: the snapshots, newest first."""
            menu = self.rollback_menu
            menu.clear()
            if not self.snapshots:
                menu.addAction("No snapshots yet").setEnabled(False)
                return
            for snapshot in reversed(self.snapshots):
                item = menu.addAction(f"{snapshot.label} ({snapshot.taken:%H:%M})")
                item.setToolTip(
                    f"Put every open file's lines back as they were at "
                    f"{snapshot.taken:%H:%M:%S}, in memory, as one Undo step. Nothing is "
                    "written until Save or Deploy.")
                item.triggered.connect(
                    lambda _checked=False, chosen=snapshot: self.roll_back_snapshot(chosen))

        def roll_back_snapshot(self, snapshot: Snapshot) -> None:
            """Put the open files' lines back as ``snapshot`` kept them, as one operation."""
            if snapshot not in self.snapshots:
                return
            with self.recording(f"roll back to snapshot '{snapshot.label}'") as operation:
                roll_back_to(snapshot)
            if not operation.changed:
                self.statusBar().showMessage(
                    f"The open files already match snapshot '{snapshot.label}': nothing to "
                    "roll back.", 8000)
                return
            if operation.structural:
                self.reload_views()
            else:
                self.after_edit()
            self.statusBar().showMessage(
                f"Rolled back to snapshot '{snapshot.label}' ({snapshot.taken:%H:%M}): the "
                "lines are as they were then. Undo takes the roll back away; nothing is "
                "written until Save or Deploy.", 10000)

        # ----- going places -----
        def show_changes_tab(self) -> None:
            self.tabs.setCurrentIndex(self.CHANGES_TAB)
            self.change_view.setFocus()

        def go_to_change(self, index) -> None:
            """Double-click on the Changes tab: show that line on the All lines tab."""
            if not index.isValid():
                return
            row = self.change_model.rows[self.change_proxy.mapToSource(index).row()]
            if row.entry is None or row.state == "removed":
                self.statusBar().showMessage(
                    "That change has no line in memory to go to: "
                    + ("the line is on disk and the next Save or Deploy takes it out."
                       if row.state == "removed" else "it stands for lines outside the names."),
                    10000)
                return
            try:
                source_row = self.line_model.rows.index(row.entry)
            except ValueError:
                return
            source = self.line_model.index(source_row, EntryModel.NAME_COL)
            target = self.line_proxy.mapFromSource(source)
            cleared = False
            if not target.isValid():            # hidden by the All lines filters
                self.clear_line_filters()
                cleared = True
                target = self.line_proxy.mapFromSource(source)
            self.tabs.setCurrentIndex(1)
            self.line_view.setFocus()
            self.line_view.selectionModel().setCurrentIndex(
                target, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            self.line_view.scrollTo(target, QAbstractItemView.PositionAtCenter)
            message = f"Line {row.entry.lineno} of {row.entry.doc.path.name}."
            if cleared:
                message += " The All lines filters were cleared to show it."
            self.statusBar().showMessage(message, 10000)

        def clear_line_filters(self) -> None:
            for widget in (self.line_search, self.type_box, self.changed_box):
                widget.blockSignals(True)
            self.line_search.clear()
            self.type_box.setCurrentIndex(0)
            self.changed_box.setChecked(False)
            for widget in (self.line_search, self.type_box, self.changed_box):
                widget.blockSignals(False)
            self.line_timer.stop()
            self.apply_line_filter()

        def edit_current(self) -> None:
            """F2: edit the current cell; on a row, its name."""
            view = {0: self.entity_view, 1: self.line_view}.get(self.tabs.currentIndex())
            if view is None:
                self.statusBar().showMessage(
                    "Changes are not edited on this tab. Double-click a row to go to its line.",
                    8000)
                return
            index = view.currentIndex()
            if not index.isValid():
                self.statusBar().showMessage("Select a row to edit first.", 6000)
                return
            if not index.flags() & Qt.ItemIsEditable:
                # A row is selected whole, so the current cell can sit in a column
                # that is not edited: take the first name column instead.
                index = index.siblingAtColumn(2 if view is self.entity_view
                                              else EntryModel.NAME_COL)
                view.setCurrentIndex(index)
            view.setFocus()
            view.edit(index)

        def shortcut_rows(self) -> list[tuple[str, str]]:
            """Every key the editor knows, read from the menus, then the keys inside the tables."""
            rows = []
            def add_menu(menu, path):
                for action in menu.actions():
                    name = action.text().replace('&', '')
                    if action.menu() is not None:
                        add_menu(action.menu(), f"{path} > {name}")
                        continue
                    keys = [key.toString(QKeySequence.NativeText) for key in action.shortcuts()]
                    if not keys or not action.text():
                        continue
                    name = {self.undo_act: "Undo", self.redo_act: "Redo"}.get(
                        action, action.text())
                    rows.append((" or ".join(keys),
                                 f"{path} > {name.replace('&', '')}"))
            for menu in self.menus:
                add_menu(menu, menu.title().replace('&', ''))
            rows.extend([
                ("Double-click", "Edit a cell; on the Changes tab, go to its line"),
                ("Enter", "Keep what was typed in an inspector field; in a grid cell, keep it "
                          "and edit the cell below"),
                ("Esc", "Leave a cell unchanged; in the inspector, put back the name in memory"),
                ("Tab", "Move to the next field; in a grid cell, keep it and edit the next name "
                        "on the row (Shift+Tab: the one before)"),
                ("Alt+Down or Shift+Enter", "In an inspector field: keep it, go to the next row "
                                            "shown, and stay in the same field"),
                ("Alt+Up", "In an inspector field: keep it, go to the row before, and stay in "
                           "the same field"),
            ])
            return rows

        def show_about(self) -> None:
            """Name, version, and the copyright notice, matching LICENSE and the README."""
            dialog = QDialog(self)
            dialog.setWindowTitle(f"About {APP_NAME}")
            lay = QVBoxLayout(dialog)
            name = QLabel(APP_NAME)
            name.setObjectName("title")
            lay.addWidget(name)
            lay.addWidget(QLabel(f"Version {VERSION}"))
            copyright_line = QLabel(COPYRIGHT_FULL)
            copyright_line.setWordWrap(True)
            copyright_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(copyright_line)
            # The repository link sits directly beneath the copyright line, as a
            # clickable link that opens in the default browser.
            self.about_repo_label = QLabel(
                f'<a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a>')
            self.about_repo_label.setObjectName("repository")
            self.about_repo_label.setTextFormat(Qt.RichText)
            self.about_repo_label.setOpenExternalLinks(True)
            self.about_repo_label.setTextInteractionFlags(
                Qt.TextBrowserInteraction)
            lay.addWidget(self.about_repo_label)
            lay.addWidget(QLabel(COPYRIGHT_NOTE))
            lay.addWidget(QLabel(
                "See the LICENSE file beside the application for the full terms."))
            box = QDialogButtonBox(QDialogButtonBox.Close)
            box.rejected.connect(dialog.reject)
            lay.addWidget(box)
            dialog.resize(480, 240)
            dialog.exec()

        def show_guide(self) -> None:
            """Help > User guide: the sections of USER_GUIDE, read-only."""
            import html as html_text
            dialog = QDialog(self)
            dialog.setWindowTitle("User guide")
            lay = QVBoxLayout(dialog)
            body = QTextEdit()
            body.setObjectName("guide")
            body.setReadOnly(True)
            body.setHtml("".join(
                f"<h3>{html_text.escape(heading)}</h3><p>{html_text.escape(text)}</p>"
                for heading, text in USER_GUIDE))
            lay.addWidget(body, 1)
            box = QDialogButtonBox(QDialogButtonBox.Close)
            keys = box.addButton("Keyboard shortcuts", QDialogButtonBox.ActionRole)
            keys.clicked.connect(self.show_shortcuts)
            box.rejected.connect(dialog.reject)
            lay.addWidget(box)
            free = self.screen().availableGeometry() if self.screen() else None
            dialog.resize(min(640, free.width() - 40) if free else 640,
                          min(600, free.height() - 80) if free else 600)
            self.guide_dialog = dialog
            dialog.exec()

        def show_shortcuts(self) -> None:
            rows = self.shortcut_rows()
            dialog = QDialog(self)
            dialog.setWindowTitle("Keyboard shortcuts")
            lay = QVBoxLayout(dialog)
            table = QTableWidget(len(rows), 2)
            table.setHorizontalHeaderLabels(["Keys", "What it does"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.NoSelection)
            for number, (keys, what) in enumerate(rows):
                table.setItem(number, 0, QTableWidgetItem(keys))
                table.setItem(number, 1, QTableWidgetItem(what))
            table.resizeColumnsToContents()
            table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(table)
            box = QDialogButtonBox(QDialogButtonBox.Close)
            box.rejected.connect(dialog.reject)
            lay.addWidget(box)
            dialog.resize(620, 560)
            dialog.exec()

        def quick_load(self) -> None:
            if not self.confirm_discard():
                return
            version = self.selected_version()
            if version is None or not version_has_names(version):
                QMessageBox.warning(
                    self, APP_NAME,
                    "No FM27 name files were found in the selected database folder.\n"
                    f"Looked under {GAME_DB_ROOT}")
                return
            self.load_in_background([str(path) for path in name_paths(version)])

        def deploy(self) -> None:
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open the name files first.")
                return
            version = self.selected_version()
            if version is None:
                QMessageBox.warning(self, APP_NAME, "No database folder is selected.")
                return
            targets = {name: version / "lnc" / "all" / name for name in NAME_FILES}
            seen = {}
            skipped = []
            duplicate = False
            for doc in self.docs:
                if doc.path.name not in targets:
                    skipped.append(doc.path.name)
                    continue
                if doc.path.name in seen:
                    duplicate = True
                seen[doc.path.name] = doc
            if duplicate:
                QMessageBox.warning(
                    self, APP_NAME,
                    "Two open files share a name. Close one of them before deploying.")
                return
            if not seen:
                QMessageBox.warning(
                    self, APP_NAME,
                    "None of the open files are FM27_Club_Names.lnc or FM27_Fix.lnc.")
                return
            pairs = [(seen[name], targets[name]) for name in NAME_FILES if name in seen]
            self.review_and_write("Deploy", pairs, None, skipped)

        def open_licensing(self) -> None:
            version = self.selected_version()
            if version is None or not version.is_dir():
                QMessageBox.warning(
                    self, APP_NAME,
                    f"No database folder was found under\n{GAME_DB_ROOT}")
                return
            LicenceDialog(self, version).exec()

        def visible_entities(self) -> list[NameEntity]:
            rows = []
            for row in range(self.entity_proxy.rowCount()):
                source = self.entity_proxy.mapToSource(self.entity_proxy.index(row, 0))
                rows.append(self.entity_model.rows[source.row()])
            return rows

        def open_bulk(self) -> None:
            shown = self.visible_entities()
            family = list(self.entity_model.rows)
            if not family:
                QMessageBox.information(
                    self, APP_NAME, "There are no entities in this family.")
                return
            scopes = {"shown": shown, "family": family,
                      "selected": self.selected_entities()}
            dialog = BulkDialog(self, shown, self.docs, scopes)
            with self.recording("bulk") as operation:
                accepted = dialog.exec()
                kind = {"affix": "strip affix", "sponsor": "remove sponsors",
                        "title": "title case"}.get(dialog.kind(), dialog.kind())
                operation.label = f"bulk: {kind} ({count_of(dialog.applied, 'name')})"
            if accepted:
                self.reload_views()
                self.statusBar().showMessage(
                    f"Bulk edit updated {dialog.applied} line(s). "
                    "Nothing is written until you press Save or Deploy.",
                    10000)

        def open_replace(self) -> None:
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open a name file first.")
                return
            dialog = ReplaceDialog(self, self.docs)
            with self.recording("replace") as operation:
                accepted = dialog.exec()
                operation.label = f"replace: {count_of(dialog.applied, 'name')}"
            if accepted and dialog.applied:
                self.reload_views()
                self.statusBar().showMessage(
                    f"Replace updated {dialog.applied} line(s). "
                    "Nothing is written until you press Save or Deploy.",
                    10000)

        def export_pack(self) -> None:
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open a name file first.")
                return
            choice = QDialog(self)
            choice.setWindowTitle("Export name pack")
            lay = QVBoxLayout(choice)
            edited = QRadioButton("Edited names only")
            every = QRadioButton("Every name line")
            edited.setChecked(True)
            lay.addWidget(edited)
            lay.addWidget(every)
            lay.addWidget(QLabel(
                "A pack stores command, database ID, language, and name. "
                "Person-name rules are not included."))
            box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            box.accepted.connect(choice.accept)
            box.rejected.connect(choice.reject)
            lay.addWidget(box)
            if not choice.exec():
                return
            pack = pack_document(self.docs, edited.isChecked())
            if not pack["names"]:
                if edited.isChecked():
                    message = "There are no edited names to export."
                else:
                    message = "The open files have no database-id name lines to export."
                QMessageBox.information(self, APP_NAME, message)
                return
            path, selected = QFileDialog.getSaveFileName(
                self, "Export name pack", str(Path(self.start_folder()) / "fm-name-pack.json"),
                "JSON name pack (*.json);;CSV name pack (*.csv)")
            if not path:
                return
            as_csv = path.casefold().endswith(".csv") or (
                selected.startswith("CSV") and not path.casefold().endswith(".json"))
            if as_csv and not path.casefold().endswith(".csv"):
                path += ".csv"
            elif not as_csv and not path.casefold().endswith(".json"):
                path += ".json"
            if in_game_tree(path):
                # The picker can now open in lnc\all (Session 19); only Save and Deploy
                # write into the game's folders, after a backup.
                QMessageBox.warning(
                    self, APP_NAME,
                    "A name pack is not saved inside the game's folders: only Save and Deploy "
                    "write there, after a backup. Choose another folder, such as Documents.")
                return
            text = pack_to_csv(pack) if as_csv else pack_to_json(pack)
            data = text.encode("utf-8-sig" if as_csv else "utf-8")
            try:
                write_file_atomically(Path(path), data)
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not write the pack:\n{exc}")
                return
            self.statusBar().showMessage(
                f"Exported {len(pack['names'])} name(s) to {path}.", 8000)

        def import_pack(self) -> None:
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open a name file first.")
                return
            path, _selected = QFileDialog.getOpenFileName(
                self, "Import name pack", self.start_folder(),
                "Name packs (*.json *.csv);;JSON (*.json);;CSV (*.csv);;All files (*)")
            if not path:
                return
            try:
                raw = Path(path).read_bytes()
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not read the pack:\n{exc}")
                return
            if raw.startswith(UTF8_BOM):
                raw = raw[len(UTF8_BOM):]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                QMessageBox.critical(
                    self, APP_NAME, "Name packs must be UTF-8 text.")
                return
            kind = "csv" if path.casefold().endswith(".csv") else "json"
            rows, skipped, error = parse_pack(text, kind)
            if error:
                QMessageBox.critical(self, APP_NAME, error)
                return
            changes, missing, stats = proposals_from_pack(self.docs, rows)
            summary = (
                f"{stats['rows']} usable name(s). {stats['same']} already match. "
                f"{stats['duplicate']} repeated key(s) kept the last spelling.")
            if skipped:
                summary += (
                    f" {skipped} row(s) were skipped because their command, id, name, "
                    "or language could not be written as one line.")
            dialog = PackDialog(self, changes, missing, summary,
                                apply_func=lambda c, m, d: apply_proposals(c, m, d, "pack"))
            with self.recording("name pack") as operation:
                accepted = dialog.exec()
                if dialog.result_counts is not None:
                    operation.label = (f"name pack: {dialog.result_counts[0]:,} changed, "
                                       f"{len(dialog.result_counts[1]):,} added")
            if accepted and dialog.result_counts is not None:
                updated, added = dialog.result_counts
                self.reload_views()
                self.statusBar().showMessage(
                    f"Name pack updated {updated} line(s) and added {len(added)}. "
                    "Nothing is written until you press Save or Deploy.",
                    10000)

        def open_backups(self) -> None:
            BackupDialog(self, self.docs).exec()

        # ----- spelling profiles -----
        def refresh_profiles(self, select_file: str | None = None) -> None:
            """Read the profiles folder again and fill the selector.

            ``select_file`` is a profile's file name; "" selects No profile.
            By default the remembered profile is selected. Nothing is saved.
            """
            self.profiles, problems = list_profiles(PROFILE_ROOT)
            if select_file is None:
                select_file = str(self.state.get("active_profile_file", ""))
            names = [profile.name.casefold() for profile in self.profiles]
            self.profile_box.blockSignals(True)
            self.profile_box.clear()
            self.profile_box.addItem("No profile", "")
            for profile in self.profiles:
                label = profile.name
                if names.count(profile.name.casefold()) > 1:
                    label += f" ({profile.path.name})"
                self.profile_box.addItem(label, profile.path.name)
                tip = f"{len(profile.rows):,} spelling(s) in {profile.path}"
                if profile.note:
                    tip = f"{profile.note}\n{tip}"
                self.profile_box.setItemData(self.profile_box.count() - 1, tip, Qt.ToolTipRole)
            index = self.profile_box.findData(select_file) if select_file else 0
            self.profile_box.setCurrentIndex(max(index, 0))
            self.profile_box.blockSignals(False)
            self.update_profile_actions()
            if problems:
                self.statusBar().showMessage(
                    f"{len(problems)} profile file(s) could not be read and were left "
                    "alone: " + " | ".join(problems), 20000)

        def current_profile(self):
            wanted = self.profile_box.currentData()
            for profile in self.profiles:
                if wanted and profile.path is not None and profile.path.name == wanted:
                    return profile
            return None

        def update_profile_actions(self) -> None:
            chosen = self.current_profile() is not None
            self.apply_profile_act.setEnabled(chosen)     # the toolbar button and the menu item
            self.rename_profile_act.setEnabled(chosen)
            self.delete_profile_act.setEnabled(chosen)

        def remember_profile(self) -> None:
            """Keep the chosen profile in the local state file for next time."""
            profile = self.current_profile()
            self.state["active_profile_file"] = profile.path.name if profile else ""
            problem = self.keep_settings(self.state)
            if problem:
                self.statusBar().showMessage(
                    "The chosen profile is not remembered for next time. "
                    + problem.replace("\n", " "), 15000)

        def on_profile_chosen(self) -> None:
            self.update_profile_actions()
            self.remember_profile()

        def new_profile(self) -> bool:
            dialog = ProfileDialog(
                self, "New profile", lambda name: profile_name_problem(name, self.profiles))
            if not dialog.exec():
                return False
            name, note = dialog.values()
            try:
                profile = create_profile(name, note, PROFILE_ROOT, self.profiles)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not create the profile:\n{exc}")
                return False
            self.refresh_profiles(profile.path.name)
            self.remember_profile()
            self.statusBar().showMessage(
                f"Created the profile {profile.name}. Record edits into it before you "
                "Save or Deploy.", 10000)
            return True

        def rename_current_profile(self) -> None:
            profile = self.current_profile()
            if profile is None:
                return
            dialog = ProfileDialog(
                self, "Rename profile",
                lambda name: profile_name_problem(name, self.profiles, own=profile),
                profile.name, profile.note)
            if not dialog.exec():
                return
            name, note = dialog.values()
            try:
                renamed = rename_profile(profile, name, note, PROFILE_ROOT, self.profiles)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not rename the profile:\n{exc}")
                self.refresh_profiles()
                return
            self.refresh_profiles(renamed.path.name)
            self.remember_profile()
            self.statusBar().showMessage(f"Renamed the profile to {renamed.name}.", 8000)

        def delete_current_profile(self) -> None:
            profile = self.current_profile()
            if profile is None:
                return
            answer = QMessageBox.question(
                self, APP_NAME,
                f"Delete the profile {profile.name} ({len(profile.rows):,} spelling(s))?\n\n"
                f"Its file moves to {PROFILE_ROOT / 'deleted'}, so it can be recovered "
                "by hand. The name files are not changed.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            try:
                moved = delete_profile(profile, PROFILE_ROOT)
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not delete the profile:\n{exc}")
                return
            self.refresh_profiles("")
            self.remember_profile()
            self.statusBar().showMessage(
                f"Deleted the profile {profile.name}. Its file is now {moved}.", 10000)

        def record_into_profile(self) -> None:
            """Copy the unsaved name edits into the chosen profile, after a confirmation."""
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open the name files first.")
                return
            profile = self.current_profile()
            if profile is None:
                answer = QMessageBox.question(
                    self, APP_NAME,
                    "No profile is chosen. Make a new profile to record into?",
                    QMessageBox.Yes | QMessageBox.No)
                if answer != QMessageBox.Yes or not self.new_profile():
                    return
                profile = self.current_profile()
                if profile is None:
                    return
            trial = profile.copy()
            counts = record_edits(trial, self.docs)
            notes = []
            if counts["persons"]:
                notes.append(f"{counts['persons']:,} person rule(s) are not names and are "
                             "not recorded.")
            if counts["removed"]:
                notes.append(f"{counts['removed']:,} row(s) a restore left out are not "
                             "recorded.")
            if counts["skipped"]:
                notes.append(f"{counts['skipped']:,} row(s) could not be stored as one "
                             "line and were skipped.")
            if counts["repeated"]:
                notes.append(f"{counts['repeated']:,} repeated key(s) kept the last spelling.")
            wanted = counts["added"] + counts["updated"]
            if not wanted:
                if counts["same"]:
                    text = (f"{profile.name} already holds these {counts['same']:,} "
                            "spelling(s) with the same baselines.")
                else:
                    text = ("There are no unsaved name edits to record. An edit that "
                            "has been saved is part of the file on disk, so record "
                            "edits before you Save or Deploy.")
                QMessageBox.information(self, APP_NAME, " ".join([text, *notes]))
                return
            question = (f"Record {wanted:,} spelling(s) into {profile.name}? "
                        f"{counts['added']:,} new, {counts['updated']:,} replacing an "
                        "earlier spelling. Each keeps the name on disk as its baseline.")
            if notes:
                question += "\n\n" + "\n".join(notes)
            answer = QMessageBox.question(
                self, APP_NAME, question, QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            try:
                save_profile(trial, PROFILE_ROOT)
            except OSError as exc:
                QMessageBox.critical(
                    self, APP_NAME,
                    f"Could not write the profile:\n{exc}\n\nThe profile on disk is "
                    "unchanged.")
                return
            self.refresh_profiles(trial.path.name)
            self.statusBar().showMessage(
                f"Recorded {wanted:,} spelling(s) into {trial.name}, which now holds "
                f"{len(trial.rows):,}.", 10000)

        def apply_profile_to_files(self) -> None:
            """Preview the chosen profile against the open files, then apply the ticked rows."""
            profile = self.current_profile()
            if profile is None:
                QMessageBox.information(self, APP_NAME, "Choose a profile first.")
                return
            if not self.docs:
                QMessageBox.information(self, APP_NAME, "Open the name files first.")
                return
            try:
                fresh = load_profile(profile.path)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not read the profile:\n{exc}")
                self.refresh_profiles()
                return
            changes, missing, stats = apply_profile(fresh, self.docs)
            if not changes and not missing:
                text = (f"All {stats['same']:,} spelling(s) in {fresh.name} that the open "
                        "files have already match.")
                if stats["elsewhere"]:
                    text += (f" {stats['elsewhere']:,} belong to a file that is not open.")
                if not stats["rows"]:
                    text = f"{fresh.name} holds no spellings yet. Record some edits first."
                QMessageBox.information(self, APP_NAME, text)
                return
            dialog = PackDialog(
                self, changes, missing, describe_profile_apply(fresh, stats),
                title=f"Apply profile: {fresh.name}", new_label="Profile spelling",
                base_label="Baseline when recorded",
                apply_func=lambda c, m, d: apply_profile_proposals(fresh.name, c, m, d))
            with self.recording(f"profile {fresh.name}") as operation:
                accepted = dialog.exec()
                if dialog.result_counts is not None:
                    operation.label = (f"profile {fresh.name}: {dialog.result_counts[0]:,} "
                                       f"changed, {len(dialog.result_counts[1]):,} added")
            if accepted and dialog.result_counts is not None:
                updated, added = dialog.result_counts
                self.reload_views()
                self.statusBar().showMessage(
                    f"Profile {fresh.name} updated {updated} line(s) and added {len(added)}. "
                    "Nothing is written until you press Save or Deploy.", 10000)

        def migrate_profile_to_files(self) -> None:
            """Preview migrating the chosen profile into the newly loaded files.

            The usual flow: the user loads the new version's name files (Open or
            Quick load) and then picks Migrate. Each recorded preference is
            compared with the new file's spelling, and the proposals that would
            carry forward safely are pre-ticked. Nothing is written until Save
            or Deploy.
            """
            profile = self.current_profile()
            if profile is None:
                QMessageBox.information(self, APP_NAME, "Choose a profile first.")
                return
            if not self.docs:
                QMessageBox.information(
                    self, APP_NAME,
                    "Open the new files first (Quick load, or Open), then try again.")
                return
            try:
                fresh = load_profile(profile.path)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not read the profile:\n{exc}")
                self.refresh_profiles()
                return
            changes, missing, stats = migrate_profile(fresh, self.docs)
            if not changes and not missing:
                if not stats["rows"]:
                    text = f"{fresh.name} holds no spellings yet. Record some edits first."
                else:
                    text = (f"All {stats['already_preferred']:,} spelling(s) in {fresh.name} "
                            "that the open files have already match. The new files need no "
                            "migration.")
                    if stats["elsewhere"]:
                        text += (f" {stats['elsewhere']:,} belong to a file that is not open.")
                QMessageBox.information(self, APP_NAME, text)
                return
            dialog = PackDialog(
                self, changes, missing, describe_profile_migration(fresh, stats),
                title=f"Migrate profile: {fresh.name}",
                new_label="Profile spelling",
                base_label="Baseline when recorded",
                apply_func=lambda c, m, d: apply_profile_proposals(fresh.name, c, m, d))
            with self.recording(f"migrate profile {fresh.name}") as operation:
                accepted = dialog.exec()
                if dialog.result_counts is not None:
                    operation.label = (
                        f"migrate profile {fresh.name}: {dialog.result_counts[0]:,} changed, "
                        f"{len(dialog.result_counts[1]):,} added")
            if accepted and dialog.result_counts is not None:
                updated, added = dialog.result_counts
                self.reload_views()
                self.statusBar().showMessage(
                    f"Profile {fresh.name} migrated into {updated} line(s) and added "
                    f"{len(added)}. Nothing is written until you press Save or Deploy.", 10000)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    icon_path = resource_path(ICON_FILE)
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    if paths:
        win.load(paths)
    win.show()
    return app, win


def main():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print("PySide6 is required. Install it with:  pip install PySide6")
        sys.exit(1)
    app, _win = run_gui(sys.argv[1:])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
