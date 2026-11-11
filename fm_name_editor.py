#!/usr/bin/env python3
"""
FM Name Editor v2.2
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
state, and files replaced one at a time with a way back.

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
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

APP_NAME = "FM Name Editor"
VERSION = "2.2"

GAME_DB_ROOT = Path(
    r"D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db")
BACKUP_ROOT = Path(r"C:\FM Name Editor\backups")
PROFILE_ROOT = Path(r"C:\FM Name Editor\profiles")
STATE_ROOT = Path(r"C:\FM Name Editor\state")
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

FILE_SECTION_HINT = (
    "The # comment heading this line sits under in the name file. It is file "
    "structure, not a reliable country. In FM27_Fix.lnc, for instance, the Premier "
    "League lines come before the #England heading, so they sit under the heading "
    "above it.")

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
    """Lower-case and strip accents, for accent-insensitive searching."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").casefold()


ROW_KINDS = ("name", "person")

# Which operation last changed a line in memory, as the Changes view words it.
CHANGE_REASONS = {
    "manual": "Manual edit",
    "bulk": "Bulk tool",
    "replace": "Replace",
    "pack": "Name pack",
    "import": "Older files",
    "profile": "Profile",
    "restore": "Restore",
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
    matched row takes the disk text as its original, so it shows as edited
    when it differs. A row with no match is marked added. Returns the disk
    rows that no restored row matched.
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
        entries, encoding, has_bom, default_eol = parse_lnc_bytes(self, data)
        for entry in entries:
            entry.orig_raw = None       # where a backup line sits on disk is not known
            if entry.kind in ROW_KINDS:
                entry.reason = "restore"
        removed: list[Entry] = []
        if self.baseline_bytes:
            on_disk = parse_lnc_bytes(None, self.baseline_bytes)[0]
            removed = adopt_disk_originals(entries, on_disk)
        self.encoding = encoding
        self.has_bom = has_bom
        self.default_eol = default_eol
        self.entries = entries
        self.removed_rows = removed
        self.restore_pending = True
        self.restored_from = Path(source) if source is not None else None
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
        if self.entries and not self.entries[-1].eol:
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


def entity_status(entity: NameEntity) -> str:
    """Short status for the entity grid."""
    parts = []
    if entity.duplicate():
        parts.append("Duplicate")
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
    if not anchor.eol:
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


def strip_affix(name: str, affixes: tuple[str, ...] = AFFIXES) -> str:
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


def title_case_name(name: str) -> str:
    """Title-case a name that is entirely capitals. Anything else is unchanged."""
    letters = [ch for ch in name if ch.isalpha()]
    if not letters or not all(ch.isupper() for ch in letters):
        return name
    words = name.split(" ")
    cased = []
    for index, word in enumerate(words):
        bare = word.casefold().strip(".'’")
        if index > 0 and bare in SMALL_WORDS:
            cased.append(word.lower())
        else:
            cased.append(_cap_token(word))
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
    """One preview row. Nothing is written until apply_bulk."""

    __slots__ = ("entity", "slot", "entry", "before", "after")

    def __init__(self, entity: NameEntity, slot: str, entry: Entry, before: str, after: str):
        self.entity = entity
        self.slot = slot
        self.entry = entry
        self.before = before
        self.after = after


def _transform_name(kind: str, before: str, sponsors: list[str]) -> str:
    if kind == "affix":
        return strip_affix(before)
    if kind == "sponsor":
        return strip_sponsor(before, sponsors)
    if kind == "title":
        return title_case_name(before)
    raise ValueError(kind)


def preview_bulk(entities, kind: str, sponsors: list[str] | None = None) -> list[BulkEdit]:
    """Build the before/after list for the entities currently on screen.

    Codes are left alone. The sponsor cleanser only looks at competitions.
    Each source line is listed on its own, so duplicate IDs are not collapsed.
    """
    edits = []
    phrases = list(sponsors or [])
    for entity in entities:
        if kind == "sponsor" and entity.family != "comp":
            continue
        for slot, _label, _cmd in FAMILY_FIELDS[entity.family]:
            if slot not in TEXT_SLOTS:
                continue
            for entry in entity.slots.get(slot) or []:
                before = entry.name
                after = _transform_name(kind, before, phrases)
                if after != before and name_is_legal(after):
                    edits.append(BulkEdit(entity, slot, entry, before, after))
    return edits


def apply_bulk(edits, docs, reason: str = "bulk") -> int:
    """Apply a preview. Returns how many lines changed.

    docs is unused; each edit already points at its line. It is kept so
    callers can pass the open documents beside the preview. ``reason`` is
    "bulk" for the bulk tools and "replace" for Replace.
    """
    del docs
    count = 0
    for edit in edits:
        if try_set_name(edit.entry, edit.after, reason):
            count += 1
    return count


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
        if self.entry is None or self.state == "removed":
            key = "restore" if self.doc.restore_pending else ""
        else:
            key = self.entry.reason or ""
        if key == "profile":
            mark = self.entry.profile_mark
            if mark is not None and mark[1] == self.entry.name:
                return f"Profile {mark[0]}"
        return CHANGE_REASONS.get(key, "")

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


def toggle_licence(version_dir: Path, rel: Path, archive_root: Path) -> str:
    """Rename a name-mask file to `.disabled`, or restore it.

    The current file is copied into a new backup folder first, with a
    manifest, through write_file_atomically. No bytes are written into the
    game tree: the toggle is one rename inside one folder, which never
    replaces a file. When both names exist it refuses, because choosing
    between them is the user's call. Nothing is deleted.

    Raises:
        FileExistsError: the file and its ``.disabled`` copy both exist.
        FileNotFoundError: neither exists.
    """
    if rel not in MASK_FILES:
        raise ValueError(f"Not a name-mask file: {rel}")
    src = version_dir / rel
    disabled = src.with_name(src.name + ".disabled")
    if src.exists() and disabled.exists():
        raise FileExistsError(
            f"Both {src.name} and {disabled.name} are in {src.parent}. The editor will "
            "not choose between them. Move or rename one of them yourself.")
    if src.is_file():
        current, target, operation, result = src, disabled, "Disable licensing file", "disabled"
    elif disabled.is_file():
        current, target, operation, result = disabled, src, "Restore licensing file", "restored"
    else:
        raise FileNotFoundError(src)
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


def profile_name_problem(name: str, existing=(), own=None) -> str:
    """Why ``name`` cannot name a profile, or "" when it can.

    ``existing`` lists the profiles there are; a name must differ from
    theirs, ignoring case. ``own`` is the profile being renamed, which may
    keep its name.
    """
    cleaned = name.strip()
    if not cleaned:
        return "Give the profile a name."
    if len(cleaned) > 80:
        return "Keep the name to 80 characters or fewer."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return "A profile name cannot contain control characters."
    for other in existing:
        if other is not own and other.name.casefold() == cleaned.casefold():
            return f"There is already a profile called {other.name}."
    return ""


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
    edit of its own, or when another profile set it in this session. A row
    the open files lack becomes an added line in the open file it was
    recorded from; when no open file has that name it is counted under
    "elsewhere" and left out. Rows that already read the preferred name
    are counted as "same".

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
        current = found[-1]
        notes = []
        mark = current.profile_mark
        if mark is not None and mark[0] != profile.name and current.name == mark[1]:
            notes.append(f"Competes with profile {mark[0]}, which set {mark[1]} in this session")
        elif current.changed:
            notes.append(f"Unsaved edit {current.name} would be replaced")
        on_disk = None if current.imported else current.orig_name
        if on_disk != recorded:
            notes.append(f"Baseline changed: the file says {_shown(on_disk)}; when "
                         f"recorded it said {_shown(recorded)}")
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


def load_state(root) -> dict:
    """The editor's local settings. Missing or unreadable settings read as empty."""
    try:
        data = json.loads((Path(root) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict, root) -> None:
    """Write the local settings through write_file_atomically."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_file_atomically(root / STATE_FILE, text.encode("utf-8"))


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
    if not archive_file.is_file():
        raise FileNotFoundError(archive_file)
    doc.replace_working(archive_file.read_bytes(), archive_file)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def run_gui(paths):
    from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
                                Qt, QTimer, Signal)
    from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
    from PySide6.QtWidgets import (
        QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
        QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
        QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
        QPlainTextEdit, QPushButton, QRadioButton, QSplitter, QStyledItemDelegate,
        QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QToolButton,
        QVBoxLayout, QWidget)

    FILTER = "FM name files (*.lnc);;All files (*)"
    GAME_WRITE_NOTE = (
        "A copy of each existing game file is stored under backups first. Files are "
        "replaced one at a time; if one fails, the files already replaced are put back "
        "from that copy.")

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
        COLS = ["File section or ending", "Type", "ID", "Name", "Language", "File", "Status"]
        NAME_COL = 3

        def __init__(self):
            super().__init__()
            self.rows: list[Entry] = []
            self.bold = QFont()
            self.bold.setBold(True)

        def set_docs(self, docs):
            self.beginResetModel()
            self.rows = [e for d in docs for e in d.editable()]
            self.endResetModel()

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return len(self.COLS)

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                return self.COLS[section]
            if role == Qt.ToolTipRole and orientation == Qt.Horizontal and section == 0:
                return FILE_SECTION_HINT
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
            e = self.rows[index.row()]
            c = index.column()
            if role in (Qt.DisplayRole, Qt.EditRole):
                if c == 0:
                    return e.source if e.kind == "person" else e.section
                if c == 1: return friendly(e.cmd)
                if c == 2: return int(e.id) if role == Qt.EditRole else e.id
                if c == 3: return e.name
                if c == 4: return e.lang
                if c == 5: return e.doc.path.name
                if c == 6:
                    return "Added" if e.imported else ("Edited" if e.changed else "")
            if role == Qt.FontRole and e.changed:
                return self.bold
            if role == Qt.ToolTipRole and e.kind == "person":
                return f"Ending was: {e.orig_source}. Replacement was: {e.orig_name}."
            if role == Qt.ToolTipRole and e.changed and not e.imported:
                return f"Was: {e.orig_name}"
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if role != Qt.EditRole:
                return False
            entry = self.rows[index.row()]
            if index.column() == 0:
                if not try_set_source(entry, str(value)):
                    return False
            elif index.column() == self.NAME_COL:
                if not try_set_name(entry, str(value)):
                    return False
            else:
                return False
            self.row_changed(index.row())
            return True

        def row_changed(self, row):
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.COLS) - 1))

    class EntryProxy(QSortFilterProxyModel):
        def __init__(self):
            super().__init__()
            self.words = []
            self.cmd = ""
            self.changed_only = False
            self.setSortRole(Qt.EditRole)
            self.setDynamicSortFilter(False)   # edited rows stay put until re-filtered
            self.setSortCaseSensitivity(Qt.CaseInsensitive)

        def set_filter(self, text, cmd, changed_only):
            self.words = fold(text).split()
            self.cmd = cmd
            self.changed_only = changed_only
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
            paths, _ = QFileDialog.getOpenFileNames(self, "Your edited older files", "", FILTER)
            if paths:
                self.old_paths = paths
                self.old_label.setText(", ".join(Path(p).name for p in paths))
                self.compare_btn.setEnabled(True)

        def pick_base(self):
            paths, _ = QFileDialog.getOpenFileNames(self, "Unedited originals", "", FILTER)
            self.base_paths = paths
            self.base_label.setText(", ".join(Path(p).name for p in paths) or "None (optional)")

        def compare(self):
            try:
                old = [LncDoc(p) for p in self.old_paths]
                base = [LncDoc(p) for p in self.base_paths] or None
            except (OSError, UnicodeError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not read file:\n{exc}")
                return
            changes, missing, stats = build_proposals(self.docs, old, base)
            key = lambda p: (fold(p.section), p.cmd, p.new)
            self.change_model.set_items(sorted(changes, key=key))
            self.missing_model.set_items(sorted(missing, key=key))
            self.tabs.setTabText(0, f"Different names ({len(changes)})")
            self.tabs.setTabText(1, f"Not in current files ({len(missing)})")
            for i in range(2):
                self.tabs.widget(i).resizeColumnsToContents()
            bad = sum(len(d.problems()) for d in old)
            text = (f"{stats['old']} names read from the older files. "
                    f"{stats['same']} already match the current files.")
            if base:
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

        def refilter(self, text):
            self.change_model.apply_filter(text)
            self.missing_model.apply_filter(text)

        def apply(self):
            n, added = apply_proposals(self.change_model.items, self.missing_model.items,
                                       self.docs)
            self.result_counts = (n, len(added))
            self.accept()

    DARK_QSS = """
    QWidget { background-color: #13151b; color: #e2e8f0; font-size: 13px; }
    QMainWindow, QDialog { background-color: #13151b; }
    QToolBar {
        background: #1a1e28; border: 0; border-bottom: 1px solid #2a3040;
        spacing: 6px; padding: 4px;
    }
    QStatusBar { background: #1a1e28; color: #8a94a6; }
    QLabel#metrics { color: #8a94a6; background: transparent; padding: 2px 6px; }
    QLabel#muted { color: #8a94a6; background: transparent; }
    QLabel#warning { color: #f59e0b; background: transparent; }
    QLabel#blocked { color: #f59e0b; background: transparent; font-weight: bold; }
    QLabel#ok { color: #10b981; background: transparent; }
    QLabel#heading { background: transparent; font-weight: bold; }
    QToolButton#manage {
        background: #1a1e28; color: #e2e8f0; border: 1px solid #2a3040;
        padding: 4px 10px; border-radius: 4px;
    }
    QToolButton#manage:hover { border-color: #8b5cf6; }
    QMenu { background: #1a1e28; color: #e2e8f0; border: 1px solid #2a3040; }
    QMenu::item { padding: 4px 18px; }
    QMenu::item:selected { background: #8b5cf6; color: white; }
    QMenu::item:disabled { color: #8a94a6; }
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTableView, QTableWidget {
        background: #1a1e28; color: #e2e8f0; border: 1px solid #2a3040;
        selection-background-color: #8b5cf6; selection-color: #ffffff;
    }
    QHeaderView::section {
        background: #1a1e28; color: #8a94a6; border: 1px solid #2a3040; padding: 4px;
    }
    QTableView, QTableWidget {
        alternate-background-color: #161b26; gridline-color: #2a3040;
    }
    QPushButton {
        background: #1a1e28; color: #e2e8f0; border: 1px solid #2a3040;
        padding: 4px 10px; border-radius: 4px;
    }
    QPushButton:hover { border-color: #8b5cf6; }
    QPushButton:checked { background: #8b5cf6; color: white; border-color: #8b5cf6; }
    QTabBar::tab {
        background: #1a1e28; color: #8a94a6; padding: 6px 14px; border: 1px solid #2a3040;
    }
    QTabBar::tab:selected { color: #e2e8f0; border-bottom: 2px solid #8b5cf6; }
    QListWidget::item:selected, QTableWidget::item:selected { background: #8b5cf6; color: white; }
    QComboBox QAbstractItemView {
        background: #1a1e28; color: #e2e8f0; selection-background-color: #8b5cf6;
    }
    QSplitter::handle { background: #2a3040; }
    QLabel { background: transparent; }
    QCheckBox, QRadioButton { background: transparent; spacing: 6px; }
    """

    class EntityModel(QAbstractTableModel):
        """Side-by-side rows. Column set follows the selected family."""

        def __init__(self, docs):
            super().__init__()
            self.docs = docs
            self.family = "club"
            self.rows: list[NameEntity] = []
            self.bold = QFont()
            self.bold.setBold(True)
            self._structure = False

        def columns(self) -> list[str]:
            cols = ["section", "id"]
            cols.extend(slot for slot, _label, _cmd in FAMILY_FIELDS[self.family])
            if self.family == "award":
                cols.append("lang")
            cols.append("status")
            return cols

        def set_family_rows(self, family: str, rows: list[NameEntity]) -> None:
            self.beginResetModel()
            self.family = family
            self.rows = rows
            self.endResetModel()

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.columns())

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
                if self.columns()[section] == "section":
                    return FILE_SECTION_HINT
                return None
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                key = self.columns()[section]
                if key == "section":
                    return "File section"
                if key == "id":
                    return "ID"
                if key == "lang":
                    return "Language"
                if key == "status":
                    return "Status"
                for slot, label, _cmd in FAMILY_FIELDS[self.family]:
                    if slot == key:
                        return label
            return None

        def flags(self, index):
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            key = self.columns()[index.column()]
            slots = {slot for slot, _label, _cmd in FAMILY_FIELDS[self.family]}
            if key in slots:
                flags |= Qt.ItemIsEditable
            return flags

        def data(self, index, role=Qt.DisplayRole):
            if not index.isValid():
                return None
            entity = self.rows[index.row()]
            key = self.columns()[index.column()]
            slots = {slot for slot, _label, _cmd in FAMILY_FIELDS[self.family]}
            if role in (Qt.DisplayRole, Qt.EditRole):
                if key == "section":
                    return entity.section
                if key == "id":
                    if role == Qt.EditRole and entity.id.isdigit():
                        return int(entity.id)
                    return entity.id
                if key == "lang":
                    return entity.lang
                if key == "status":
                    return entity_status(entity)
                return entity.name_in(key)
            if role == Qt.FontRole and entity.changed():
                return self.bold
            if role == Qt.ForegroundRole and key == "status" and entity.duplicate():
                return QColor("#f59e0b")
            if role == Qt.ToolTipRole and key in slots:
                group = entity.slots.get(key) or []
                if len(group) > 1:
                    return "Duplicate lines: " + " | ".join(entry.name for entry in group)
                if group and group[0].changed and not group[0].imported:
                    return f"Was: {group[0].orig_name}"
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if role != Qt.EditRole:
                return False
            key = self.columns()[index.column()]
            slots = {slot for slot, _label, _cmd in FAMILY_FIELDS[self.family]}
            if key not in slots:
                return False
            entity = self.rows[index.row()]
            was_empty = not entity.slots.get(key)
            if not set_entity_field(entity, key, str(value), self.docs):
                return False
            self._structure = was_empty
            self.row_changed(index.row())
            return True

        def row_changed(self, row):
            self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

    class EntityProxy(QSortFilterProxyModel):
        def __init__(self):
            super().__init__()
            self.words: list[str] = []
            self.section = ""
            self.mode = "all"
            self.setSortRole(Qt.EditRole)
            self.setDynamicSortFilter(False)
            self.setSortCaseSensitivity(Qt.CaseInsensitive)

        def set_filter(self, text: str, section: str, mode: str) -> None:
            self.words = fold(text).split()
            self.section = section
            self.mode = mode
            self.invalidate()

        def filterAcceptsRow(self, row, parent):
            entity = self.sourceModel().rows[row]
            if self.section and entity.section != self.section:
                return False
            if self.mode == "edited" and not entity.changed():
                return False
            if self.mode == "missing_short" and not entity.missing("short"):
                return False
            if self.mode == "missing_code" and not entity.missing("code"):
                return False
            if self.words:
                parts = [entity.section, entity.id, entity.lang]
                parts.extend(
                    entity.name_in(slot) for slot, _label, _cmd in FAMILY_FIELDS[entity.family])
                hay = fold(" ".join(parts))
                return all(word in hay for word in self.words)
            return True

    class BulkDialog(QDialog):
        """Preview a bulk rename, then apply it in memory."""

        def __init__(self, parent, entities, docs):
            super().__init__(parent)
            self.setWindowTitle("Bulk transformer")
            self.resize(920, 560)
            self.entities = entities
            self.docs = docs
            self.edits: list[BulkEdit] = []
            self.applied = 0
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(
                "Works on the entities in the current filter. "
                "Preview comes first. Apply only marks the files as unsaved."))
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
            self.sponsor_box = QTextEdit()
            self.sponsor_box.setPlaceholderText("One sponsor phrase per line")
            self.sponsor_box.setPlainText("\n".join(STARTER_SPONSORS))
            self.sponsor_box.setMaximumHeight(110)
            lay.addWidget(self.sponsor_box)
            buttons = QHBoxLayout()
            preview = QPushButton("Preview")
            preview.clicked.connect(self.preview)
            buttons.addWidget(preview)
            buttons.addStretch(1)
            lay.addLayout(buttons)
            self.preview_label = QLabel("Choose Preview to see the changes. Nothing is written yet.")
            self.preview_label.setWordWrap(True)
            lay.addWidget(self.preview_label)
            self.table = QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(["File section", "ID", "Field", "Before", "After"])
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.setSelectionBehavior(QTableWidget.SelectRows)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table, 1)
            box = QDialogButtonBox()
            self.apply_btn = box.addButton("Apply", QDialogButtonBox.AcceptRole)
            box.addButton(QDialogButtonBox.Cancel)
            self.apply_btn.setEnabled(False)
            box.accepted.connect(self.apply_edits)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.mode_group.buttonClicked.connect(lambda _button: self.invalidate())
            self.sponsor_box.textChanged.connect(self.invalidate)
            self.sync_sponsor()

        def kind(self) -> str:
            button = self.mode_group.checkedButton()
            return button.property("kind") if button else "affix"

        def sync_sponsor(self) -> None:
            self.sponsor_box.setVisible(self.kind() == "sponsor")

        def invalidate(self) -> None:
            self.edits = []
            self.apply_btn.setEnabled(False)
            self.table.setRowCount(0)
            self.preview_label.setText("Choose Preview to see the changes. Nothing is written yet.")
            self.sync_sponsor()

        def preview(self) -> None:
            sponsors = self.sponsor_box.toPlainText().splitlines()
            self.edits = preview_bulk(self.entities, self.kind(), sponsors)
            self.table.setRowCount(len(self.edits))
            labels = {slot: label for slot, label, _cmd in FAMILY_FIELDS[self.entities[0].family]}
            for row, edit in enumerate(self.edits):
                field = labels.get(edit.slot, edit.slot)
                values = [edit.entity.section, edit.entity.id, field, edit.before, edit.after]
                for col, value in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            self.apply_btn.setEnabled(bool(self.edits))
            if self.kind() == "sponsor" and self.entities[0].family != "comp":
                note = " The sponsor cleanser only changes competitions."
            else:
                note = ""
            self.preview_label.setText(f"{len(self.edits)} line(s) would change.{note}")

        def apply_edits(self) -> None:
            if not self.edits:
                return
            self.applied = apply_bulk(self.edits, self.docs)
            self.accept()

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
        """Report licensing files, and set aside the name-mask set."""

        def __init__(self, parent, version: Path):
            super().__init__(parent)
            self.version = version
            self.rows: list[dict] = []
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
            toggle = QPushButton("Toggle selected name mask")
            toggle.clicked.connect(self.toggle_selected)
            row.addWidget(toggle)
            row.addStretch(1)
            close = QPushButton("Close")
            close.clicked.connect(self.accept)
            row.addWidget(close)
            lay.addLayout(row)
            self.refresh()

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
            verb = "disable" if row["state"] == "present" else "restore"
            target = row["path"]
            if row["state"] == "disabled":
                target = target.with_name(target.name + ".disabled")
            preflight = game_write_preflight(f"{verb} a licensing file", [target])
            if not confirm_game_write(
                    self, preflight, f"This will {verb} the file below.",
                    "A copy is stored in the backups folder first. The file is renamed "
                    "in one step and its contents are not changed."):
                return
            try:
                result = toggle_licence(self.version, row["rel"], BACKUP_ROOT)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not change the file:\n{exc}")
                return
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
        """Name a spelling profile and give it a note.

        ``check`` returns why a name cannot be used, or "". The problem is
        shown under the fields and the dialog stays open, so the text the
        user typed is never thrown away.
        """

        def __init__(self, parent, title: str, check, name: str = "", note: str = ""):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.check = check
            lay = QVBoxLayout(self)
            form = QFormLayout()
            self.name_edit = QLineEdit(name)
            self.name_edit.setMaxLength(80)
            self.note_edit = QLineEdit(note)
            self.note_edit.setPlaceholderText("Optional, for example: traditional English names")
            form.addRow("Name", self.name_edit)
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
            self.table = QTableWidget(0, 6)
            self.table.setHorizontalHeaderLabels(
                ["Type", "ID", "Language", "Open file", "Backup", "Note"])
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table, 1)
            box = QDialogButtonBox(QDialogButtonBox.Close)
            self.restore_btn = QPushButton("Restore into open file")
            self.restore_btn.setEnabled(False)
            box.addButton(self.restore_btn, QDialogButtonBox.ActionRole)
            self.restore_btn.clicked.connect(self.restore)
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
                values = [
                    friendly(row["command"]),
                    row["id"],
                    row["language"],
                    row["working"],
                    row["archived"],
                    row["note"],
                ]
                for column, value in enumerate(values):
                    self.table.setItem(index, column, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            text = describe_backup_match(len(rows), identical)
            if doc.dirty:
                text += " The open file has unsaved changes, and the comparison includes them."
            if how == "name" and manifest_entry(self.manifest_for(path)[0], path.name):
                text += (f" It is compared with {doc.path}, which has the same name but is "
                         "not the file this copy came from.")
            self.summary.setText(text)
            self.restore_btn.setEnabled(True)

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
            try:
                restore_into(doc, path)
            except (OSError, UnicodeError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not restore:\n{exc}")
                return
            parent = self.parent()
            if parent is not None:
                parent.reload_views()
            self.docs = parent.docs if parent is not None else self.docs
            self.show_diff()
            self.summary.setText(
                f"Restored {path.name} into the open file. Save or Deploy to write it.")

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
            self.muted = QColor("#8a94a6")

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
        header = view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setResizeContentsPrecision(200)
        return view

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
            self.table.resizeColumnsToContents()
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
            """Look for a running game once more, then close the dialog to write."""
            self.review.recheck()
            self.update_state()
            if self.review.preflight.blocked:
                QMessageBox.warning(self, APP_NAME, self.review.preflight.blocked_message())
                return
            if self.write_btn.isEnabled():
                self.accept()

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

    class MainWindow(QMainWindow):
        CHANGES_TAB = 2

        def __init__(self):
            super().__init__()
            self.docs: list[LncDoc] = []
            self.all_entities: list[NameEntity] = []
            self.family = "club"
            self.status_mode = "all"
            self.section_filter = ""
            self.inspector_entity = None
            self.inspector_edits: dict = {}
            self._filling = False
            self._updating = False
            self._inspector_family = ""
            self.state = load_state(STATE_ROOT)
            self.profiles: list[Profile] = []
            self.resize(1280, 820)

            self.line_model = EntryModel()
            self.model = self.line_model
            self.line_proxy = EntryProxy()
            self.proxy = self.line_proxy
            self.line_proxy.setSourceModel(self.line_model)
            self.line_model.dataChanged.connect(self.on_line_data)

            self.entity_model = EntityModel(self.docs)
            self.entity_proxy = EntityProxy()
            self.entity_proxy.setSourceModel(self.entity_model)
            self.entity_model.dataChanged.connect(self.on_entity_data)

            tb = self.addToolBar("Main")
            tb.setMovable(False)

            def act(text, slot, shortcut=None, tip=""):
                action = QAction(text, self)
                action.triggered.connect(slot)
                if shortcut:
                    action.setShortcut(shortcut)
                if tip:
                    action.setToolTip(tip)
                tb.addAction(action)
                return action

            act("Open files...", self.open_dialog, QKeySequence.Open)
            act("Quick load FM27", self.quick_load, tip="Open the name files in the selected database")
            self.save_act = act("Save", self.save, QKeySequence.Save)
            act("Deploy to FM27", self.deploy,
                tip="Write the open name files into lnc\\all after a backup")
            tb.addSeparator()
            self.import_act = act("Import older edits...", self.import_old)
            self.revert_act = act("Revert selected", self.revert_selected)
            self.problem_act = act("Problem lines...", self.show_problems)
            act("Licensing...", self.open_licensing)
            act("Bulk tools...", self.open_bulk)
            act("Replace...", self.open_replace, tip="Find and replace with a regular expression")
            act("Export pack...", self.export_pack, tip="Save edited names as JSON or CSV")
            act("Import pack...", self.import_pack, tip="Apply a JSON or CSV name pack")
            act("Backups...", self.open_backups, tip="Compare a backup with the open file and restore it")
            tb.addSeparator()
            tb.addWidget(QLabel(" Database "))
            self.version_box = QComboBox()
            self.version_box.setMinimumWidth(150)
            tb.addWidget(self.version_box)

            central = QWidget()
            outer = QVBoxLayout(central)
            outer.setContentsMargins(8, 8, 8, 8)
            header = QHBoxLayout()
            self.metrics = QLabel()
            self.metrics.setObjectName("metrics")
            header.addWidget(self.metrics, 1)
            header.addWidget(QLabel("Profile"))
            self.profile_box = QComboBox()
            self.profile_box.setMinimumWidth(220)
            self.profile_box.setToolTip(
                "A spelling profile keeps your preferred names after Save and Deploy, "
                "so they can be applied again when the game's files change.")
            header.addWidget(self.profile_box)
            self.record_btn = QPushButton("Record edits")
            self.record_btn.setToolTip(
                "Copy the unsaved name edits into this profile, with the names on disk "
                "as their baselines. Record before you Save or Deploy.")
            self.record_btn.clicked.connect(self.record_into_profile)
            header.addWidget(self.record_btn)
            self.apply_profile_btn = QPushButton("Apply...")
            self.apply_profile_btn.setToolTip(
                "Preview this profile's spellings against the open files. Nothing is "
                "written until you Save or Deploy.")
            self.apply_profile_btn.clicked.connect(self.apply_profile_to_files)
            header.addWidget(self.apply_profile_btn)
            self.manage_btn = QToolButton()
            self.manage_btn.setObjectName("manage")
            self.manage_btn.setText("Manage")
            self.manage_btn.setPopupMode(QToolButton.InstantPopup)
            manage_menu = QMenu(self.manage_btn)
            self.new_profile_act = QAction("New profile...", self)
            self.new_profile_act.triggered.connect(self.new_profile)
            self.rename_profile_act = QAction("Rename profile...", self)
            self.rename_profile_act.triggered.connect(self.rename_current_profile)
            self.delete_profile_act = QAction("Delete profile...", self)
            self.delete_profile_act.triggered.connect(self.delete_current_profile)
            for action in (self.new_profile_act, self.rename_profile_act,
                           self.delete_profile_act):
                manage_menu.addAction(action)
            self.manage_btn.setMenu(manage_menu)
            header.addWidget(self.manage_btn)
            outer.addLayout(header)
            self.tabs = QTabWidget()
            outer.addWidget(self.tabs, 1)
            self.setCentralWidget(central)

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
            self.entity_search = QLineEdit()
            self.entity_search.setPlaceholderText(
                "Search entities (accents ignored). Ctrl+F")
            self.entity_search.setClearButtonEnabled(True)
            status_row.addWidget(self.entity_search, 1)
            self.status_group = QButtonGroup(self)
            self.status_group.setExclusive(True)
            self.status_buttons = []
            for mode, label in (
                ("all", "All"),
                ("edited", "Edited"),
                ("missing_short", "No short-name override"),
                ("missing_code", "No code override"),
            ):
                button = QPushButton(label)
                button.setCheckable(True)
                button.setProperty("mode", mode)
                self.status_group.addButton(button)
                self.status_buttons.append(button)
                status_row.addWidget(button)
            entity_lay.addLayout(status_row)

            splitter = QSplitter()
            left = QWidget()
            left_lay = QVBoxLayout(left)
            left_lay.setContentsMargins(0, 0, 0, 0)
            left_lay.addWidget(QLabel("File sections"))
            self.section_list = QListWidget()
            left_lay.addWidget(self.section_list)
            splitter.addWidget(left)

            self.entity_view = QTableView()
            self.entity_view.setModel(self.entity_proxy)
            self.entity_view.setSortingEnabled(True)
            self.entity_view.setSelectionBehavior(QTableView.SelectRows)
            self.entity_view.setAlternatingRowColors(True)
            self.entity_view.verticalHeader().setVisible(False)
            self.entity_view.verticalHeader().setDefaultSectionSize(24)
            self.entity_view.setEditTriggers(
                QTableView.DoubleClicked | QTableView.EditKeyPressed)
            splitter.addWidget(self.entity_view)

            self.inspector = QWidget()
            self.inspector_lay = QVBoxLayout(self.inspector)
            self.inspector_lay.setContentsMargins(8, 0, 0, 0)
            splitter.addWidget(self.inspector)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([210, 760, 260])
            entity_lay.addWidget(splitter, 1)
            self.tabs.addTab(entity_page, "Entities")

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
            self.line_view.setSortingEnabled(True)
            self.line_view.setSelectionBehavior(QTableView.SelectRows)
            self.line_view.setAlternatingRowColors(True)
            self.line_view.verticalHeader().setVisible(False)
            self.line_view.verticalHeader().setDefaultSectionSize(24)
            self.line_view.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.line_view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
            line_lay.addWidget(self.line_view, 1)
            self.tabs.addTab(line_page, "All lines")

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
            change_lay.addWidget(self.change_view, 1)
            self.tabs.addTab(change_page, "Changes")
            self.change_search.textChanged.connect(self.change_proxy.set_filter)
            self.change_model.ticks_changed.connect(
                lambda: self.change_summary.setText(describe_ticks(self.change_model.rows)))

            self.pending_label = QLabel("")
            self.pending_label.setObjectName("warning")
            self.statusBar().addPermanentWidget(self.pending_label)

            find = QAction(self)
            find.setShortcut(QKeySequence.Find)
            find.triggered.connect(self.focus_find)
            self.addAction(find)

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
            self.tabs.currentChanged.connect(lambda _index: self.refresh_status())
            self.profile_box.currentIndexChanged.connect(lambda _index: self.on_profile_chosen())

            for button in self.family_buttons:
                button.setChecked(button.property("family") == "club")
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "all")
            self.refresh_versions()
            self.apply_family()
            self.refresh_status()
            self.refresh_profiles()

        def open_dialog(self):
            if not self.confirm_discard():
                return
            paths, _ = QFileDialog.getOpenFileNames(self, "Open .lnc files", "", FILTER)
            if paths:
                self.load(paths)

        def load(self, paths) -> bool:
            """Open the files as the new workspace.

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
                QMessageBox.critical(
                    self, APP_NAME,
                    f"{exc}\n\nNothing was opened. The current files are unchanged.")
                return False
            self.docs.clear()
            self.docs.extend(docs)
            self.family = "club"
            self.section_filter = ""
            self.status_mode = "all"
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "all")
            self.reload_views()
            self.tabs.setCurrentIndex(0)
            return True

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

        def review_and_write(self, operation: str, pairs, game_root, left_alone=()) -> bool:
            """Show the Review changes dialog for a Save or Deploy, then write.

            A running game refuses the write before the review opens, with
            the same message for Save and Deploy. Returns True when files
            were written.
            """
            review = WriteReview(operation, pairs, game_root, left_alone=left_alone)
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
            self.reload_views()
            self.statusBar().showMessage(review.outcome(archive), 10000)
            return True

        def confirm_discard(self) -> bool:
            if not any(d.dirty for d in self.docs):
                return True
            r = QMessageBox.question(
                self, APP_NAME, "You have unsaved changes. Save them first?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Save:
                self.save()
                return not any(d.dirty for d in self.docs)
            return r == QMessageBox.Discard

        def closeEvent(self, event):
            event.accept() if self.confirm_discard() else event.ignore()

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
            self.entity_proxy.set_filter(
                self.entity_search.text(), self.section_filter, self.status_mode)
            self.refresh_status()

        def import_old(self):
            if not self.docs:
                QMessageBox.information(self, APP_NAME,
                                        "Open the current version's .lnc files first.")
                return
            dlg = ImportDialog(self, self.docs)
            if dlg.exec() and dlg.result_counts:
                self.reload_views()
                changed, added = dlg.result_counts
                self.statusBar().showMessage(
                    f"Imported: {changed} names changed, {added} entries added. "
                    "Nothing is written until you press Save.", 10000)

        def revert_selected(self):
            """Restore orig_name on selected edits. Imported rows are left in place."""
            if self.tabs.currentIndex() == 0:
                self._revert_entities()
            elif self.tabs.currentIndex() == self.CHANGES_TAB:
                self._revert_changes()
            else:
                self._revert_lines()

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
            self.line_model.layoutChanged.emit()
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()
            self._revert_message(counts)

        def _revert_lines(self):
            rows = {self.line_proxy.mapToSource(index).row()
                    for index in self.line_view.selectionModel().selectedIndexes()}
            counts = {"name": 0, "rule": 0, "added": 0, "same": 0}
            for row in sorted(rows):
                outcome = revert_entry(self.line_model.rows[row])
                counts[outcome] += 1
                if outcome in ("name", "rule"):
                    self.line_model.row_changed(row)
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()
            self._revert_message(counts)

        def _revert_entities(self):
            rows = {self.entity_proxy.mapToSource(index).row()
                    for index in self.entity_view.selectionModel().selectedIndexes()}
            entries = [entry for row in sorted(rows)
                       for entry in self.entity_model.rows[row].entries()]
            counts = revert_entries(entries)
            self.line_model.layoutChanged.emit()
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()
            self._revert_message(counts)
            if self.inspector_entity is not None:
                self.show_inspector(self.inspector_entity)

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
            version = self.selected_version()
            version_name = version.name if version is not None else "none"
            self.metrics.setText(
                f"Database {version_name}    {clubs:,} clubs    "
                f"{comps:,} competitions    {unsaved}")
            changes = collect_changes(self.docs)
            self.tabs.setTabText(
                self.CHANGES_TAB, f"Changes ({len(changes):,})" if changes else "Changes")
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
            self.change_view.resizeColumnsToContents()
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
                label = path.name + (" names" if version_has_names(path) else "")
                self.version_box.addItem(label, str(path))
                if version_has_names(path):
                    chosen = path
            if chosen is not None:
                index = self.version_box.findData(str(chosen))
                if index >= 0:
                    self.version_box.setCurrentIndex(index)
            self.version_box.blockSignals(False)

        def rebuild_type_filter(self) -> None:
            """Refill the type combo from the name rows currently loaded.

            The current command filter is kept when that command is still present.
            Signals are blocked so refilling does not run the filter twice.
            """
            current = self.type_box.currentData() or ""
            self.type_box.blockSignals(True)
            self.type_box.clear()
            self.type_box.addItem("All types", "")
            for cmd in sorted({entry.cmd for entry in self.line_model.rows}, key=friendly):
                self.type_box.addItem(friendly(cmd), cmd)
            restored = self.type_box.findData(current)
            self.type_box.setCurrentIndex(restored if restored >= 0 else 0)
            self.type_box.blockSignals(False)

        def reload_views(self) -> None:
            if self._updating:
                return
            self._updating = True
            try:
                self.line_model.set_docs(self.docs)
                self.all_entities = build_entities(self.docs)
                self.rebuild_type_filter()
                self.family_group.blockSignals(True)
                for button in self.family_buttons:
                    button.setChecked(button.property("family") == self.family)
                self.family_group.blockSignals(False)
                self.apply_family()
                self.apply_line_filter()
                self._size_line_columns()
            finally:
                self._updating = False

        def _size_line_columns(self) -> None:
            for col in (0, 1, 2, 4, 5, 6):
                self.line_view.resizeColumnToContents(col)
            self.line_view.setColumnWidth(0, min(self.line_view.columnWidth(0), 240))

        def apply_family(self) -> None:
            if self._inspector_family != self.family:
                self.rebuild_inspector()
                self._inspector_family = self.family
            rows = [entity for entity in self.all_entities if entity.family == self.family]
            self.entity_model.set_family_rows(self.family, rows)
            self.refill_sections()
            self._size_entity_columns()
            self.apply_entity_filter()
            self.show_inspector(None)

        def _size_entity_columns(self) -> None:
            header = self.entity_view.horizontalHeader()
            columns = self.entity_model.columns()
            for index in range(len(columns)):
                header.setSectionResizeMode(index, QHeaderView.Interactive)
            stretch = "long" if "long" in columns else "name"
            if stretch in columns:
                header.setSectionResizeMode(columns.index(stretch), QHeaderView.Stretch)
            for index, key in enumerate(columns):
                if key != stretch:
                    self.entity_view.resizeColumnToContents(index)

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

        def on_section(self) -> None:
            if self._updating:
                return
            item = self.section_list.currentItem()
            self.section_filter = item.data(Qt.UserRole) if item is not None else ""
            if self.section_filter is None:
                self.section_filter = ""
            self.apply_entity_filter()

        def on_family_clicked(self, button) -> None:
            if self._updating:
                return
            self.family = button.property("family")
            self.section_filter = ""
            self.apply_family()

        def on_status_clicked(self, button) -> None:
            self.status_mode = button.property("mode")
            self.apply_entity_filter()

        def on_entity_selection(self) -> None:
            if self._updating or self._filling:
                return
            indexes = self.entity_view.selectionModel().selectedRows()
            if not indexes:
                self.show_inspector(None)
                return
            source = self.entity_proxy.mapToSource(indexes[0])
            if not source.isValid():
                return
            self.show_inspector(self.entity_model.rows[source.row()])

        def on_entity_data(self, *_args) -> None:
            structure = self.entity_model._structure
            self.entity_model._structure = False
            if structure:
                QTimer.singleShot(0, self.reload_views)
                return
            self.line_model.layoutChanged.emit()
            self.apply_entity_filter()

        def on_line_data(self, *_args) -> None:
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()
            if self.inspector_entity is not None:
                self.show_inspector(self.inspector_entity)

        def rebuild_inspector(self) -> None:
            while self.inspector_lay.count():
                item = self.inspector_lay.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.inspector_edits = {}
            self.inspector_title = QLabel("Select a row")
            self.inspector_title.setWordWrap(True)
            self.inspector_lay.addWidget(self.inspector_title)
            for slot, label, _cmd in FAMILY_FIELDS[self.family]:
                caption = QLabel(label)
                edit = QLineEdit()
                edit.editingFinished.connect(
                    lambda slot=slot, edit=edit: self.commit_inspector(slot, edit))
                self.inspector_edits[slot] = edit
                self.inspector_lay.addWidget(caption)
                self.inspector_lay.addWidget(edit)
            revert = QPushButton("Revert")
            revert.clicked.connect(self.revert_selected)
            self.inspector_lay.addWidget(revert)
            self.inspector_lay.addStretch(1)

        def show_inspector(self, entity) -> None:
            self._filling = True
            self.inspector_entity = entity
            if not self.inspector_edits:
                self._filling = False
                return
            if entity is None:
                self.inspector_title.setText("Select a row")
                for edit in self.inspector_edits.values():
                    edit.blockSignals(True)
                    edit.clear()
                    edit.blockSignals(False)
                self._filling = False
                return
            bits = [f"{FAMILY_LABELS[entity.family]} {entity.id}"]
            if entity.section:
                bits.append(entity.section)
            if entity.lang:
                bits.append(entity.lang)
            self.inspector_title.setText(" | ".join(bits))
            for slot, edit in self.inspector_edits.items():
                edit.blockSignals(True)
                edit.setText(entity.name_in(slot))
                edit.blockSignals(False)
            self._filling = False

        def commit_inspector(self, slot: str, edit) -> None:
            if self._filling:
                return
            entity = self.inspector_entity
            if entity is None:
                return
            was_empty = not entity.slots.get(slot)
            if not set_entity_field(entity, slot, edit.text(), self.docs):
                edit.blockSignals(True)
                edit.setText(entity.name_in(slot))
                edit.blockSignals(False)
                return
            if was_empty:
                QTimer.singleShot(0, self.reload_views)
                return
            self.line_model.layoutChanged.emit()
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()
            self.show_inspector(entity)

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
            self.load([str(path) for path in name_paths(version)])

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
            entities = self.visible_entities()
            if not entities:
                QMessageBox.information(
                    self, APP_NAME, "Nothing in the current entity filter.")
                return
            dialog = BulkDialog(self, entities, self.docs)
            if dialog.exec():
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
            if dialog.exec() and dialog.applied:
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
                self, "Export name pack", "fm-name-pack.json",
                "JSON name pack (*.json);;CSV name pack (*.csv)")
            if not path:
                return
            as_csv = path.casefold().endswith(".csv") or (
                selected.startswith("CSV") and not path.casefold().endswith(".json"))
            if as_csv and not path.casefold().endswith(".csv"):
                path += ".csv"
            elif not as_csv and not path.casefold().endswith(".json"):
                path += ".json"
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
                self, "Import name pack", "",
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
            if dialog.exec() and dialog.result_counts is not None:
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
            self.apply_profile_btn.setEnabled(chosen)
            self.rename_profile_act.setEnabled(chosen)
            self.delete_profile_act.setEnabled(chosen)

        def remember_profile(self) -> None:
            """Keep the chosen profile in the local state file for next time."""
            profile = self.current_profile()
            self.state["active_profile_file"] = profile.path.name if profile else ""
            try:
                save_state(self.state, STATE_ROOT)
            except OSError as exc:
                self.statusBar().showMessage(
                    f"Could not remember the chosen profile: {exc}", 8000)

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
            if dialog.exec() and dialog.result_counts is not None:
                updated, added = dialog.result_counts
                self.reload_views()
                self.statusBar().showMessage(
                    f"Profile {fresh.name} updated {updated} line(s) and added {len(added)}. "
                    "Nothing is written until you press Save or Deploy.", 10000)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
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
