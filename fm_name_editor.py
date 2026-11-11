#!/usr/bin/env python3
"""
FM Name Editor v2.1
===================
Browse and edit Football Manager .lnc name files. Clubs and competitions
are shown side by side (long name, short name, code). The line-by-line
table is still there. Edits can be carried across from an older version
by database ID, deployed into the FM27 database, and transformed in bulk.
Release 2.1 adds name packs, a backup browser, section-scoped replace,
and the UTF-16 Greek person-name file.

Requires:  pip install PySide6
Run:       python fm_name_editor.py [file1.lnc file2.lnc ...]

Design rules
------------
* Lines you do not touch are written back byte-for-byte as they were read.
* Editing a name replaces only the quoted name on that line.
* Bytes are built before any backup. A file outside the game tree still
  gets a timestamped .bak beside it. A file inside the game tree is copied
  into the project's backups folder instead.
* UTF-16 files, including the Greek person-name file, are written back
  in the encoding they were opened with.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

APP_NAME = "FM Name Editor"
VERSION = "2.1"

GAME_DB_ROOT = Path(
    r"D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db")
BACKUP_ROOT = Path(r"C:\FM Name Editor\backups")
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

PACK_FORMAT = "fm-name-pack"
PACK_VERSION = 1
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


class Entry:
    """One line of a .lnc file."""

    __slots__ = ("doc", "raw", "eol", "kind", "cmd", "id", "name", "lang",
                 "span", "section", "orig_name", "imported", "lineno", "_fold",
                 "source", "orig_source", "source_span")

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
        if self.changed:
            self.doc.dirty = True
            return
        self.doc.dirty = any(
            entry.kind in ("name", "person") and entry.changed
            for entry in self.doc.entries)

    def set_name(self, new: str):
        start, end = self.span
        self.raw = self.raw[:start] + '"' + new + '"' + self.raw[end:]
        self.span = (start, start + len(new) + 2)
        self.name = new
        self._note_edit()

    def set_source(self, new: str):
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
        self._note_edit()


def try_set_name(entry: Entry, new: str) -> bool:
    """Rename one line when the text is a single legal field."""
    cleaned = new.strip()
    if not name_is_legal(cleaned) or cleaned == entry.name:
        return False
    entry.set_name(cleaned)
    return True


def try_set_source(entry: Entry, new: str) -> bool:
    """Change the matched ending on a person-name rule."""
    if entry.kind != "person" or entry.source_span is None:
        return False
    cleaned = new.strip()
    if not name_is_legal(cleaned) or cleaned == entry.source:
        return False
    entry.set_source(cleaned)
    return True


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


class LncDoc:
    """A whole .lnc file, kept line-by-line so it can be written back exactly."""

    def __init__(self, path):
        self.path = Path(path)
        self.entries: list[Entry] = []
        self.dirty = False
        self.has_bom = False
        self.encoding = "utf-8"
        self.load()

    def load(self):
        self._read_into(self.path.read_bytes())

    def _read_into(self, data: bytes) -> None:
        """Replace the in-memory lines from already-read bytes.

        The path is left as it is. Assignment happens after a successful
        decode, so a bad file does not wipe the lines already loaded.
        """
        text, encoding, has_bom = decode_lnc_bytes(data)
        section = ""
        default_eol = "\r\n" if "\r\n" in text else "\n"
        entries: list[Entry] = []
        for n, line in enumerate(text.splitlines(keepends=True), 1):
            body = line.rstrip("\r\n")
            entry = Entry(self, body, line[len(body):], n)
            parse_line(entry)
            if entry.kind == "comment":
                heading = body.strip().lstrip("#").strip().rstrip(":").strip()
                if heading and not set(heading) <= set("=-_*~ "):
                    section = heading
            entry.section = section
            entries.append(entry)
        self.encoding = encoding
        self.has_bom = has_bom
        self.default_eol = default_eol
        self.entries = entries
        self.dirty = False

    def to_bytes(self) -> bytes:
        """Serialise every line, preserving BOM, encoding, and line endings.

        Raises:
            UnicodeEncodeError: the working text does not fit self.encoding.
                Callers should catch this and leave the original file untouched.
        """
        text = "".join(entry.raw + entry.eol for entry in self.entries)
        body = text.encode(self.encoding)
        if self.encoding == "utf-16-le":
            return (UTF16_LE_BOM if self.has_bom else b"") + body
        if self.encoding == "utf-16-be":
            return (UTF16_BE_BOM if self.has_bom else b"") + body
        return (UTF8_BOM if self.has_bom else b"") + body

    def mark_clean(self) -> None:
        """Treat the current names as the saved original."""
        for entry in self.entries:
            if entry.kind in ("name", "person"):
                entry.orig_name = entry.name
                entry.orig_source = entry.source
                entry.imported = False
        self.dirty = False

    def save(self, backup: bool = True) -> None:
        """Write this document back to its path.

        The full byte string is built first. If encoding fails, no backup is
        taken and the original file is not opened for writing. This path
        still uses a beside-file .bak. Saves into the game tree go through
        save_documents, which archives under the project backups folder.
        """
        payload = self.to_bytes()
        if backup and self.path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.bak-{stamp}"))
        self.path.write_bytes(payload)
        self.mark_clean()

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

    def append_entry(self, cmd, id_, name, lang) -> Entry:
        """Add a name line at the end of the file.

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
        self.entries.append(e)
        self.dirty = True
        return e


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
                 "section", "checked", "base", "note")

    def __init__(self, cmd, id_, lang, new, target, section, checked, base="", note="",
                 target_rows=None):
        self.cmd, self.id, self.lang, self.new = cmd, id_, lang, new
        self.base = base          # name in the unedited older original, if known
        self.note = note
        self.target = target      # Entry in the current file, or None if missing
        self.section = section
        self.checked = checked
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


def apply_proposals(changes, missing, docs):
    """Write ticked proposals into the loaded documents.

    A change updates every duplicate row, so two lines with the same
    database id cannot drift apart. A name that would break the line is
    left untouched.
    """
    n = 0
    for proposal in changes:
        if not proposal.checked:
            continue
        rows = proposal.target_rows or (
            [proposal.target] if proposal.target is not None else [])
        for target in rows:
            if target is not None and try_set_name(target, proposal.new):
                n += 1
    added = []
    for proposal in missing:
        if not proposal.checked:
            continue
        try:
            added.append(pick_doc_for(proposal.cmd, docs).append_entry(
                proposal.cmd, proposal.id, proposal.new, proposal.lang))
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


def insert_name_after(anchor: Entry, cmd: str, id_: str, name: str, lang: str) -> Entry:
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
    index_at = doc.entries.index(anchor) + 1
    doc.entries.insert(index_at, entry)
    for number, item in enumerate(doc.entries, 1):
        item.lineno = number
    doc.dirty = True
    return entry


def set_entity_field(entity: NameEntity, slot: str, new: str, docs) -> bool:
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
            if try_set_name(entry, cleaned):
                changed = True
        return changed
    cmd = command_for(entity.family, slot)
    anchor = next(entity.entries(), None)
    try:
        if anchor is not None:
            created = insert_name_after(anchor, cmd, entity.id, cleaned, entity.lang)
        else:
            created = pick_doc_for(cmd, docs).append_entry(cmd, entity.id, cleaned, entity.lang)
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


def apply_bulk(edits, docs) -> int:
    """Apply a preview. Returns how many lines changed.

    docs is unused; each edit already points at its line. It is kept so
    callers can pass the open documents beside the preview.
    """
    del docs
    count = 0
    for edit in edits:
        if try_set_name(edit.entry, edit.after):
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


def new_archive_dir(archive_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = archive_root / stamp
    suffix = 0
    while dest.exists():
        suffix += 1
        dest = archive_root / f"{stamp}-{suffix}"
    dest.mkdir(parents=True)
    return dest


def archive_files(paths: list[Path], archive_root: Path) -> Path:
    """Copy existing files into a new timestamped folder. Missing paths are skipped."""
    dest_dir = new_archive_dir(archive_root)
    used: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        name = path.name
        target = dest_dir / name
        if name.casefold() in used or target.exists():
            target = dest_dir / f"{path.stem}-{len(used)}{path.suffix}"
        shutil.copy2(path, target)
        used.add(name.casefold())
    return dest_dir


def save_documents(docs, game_root: Path | None, archive_root: Path) -> Path | None:
    """Write documents. Every payload is encoded before any backup is made.

    Files under game_root share one archive folder. Other files keep a
    timestamped .bak beside them. Returns the archive path, or None when
    no game file was copied.
    """
    if not docs:
        return None
    payloads = [(doc, doc.to_bytes()) for doc in docs]
    game_paths = [
        doc.path for doc, _payload in payloads
        if doc.path.exists() and under_game_tree(doc.path, game_root)
    ]
    archive = archive_files(game_paths, archive_root) if game_paths else None
    for doc, _payload in payloads:
        if doc.path.exists() and not under_game_tree(doc.path, game_root):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(doc.path, doc.path.with_name(f"{doc.path.name}.bak-{stamp}"))
    for doc, payload in payloads:
        doc.path.write_bytes(payload)
    for doc, _payload in payloads:
        doc.mark_clean()
    return archive


def deploy_documents(pairs, archive_root: Path) -> Path | None:
    """Write each document to its game destination.

    Payloads are written to temporary siblings first. Existing game files
    are archived only after that succeeds. A failed encode leaves the game
    files untouched and creates no archive.

    pairs: list of (LncDoc, destination Path).
    """
    staged = [(doc, dest, doc.to_bytes()) for doc, dest in pairs]
    written: list[Path] = []
    try:
        for _doc, dest, payload in staged:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".writing")
            tmp.write_bytes(payload)
            written.append(tmp)
        existing = [dest for _doc, dest, _payload in staged if dest.exists()]
        archive = archive_files(existing, archive_root) if existing else None
        for (_doc, dest, _payload), tmp in zip(staged, written):
            tmp.replace(dest)
        for doc, dest, _payload in staged:
            doc.path = dest
            doc.mark_clean()
        return archive
    except Exception:
        for tmp in written:
            tmp.unlink(missing_ok=True)
        raise


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


def licence_inventory(version_dir: Path) -> list[dict]:
    """Status of each known licensing file. Binary files are not opened."""
    rows = []
    for rel, toggle in (
        *((path, True) for path in MASK_FILES),
        *((path, False) for path in REPORT_FILES),
    ):
        src = version_dir / rel
        disabled = src.with_name(src.name + ".disabled")
        if src.is_file():
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

    The current file is copied into the archive first. Nothing is deleted.
    """
    if rel not in MASK_FILES:
        raise ValueError(f"Not a name-mask file: {rel}")
    src = version_dir / rel
    disabled = src.with_name(src.name + ".disabled")
    if src.is_file():
        archive_files([src], archive_root)
        src.rename(disabled)
        return "disabled"
    if disabled.is_file():
        archive_files([disabled], archive_root)
        disabled.rename(src)
        return "restored"
    raise FileNotFoundError(src)


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


def restore_into(doc: LncDoc, archive_file: Path) -> None:
    """Replace the open document's lines with a backup. The path is kept.

    Nothing is written to ``doc.path``. The caller saves or deploys later.
    """
    if not archive_file.is_file():
        raise FileNotFoundError(archive_file)
    doc._read_into(archive_file.read_bytes())
    doc.dirty = True


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def run_gui(paths):
    from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
                                Qt, QTimer)
    from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
    from PySide6.QtWidgets import (
        QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
        QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
        QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
        QPlainTextEdit, QPushButton, QRadioButton, QSplitter, QTableView,
        QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
        QWidget)

    FILTER = "FM name files (*.lnc);;All files (*)"

    # ---------------- main table ----------------
    class EntryModel(QAbstractTableModel):
        COLS = ["Section or ending", "Type", "ID", "Name", "Language", "File", "Status"]
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
                if name == "Your older name": return p.new
                if name == "Language": return p.lang
                if name == "Section": return p.section
                if name == "Older original": return p.base
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
                ["Use", "Section", "Type", "ID", "Current name", "Your older name",
                 "Older original", "Note", "Language"])
            self.missing_model = ProposalModel(
                ["Use", "Section", "Type", "ID", "Your older name", "Older original", "Note",
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
            except OSError as exc:
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
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                key = self.columns()[section]
                if key == "section":
                    return "Section"
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
            self.table.setHorizontalHeaderLabels(["Section", "ID", "Field", "Before", "After"])
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
            labels = {"present": "Present", "disabled": "Disabled", "missing": "Missing"}
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
            verb = "disable" if row["state"] == "present" else "restore"
            target = row["path"]
            if row["state"] == "disabled":
                target = target.with_name(target.name + ".disabled")
            preflight = game_write_preflight(f"{verb} a licensing file", [target])
            if not confirm_game_write(
                    self, preflight, f"This will {verb} the file below.",
                    "A copy is stored in the backups folder first."):
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
            form.addWidget(QLabel("Section"))
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
                ["Section", "Type", "ID", "Before", "After"])
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
            self.applied = apply_bulk(self.edits, self.docs)
            self.accept()

    class PackDialog(QDialog):
        """Tick pack rows, then apply them to the open files."""

        def __init__(self, parent, changes, missing, summary: str):
            super().__init__(parent)
            self.setWindowTitle("Import name pack")
            self.resize(980, 620)
            self.changes = changes
            self.missing = missing
            self.result_counts = None
            lay = QVBoxLayout(self)
            self.summary = QLabel(summary)
            self.summary.setWordWrap(True)
            lay.addWidget(self.summary)
            self.tabs = QTabWidget()
            self.change_model = ProposalModel(
                ["Use", "Section", "Type", "ID", "Current name", "Your older name",
                 "Note", "Language"])
            self.missing_model = ProposalModel(
                ["Use", "Section", "Type", "ID", "Your older name", "Note", "Language"])
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
            self.result_counts = apply_proposals(self.changes, self.missing, self.parent().docs)
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
            if not self.archives:
                self.summary.setText("No backups yet. Save or Deploy a game file to create one.")
            for folder in self.archives:
                self.archive_list.addItem(folder.name)
            if self.archives:
                self.archive_list.setCurrentRow(0)

        def show_archive(self, row: int):
            self.file_list.clear()
            self.table.setRowCount(0)
            self.restore_btn.setEnabled(False)
            if row < 0 or row >= len(self.archives):
                return
            folder = self.archives[row]
            files = sorted(
                (path for path in folder.iterdir() if path.is_file()),
                key=lambda path: path.name.casefold())
            for path in files:
                item = QListWidgetItem(f"{path.name}  ({path.stat().st_size} bytes)")
                item.setData(Qt.UserRole, str(path))
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
            found = [
                doc for doc in self.docs
                if doc.path.name.casefold() == path.name.casefold()
            ]
            if len(found) == 1:
                return found[0]
            return None

        def show_diff(self):
            self.table.setRowCount(0)
            self.restore_btn.setEnabled(False)
            path = self.selected_file()
            if path is None:
                return
            if path.suffix.casefold() != ".lnc":
                self.summary.setText(
                    "That backup is not a name file. It is listed so you can see it "
                    "was archived. Restore it from Licensing, not from here.")
                return
            doc = self.matching_doc(path)
            if doc is None:
                self.summary.setText(
                    f"Open a file named {path.name} before comparing or restoring it.")
                return
            try:
                archived = LncDoc(path)
            except (OSError, UnicodeError) as exc:
                self.summary.setText(f"Could not read the backup:\n{exc}")
                return
            rows = diff_documents(doc, archived)
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
            if rows:
                self.summary.setText(f"{len(rows)} difference(s) against the open file.")
            else:
                self.summary.setText("The open file matches this backup.")
            self.restore_btn.setEnabled(True)

        def restore(self):
            path = self.selected_file()
            doc = None if path is None else self.matching_doc(path)
            if path is None or doc is None:
                return
            answer = QMessageBox.question(
                self, APP_NAME,
                f"Replace the open {doc.path.name} with the copy from "
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

    class MainWindow(QMainWindow):
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
            self.metrics = QLabel()
            self.metrics.setObjectName("metrics")
            outer.addWidget(self.metrics)
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
                ("missing_short", "Missing short name"),
                ("missing_code", "Missing code"),
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
            left_lay.addWidget(QLabel("Sections"))
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

            for button in self.family_buttons:
                button.setChecked(button.property("family") == "club")
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "all")
            self.refresh_versions()
            self.apply_family()
            self.refresh_status()

        def open_dialog(self):
            if not self.confirm_discard():
                return
            paths, _ = QFileDialog.getOpenFileNames(self, "Open .lnc files", "", FILTER)
            if paths:
                self.load(paths)

        def load(self, paths):
            docs = []
            for path in paths:
                try:
                    docs.append(LncDoc(path))
                except OSError as exc:
                    QMessageBox.critical(self, APP_NAME, f"Could not open {path}:\n{exc}")
            self.docs.clear()
            self.docs.extend(docs)
            self.family = "club"
            self.section_filter = ""
            self.status_mode = "all"
            for button in self.status_buttons:
                button.setChecked(button.property("mode") == "all")
            self.reload_views()
            self.tabs.setCurrentIndex(0)

        def save(self):
            """Write every dirty document, and report encode errors without crashing.

            A document that lives inside the game tree goes through the same
            preflight as Deploy: refused while the game runs, and confirmed
            with the exact paths first. Files elsewhere are written as before.
            """
            dirty = [doc for doc in self.docs if doc.dirty]
            if not dirty:
                self.statusBar().showMessage("Nothing to save.", 4000)
                return
            preflight = game_write_preflight("Save", [doc.path for doc in dirty], GAME_DB_ROOT)
            if preflight.game_paths and not confirm_game_write(
                    self, preflight, "Save these files into the game folder?",
                    "A copy of each existing game file is stored under backups first."):
                return
            try:
                archive = save_documents(dirty, GAME_DB_ROOT, BACKUP_ROOT)
            except (OSError, UnicodeError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Save failed:\n{exc}")
                return
            self.reload_views()
            if archive is not None:
                message = (
                    f"Saved {len(dirty)} file(s). Game files were copied to {archive} first.")
            else:
                message = (
                    f"Saved {len(dirty)} file(s). Backups written alongside as .bak-<date>.")
            self.statusBar().showMessage(message, 8000)

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
            else:
                self._revert_lines()

        def _revert_lines(self):
            rows = {self.line_proxy.mapToSource(index).row()
                    for index in self.line_view.selectionModel().selectedIndexes()}
            changed = 0
            skipped_added = 0
            for row in rows:
                entry = self.line_model.rows[row]
                if entry.imported:
                    skipped_added += 1
                    continue
                if entry.name != entry.orig_name:
                    entry.set_name(entry.orig_name)
                    self.line_model.row_changed(row)
                    changed += 1
            self._revert_message(changed, skipped_added)
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()

        def _revert_entities(self):
            rows = {self.entity_proxy.mapToSource(index).row()
                    for index in self.entity_view.selectionModel().selectedIndexes()}
            changed = 0
            skipped_added = 0
            for row in rows:
                for entry in self.entity_model.rows[row].entries():
                    if entry.imported:
                        skipped_added += 1
                        continue
                    if entry.name != entry.orig_name:
                        entry.set_name(entry.orig_name)
                        changed += 1
            self.line_model.layoutChanged.emit()
            self.entity_model.layoutChanged.emit()
            self.apply_entity_filter()
            self._revert_message(changed, skipped_added)
            if self.inspector_entity is not None:
                self.show_inspector(self.inspector_entity)

        def _revert_message(self, changed: int, skipped_added: int) -> None:
            message = f"Reverted {changed} name(s)."
            if skipped_added:
                message += f" Left {skipped_added} added row(s) unchanged."
            self.statusBar().showMessage(message, 5000)

        def show_problems(self):
            lines = [f"{e.doc.path.name}  line {e.lineno}:  {e.raw}"
                     for d in self.docs for e in d.problems()]
            dlg = QDialog(self)
            dlg.setWindowTitle("Problem lines")
            dlg.resize(900, 400)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel(
                "These lines look malformed (usually a missing or doubled quote). "
                "They are left exactly as they are when saving."))
            box = QPlainTextEdit("\n".join(lines) or "No problem lines found.")
            box.setReadOnly(True)
            box.setLineWrapMode(QPlainTextEdit.NoWrap)
            lay.addWidget(box)
            dlg.exec()

        def refresh_status(self, *_):
            total = len(self.line_model.rows)
            changed = sum(1 for entry in self.line_model.rows if entry.changed)
            dirty = any(doc.dirty for doc in self.docs)
            names = ", ".join(doc.path.name for doc in self.docs) or "no files open"
            self.setWindowTitle(f"{'* ' if dirty else ''}{APP_NAME} {VERSION} - {names}")
            clubs = sum(1 for entity in self.all_entities if entity.family == "club")
            comps = sum(1 for entity in self.all_entities if entity.family == "comp")
            version = self.selected_version()
            version_name = version.name if version is not None else "none"
            self.metrics.setText(
                f"Database {version_name}    {clubs:,} clubs    "
                f"{comps:,} competitions    {changed:,} unsaved")
            if self.tabs.currentIndex() == 0:
                shown = self.entity_proxy.rowCount()
                self.statusBar().showMessage(
                    f"{shown:,} entities shown    |    {total:,} name lines    |    "
                    "double-click a cell to edit")
            else:
                self.statusBar().showMessage(
                    f"{self.line_proxy.rowCount():,} shown of {total:,} names    |    "
                    f"{changed:,} unsaved change(s)    |    double-click a name to edit")

        def focus_find(self):
            box = self.entity_search if self.tabs.currentIndex() == 0 else self.line_search
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
            note = "A copy of each existing game file is stored under backups first."
            if skipped:
                note += "\n\nLeft untouched:\n" + "\n".join(skipped)
            preflight = game_write_preflight("Deploy", [dest for _doc, dest in pairs])
            if not confirm_game_write(self, preflight, "Deploy these files into the game?", note):
                return
            try:
                archive = deploy_documents(pairs, BACKUP_ROOT)
            except (OSError, UnicodeError) as exc:
                QMessageBox.critical(self, APP_NAME, f"Deploy failed:\n{exc}")
                return
            self.reload_views()
            where = str(archive) if archive is not None else "no previous file to copy"
            self.statusBar().showMessage(
                f"Deployed {len(pairs)} file(s). Backup: {where}", 10000)

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
                Path(path).write_bytes(data)
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
            dialog = PackDialog(self, changes, missing, summary)
            if dialog.exec() and dialog.result_counts is not None:
                updated, added = dialog.result_counts
                self.reload_views()
                self.statusBar().showMessage(
                    f"Name pack updated {updated} line(s) and added {len(added)}. "
                    "Nothing is written until you press Save or Deploy.",
                    10000)

        def open_backups(self) -> None:
            BackupDialog(self, self.docs).exec()

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
