"""Checks for the name editor engine, and headless window tests.

The Steam database is only read, and only when it is present. Writes use
temporary copies.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Without real fonts, offscreen Qt guesses text widths and the window comes up
# far wider than it is on the desktop, so size checks would mean nothing.
if Path(r"C:\Windows\Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fm_name_editor as editor

_SANDBOX: list = []


def setUpModule():
    """Point every folder the editor writes to at a temporary folder for the whole run.

    Tests that need their own folders still patch these; this only makes
    sure nothing reaches the real backups, profiles, or state folders.
    """
    sandbox = tempfile.TemporaryDirectory()
    _SANDBOX.append(sandbox)
    root = Path(sandbox.name)
    for name in ("BACKUP_ROOT", "PROFILE_ROOT", "STATE_ROOT"):
        patcher = mock.patch.object(editor, name, root / name.split("_")[0].lower())
        patcher.start()
        _SANDBOX.append(patcher)
    # A dialog that opens without a stand-in would wait for a click that never
    # comes, and the run would hang. Make it fail the test instead.
    try:
        from PySide6.QtWidgets import QDialog
    except ImportError:
        return

    def unattended(dialog):
        raise AssertionError(f"The dialog {dialog.windowTitle()!r} opened without a stand-in.")

    guard = mock.patch.object(QDialog, "exec", unattended)
    guard.start()
    _SANDBOX.append(guard)


def tearDownModule():
    for item in reversed(_SANDBOX):
        if isinstance(item, tempfile.TemporaryDirectory):
            item.cleanup()
        else:
            item.stop()
    _SANDBOX.clear()

BOM = b"\xef\xbb\xbf"
LIVE_DIR = Path(
    r"D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db"
    r"\2700\lnc\all")
GREEK_FILE = Path(
    r"D:\Steam\steamapps\common\Football Manager 27\shared\data\database\db"
    r"\2700\lnc\greek\person_name_changes.lnc")


def write_lnc(path: Path, text: str, bom: bool = True) -> None:
    """Write a UTF-8 .lnc file with LF endings, matching the FM27 name files."""
    data = text.encode("utf-8")
    path.write_bytes((BOM if bom else b"") + data)


def close_window(win) -> None:
    """Close and delete a test window, without the unsaved-changes prompt.

    Deleting matters: each new window sets the application style sheet again,
    which restyles every widget still alive, so closed windows left around
    make every later window test slower.
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    for doc in win.docs:
        doc.mark_clean()
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def failing_replace(*targets):
    """An os.replace that refuses to replace these paths and works for every other."""
    real = os.replace
    keys = {os.path.normcase(str(path)) for path in targets}

    def replace(src, dst):
        if os.path.normcase(str(dst)) in keys:
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)

    return replace


def staging_files(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir() if path.name.endswith(".writing"))


def press_write(seen: list):
    """A stand-in for QDialog.exec: note the Review changes dialog, then press its Write button.

    Write is the dialog's own button (Save or Deploy). The dialog closes only
    when it would really write; ``result()`` says whether it did.
    """
    def run(dialog):
        seen.append(dialog)
        dialog.try_write()
        return dialog.result()
    return run


class LegalNames(unittest.TestCase):
    def test_rejects_empty_quote_and_controls(self):
        self.assertFalse(editor.name_is_legal(""))
        self.assertFalse(editor.name_is_legal('Say "hi"'))
        self.assertFalse(editor.name_is_legal("Line\nbreak"))
        self.assertFalse(editor.name_is_legal("Line\rbreak"))
        self.assertTrue(editor.name_is_legal("Skënderbeu"))
        self.assertTrue(editor.name_is_legal("Tab\tname"))

    def test_try_set_name_leaves_the_line_when_illegal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            write_lnc(path, '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n')
            doc = editor.LncDoc(path)
            entry = doc.names()[0]
            raw = entry.raw
            self.assertFalse(editor.try_set_name(entry, "Bad\nName"))
            self.assertEqual(entry.raw, raw)
            self.assertEqual(entry.name, "Alpha")


class RoundTrip(unittest.TestCase):
    def test_untouched_file_matches_bytes(self):
        text = (
            "#England\n"
            '"CLUB_NAME_CHANGE"\t1\t"Manchester United"\t""\n'
            "\n"
            "not a command\n"
            '"CLUB_NAME_CHANGE"\t2\t"Broken\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            write_lnc(path, text)
            original = path.read_bytes()
            doc = editor.LncDoc(path)
            self.assertTrue(doc.has_bom)
            self.assertEqual(doc.to_bytes(), original)
            self.assertEqual(len(doc.problems()), 1)

    def test_edit_changes_only_the_quoted_name(self):
        text = '#England\n"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            write_lnc(path, text)
            doc = editor.LncDoc(path)
            self.assertTrue(editor.try_set_name(doc.names()[0], "Beta"))
            body = doc.to_bytes().decode("utf-8-sig")
            self.assertIn('"Beta"', body)
            self.assertNotIn('"Alpha"', body)
            self.assertTrue(body.startswith("#England\n"))


class SaveAndDeploy(unittest.TestCase):
    def test_encode_failure_does_not_write_a_backup(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            write_lnc(path, text)
            original = path.read_bytes()
            doc = editor.LncDoc(path)
            doc.encoding = "cp1252"
            self.assertTrue(editor.try_set_name(doc.names()[0], "\u0100"))
            with self.assertRaises(UnicodeEncodeError):
                doc.save()
            self.assertEqual(list(path.parent.glob("*.bak-*")), [])
            self.assertEqual(path.read_bytes(), original)

    def test_game_tree_save_uses_the_archive(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "db"
            archive = root / "backups"
            path = game / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            path.parent.mkdir(parents=True)
            write_lnc(path, text)
            doc = editor.LncDoc(path)
            editor.try_set_name(doc.names()[0], "Beta")
            saved = editor.save_documents([doc], game, archive)
            self.assertIsNotNone(saved)
            self.assertEqual((saved / path.name).read_bytes()[:3], BOM)
            self.assertIn(b'"Alpha"', (saved / path.name).read_bytes())
            self.assertIn(b'"Beta"', path.read_bytes())
            self.assertEqual(list(path.parent.glob("*.bak-*")), [])
            self.assertFalse(doc.dirty)

    def test_outside_save_keeps_a_beside_bak(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "notes" / "mine.lnc"
            path.parent.mkdir()
            write_lnc(path, text)
            doc = editor.LncDoc(path)
            editor.try_set_name(doc.names()[0], "Beta")
            archive = editor.save_documents([doc], root / "db", root / "backups")
            self.assertIsNone(archive)
            backups = list(path.parent.glob("*.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn(b'"Alpha"', backups[0].read_bytes())

    def test_deploy_archives_before_replacing(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "game" / "FM27_Club_Names.lnc"
            dest.parent.mkdir()
            write_lnc(dest, text)
            original = dest.read_bytes()
            doc = editor.LncDoc(dest)
            editor.try_set_name(doc.names()[0], "Beta")
            archive = editor.deploy_documents([(doc, dest)], root / "backups")
            self.assertEqual((archive / dest.name).read_bytes(), original)
            self.assertIn(b'"Beta"', dest.read_bytes())
            self.assertEqual(list(dest.parent.glob("*.writing")), [])
            self.assertEqual(list(dest.parent.glob("*.bak-*")), [])
            self.assertEqual(doc.path, dest)

    def test_deploy_encode_failure_leaves_the_destination(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "game" / "FM27_Club_Names.lnc"
            dest.parent.mkdir()
            write_lnc(dest, text)
            original = dest.read_bytes()
            doc = editor.LncDoc(dest)
            doc.encoding = "cp1252"
            editor.try_set_name(doc.names()[0], "\u0100")
            with self.assertRaises(UnicodeEncodeError):
                editor.deploy_documents([(doc, dest)], root / "backups")
            self.assertEqual(dest.read_bytes(), original)
            self.assertFalse((root / "backups").exists())


class ImportProposals(unittest.TestCase):
    def _doc(self, folder: Path, name: str, line: str) -> editor.LncDoc:
        path = folder / name
        write_lnc(path, line + "\n")
        return editor.LncDoc(path)

    def test_renamed_since_is_not_pre_ticked_and_skips_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base = self._doc(folder, "base.lnc", '"CLUB_NAME_CHANGE"\t1\t"Old Stock"\t""')
            old = self._doc(folder, "old.lnc", '"CLUB_NAME_CHANGE"\t1\t"My Name"\t""')
            target = self._doc(folder, "new.lnc", '"CLUB_NAME_CHANGE"\t1\t"New Stock"\t""')
            old.names()[0].name = 'Say "hi"'
            changes, _missing, stats = editor.build_proposals([target], [old], [base])
            self.assertEqual(changes, [])
            self.assertEqual(stats["skipped"], 1)

            old.names()[0].name = "My Name"
            changes, _missing, _stats = editor.build_proposals([target], [old], [base])
            self.assertEqual(len(changes), 1)
            self.assertFalse(changes[0].checked)
            self.assertEqual(changes[0].note, "Renamed since")

    def test_personal_edit_is_pre_ticked(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base = self._doc(folder, "base.lnc", '"CLUB_NAME_CHANGE"\t1\t"Stock"\t""')
            old = self._doc(folder, "old.lnc", '"CLUB_NAME_CHANGE"\t1\t"My Name"\t""')
            target = self._doc(folder, "new.lnc", '"CLUB_NAME_CHANGE"\t1\t"Stock"\t""')
            changes, _missing, _stats = editor.build_proposals([target], [old], [base])
            self.assertTrue(changes[0].checked)
            self.assertEqual(changes[0].note, "")

    def test_duplicate_ids_all_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            target = self._doc(
                folder, "new.lnc",
                '"CLUB_NAME_CHANGE"\t5\t"Alpha"\t""\n'
                '"CLUB_NAME_CHANGE"\t5\t"Beta"\t""')
            old = self._doc(folder, "old.lnc", '"CLUB_NAME_CHANGE"\t5\t"Gamma"\t""')
            changes, _missing, _stats = editor.build_proposals([target], [old], None)
            self.assertEqual(len(changes[0].target_rows), 2)
            self.assertFalse(changes[0].checked)
            changes[0].checked = True
            count, _added = editor.apply_proposals(changes, [], [target])
            self.assertEqual(count, 2)
            self.assertEqual([entry.name for entry in target.names()], ["Gamma", "Gamma"])


class EntitiesAndBulk(unittest.TestCase):
    def sample(self, folder: Path) -> editor.LncDoc:
        text = (
            "#England\n"
            '"CLUB_NAME_CHANGE"\t1\t"Manchester United FC"\t""\n'
            '"CLUB_SHORT_NAME_CHANGE"\t1\t"Man Utd"\t""\n'
            '"CLUB_3LETTER_NAME_CHANGE"\t1\t"MUN"\t""\n'
            '"CLUB_SHORT_NAME_CHANGE"\t2\t"Arsenal"\t""\n'
            '"CLUB_NAME_CHANGE"\t3\t"FC Barcelona"\t""\n'
            "#Competitions\n"
            '"COMP_LONG_NAME_CHANGE"\t9\t"Sky Bet Championship"\t""\n'
            '"COMP_SHORT_NAME_CHANGE"\t9\t"Championship"\t""\n'
            '"COMP_LONG_NAME_CHANGE"\t10\t"PARIS SAINT-GERMAIN"\t""\n'
            '"STADIUM_NAME_CHANGE"\t4\t"Old Trafford"\t""\n'
        )
        path = folder / "FM27_Club_Names.lnc"
        write_lnc(path, text)
        return editor.LncDoc(path)

    def test_union_and_empty_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self.sample(Path(tmp))
            clubs = [entity for entity in editor.build_entities([doc]) if entity.family == "club"]
            by_id = {entity.id: entity for entity in clubs}
            self.assertEqual(by_id["1"].name_in("long"), "Manchester United FC")
            self.assertEqual(by_id["1"].name_in("short"), "Man Utd")
            self.assertEqual(by_id["1"].name_in("code"), "MUN")
            self.assertEqual(by_id["1"].section, "England")
            self.assertTrue(by_id["2"].missing("long"))
            self.assertTrue(by_id["2"].missing("code"))
            self.assertEqual(by_id["3"].section, "England")
            comps = [entity for entity in editor.build_entities([doc]) if entity.family == "comp"]
            self.assertTrue(all(entity.missing("code") for entity in comps))

    def test_empty_cell_inserts_beside_the_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self.sample(Path(tmp))
            entity = next(
                item for item in editor.build_entities([doc])
                if item.family == "club" and item.id == "2")
            self.assertTrue(editor.set_entity_field(entity, "long", "Arsenal FC", [doc]))
            names = [(entry.id, entry.cmd, entry.name, entry.section) for entry in doc.names()]
            self.assertIn(("2", "CLUB_NAME_CHANGE", "Arsenal FC", "England"), names)
            self.assertTrue(entity.slots["long"][0].imported)

    def test_affix_sponsor_and_title(self):
        self.assertEqual(editor.strip_affix("Manchester United FC"), "Manchester United")
        self.assertEqual(editor.strip_affix("FC Barcelona"), "Barcelona")
        self.assertEqual(editor.strip_affix("AFC Bournemouth"), "Bournemouth")
        self.assertEqual(editor.strip_affix("AC Milan"), "Milan")
        self.assertEqual(editor.strip_affix("SK Rapid Wien"), "Rapid Wien")
        self.assertEqual(editor.strip_affix("Calcio"), "Calcio")
        self.assertEqual(editor.strip_affix("Athletic Club"), "Athletic Club")
        self.assertEqual(
            editor.strip_sponsor("Sky Bet Championship", ["Sky Bet", "Barclays"]),
            "Championship")
        self.assertEqual(
            editor.strip_sponsor("Barclays Women's Super League", ["Barclays"]),
            "Women's Super League")
        self.assertEqual(
            editor.strip_sponsor("League Sky Bet", ["Sky Bet"]), "League")
        self.assertEqual(editor.strip_sponsor("Championship", ["Sky Bet"]), "Championship")
        self.assertEqual(editor.title_case_name("PARIS SAINT-GERMAIN"), "Paris Saint-Germain")
        self.assertEqual(editor.title_case_name("THE CLUB OF ROME"), "The Club of Rome")
        self.assertEqual(editor.title_case_name("VAN DE BEEK"), "Van de Beek")
        self.assertEqual(editor.title_case_name("Manchester United"), "Manchester United")

    def test_preview_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self.sample(Path(tmp))
            entities = [
                entity for entity in editor.build_entities([doc]) if entity.family == "club"]
            edits = editor.preview_bulk(entities, "affix")
            befores = {edit.before for edit in edits}
            self.assertIn("Manchester United FC", befores)
            self.assertIn("FC Barcelona", befores)
            self.assertEqual(doc.names()[0].name, "Manchester United FC")
            self.assertGreater(editor.apply_bulk(edits, [doc]), 0)
            self.assertEqual(doc.names()[0].name, "Manchester United")


class Licensing(unittest.TestCase):
    def test_toggle_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = root / "2700"
            rel = editor.MASK_FILES[-1]
            src = version / rel
            src.parent.mkdir(parents=True)
            src.write_bytes(b"mask-bytes")
            rows = {row["name"]: row for row in editor.licence_inventory(version)}
            self.assertEqual(rows[rel.as_posix()]["state"], "present")
            self.assertTrue(rows[rel.as_posix()]["toggle"])
            result = editor.toggle_licence(version, rel, root / "backups")
            self.assertEqual(result, "disabled")
            self.assertFalse(src.exists())
            self.assertTrue(src.with_name(src.name + ".disabled").is_file())
            archived = list((root / "backups").rglob("fake.edt"))
            self.assertEqual(archived[0].read_bytes(), b"mask-bytes")
            self.assertEqual(editor.toggle_licence(version, rel, root / "backups"), "restored")
            self.assertEqual(src.read_bytes(), b"mask-bytes")

    def test_report_only_file_is_not_toggled(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                editor.toggle_licence(Path(tmp), editor.REPORT_FILES[0], Path(tmp) / "backups")


class ProcessList(unittest.TestCase):
    def test_parser_finds_fm_only(self):
        text = (
            '"fm.exe","1234","Console","1","12,345 K"\n'
            '"notepad.exe","1","Console","1","1 K"\n'
            '"Football Manager 27.exe","2","Console","1","1 K"\n'
        )
        self.assertEqual(
            editor.process_names_from_tasklist(text),
            ["fm.exe", "Football Manager 27.exe"])


@unittest.skipUnless(LIVE_DIR.is_dir(), "FM27 name files are not on this machine")
class LiveFiles(unittest.TestCase):
    def test_read_only_round_trip(self):
        docs = []
        for name, lines in (("FM27_Club_Names.lnc", 8935), ("FM27_Fix.lnc", 9092)):
            path = LIVE_DIR / name
            original = path.read_bytes()
            self.assertTrue(original.startswith(BOM))
            self.assertNotIn(b"\r", original)
            doc = editor.LncDoc(path)
            self.assertEqual(doc.to_bytes(), original)
            self.assertEqual(len(original.splitlines()), lines)
            docs.append(doc)
        entities = editor.build_entities(docs)
        clubs = [entity for entity in entities if entity.family == "club"]
        comps = [entity for entity in entities if entity.family == "comp"]
        # The raw command count includes the blank header line, so the entity
        # view has one fewer club than that token count.
        club_text = (LIVE_DIR / "FM27_Club_Names.lnc").read_text(encoding="utf-8-sig")
        self.assertEqual(club_text.count('"CLUB_SHORT_NAME_CHANGE"'), 4298)
        self.assertEqual(len(clubs), 4297)
        self.assertGreaterEqual(len(comps), 3600)
        self.assertTrue(all(entity.missing("code") or entity.name_in("code") for entity in comps))
        self.assertTrue(all(not entity.slots.get("code") for entity in comps))
        self.assertEqual(path.read_bytes(), original)

    @unittest.skipUnless(GREEK_FILE.is_file(), "Greek person-name file is not on this machine")
    def test_greek_file_round_trip(self):
        original = GREEK_FILE.read_bytes()
        doc = editor.LncDoc(GREEK_FILE)
        self.assertEqual(doc.encoding, "utf-16-le")
        self.assertTrue(doc.has_bom)
        self.assertEqual(doc.to_bytes(), original)
        self.assertEqual(len(doc.persons()), 80)
        self.assertEqual(len(doc.names()), 0)
        self.assertEqual(GREEK_FILE.read_bytes(), original)


class Release21(unittest.TestCase):
    def _club(self, path: Path, text: str) -> editor.LncDoc:
        write_lnc(path, text)
        return editor.LncDoc(path)

    def test_utf16_person_edit_keeps_the_other_fields(self):
        line = '"PERSON_FIRST_NAME_END_CHANGE"\t"GREEK"\t"ος"\t2\t"ης"\r\n'
        raw = b"\xff\xfe" + line.encode("utf-16-le")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "person_name_changes.lnc"
            path.write_bytes(raw)
            doc = editor.LncDoc(path)
            self.assertEqual(doc.to_bytes(), raw)
            person = doc.persons()[0]
            self.assertEqual(person.source, "ος")
            self.assertEqual(person.name, "ης")
            self.assertEqual(person.id, "2")
            self.assertTrue(editor.try_set_name(person, "ου"))
            self.assertFalse(editor.try_set_name(person, "bad\nname"))
            self.assertTrue(editor.try_set_source(person, "ας"))
            text = doc.to_bytes()[2:].decode("utf-16-le")
            self.assertIn('"ας"', text)
            self.assertIn('"ου"', text)
            self.assertIn('"GREEK"', text)
            self.assertIn("\t2\t", text)
            self.assertNotIn('"ος"', text)
            self.assertNotIn('"ης"', text)
            self.assertTrue(doc.to_bytes().startswith(b"\xff\xfe"))
            self.assertEqual(path.read_bytes(), raw)

    def test_replace_is_scoped_and_does_not_write(self):
        text = (
            "#England\n"
            '"CLUB_NAME_CHANGE"\t1\t"Manchester United FC"\t""\n'
            "#Spain\n"
            '"CLUB_NAME_CHANGE"\t2\t"Real Madrid FC"\t""\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            doc = self._club(path, text)
            original = path.read_bytes()
            edits, skipped, error = editor.preview_replace(docs=[doc], pattern=" FC$", replacement="", section="England")
            self.assertEqual(error, "")
            self.assertEqual(skipped, 0)
            self.assertEqual(len(edits), 1)
            self.assertEqual(edits[0].after, "Manchester United")
            self.assertEqual(doc.names()[0].name, "Manchester United FC")
            self.assertEqual(path.read_bytes(), original)
            bad, _skipped, error = editor.preview_replace([doc], "(", "", "")
            self.assertTrue(error)
            self.assertEqual(bad, [])
            editor.apply_bulk(edits, [doc])
            self.assertEqual(doc.names()[0].name, "Manchester United")
            self.assertEqual(doc.names()[1].name, "Real Madrid FC")
            self.assertEqual(path.read_bytes(), original)

    def test_pack_round_trip_updates_only_matching_ids(self):
        text = (
            '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
            '"CLUB_NAME_CHANGE"\t2\t"Beta"\t""\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            doc = self._club(path, text)
            editor.try_set_name(doc.names()[0], "Alpha United")
            pack = editor.pack_document([doc], changed_only=True)
            self.assertEqual(len(pack["names"]), 1)
            parsed, skipped, error = editor.parse_pack(editor.pack_to_json(pack), "json")
            self.assertEqual(error, "")
            self.assertEqual(skipped, 0)
            self.assertEqual(parsed[0]["name"], "Alpha United")
            csv_rows, csv_skipped, csv_error = editor.parse_pack(editor.pack_to_csv(pack), "csv")
            self.assertEqual(csv_error, "")
            self.assertEqual(csv_skipped, 0)
            self.assertEqual(csv_rows, parsed)
            fresh = self._club(Path(tmp) / "current.lnc", text)
            changes, missing, stats = editor.proposals_from_pack([fresh], parsed)
            self.assertEqual(stats["same"], 0)
            self.assertEqual(len(missing), 0)
            self.assertEqual(len(changes), 1)
            self.assertTrue(changes[0].checked)
            updated, added = editor.apply_proposals(changes, missing, [fresh])
            self.assertEqual(updated, 1)
            self.assertEqual(added, [])
            self.assertEqual(fresh.names()[0].name, "Alpha United")
            self.assertEqual(fresh.names()[1].name, "Beta")
            illegal, skipped, error = editor.parse_pack(
                '{"format":"fm-name-pack","version":1,"names":['
                '{"command":"CLUB_NAME_CHANGE","id":"1","language":"","name":"Bad\\nName"}]}',
                "json")
            self.assertEqual(error, "")
            self.assertEqual(illegal, [])
            self.assertEqual(skipped, 1)

    def test_restore_changes_memory_only(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "FM27_Club_Names.lnc"
            doc = self._club(path, text)
            archive = root / "backups" / "20261111-120000"
            archive.mkdir(parents=True)
            stored = archive / path.name
            write_lnc(stored, '"CLUB_NAME_CHANGE"\t1\t"Alpha Old"\t""\n')   # an older copy
            on_disk = path.read_bytes()
            editor.try_set_name(doc.names()[0], "Beta")
            self.assertEqual(editor.list_archives(root / "backups"), [archive])
            diff = editor.diff_documents(doc, editor.LncDoc(stored))
            self.assertEqual(len(diff), 1)
            self.assertEqual(diff[0]["working"], "Beta")
            self.assertEqual(diff[0]["archived"], "Alpha Old")
            editor.restore_into(doc, stored)
            self.assertEqual(doc.path, path)
            self.assertTrue(doc.dirty)
            self.assertEqual(doc.names()[0].name, "Alpha Old")
            self.assertEqual(path.read_bytes(), on_disk)


class WindowSmoke(unittest.TestCase):
    def test_entity_tab_edit_and_cancelled_bulk(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")

        self.addCleanup(close_window, win)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            text = (
                "#England\n"
                '"CLUB_NAME_CHANGE"\t1\t"Manchester United FC"\t""\n'
                '"CLUB_NAME_CHANGE"\t3\t"FC Barcelona"\t""\n'
            )
            path = folder / "FM27_Club_Names.lnc"
            write_lnc(path, text)
            win.load([str(path)])
            self.assertEqual(win.tabs.currentIndex(), 0)
            self.assertEqual(win.tabs.tabText(0), "Entities")
            self.assertEqual(win.tabs.tabText(1), "All lines")
            self.assertGreaterEqual(win.entity_model.rowCount(), 2)
            model = win.entity_model
            row = next(index for index, entity in enumerate(model.rows) if entity.id == "1")
            self.assertTrue(model.setData(model.index(row, 2), "Manchester United"))
            self.assertEqual(model.rows[row].name_in("long"), "Manchester United")
            self.assertFalse(model.setData(model.index(row, 2), "Bad\nName"))
            self.assertEqual(model.rows[row].name_in("long"), "Manchester United")
            edits = editor.preview_bulk(win.visible_entities(), "affix")
            self.assertTrue(any(edit.before == "FC Barcelona" for edit in edits))
            self.assertEqual(
                next(entity for entity in model.rows if entity.id == "3").name_in("long"),
                "FC Barcelona")
            win.tabs.setCurrentIndex(1)
            self.assertIn("Manchester United", win.line_model.rows[0].name)

    def test_save_into_game_tree_is_refused_while_the_game_runs(self):
        """Release 2.2, F1: Quick load, edit, Save gets the same guard as Deploy."""
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog, QMessageBox

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")

        self.addCleanup(close_window, win)
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "db"
            path = game / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            path.parent.mkdir(parents=True)
            write_lnc(path, text)
            original = path.read_bytes()
            win.load([str(path)])
            model = win.entity_model
            row = next(index for index, entity in enumerate(model.rows) if entity.id == "1")
            self.assertTrue(model.setData(model.index(row, 2), "Beta"))
            self.assertTrue(win.docs[0].dirty)
            with patch.object(editor, "GAME_DB_ROOT", game), \
                    patch.object(editor, "BACKUP_ROOT", root / "backups"), \
                    patch.object(editor, "football_manager_running", return_value=["fm.exe"]), \
                    patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as warned, \
                    patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as asked:
                win.save()
                self.assertEqual(warned.call_count, 1)
                self.assertIn("fm.exe", warned.call_args.args[2])
                self.assertEqual(asked.call_count, 0)
                self.assertTrue(win.docs[0].dirty)
                self.assertEqual(path.read_bytes(), original)
                # With the game closed, Save opens the review, which says it is the
                # same as Deploy and names the file, then writes. (Session 5.)
                seen = []
                with patch.object(editor, "football_manager_running", return_value=[]), \
                        patch.object(QDialog, "exec", press_write(seen)):
                    win.save()
                self.assertEqual(asked.call_count, 0)
                self.assertEqual(seen[0].windowTitle(),
                                 "Review changes: Save into the game folder, the same as Deploy")
                self.assertEqual(seen[0].files_table.item(0, 1).text(), str(path))
                self.assertFalse(win.docs[0].dirty)
                self.assertIn(b'"Beta"', path.read_bytes())
                self.assertTrue((root / "backups").is_dir())


class Session1Safety(unittest.TestCase):
    """Release 2.2, session 1: game-write preflight, field checks, EOF insertion."""

    def test_football_manager_running_is_tri_state(self):
        from unittest.mock import patch
        import subprocess

        class Result:
            def __init__(self, stdout, returncode=0):
                self.stdout = stdout
                self.returncode = returncode

        with patch.object(editor.subprocess, "run",
                          return_value=Result('"fm.exe","1","Console","1","1 K"\n')):
            self.assertEqual(editor.football_manager_running(), ["fm.exe"])
        with patch.object(editor.subprocess, "run", return_value=Result("")):
            self.assertEqual(editor.football_manager_running(), [])
        with patch.object(editor.subprocess, "run", side_effect=OSError("no tasklist")):
            self.assertIsNone(editor.football_manager_running())
        with patch.object(editor.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired("tasklist", 10)):
            self.assertIsNone(editor.football_manager_running())
        with patch.object(editor.subprocess, "run", return_value=Result("", returncode=1)):
            self.assertIsNone(editor.football_manager_running())

    def test_preflight_checks_only_game_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "db"
            inside = game / "2700" / "lnc" / "all" / "FM27_Fix.lnc"
            outside = root / "mine.lnc"
            calls = []

            def running():
                calls.append(1)
                return ["fm.exe"]

            result = editor.game_write_preflight("Save", [outside], game, check=running)
            self.assertEqual(calls, [])
            self.assertEqual(result.game_paths, [])
            self.assertFalse(result.blocked)
            self.assertFalse(result.check_failed)

            result = editor.game_write_preflight("Save", [outside, inside], game, check=running)
            self.assertEqual(calls, [1])
            self.assertEqual(result.game_paths, [inside])
            self.assertTrue(result.blocked)
            self.assertIn("fm.exe", result.blocked_message())

            result = editor.game_write_preflight("Deploy", [inside], check=lambda: [])
            self.assertEqual(result.game_paths, [inside])
            self.assertFalse(result.blocked)
            self.assertFalse(result.check_failed)

            result = editor.game_write_preflight("Deploy", [inside], check=lambda: None)
            self.assertFalse(result.blocked)
            self.assertTrue(result.check_failed)
            self.assertIn("could not be made", result.unknown_message())

    def test_fields_are_checked_before_a_line_is_built(self):
        self.assertTrue(editor.field_is_legal(""))
        self.assertTrue(editor.field_is_legal("English"))
        self.assertFalse(editor.field_is_legal('Eng"lish'))
        self.assertFalse(editor.field_is_legal("Eng\nlish"))
        self.assertFalse(editor.field_is_legal("Eng\rlish"))
        self.assertFalse(editor.field_is_legal("Eng\x01lish"))
        self.assertTrue(editor.id_is_legal("740"))
        self.assertFalse(editor.id_is_legal(""))
        self.assertFalse(editor.id_is_legal("74a"))
        self.assertFalse(editor.id_is_legal("٣"))   # Arabic-Indic three
        self.assertTrue(editor.is_name_command("CLUB_NAME_CHANGE"))
        self.assertFalse(editor.is_name_command("CHANGE_PLAYER_NAME"))
        self.assertFalse(editor.is_name_command("club_name_change"))
        self.assertEqual(
            editor.build_name_line("CLUB_NAME_CHANGE", "1", "Alpha", ""),
            '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""')
        self.assertEqual(
            editor.build_name_line("AWARD_NAME_CHANGE", "7", "Golden Boot", "English"),
            '"AWARD_NAME_CHANGE"\t7\t"Golden Boot"\t"English"')
        for lang in ('Eng"lish', "Eng\nlish", "Eng\x01lish"):
            with self.assertRaises(ValueError):
                editor.build_name_line("CLUB_NAME_CHANGE", "1", "Alpha", lang)
        with self.assertRaises(ValueError):
            editor.build_name_line("CLUB_NAME_CHANGE", "x1", "Alpha", "")
        with self.assertRaises(ValueError):
            editor.build_name_line("CHANGE_PLAYER_NAME", "1", "Alpha", "")
        with self.assertRaises(ValueError):
            editor.build_name_line("CLUB_NAME_CHANGE", "1", "", "")

    def test_bad_language_cannot_reach_the_file(self):
        text = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            write_lnc(path, text)
            doc = editor.LncDoc(path)
            before = doc.to_bytes()
            with self.assertRaises(ValueError):
                doc.append_entry("CLUB_NAME_CHANGE", "2", "Beta", 'x"\t2\t"y')
            with self.assertRaises(ValueError):
                editor.insert_name_after(
                    doc.names()[0], "CLUB_SHORT_NAME_CHANGE", "1", "Alph", "a\nb")
            self.assertEqual(doc.to_bytes(), before)
            self.assertFalse(doc.dirty)
            self.assertEqual(len(doc.entries), 1)
            # A pack row with a bad language or id is rejected and counted.
            pack = (
                '{"format":"fm-name-pack","version":1,"names":['
                '{"command":"CLUB_NAME_CHANGE","id":"2","language":"x\\"","name":"Beta"},'
                '{"command":"CLUB_NAME_CHANGE","id":"3","language":"a\\nb","name":"Gamma"},'
                '{"command":"CLUB_NAME_CHANGE","id":"4x","language":"","name":"Delta"},'
                '{"command":"CLUB_NAME_CHANGE","id":"5","language":"English","name":"Eps"}]}')
            rows, skipped, error = editor.parse_pack(pack, "json")
            self.assertEqual(error, "")
            self.assertEqual(skipped, 3)
            self.assertEqual([row["id"] for row in rows], ["5"])
            changes, missing, _stats = editor.proposals_from_pack([doc], rows)
            self.assertEqual(changes, [])
            self.assertEqual(len(missing), 1)
            missing[0].checked = True
            _count, added = editor.apply_proposals(changes, missing, [doc])
            self.assertEqual(len(added), 1)
            self.assertEqual(added[0].lang, "English")
            # A hand-made missing proposal with a bad language is left out, not raised.
            bad = editor.Proposal("CLUB_NAME_CHANGE", "9", 'x"', "Mine", None, "", True)
            count, added = editor.apply_proposals([], [bad], [doc])
            self.assertEqual((count, added), (0, []))
            reloaded = editor.LncDoc(path)
            self.assertEqual(len(reloaded.names()), 1)

    def test_older_file_with_bad_language_is_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            old_path = folder / "old.lnc"
            write_lnc(old_path, '"CLUB_NAME_CHANGE"\t9\t"Mine"\t"Eng\x01lish"\n')
            old = editor.LncDoc(old_path)
            self.assertEqual(len(old.names()), 1)
            target_path = folder / "new.lnc"
            write_lnc(target_path, '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n')
            target = editor.LncDoc(target_path)
            changes, missing, stats = editor.build_proposals([target], [old], None)
            self.assertEqual((changes, missing), ([], []))
            self.assertEqual(stats["skipped"], 1)

    def test_insert_after_last_line_without_ending(self):
        cases = (
            ("utf-8", b"\xef\xbb\xbf", "\n"),
            ("utf-8", b"\xef\xbb\xbf", "\r\n"),
            ("utf-16-le", b"\xff\xfe", "\r\n"),
        )
        for encoding, bom, eol in cases:
            with self.subTest(encoding=encoding, eol=repr(eol)):
                text = (
                    f"#England{eol}"
                    f'"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""{eol}'
                    '"CLUB_SHORT_NAME_CHANGE"\t2\t"Arsenal"\t""'
                )
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "FM27_Club_Names.lnc"
                    path.write_bytes(bom + text.encode(encoding))
                    doc = editor.LncDoc(path)
                    self.assertEqual(doc.to_bytes(), path.read_bytes())
                    entity = next(
                        item for item in editor.build_entities([doc])
                        if item.family == "club" and item.id == "2")
                    self.assertTrue(
                        editor.set_entity_field(entity, "long", "Arsenal FC", [doc]))
                    out = Path(tmp) / "out.lnc"
                    out.write_bytes(doc.to_bytes())
                    again = editor.LncDoc(out)
                    self.assertEqual(again.problems(), [])
                    self.assertEqual(
                        [(entry.cmd, entry.id, entry.name) for entry in again.names()],
                        [("CLUB_NAME_CHANGE", "1", "Alpha"),
                         ("CLUB_SHORT_NAME_CHANGE", "2", "Arsenal"),
                         ("CLUB_NAME_CHANGE", "2", "Arsenal FC")])
                    self.assertTrue(out.read_bytes().endswith(eol.encode(encoding)))
                    self.assertEqual(again.encoding, encoding)


class Session2WorkingState(unittest.TestCase):
    """Release 2.2, session 2: the disk baseline, restore, and revert (F4, F5)."""

    ROWS = (
        '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        '"CLUB_NAME_CHANGE"\t2\t"Beta"\t""\n'
        '"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""\n'
    )

    def _open(self, tmp, archive_text):
        root = Path(tmp)
        path = root / "FM27_Club_Names.lnc"
        write_lnc(path, self.ROWS)
        stored = root / "backups" / "20261111-120000" / path.name
        stored.parent.mkdir(parents=True)
        write_lnc(stored, archive_text)
        return editor.LncDoc(path), path, stored

    def test_dirty_means_the_bytes_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path, _stored = self._open(tmp, self.ROWS)
            first = doc.names()[0]
            self.assertFalse(doc.dirty)
            editor.try_set_name(first, "Alpha United")
            self.assertTrue(doc.dirty)
            self.assertEqual(editor.revert_entry(first), "name")
            self.assertFalse(doc.dirty)
            editor.try_set_name(first, "Alpha United")
            doc.save(backup=False)
            self.assertFalse(doc.dirty)
            self.assertEqual(doc.baseline_bytes, path.read_bytes())
            self.assertEqual(first.orig_name, "Alpha United")
            doc.encoding = "cp1252"
            editor.try_set_name(first, "\u0100")
            self.assertTrue(doc.dirty)      # text that cannot be written differs from disk

    def test_restore_keeps_the_disk_text_as_the_original(self):
        archive = (
            '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
            '"CLUB_NAME_CHANGE"\t2\t"Beta Old"\t""\n'
            '"CLUB_NAME_CHANGE"\t4\t"Delta"\t""\n')
        with tempfile.TemporaryDirectory() as tmp:
            doc, path, stored = self._open(tmp, archive)
            on_disk = path.read_bytes()
            editor.restore_into(doc, stored)
            self.assertTrue(doc.dirty)
            rows = {entry.id: entry for entry in doc.names()}
            self.assertFalse(rows["1"].changed)
            self.assertTrue(rows["2"].changed)
            self.assertEqual(rows["2"].orig_name, "Beta")
            self.assertTrue(rows["4"].imported)
            self.assertEqual([row.id for row in doc.removed_rows], ["3"])
            pack = editor.pack_document([doc], changed_only=True)
            self.assertEqual(
                {(item["id"], item["name"]) for item in pack["names"]},
                {("2", "Beta Old"), ("4", "Delta")})
            self.assertEqual(path.read_bytes(), on_disk)

    def test_edit_and_revert_after_a_restore_stays_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path, stored = self._open(tmp, self.ROWS.replace("Beta", "Beta Old"))
            editor.restore_into(doc, stored)
            first, second = doc.names()[0], doc.names()[1]
            editor.try_set_name(first, "Alpha United")
            self.assertEqual(editor.revert_entry(first), "name")
            self.assertTrue(doc.dirty)              # row 2 still differs from the disk file
            self.assertEqual(editor.revert_entry(second), "name")
            self.assertEqual(second.name, "Beta")   # reverting goes back to the disk text
            self.assertFalse(doc.dirty)             # memory now equals the file

    def test_restore_that_drops_a_disk_row_still_counts(self):
        archive = self.ROWS.replace('"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""\n', "")
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path, stored = self._open(tmp, archive)
            editor.restore_into(doc, stored)
            self.assertTrue(doc.dirty)
            self.assertFalse(any(entry.changed for entry in doc.names()))
            self.assertEqual([row.id for row in doc.removed_rows], ["3"])
            self.assertEqual(editor.pack_document([doc])["names"], [])

    def test_restoring_a_copy_of_the_disk_file_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path, stored = self._open(tmp, self.ROWS)
            editor.try_set_name(doc.names()[0], "Alpha United")
            self.assertTrue(doc.dirty)
            editor.restore_into(doc, stored)
            self.assertFalse(doc.dirty)
            self.assertEqual(doc.names()[0].name, "Alpha")
            self.assertEqual(doc.removed_rows, [])

    def test_a_second_restore_can_bring_a_removed_row_back(self):
        short = self.ROWS.replace('"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""\n', "")
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path, stored = self._open(tmp, short)
            full = stored.parent / "full.lnc"
            write_lnc(full, self.ROWS)
            editor.restore_into(doc, stored)
            self.assertEqual([row.id for row in doc.removed_rows], ["3"])
            editor.restore_into(doc, full)
            self.assertEqual(doc.removed_rows, [])
            self.assertFalse(any(entry.imported for entry in doc.names()))
            self.assertFalse(doc.dirty)

    def test_a_bad_backup_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path, stored = self._open(tmp, self.ROWS)
            bad = stored.parent / "bad.lnc"
            bad.write_bytes(b'"CLUB_NAME_CHANGE"\t1\t"\x81"\t""\n')
            editor.try_set_name(doc.names()[0], "Alpha United")
            snapshot = doc.to_bytes()
            with self.assertRaises(UnicodeError):
                editor.restore_into(doc, bad)
            self.assertEqual(doc.to_bytes(), snapshot)
            self.assertTrue(doc.dirty)

    def test_save_after_a_restore_writes_and_clears_it(self):
        archive = (
            '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
            '"CLUB_NAME_CHANGE"\t2\t"Beta Old"\t""\n'
            '"CLUB_NAME_CHANGE"\t4\t"Delta"\t""\n')
        with tempfile.TemporaryDirectory() as tmp:
            doc, path, stored = self._open(tmp, archive)
            editor.restore_into(doc, stored)
            doc.save(backup=False)
            self.assertEqual(path.read_bytes(), stored.read_bytes())
            self.assertFalse(doc.dirty)
            self.assertEqual(doc.removed_rows, [])
            self.assertFalse(any(entry.changed for entry in doc.names()))


class Session2Revert(unittest.TestCase):
    """Release 2.2, session 2: revert puts back every editable field (F5)."""

    OS = "\u03bf\u03c2"          # a matched ending
    IS = "\u03b7\u03c2"          # its replacement
    OUS = "\u03bf\u03c5\u03c2"   # a longer ending
    OU = "\u03bf\u03c5"          # a shorter replacement
    AS = "\u03b1\u03c2"
    A = "\u03b1"

    def _greek(self, tmp, rules):
        path = Path(tmp) / "person_name_changes.lnc"
        lines = "".join(
            f'"PERSON_FIRST_NAME_END_CHANGE"\t"GREEK"\t"{ending}"\t{number}\t"{new}"\r\n'
            for ending, number, new in rules)
        path.write_bytes(b"\xff\xfe" + lines.encode("utf-16-le"))
        return editor.LncDoc(path), path

    def test_revert_restores_both_person_rule_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path = self._greek(tmp, [(self.OS, 2, self.IS), (self.AS, 3, self.A)])
            raw = path.read_bytes()
            first, second = doc.persons()
            changes = {
                "ending only": lambda r: editor.try_set_source(r, self.OUS),
                "replacement only": lambda r: editor.try_set_name(r, self.OU),
                "ending then replacement": lambda r: (
                    editor.try_set_source(r, self.OUS), editor.try_set_name(r, self.OU)),
                "replacement then ending": lambda r: (
                    editor.try_set_name(r, self.OU), editor.try_set_source(r, self.OUS)),
            }
            for label, change in changes.items():
                with self.subTest(label):
                    change(first)
                    self.assertTrue(doc.dirty)
                    self.assertEqual(editor.revert_entry(first), "rule")
                    self.assertEqual(doc.to_bytes(), raw)
                    self.assertFalse(doc.dirty)
                    self.assertEqual((first.source, first.name), (self.OS, self.IS))
            self.assertFalse(second.changed)

    def test_revert_entries_counts_each_outcome(self):
        rows = (
            '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
            '"CLUB_NAME_CHANGE"\t2\t"Beta"\t""\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            write_lnc(path, rows)
            doc = editor.LncDoc(path)
            editor.try_set_name(doc.names()[0], "Alpha United")
            doc.append_entry("CLUB_NAME_CHANGE", "9", "Nine", "")
            counts = editor.revert_entries(doc.names())
            self.assertEqual(counts, {"name": 1, "rule": 0, "added": 1, "same": 1})
            self.assertEqual(doc.names()[0].name, "Alpha")
            self.assertTrue(doc.dirty)      # the added row is still pending


class Session2Load(unittest.TestCase):
    """Release 2.2, session 2: opening several files is all or nothing."""

    def test_open_documents_is_all_or_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            good = folder / "FM27_Club_Names.lnc"
            write_lnc(good, '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n')
            other = folder / "FM27_Fix.lnc"
            write_lnc(other, '"COMP_LONG_NAME_CHANGE"\t9\t"Cup"\t""\n')
            bad = folder / "broken.lnc"
            bad.write_bytes(b'"CLUB_NAME_CHANGE"\t1\t"\x81"\t""\n')
            truncated = folder / "truncated.lnc"
            truncated.write_bytes(b"\xff\xfeA")
            self.assertEqual(len(editor.open_documents([good, other])), 2)
            for broken in (bad, truncated, folder / "missing.lnc"):
                with self.subTest(broken.name):
                    with self.assertRaises(editor.LoadError) as caught:
                        editor.open_documents([good, broken])
                    self.assertEqual(caught.exception.path, broken)
                    self.assertIn(broken.name, str(caught.exception))


class Session2Window(unittest.TestCase):
    """Release 2.2, session 2: the window follows the new meanings."""

    def _window(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")
        self.addCleanup(close_window, win)
        return win

    def _restorable(self, tmp, archive_text):
        root = Path(tmp)
        path = root / "FM27_Club_Names.lnc"
        write_lnc(path, Session2WorkingState.ROWS)
        stored = root / "backups" / "20261111-120000" / path.name
        stored.parent.mkdir(parents=True)
        write_lnc(stored, archive_text)
        return path, stored

    def test_close_still_prompts_after_a_restore_edit_and_revert(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path, stored = self._restorable(
                tmp, Session2WorkingState.ROWS.replace("Beta", "Beta Old"))
            self.assertTrue(win.load([str(path)]))
            doc = win.docs[0]
            editor.restore_into(doc, stored)
            win.reload_views()
            first = doc.names()[0]
            editor.try_set_name(first, "Alpha United")
            editor.revert_entry(first)
            win.refresh_status()
            self.assertIn("1 unsaved", win.metrics.text())
            self.assertTrue(win.windowTitle().startswith("* "))
            with patch.object(QMessageBox, "question",
                              return_value=QMessageBox.Cancel) as asked:
                self.assertFalse(win.confirm_discard())
            self.assertEqual(asked.call_count, 1)

    def test_a_row_the_restore_left_out_is_counted_as_unsaved(self):
        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path, stored = self._restorable(
                tmp, Session2WorkingState.ROWS.replace(
                    '"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""\n', ""))
            self.assertTrue(win.load([str(path)]))
            editor.restore_into(win.docs[0], stored)
            win.reload_views()
            self.assertIn("1 unsaved", win.metrics.text())
            self.assertTrue(win.windowTitle().startswith("* "))

    def test_a_comment_only_restore_is_still_pending(self):
        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path, stored = self._restorable(
                tmp, Session2WorkingState.ROWS + "#Added by an older copy\n")
            self.assertTrue(win.load([str(path)]))
            doc = win.docs[0]
            editor.restore_into(doc, stored)
            win.reload_views()
            self.assertTrue(doc.dirty)
            self.assertFalse(any(entry.changed for entry in doc.names()))
            self.assertEqual(doc.removed_rows, [])
            self.assertIn("file differs from disk", win.metrics.text())
            self.assertTrue(win.windowTitle().startswith("* "))

    def test_a_bad_file_leaves_the_open_files_alone(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            good = folder / "FM27_Club_Names.lnc"
            write_lnc(good, Session2WorkingState.ROWS)
            other = folder / "FM27_Fix.lnc"
            write_lnc(other, '"COMP_LONG_NAME_CHANGE"\t9\t"Cup"\t""\n')
            bad = folder / "broken.lnc"
            bad.write_bytes(b'"CLUB_NAME_CHANGE"\t1\t"\x81"\t""\n')
            self.assertTrue(win.load([str(good)]))
            for broken in (bad, folder / "missing.lnc"):
                with self.subTest(broken.name), \
                        patch.object(QMessageBox, "critical") as shown:
                    self.assertFalse(win.load([str(other), str(broken)]))
                    self.assertEqual([doc.path for doc in win.docs], [good])
                    self.assertEqual(shown.call_count, 1)
                    self.assertIn(broken.name, shown.call_args.args[2])
            self.assertTrue(win.load([str(other)]))
            self.assertEqual([doc.path for doc in win.docs], [other])

    def test_revert_selected_restores_a_person_ending(self):
        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            line = ('"PERSON_FIRST_NAME_END_CHANGE"\t"GREEK"\t"\u03bf\u03c2"\t2'
                    '\t"\u03b7\u03c2"\r\n')
            raw = b"\xff\xfe" + line.encode("utf-16-le")
            path = Path(tmp) / "person_name_changes.lnc"
            path.write_bytes(raw)
            self.assertTrue(win.load([str(path)]))
            win.tabs.setCurrentIndex(1)
            model = win.line_model
            self.assertTrue(model.setData(model.index(0, 0), "\u03bf\u03c5\u03c2"))
            self.assertTrue(model.setData(model.index(0, model.NAME_COL), "\u03bf\u03c5"))
            self.assertNotEqual(win.docs[0].to_bytes(), raw)
            win.line_view.selectRow(0)
            win.revert_selected()
            self.assertEqual(win.docs[0].to_bytes(), raw)
            self.assertFalse(win.docs[0].dirty)
            self.assertIn("1 person rule(s)", win.statusBar().currentMessage())

    def test_labels_say_what_they_mean(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        win = self._window()
        self.assertEqual(
            [button.text() for button in win.status_buttons],
            ["All", "Edited", "No short-name override", "No code override"])
        for model, title in ((win.entity_model, "File section"),
                             (win.line_model, "File section or ending")):
            self.assertEqual(model.headerData(0, Qt.Horizontal, Qt.DisplayRole), title)
            self.assertEqual(
                model.headerData(0, Qt.Horizontal, Qt.ToolTipRole), editor.FILE_SECTION_HINT)
        self.assertIn("File sections", [label.text() for label in win.findChildren(QLabel)])


class Session3Writes(unittest.TestCase):
    """Release 2.2, session 3: files are replaced one at a time, with a way back (F6)."""

    CLUB = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
    FIX = '"COMP_LONG_NAME_CHANGE"\t9\t"Cup"\t""\n'

    def _game(self, tmp):
        """Both name files in a stand-in for lnc\\all, opened and edited."""
        root = Path(tmp)
        folder = root / "db" / "2700" / "lnc" / "all"
        folder.mkdir(parents=True)
        write_lnc(folder / "FM27_Club_Names.lnc", self.CLUB)
        write_lnc(folder / "FM27_Fix.lnc", self.FIX)
        docs = editor.open_documents(
            [folder / "FM27_Club_Names.lnc", folder / "FM27_Fix.lnc"])
        editor.try_set_name(docs[0].names()[0], "Alpha United")
        editor.try_set_name(docs[1].names()[0], "Cup Final")
        return root, folder, docs

    def test_atomic_write_leaves_the_file_alone_on_failure(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.lnc"
            path.write_bytes(b"old")
            editor.write_file_atomically(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")
            failures = (
                ("replace", PermissionError(13, "Access is denied")),
                ("fsync", OSError(28, "No space left on device")),
            )
            for name, error in failures:
                with self.subTest(name):
                    with patch.object(editor.os, name, side_effect=error):
                        with self.assertRaises(OSError):
                            editor.write_file_atomically(path, b"newer")
                    self.assertEqual(path.read_bytes(), b"new")
                    self.assertEqual([item.name for item in Path(tmp).iterdir()], ["names.lnc"])

    def test_a_replacement_that_fails_leaves_the_destination(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root, folder, docs = self._game(tmp)
            club = docs[0]
            original = club.path.read_bytes()
            with patch.object(editor.os, "replace", side_effect=failing_replace(club.path)):
                with self.assertRaises(editor.WriteError) as caught:
                    editor.save_documents([club], root / "db", root / "backups")
            error = caught.exception
            self.assertEqual(club.path.read_bytes(), original)
            self.assertTrue(club.dirty)
            self.assertEqual(staging_files(folder), [])
            self.assertEqual([write.state for write in error.files], ["failed"])
            self.assertIn("stopped before any file was replaced", str(error))
            manifest = editor.read_manifest(error.archive)
            self.assertEqual(manifest["result"], "stopped")
            self.assertEqual(manifest["files"][0]["outcome"], "failed")

    def test_second_replacement_failure_puts_the_first_back(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root, folder, docs = self._game(tmp)
            originals = {doc.path: doc.path.read_bytes() for doc in docs}
            pairs = [(doc, doc.path) for doc in docs]
            with patch.object(editor.os, "replace", side_effect=failing_replace(docs[1].path)):
                with self.assertRaises(editor.WriteError) as caught:
                    editor.deploy_documents(pairs, root / "backups")
            error = caught.exception
            for path, data in originals.items():
                self.assertEqual(path.read_bytes(), data)
            self.assertEqual(staging_files(folder), [])
            self.assertEqual([write.state for write in error.files], ["restored", "failed"])
            self.assertTrue(all(doc.dirty for doc in docs))
            self.assertEqual([doc.path for doc in docs], list(originals))
            text = str(error)
            self.assertIn("one at a time, per file", text)
            self.assertNotIn("atomic", text)
            self.assertIn(f"{docs[0].path}\n    put back as it was", text)
            self.assertIn(f"{docs[1].path}\n    could not be replaced", text)
            manifest = editor.read_manifest(error.archive)
            self.assertEqual(manifest["result"], "rolled back")
            self.assertEqual(
                {entry["archived"]: entry["outcome"] for entry in manifest["files"]},
                {"FM27_Club_Names.lnc": "restored", "FM27_Fix.lnc": "failed"})
            for entry in manifest["files"]:
                self.assertEqual(
                    (error.archive / entry["archived"]).read_bytes(),
                    originals[Path(entry["original"])])

    def test_a_new_file_is_removed_when_a_later_file_fails(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root, folder, docs = self._game(tmp)
            target = root / "db" / "2730" / "lnc" / "all"
            target.mkdir(parents=True)
            write_lnc(target / "FM27_Fix.lnc", self.FIX)
            pairs = [(docs[0], target / "FM27_Club_Names.lnc"),
                     (docs[1], target / "FM27_Fix.lnc")]
            with patch.object(editor.os, "replace",
                              side_effect=failing_replace(target / "FM27_Fix.lnc")):
                with self.assertRaises(editor.WriteError) as caught:
                    editor.deploy_documents(pairs, root / "backups")
            self.assertEqual([write.state for write in caught.exception.files],
                             ["removed", "failed"])
            self.assertFalse((target / "FM27_Club_Names.lnc").exists())
            self.assertEqual(staging_files(target), [])
            self.assertEqual(docs[0].path, folder / "FM27_Club_Names.lnc")
            self.assertIn("removed again (it did not exist before)", str(caught.exception))

    def test_a_file_that_cannot_be_put_back_is_reported(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root, folder, docs = self._game(tmp)
            club, fix = docs[0].path, docs[1].path
            real = os.replace
            calls = []

            def replace(src, dst):
                if Path(dst) == fix:
                    raise PermissionError(13, "Access is denied", str(dst))
                if Path(dst) == club:
                    calls.append(src)
                    if len(calls) > 1:          # the second call is the put-back
                        raise PermissionError(13, "Access is denied", str(dst))
                return real(src, dst)

            payload = docs[0].to_bytes()
            with patch.object(editor.os, "replace", side_effect=replace):
                with self.assertRaises(editor.WriteError) as caught:
                    editor.deploy_documents([(doc, doc.path) for doc in docs], root / "backups")
            error = caught.exception
            self.assertEqual([write.state for write in error.files], ["left written", "failed"])
            self.assertEqual(club.read_bytes(), payload)
            self.assertFalse(docs[0].dirty)     # the file on disk now holds what the editor has
            self.assertTrue(docs[1].dirty)
            self.assertIn(f"The previous version is in {error.archive}", str(error))
            self.assertEqual(staging_files(folder), [])
            self.assertEqual(editor.read_manifest(error.archive)["result"], "partly written")

    def test_a_file_changed_since_it_was_read_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, folder, docs = self._game(tmp)
            doc = docs[0]
            write_lnc(doc.path, self.CLUB.replace("Alpha", "Steam update"))
            outside = doc.path.read_bytes()
            attempts = {
                "save": lambda: editor.save_documents([doc], root / "db", root / "backups"),
                "deploy": lambda: editor.deploy_documents([(doc, doc.path)], root / "backups"),
                "save beside": lambda: doc.save(),
            }
            for label, attempt in attempts.items():
                with self.subTest(label):
                    with self.assertRaises(editor.ExternalChangeError) as caught:
                        attempt()
                    self.assertEqual(caught.exception.paths, [doc.path])
                    self.assertIn("Nothing was written", str(caught.exception))
                    self.assertEqual(doc.path.read_bytes(), outside)
                    self.assertTrue(doc.dirty)
            self.assertFalse((root / "backups").exists())
            self.assertEqual(
                sorted(path.name for path in folder.iterdir()),
                ["FM27_Club_Names.lnc", "FM27_Fix.lnc"])
            doc.path.unlink()
            with self.assertRaises(editor.ExternalChangeError):
                editor.save_documents([doc], root / "db", root / "backups")
            self.assertFalse(doc.path.exists())
            # A deploy over a file the document was not opened from has no earlier
            # reading to compare with. The file there is backed up, then replaced.
            other = root / "db" / "2730" / "lnc" / "all" / "FM27_Fix.lnc"
            other.parent.mkdir(parents=True)
            write_lnc(other, self.FIX.replace("Cup", "Other"))
            before = other.read_bytes()
            archive = editor.deploy_documents([(docs[1], other)], root / "backups")
            self.assertEqual((archive / "FM27_Fix.lnc").read_bytes(), before)
            self.assertEqual(docs[1].path, other)
            self.assertFalse(docs[1].dirty)

    def test_two_documents_cannot_write_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _folder, docs = self._game(tmp)
            twin = editor.LncDoc(docs[0].path)
            editor.try_set_name(twin.names()[0], "Other")
            original = docs[0].path.read_bytes()
            with self.assertRaises(editor.WriteError) as caught:
                editor.save_documents([docs[0], twin], root / "db", root / "backups")
            self.assertEqual(caught.exception.files, [])
            self.assertEqual(docs[0].path.read_bytes(), original)
            self.assertFalse((root / "backups").exists())


class Session3Archive(unittest.TestCase):
    """Release 2.2, session 3: backup manifests, matching, and the honest diff."""

    def test_manifest_describes_each_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            club = root / "db" / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            greek = root / "db" / "2700" / "lnc" / "greek" / "person_name_changes.lnc"
            club.parent.mkdir(parents=True)
            greek.parent.mkdir(parents=True)
            write_lnc(club, '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n')
            greek.write_bytes(b"\xff\xfe" + (
                '"PERSON_FIRST_NAME_END_CHANGE"\t"GREEK"\t"ος"\t2\t"ης"\r\n'
            ).encode("utf-16-le"))
            os.utime(club, (1_700_000_000, 1_700_000_000))
            originals = {club: club.read_bytes(), greek: greek.read_bytes()}
            docs = editor.open_documents([club, greek])
            editor.try_set_name(docs[0].names()[0], "Alpha United")
            editor.try_set_name(docs[1].persons()[0], "ου")
            archive = editor.save_documents(docs, root / "db", root / "backups")
            manifest = editor.read_manifest(archive)
            self.assertEqual(manifest["format"], "fm-name-editor-archive")
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(manifest["operation"], "Save")
            self.assertEqual(manifest["database"], "2700")
            self.assertEqual(manifest["editor_version"], editor.VERSION)
            self.assertEqual(manifest["result"], "complete")
            datetime.fromisoformat(manifest["timestamp"])
            entries = {entry["original"]: entry for entry in manifest["files"]}
            self.assertEqual(set(entries), {str(club), str(greek)})
            for path, data in originals.items():
                entry = entries[str(path)]
                self.assertEqual((archive / entry["archived"]).read_bytes(), data)
                self.assertEqual(entry["size"], len(data))
                self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
                self.assertTrue(entry["bom"])
                self.assertEqual(entry["outcome"], "written")
            self.assertEqual(entries[str(club)]["encoding"], "utf-8")
            self.assertEqual(entries[str(greek)]["encoding"], "utf-16-le")
            self.assertEqual((archive / "FM27_Club_Names.lnc").stat().st_mtime, 1_700_000_000)
            self.assertEqual(staging_files(archive), [])
            # A folder from before 2.2 has no manifest. A broken one is reported.
            older = root / "backups" / "20250101-000000"
            older.mkdir()
            self.assertIsNone(editor.read_manifest(older))
            (older / "manifest.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                editor.read_manifest(older)
            (older / "manifest.json").write_text('{"format": "other"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                editor.read_manifest(older)

    def test_same_name_sources_are_told_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "db" / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            work = root / "db" / "2400" / "lnc" / "all" / "FM27_Club_Names.lnc"
            for path, name in ((live, "Alpha"), (work, "Beta")):
                path.parent.mkdir(parents=True)
                write_lnc(path, f'"CLUB_NAME_CHANGE"\t1\t"{name}"\t""\n')
            archive = editor.archive_files([live, work], root / "backups", "Save")
            manifest = editor.read_manifest(archive)
            self.assertEqual(
                [entry["archived"] for entry in manifest["files"]],
                ["FM27_Club_Names.lnc", "FM27_Club_Names-2.lnc"])
            self.assertEqual(manifest["database"], "2400, 2700")
            self.assertIn(b"Beta", (archive / "FM27_Club_Names-2.lnc").read_bytes())
            docs = editor.open_documents([work, live])
            for entry, expected in zip(manifest["files"], (live, work)):
                doc, how = editor.match_open_document(archive / entry["archived"], docs, manifest)
                self.assertEqual((doc.path, how), (expected, "path"))
            # Without a manifest, two open files with one name cannot be told apart.
            copy = archive / "FM27_Club_Names.lnc"
            self.assertEqual(editor.match_open_document(copy, docs, None), (None, ""))
            self.assertEqual(editor.match_open_document(copy, docs[:1], None), (docs[0], "name"))

    def test_backup_comparison_separates_names_from_bytes(self):
        rows = '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        cases = {
            "same.lnc": (rows, 0, True, "Supported names match, and the files are byte-identical."),
            "comment.lnc": ("#An older comment\n" + rows, 0, False,
                            "Supported names match, but the files are not byte-identical"),
            "name.lnc": (rows.replace("Alpha", "Alpha Old"), 1, False,
                         "1 difference(s) in supported names"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "FM27_Club_Names.lnc"
            write_lnc(path, rows)
            doc = editor.LncDoc(path)
            for name, (text, count, identical, phrase) in cases.items():
                with self.subTest(name):
                    copy = root / name
                    write_lnc(copy, text)
                    diff, same = editor.compare_with_backup(doc, copy)
                    self.assertEqual(len(diff), count)
                    self.assertIs(same, identical)
                    self.assertIn(phrase, editor.describe_backup_match(len(diff), same))
            doc.encoding = "cp1252"
            editor.try_set_name(doc.names()[0], "Ā")
            diff, same = editor.compare_with_backup(doc, root / "same.lnc")
            self.assertIsNone(same)
            self.assertIn("could not be made", editor.describe_backup_match(0, None))

    def test_licensing_rename_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = root / "2700"
            rel = editor.MASK_FILES[-1]
            src = version / rel
            src.parent.mkdir(parents=True)
            src.write_bytes(b"mask-bytes")
            disabled = src.with_name(src.name + ".disabled")
            disabled.write_bytes(b"older-mask")
            rows = {row["name"]: row for row in editor.licence_inventory(version)}
            self.assertEqual(rows[rel.as_posix()]["state"], "both")
            with self.assertRaises(FileExistsError):
                editor.toggle_licence(version, rel, root / "backups")
            self.assertEqual(src.read_bytes(), b"mask-bytes")
            self.assertEqual(disabled.read_bytes(), b"older-mask")
            self.assertFalse((root / "backups").exists())
            disabled.unlink()
            self.assertEqual(editor.toggle_licence(version, rel, root / "backups"), "disabled")
            archive = editor.list_archives(root / "backups")[0]
            manifest = editor.read_manifest(archive)
            self.assertEqual(manifest["operation"], "Disable licensing file")
            self.assertEqual(manifest["database"], "2700")
            self.assertEqual(manifest["result"], "complete")
            entry = manifest["files"][0]
            self.assertEqual(entry["original"], str(src))
            self.assertIsNone(entry["encoding"])
            self.assertEqual(entry["outcome"], "renamed")
            self.assertEqual(staging_files(src.parent), [])


class Session3Window(unittest.TestCase):
    """Release 2.2, session 3: the window reports each file and matches backups by path."""

    def _window(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")
        self.addCleanup(close_window, win)
        return win

    def test_a_failed_deploy_says_where_each_file_stands(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog, QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "db"
            folder = game / "2700" / "lnc" / "all"
            folder.mkdir(parents=True)
            club, fix = folder / "FM27_Club_Names.lnc", folder / "FM27_Fix.lnc"
            write_lnc(club, Session3Writes.CLUB)
            write_lnc(fix, Session3Writes.FIX)
            originals = {club: club.read_bytes(), fix: fix.read_bytes()}
            with patch.object(editor, "GAME_DB_ROOT", game), \
                    patch.object(editor, "BACKUP_ROOT", root / "backups"):
                win.refresh_versions()
                self.assertTrue(win.load([str(club), str(fix)]))
                editor.try_set_name(win.docs[0].names()[0], "Alpha United")
                editor.try_set_name(win.docs[1].names()[0], "Cup Final")
                seen = []
                with patch.object(editor, "football_manager_running", return_value=[]), \
                        patch.object(QDialog, "exec", press_write(seen)), \
                        patch.object(QMessageBox, "critical") as shown, \
                        patch.object(editor.os, "replace", side_effect=failing_replace(fix)):
                    win.deploy()
            self.assertIn("one at a time", seen[0].note.text())
            self.assertEqual(shown.call_count, 1)
            text = shown.call_args.args[2]
            self.assertIn("Deploy stopped part-way", text)
            self.assertIn(f"{club}\n    put back as it was", text)
            self.assertIn(f"{fix}\n    could not be replaced", text)
            for path, data in originals.items():
                self.assertEqual(path.read_bytes(), data)
            self.assertTrue(all(doc.dirty for doc in win.docs))
            self.assertEqual(staging_files(folder), [])

    def test_save_refuses_a_file_changed_on_disk(self):
        """Since Session 5 the review shows the change and will not write."""
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog, QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, Session3Writes.CLUB)
            self.assertTrue(win.load([str(path)]))
            editor.try_set_name(win.docs[0].names()[0], "Alpha United")
            write_lnc(path, Session3Writes.CLUB.replace("Alpha", "Changed elsewhere"))
            outside = path.read_bytes()
            seen = []
            with patch.object(QDialog, "exec", press_write(seen)), \
                    patch.object(QMessageBox, "warning") as warned:
                win.save()
            dialog = seen[0]
            self.assertEqual(dialog.result(), 0)            # Write did not close it
            self.assertFalse(dialog.write_btn.isEnabled())
            self.assertIn("changed on disk since the editor read it", dialog.disk_label.text())
            self.assertIn("changed on disk, or were removed, after the editor read them",
                          dialog.note.text())
            self.assertIn(str(path), dialog.note.text())
            self.assertEqual(warned.call_count, 0)
            self.assertEqual(path.read_bytes(), outside)
            self.assertTrue(win.docs[0].dirty)
            self.assertEqual(sorted(item.name for item in Path(tmp).iterdir()), ["mine.lnc"])

    def test_backups_window_matches_by_original_path(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog, QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "db" / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            work = root / "work" / "FM27_Club_Names.lnc"
            for path, name in ((live, "Alpha"), (work, "Work")):
                path.parent.mkdir(parents=True)
                write_lnc(path, f'"CLUB_NAME_CHANGE"\t1\t"{name}"\t""\n')
            backups = root / "backups"
            archive = editor.archive_files([live], backups, "Deploy")
            editor.finish_manifest(archive, "complete")
            stored = (archive / live.name).read_bytes()
            write_lnc(live, '#A heading the copy lacks\n"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n')
            self.assertTrue(win.load([str(work), str(live)]))
            opened = []
            with patch.object(editor, "BACKUP_ROOT", backups), \
                    patch.object(QDialog, "exec", lambda dialog: opened.append(dialog) or 0):
                win.open_backups()
            dialog = opened[0]
            self.assertIn("Deploy, 1 file(s)", dialog.archive_list.item(0).text())
            self.assertEqual(dialog.file_list.count(), 1)       # manifest.json is not listed
            self.assertIn(f"This copy came from {live}", dialog.origin.text())
            self.assertIn("Supported names match, but the files are not byte-identical",
                          dialog.summary.text())
            self.assertTrue(dialog.restore_btn.isEnabled())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                dialog.restore()
            by_path = {doc.path: doc for doc in win.docs}
            self.assertEqual(by_path[live].to_bytes(), stored)
            self.assertTrue(by_path[live].dirty)
            self.assertFalse(by_path[work].dirty)


class Session4Profiles(unittest.TestCase):
    """Release 2.3, session 4: spelling profiles that outlive Save and Deploy."""

    STOCK = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t740\t"Wolverhamption Wanderers"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t708\t"Sheffield United"\t""\n'
        '"CLUB_NAME_CHANGE"\t1\t"Arsenal"\t""\n'
    )
    WOLVES = ("CLUB_NAME_CHANGE", "740", "")
    SHEFF = ("CLUB_SHORT_NAME_CHANGE", "708", "")
    CODE = ("CLUB_3LETTER_NAME_CHANGE", "740", "")

    def _club(self, folder: Path, text: str | None = None) -> editor.LncDoc:
        path = folder / "FM27_Club_Names.lnc"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lnc(path, self.STOCK if text is None else text)
        return editor.LncDoc(path)

    def _recorded(self, tmp):
        """Two edits and one added line, recorded from a stock file into a saved profile."""
        root = Path(tmp)
        doc = self._club(root / "work")
        rows = {entry.id: entry for entry in doc.names()}
        editor.try_set_name(rows["740"], "Wolverhampton Wanderers")
        editor.try_set_name(rows["708"], "Sheff Utd")
        doc.append_entry("CLUB_3LETTER_NAME_CHANGE", "740", "WOL", "")
        profile = editor.create_profile(
            "My usual spellings", "Traditional names", root / "profiles")
        counts = editor.record_edits(profile, [doc])
        editor.save_profile(profile, root / "profiles")
        return root, doc, profile, counts

    def test_profile_file_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, doc, profile, _counts = self._recorded(tmp)
            self.assertEqual(profile.path, root / "profiles" / "my-usual-spellings.json")
            again = editor.load_profile(profile.path)
            self.assertEqual((again.name, again.note), ("My usual spellings", "Traditional names"))
            self.assertEqual(again.rows, profile.rows)
            self.assertEqual(again.to_bytes(), profile.path.read_bytes())
            data = json.loads(profile.path.read_text(encoding="utf-8"))
            self.assertEqual((data["format"], data["version"]), ("fm-name-profile", 1))
            wolves = again.rows[self.WOLVES]
            self.assertEqual(wolves["name"], "Wolverhampton Wanderers")
            self.assertEqual(wolves["baseline"], "Wolverhamption Wanderers")
            self.assertEqual(wolves["source"], str(doc.path))
            self.assertEqual(
                wolves["source_sha256"], hashlib.sha256(doc.path.read_bytes()).hexdigest())
            self.assertIsNone(again.rows[self.CODE]["baseline"])
            profiles, problems = editor.list_profiles(root / "profiles")
            self.assertEqual(([item.name for item in profiles], problems),
                             (["My usual spellings"], []))
            self.assertEqual(staging_files(root / "profiles"), [])

    def test_record_edits_keeps_baselines_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, doc, profile, counts = self._recorded(tmp)
            self.assertEqual(counts, {"added": 3, "updated": 0, "same": 0, "persons": 0,
                                      "removed": 0, "skipped": 0, "repeated": 0})
            self.assertNotIn(("CLUB_NAME_CHANGE", "1", ""), profile.rows)   # untouched
            again = editor.record_edits(profile, [doc])
            self.assertEqual((again["added"], again["updated"], again["same"]), (0, 0, 3))
            editor.try_set_name(next(e for e in doc.names() if e.id == "708"), "Sheffield Utd")
            again = editor.record_edits(profile, [doc])
            self.assertEqual((again["updated"], again["same"]), (1, 2))
            self.assertEqual(profile.rows[self.SHEFF]["name"], "Sheffield Utd")
            self.assertEqual(profile.rows[self.SHEFF]["baseline"], "Sheffield United")
            greek = root / "person_name_changes.lnc"
            greek.write_bytes(b"\xff\xfe" + (
                '"PERSON_FIRST_NAME_END_CHANGE"\t"GREEK"\t"ος"\t2\t"ης"\r\n'
            ).encode("utf-16-le"))
            rules = editor.LncDoc(greek)
            editor.try_set_name(rules.persons()[0], "ου")
            counts = editor.record_edits(profile, [rules])
            self.assertEqual((counts["persons"], counts["added"]), (1, 0))

    def test_saved_edits_are_not_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._club(Path(tmp))
            editor.try_set_name(doc.names()[0], "Wolves")
            doc.save(backup=False)
            profile = editor.Profile("Late")
            self.assertEqual(editor.record_edits(profile, [doc])["added"], 0)
            self.assertEqual(profile.rows, {})

    def test_apply_with_an_unchanged_baseline_is_ticked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _doc, profile, _counts = self._recorded(tmp)
            fresh = self._club(root / "game")          # the stock file again
            changes, missing, stats = editor.apply_profile(profile, [fresh])
            self.assertEqual(
                [(p.id, p.new, p.checked, p.note) for p in changes],
                [("740", "Wolverhampton Wanderers", True, "Baseline unchanged"),
                 ("708", "Sheff Utd", True, "Baseline unchanged")])
            self.assertEqual(
                [(p.cmd, p.new, p.checked, p.doc) for p in missing],
                [("CLUB_3LETTER_NAME_CHANGE", "WOL", True, fresh)])
            self.assertEqual((stats["ticked"], stats["review"], stats["same"]), (3, 0, 0))
            updated, added = editor.apply_profile_proposals(profile.name, changes, missing, [fresh])
            self.assertEqual((updated, len(added)), (2, 1))
            names = {(entry.cmd, entry.id): entry.name for entry in fresh.names()}
            self.assertEqual(names[("CLUB_NAME_CHANGE", "740")], "Wolverhampton Wanderers")
            self.assertEqual(names[("CLUB_3LETTER_NAME_CHANGE", "740")], "WOL")
            self.assertEqual(added[0].profile_mark, ("My usual spellings", "WOL"))
            self.assertTrue(fresh.dirty)
            changes, missing, stats = editor.apply_profile(profile, [fresh])
            self.assertEqual((changes, missing, stats["same"]), ([], [], 3))

    def test_apply_with_a_changed_baseline_is_unticked_and_noted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _doc, profile, _counts = self._recorded(tmp)
            update = (self.STOCK.replace("Sheffield United", "Sheffield Utd FC")
                      + '"CLUB_3LETTER_NAME_CHANGE"\t740\t"WLV"\t""\n')
            fresh = self._club(root / "game", update)
            changes, missing, stats = editor.apply_profile(profile, [fresh])
            by_key = {(p.cmd, p.id): p for p in changes}
            sheff = by_key[("CLUB_SHORT_NAME_CHANGE", "708")]
            self.assertFalse(sheff.checked)
            self.assertIn("the file says Sheffield Utd FC", sheff.note)
            self.assertIn("when recorded it said Sheffield United", sheff.note)
            self.assertEqual(sheff.base, "Sheffield United")
            code = by_key[("CLUB_3LETTER_NAME_CHANGE", "740")]
            self.assertFalse(code.checked)
            self.assertIn("when recorded it said no line", code.note)
            self.assertTrue(by_key[("CLUB_NAME_CHANGE", "740")].checked)
            self.assertEqual(missing, [])
            self.assertEqual((stats["ticked"], stats["review"]), (1, 2))
            editor.apply_profile_proposals(profile.name, changes, missing, [fresh])
            names = {(entry.cmd, entry.id): entry.name for entry in fresh.names()}
            self.assertEqual(names[("CLUB_SHORT_NAME_CHANGE", "708")], "Sheffield Utd FC")
            self.assertEqual(names[("CLUB_NAME_CHANGE", "740")], "Wolverhampton Wanderers")

    def test_a_line_the_file_no_longer_has_is_unticked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _doc, profile, _counts = self._recorded(tmp)
            update = self.STOCK.replace(
                '"CLUB_SHORT_NAME_CHANGE"\t708\t"Sheffield United"\t""\n', "")
            fresh = self._club(root / "game", update)
            _changes, missing, stats = editor.apply_profile(profile, [fresh])
            by_key = {(p.cmd, p.id): p for p in missing}
            gone = by_key[("CLUB_SHORT_NAME_CHANGE", "708")]
            self.assertFalse(gone.checked)
            self.assertIn("has no line for it now; when recorded it said Sheffield United",
                          gone.note)
            self.assertIs(gone.doc, fresh)
            self.assertTrue(by_key[("CLUB_3LETTER_NAME_CHANGE", "740")].checked)
            self.assertEqual((stats["ticked"], stats["review"]), (2, 1))

    def test_rows_for_files_that_are_not_open_are_left_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _doc, profile, _counts = self._recorded(tmp)
            other = root / "game" / "FM27_Fix.lnc"
            other.parent.mkdir(parents=True)
            write_lnc(other, '"COMP_LONG_NAME_CHANGE"\t9\t"Cup"\t""\n')
            changes, missing, stats = editor.apply_profile(profile, [editor.LncDoc(other)])
            self.assertEqual((changes, missing), ([], []))
            self.assertEqual(stats["elsewhere"], 3)
            self.assertIn("not open", editor.describe_profile_apply(profile, stats))

    def test_unsaved_edits_and_other_profiles_stay_unticked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _doc, profile, _counts = self._recorded(tmp)
            fresh = self._club(root / "game")
            wolves = next(entry for entry in fresh.names() if entry.id == "740")
            editor.try_set_name(wolves, "Wolves")
            changes, _missing, _stats = editor.apply_profile(profile, [fresh])
            first = next(p for p in changes if p.id == "740")
            self.assertFalse(first.checked)
            self.assertIn("Unsaved edit Wolves would be replaced", first.note)
            editor.revert_entry(wolves)
            other = editor.Profile("Modern names")
            other.rows[self.WOLVES] = dict(profile.rows[self.WOLVES], name="Wolves")
            changes, missing, _stats = editor.apply_profile(other, [fresh])
            self.assertTrue(changes[0].checked)
            editor.apply_profile_proposals(other.name, changes, missing, [fresh])
            self.assertEqual(wolves.name, "Wolves")
            changes, _missing, stats = editor.apply_profile(profile, [fresh])
            first = next(p for p in changes if p.id == "740")
            self.assertFalse(first.checked)
            self.assertIn("Competes with profile Modern names, which set Wolves", first.note)
            self.assertEqual(stats["review"], 1)

    def test_save_and_deploy_leave_the_profile_file_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _doc, profile, _counts = self._recorded(tmp)
            before = profile.path.read_bytes()
            stamp = profile.path.stat().st_mtime_ns
            fresh = self._club(root / "game")
            changes, missing, _stats = editor.apply_profile(profile, [fresh])
            editor.apply_profile_proposals(profile.name, changes, missing, [fresh])
            fresh.save(backup=False)
            editor.deploy_documents(
                [(fresh, root / "deployed" / fresh.path.name)], root / "backups")
            self.assertEqual(profile.path.read_bytes(), before)
            self.assertEqual(profile.path.stat().st_mtime_ns, stamp)

    def test_record_deploy_update_reopen_apply(self):
        """The roadmap's acceptance, with the game putting its own files back in between."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "db" / "2700" / "lnc" / "all"
            club = self._club(folder)
            fix_path = folder / "FM27_Fix.lnc"
            write_lnc(fix_path, '"COMP_LONG_NAME_CHANGE"\t9\t"Sky Bet Championship"\t""\n')
            stock = {path: path.read_bytes() for path in (club.path, fix_path)}
            docs = [club, editor.LncDoc(fix_path)]
            editor.try_set_name(next(e for e in club.names() if e.id == "740"),
                                "Wolverhampton Wanderers")
            editor.try_set_name(docs[1].names()[0], "Championship")
            profile = editor.create_profile("Mine", "", root / "profiles")
            editor.record_edits(profile, docs)
            editor.save_profile(profile, root / "profiles")
            editor.deploy_documents([(doc, doc.path) for doc in docs], root / "backups")
            # Reopened as deployed, every spelling already matches.
            changes, missing, stats = editor.apply_profile(
                profile, editor.open_documents(list(stock)))
            self.assertEqual((changes, missing, stats["same"]), ([], [], 2))
            # A game update puts its own files back. Reopen and Apply: the spellings
            # come back ticked, because the stock names are the recorded baselines.
            for path, data in stock.items():
                path.write_bytes(data)
            reopened = editor.open_documents(list(stock))
            changes, missing, stats = editor.apply_profile(
                editor.load_profile(profile.path), reopened)
            self.assertEqual(len(changes), 2)
            self.assertTrue(all(proposal.checked for proposal in changes))
            editor.apply_profile_proposals(profile.name, changes, missing, reopened)
            self.assertEqual(reopened[1].names()[0].name, "Championship")
            self.assertEqual(
                next(e for e in reopened[0].names() if e.id == "740").name,
                "Wolverhampton Wanderers")

    def test_profile_names_files_rename_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "profiles"
            first = editor.create_profile("  My usual spellings ", "", root)
            self.assertEqual((first.name, first.path.name),
                             ("My usual spellings", "my-usual-spellings.json"))
            for bad, words in (("", "Give the profile a name"),
                               ("x" * 81, "80 characters"),
                               ("Tab\tname", "control characters"),
                               ("MY USUAL SPELLINGS", "already a profile")):
                with self.subTest(bad=bad[:12]):
                    self.assertIn(words, editor.profile_name_problem(bad, [first]))
                    with self.assertRaises(ValueError):
                        editor.create_profile(bad, "", root, [first])
            for name, file_name in (("My usual spellings!", "my-usual-spellings-2.json"),
                                    ("Ünïcödé", "unicode.json"),
                                    ("CON", "con-profile.json"),
                                    ("!!!", "profile.json")):
                with self.subTest(name=name):
                    self.assertEqual(editor.create_profile(name, "", root).path.name, file_name)
            first.rows[self.WOLVES] = {
                "command": "CLUB_NAME_CHANGE", "id": "740", "language": "",
                "name": "Wolves", "baseline": None, "source": "", "source_sha256": "",
                "recorded": ""}
            editor.save_profile(first, root)
            old_path = first.path
            renamed = editor.rename_profile(first, "Traditional names", "Old style", root, [first])
            self.assertFalse(old_path.exists())
            self.assertEqual(renamed.path.name, "traditional-names.json")
            again = editor.load_profile(renamed.path)
            self.assertEqual((again.name, again.note, len(again.rows)),
                             ("Traditional names", "Old style", 1))
            same_file = editor.rename_profile(renamed, "TRADITIONAL NAMES", None, root, [renamed])
            self.assertEqual(same_file.path, renamed.path)
            self.assertEqual(same_file.note, "Old style")
            moved = editor.delete_profile(same_file, root)
            self.assertFalse(renamed.path.exists())
            self.assertEqual(moved.parent, root / "deleted")
            self.assertEqual(editor.load_profile(moved).name, "TRADITIONAL NAMES")
            self.assertNotIn("TRADITIONAL NAMES",
                             [item.name for item in editor.list_profiles(root)[0]])
            self.assertEqual(staging_files(root), [])

    def test_unreadable_profiles_are_reported_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            editor.create_profile("Good", "", root)
            (root / "broken.json").write_text("{not json", encoding="utf-8")
            (root / "pack.json").write_text(
                '{"format": "fm-name-pack", "version": 1, "names": []}', encoding="utf-8")
            row = {"command": "CLUB_NAME_CHANGE", "id": "1", "language": "",
                   "name": 'Say "hi"', "baseline": None}
            (root / "quote.json").write_text(json.dumps(
                {"format": "fm-name-profile", "version": 1, "name": "Quote", "rows": [row]}),
                encoding="utf-8")
            twice = dict(row, name="Fine")
            (root / "twice.json").write_text(json.dumps(
                {"format": "fm-name-profile", "version": 1, "name": "Twice",
                 "rows": [twice, twice]}), encoding="utf-8")
            profiles, problems = editor.list_profiles(root)
            self.assertEqual([item.name for item in profiles], ["Good"])
            self.assertEqual(len(problems), 4)
            joined = "\n".join(problems)
            for words in ("broken.json could not be read",
                          "pack.json is not a spelling profile",
                          "quote.json, row 1: the name",
                          "twice.json, row 2: an earlier row"):
                self.assertIn(words, joined)

    def test_local_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            self.assertEqual(editor.load_state(root), {})
            editor.save_state({"active_profile_file": "mine.json"}, root)
            self.assertEqual(editor.load_state(root), {"active_profile_file": "mine.json"})
            (root / "settings.json").write_text("[1, 2", encoding="utf-8")
            self.assertEqual(editor.load_state(root), {})
            self.assertEqual(staging_files(root), [])


class Session4Window(unittest.TestCase):
    """Release 2.3, session 4: the profile controls in the window header."""

    def _window(self, tmp):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        roots = mock.patch.multiple(
            editor, PROFILE_ROOT=Path(tmp) / "profiles", STATE_ROOT=Path(tmp) / "state")
        roots.start()
        self.addCleanup(roots.stop)
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")
        self.addCleanup(close_window, win)
        return win

    @staticmethod
    def _fill(name: str, note: str = ""):
        """A stand-in for QDialog.exec that types into the profile dialog and presses OK."""
        def run(dialog):
            dialog.name_edit.setText(name)
            dialog.note_edit.setText(note)
            dialog.try_accept()
            return dialog.result()
        return run

    def test_record_makes_a_profile_and_the_choice_is_remembered(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            win = self._window(tmp)
            self.assertEqual(win.profile_box.currentText(), "No profile")
            self.assertFalse(win.apply_profile_btn.isEnabled())
            path = Path(tmp) / "FM27_Club_Names.lnc"
            write_lnc(path, Session4Profiles.STOCK)
            self.assertTrue(win.load([str(path)]))
            editor.try_set_name(
                next(e for e in win.docs[0].names() if e.id == "740"), "Wolverhampton Wanderers")
            with mock.patch.object(QDialog, "exec", self._fill("My usual spellings", "Mine")), \
                    mock.patch.object(QMessageBox, "question",
                                      return_value=QMessageBox.Yes) as asked:
                win.record_into_profile()   # no profile yet: it offers to make one first
            self.assertEqual(asked.call_count, 2)
            self.assertIn("Record 1 spelling(s) into My usual spellings", asked.call_args.args[2])
            self.assertEqual(win.profile_box.currentText(), "My usual spellings")
            profile = win.current_profile()
            self.assertEqual(profile.note, "Mine")
            self.assertEqual(list(profile.rows), [("CLUB_NAME_CHANGE", "740", "")])
            self.assertEqual(editor.load_profile(profile.path).rows, profile.rows)
            self.assertEqual(editor.load_state(Path(tmp) / "state"),
                             {"active_profile_file": "my-usual-spellings.json"})
            # Recording the same edit again changes nothing and says so.
            with mock.patch.object(QMessageBox, "information") as told:
                win.record_into_profile()
            self.assertIn("already holds", told.call_args.args[2])
            # A new window comes up with the same profile chosen.
            _app, second = editor.run_gui([])
            self.addCleanup(close_window, second)
            self.assertEqual(second.profile_box.currentText(), "My usual spellings")
            self.assertTrue(second.apply_profile_btn.isEnabled())

    def test_apply_previews_and_changes_memory_only(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog

        with tempfile.TemporaryDirectory() as tmp:
            win = self._window(tmp)
            work = Path(tmp) / "work" / "FM27_Club_Names.lnc"
            stock = Path(tmp) / "game" / "FM27_Club_Names.lnc"
            for path in (work, stock):
                path.parent.mkdir()
                write_lnc(path, Session4Profiles.STOCK)
            doc = editor.LncDoc(work)
            editor.try_set_name(next(e for e in doc.names() if e.id == "708"), "Sheff Utd")
            profile = editor.create_profile("Mine", "", editor.PROFILE_ROOT)
            editor.record_edits(profile, [doc])
            editor.save_profile(profile, editor.PROFILE_ROOT)
            before = profile.path.read_bytes()
            win.refresh_profiles(profile.path.name)
            self.assertTrue(win.load([str(stock)]))
            on_disk = stock.read_bytes()
            shown = []

            def apply_ticked(dialog):
                model = dialog.change_model
                shown.append((dialog.windowTitle(), dialog.summary.text(),
                              [model.headerData(i, Qt.Horizontal)
                               for i in range(model.columnCount())]))
                dialog.apply()
                return dialog.result()

            with mock.patch.object(QDialog, "exec", apply_ticked):
                win.apply_profile_to_files()
            title, summary, columns = shown[0]
            self.assertEqual(title, "Apply profile: Mine")
            self.assertIn("1 ticked", summary)
            self.assertIn("Profile spelling", columns)
            self.assertIn("Baseline when recorded", columns)
            self.assertEqual(
                next(e for e in win.docs[0].names() if e.id == "708").name, "Sheff Utd")
            self.assertTrue(win.docs[0].dirty)
            self.assertEqual(stock.read_bytes(), on_disk)       # memory only until Save
            with mock.patch.object(QDialog, "exec", press_write([])):
                win.save()
            self.assertIn(b'"Sheff Utd"', stock.read_bytes())
            self.assertEqual(profile.path.read_bytes(), before)  # Save leaves the profile alone

    def test_rename_delete_and_unreadable_profiles(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "profiles"
            first = editor.create_profile("Old name", "", root)
            editor.create_profile("Other", "", root)
            (root / "broken.json").write_text("{not json", encoding="utf-8")
            win = self._window(tmp)
            self.assertIn("could not be read", win.statusBar().currentMessage())
            self.assertEqual([win.profile_box.itemText(i) for i in range(win.profile_box.count())],
                             ["No profile", "Old name", "Other"])
            win.refresh_profiles(first.path.name)
            with mock.patch.object(QDialog, "exec", self._fill("other")):
                win.rename_current_profile()        # the name is taken, so nothing changes
            self.assertTrue(first.path.exists())
            self.assertEqual(win.profile_box.currentText(), "Old name")
            with mock.patch.object(QDialog, "exec", self._fill("New name")):
                win.rename_current_profile()
            self.assertFalse(first.path.exists())
            self.assertEqual(win.profile_box.currentText(), "New name")
            self.assertEqual(editor.load_state(Path(tmp) / "state")["active_profile_file"],
                             "new-name.json")
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                win.delete_current_profile()
            self.assertEqual(win.profile_box.currentText(), "No profile")
            self.assertEqual([profile.name for profile in win.profiles], ["Other"])
            self.assertEqual(len(list((root / "deleted").glob("new-name-*.json"))), 1)
            self.assertEqual(editor.load_state(Path(tmp) / "state")["active_profile_file"], "")
            self.assertTrue((root / "broken.json").exists())     # left alone


class Session5Changes(unittest.TestCase):
    """Release 2.3, session 5: the Changes model, include ticks, and the review before a write."""

    ROWS = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t1\t"Alp"\t""\n'
        '"CLUB_NAME_CHANGE"\t2\t"Beta"\t""\n'
        '"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""\n'
    )

    def _club(self, folder: Path, text: str | None = None):
        path = folder / "FM27_Club_Names.lnc"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lnc(path, self.ROWS if text is None else text)
        return editor.LncDoc(path), path

    @staticmethod
    def _row(doc, id_: str, cmd: str = "CLUB_NAME_CHANGE"):
        return next(entry for entry in doc.names() if entry.id == id_ and entry.cmd == cmd)

    def _save(self, doc, path, tmp):
        """A Save review of a file outside the game tree."""
        return editor.WriteReview("Save", [(doc, path)], Path(tmp) / "no-game-here")

    def test_the_changes_list_edited_added_restored_and_removed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc, _path = self._club(root / "work")
            editor.try_set_name(self._row(doc, "1"), "Alpha United")
            entity = next(item for item in editor.build_entities([doc]) if item.id == "1")
            self.assertTrue(editor.set_entity_field(entity, "code", "ALP", [doc]))
            rows = editor.collect_changes([doc])
            self.assertEqual(
                [(r.state, r.reason, r.command, r.id, r.on_disk, r.proposed, r.line)
                 for r in rows],
                [("edited", "Manual edit", "CLUB_NAME_CHANGE", "1", "Alpha", "Alpha United", 2),
                 ("added", "Manual edit", "CLUB_3LETTER_NAME_CHANGE", "1", "no line", "ALP", 3)])
            self.assertTrue(all(row.included for row in rows))
            self.assertFalse(doc.grouped)
            # A restored backup: one name differs, one line is new, one disk line is missing.
            restored, path = self._club(root / "game")
            stored = root / "backups" / "20261111-120000" / path.name
            stored.parent.mkdir(parents=True)
            write_lnc(stored, self.ROWS.replace('"Beta"', '"Beta Old"').replace(
                '"CLUB_NAME_CHANGE"\t3\t"Gamma"', '"CLUB_NAME_CHANGE"\t4\t"Delta"'))
            editor.restore_into(restored, stored)
            rows = editor.collect_changes([restored])
            self.assertEqual(
                [(r.state, r.reason, r.id, r.on_disk, r.proposed) for r in rows],
                [("restored", "Restore", "2", "Beta", "Beta Old"),
                 ("added", "Restore", "4", "no line", "Delta"),
                 ("removed", "Restore", "3", "Gamma", "no line")])
            self.assertTrue(restored.grouped)
            self.assertIn(str(stored), rows[0].detail)
            self.assertEqual(
                editor.pending_restores([doc, restored]),
                "Restore pending, not written yet: FM27_Club_Names.lnc (backup 20261111-120000)")
            # A copy that differs only in a comment still shows, as one row.
            other, path = self._club(root / "other")
            copy = root / "backups" / "20261111-130000" / path.name
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.ROWS.replace("#England", "#England and Wales"))
            editor.restore_into(other, copy)
            self.assertEqual([(r.state, r.proposed) for r in editor.collect_changes([other])],
                             [("other", editor.OTHER_LINES_TEXT)])

    def test_each_operation_records_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "".join(f'"CLUB_NAME_CHANGE"\t{n}\t"Club {n}"\t""\n' for n in range(1, 7))
            doc, _path = self._club(Path(tmp), text)
            row = {entry.id: entry for entry in doc.names()}

            def proposal(entry, new):
                return editor.Proposal(entry.cmd, entry.id, "", new, entry, "", True)

            editor.try_set_name(row["1"], "Club One")
            editor.apply_bulk([editor.BulkEdit(None, "long", row["2"], "Club 2", "Club Two")],
                              [doc])
            edits, _skipped, _error = editor.preview_replace([doc], "^Club 3$", "Club Three")
            editor.apply_bulk(edits, [doc], "replace")
            editor.apply_proposals([proposal(row["4"], "Club Four")], [], [doc])
            missing = editor.Proposal("CLUB_NAME_CHANGE", "7", "", "Club Seven", None, "", True)
            editor.apply_proposals([proposal(row["5"], "Club Five")], [missing], [doc], "pack")
            editor.apply_profile_proposals("Mine", [proposal(row["6"], "Club Six")], [], [doc])
            self.assertEqual(
                {r.id: (r.state, r.reason) for r in editor.collect_changes([doc])},
                {"1": ("edited", "Manual edit"), "2": ("edited", "Bulk tool"),
                 "3": ("edited", "Replace"), "4": ("edited", "Older files"),
                 "5": ("edited", "Name pack"), "6": ("edited", "Profile Mine"),
                 "7": ("added", "Name pack")})
            row["1"].excluded = True
            self.assertEqual(editor.revert_entry(row["1"]), "name")
            self.assertIsNone(row["1"].reason)
            self.assertFalse(row["1"].excluded)     # a later change to it starts ticked

    def test_leaving_changes_out_rebuilds_the_file_on_disk(self):
        variants = (("LF", "\n", True, "utf-8"), ("CRLF", "\r\n", True, "utf-8"),
                    ("no final ending", "\n", False, "utf-8"),
                    ("UTF-16", "\r\n", True, "utf-16-le"))
        for label, eol, final, encoding in variants:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                text = eol.join(self.ROWS.rstrip("\n").split("\n")) + (eol if final else "")
                path = Path(tmp) / "FM27_Club_Names.lnc"
                if encoding == "utf-16-le":
                    path.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
                else:
                    path.write_bytes(BOM + text.encode("utf-8"))
                doc = editor.LncDoc(path)
                editor.try_set_name(self._row(doc, "2"), "Beta Town")
                entity = next(item for item in editor.build_entities([doc]) if item.id == "3")
                editor.set_entity_field(entity, "short", "Gam", [doc])  # after the last line
                doc.append_entry("CLUB_NAME_CHANGE", "9", "Iota", "")   # under an import heading
                self.assertTrue(doc.separable)
                none = editor.payload_lines(doc, lambda _entry: False)
                every = editor.payload_lines(doc, lambda _entry: True)
                self.assertEqual(doc.encode_text(editor.lines_text(none)), path.read_bytes())
                self.assertEqual(doc.encode_text(editor.lines_text(every)), doc.to_bytes())
                for row in editor.collect_changes([doc]):
                    row.set_included(row.id == "3")     # only the inserted short name
                payload = editor.build_payload(doc)
                self.assertEqual((payload.included, payload.left_out), (1, 2))
                written = editor.decode_lnc_bytes(payload.data)[0]
                self.assertIn('"Gam"', written)
                self.assertNotIn("Beta Town", written)
                self.assertNotIn("Iota", written)
                self.assertNotIn("Imported by FM Name Editor", written)

    def test_an_unticked_row_is_not_written_and_stays_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path = self._club(Path(tmp))
            alpha, beta = self._row(doc, "1"), self._row(doc, "2")
            editor.try_set_name(alpha, "Alpha United")
            editor.try_set_name(beta, "Beta Town")
            next(r for r in editor.collect_changes([doc]) if r.id == "2").set_included(False)
            review = self._save(doc, path, tmp)
            self.assertEqual((review.included, review.left_out), (1, 1))
            self.assertEqual(review.problems(), [])
            self.assertIsNone(review.write(Path(tmp) / "backups"))
            on_disk = path.read_bytes().decode("utf-8-sig")
            self.assertIn('"Alpha United"', on_disk)
            self.assertIn('"Beta"', on_disk)
            self.assertNotIn("Beta Town", on_disk)
            self.assertTrue(doc.dirty)                  # the unticked row is still pending
            self.assertEqual(beta.name, "Beta Town")
            self.assertEqual(alpha.orig_name, "Alpha United")
            rows = editor.collect_changes([doc])
            self.assertEqual([(r.id, r.on_disk, r.proposed, r.included) for r in rows],
                             [("2", "Beta", "Beta Town", False)])
            self.assertIn("1 left out, still pending", review.outcome(None))
            self.assertEqual(len(list(Path(tmp).glob("*.bak-*"))), 1)
            rows[0].set_included(True)
            self._save(doc, path, tmp).write(Path(tmp) / "backups")
            self.assertEqual(path.read_bytes(), doc.to_bytes())
            self.assertFalse(doc.dirty)
            self.assertEqual(editor.collect_changes([doc]), [])

    def test_a_restored_file_is_written_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc, path = self._club(root / "game")
            stored = root / "backups" / "20261111-120000" / path.name
            stored.parent.mkdir(parents=True)
            write_lnc(stored, self.ROWS.replace('"Alpha"', '"Alpha Old"').replace(
                '"Beta"', '"Beta Old"'))
            on_disk = path.read_bytes()
            editor.restore_into(doc, stored)
            rows = editor.collect_changes([doc])
            self.assertEqual(len(rows), 2)
            rows[0].set_included(False)                 # one tick stands for the whole file
            self.assertEqual([row.included for row in rows], [False, False])
            payload = editor.build_payload(doc)
            self.assertEqual((payload.data, payload.included, payload.left_out), (on_disk, 0, 2))
            review = self._save(doc, path, tmp)
            self.assertEqual(review.to_write, [])
            self.assertIn("Nothing is ticked", review.problems()[0])
            rows[1].set_included(True)
            review.refresh()
            self.assertEqual(review.files[0].write_state(), "2 change(s), written together")
            review.write(root / "backups")
            self.assertEqual(path.read_bytes(), stored.read_bytes())
            self.assertFalse(doc.dirty)
            self.assertFalse(doc.restore_pending)
            self.assertEqual(editor.pending_restores([doc]), "")

    def test_a_file_that_cannot_be_split_is_written_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path = self._club(Path(tmp))
            added = doc.append_entry("CLUB_NAME_CHANGE", "9", "Iota", "")
            doc.entries.remove(added)                   # leaves the import heading on its own
            doc.touch()
            self.assertTrue(doc.dirty)
            self.assertFalse(doc.separable)
            rows = editor.collect_changes([doc])
            self.assertEqual([row.state for row in rows], ["other"])
            rows[0].set_included(False)
            self.assertEqual(editor.build_payload(doc).data, doc.baseline_bytes)
            rows[0].set_included(True)
            self.assertEqual(editor.build_payload(doc).data, doc.to_bytes())

    def test_an_external_change_blocks_the_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path = self._club(Path(tmp))
            editor.try_set_name(self._row(doc, "1"), "Alpha United")
            write_lnc(path, self.ROWS.replace("Gamma", "Gamma changed elsewhere"))
            outside = path.read_bytes()
            review = self._save(doc, path, tmp)
            self.assertEqual(review.files[0].external, "changed")
            text, level = review.disk_check()
            self.assertEqual(level, "blocked")
            self.assertIn("changed on disk since the editor read it", text)
            problems = review.problems()
            self.assertEqual(len(problems), 1)
            self.assertIn("changed on disk, or were removed, after the editor read them",
                          problems[0])
            self.assertIn(str(path), problems[0])
            with self.assertRaises(editor.WriteError):
                review.write(Path(tmp) / "backups")
            self.assertEqual(path.read_bytes(), outside)
            self.assertTrue(doc.dirty)
            # A change made after the review is still caught by the write itself.
            fresh, second = self._club(Path(tmp) / "second")
            editor.try_set_name(self._row(fresh, "1"), "Alpha United")
            review = self._save(fresh, second, tmp)
            self.assertEqual(review.problems(), [])
            write_lnc(second, self.ROWS + '"CLUB_NAME_CHANGE"\t8\t"Theta"\t""\n')
            with self.assertRaises(editor.ExternalChangeError):
                review.write(Path(tmp) / "backups")
            self.assertTrue(fresh.dirty)

    def test_a_deploy_with_nothing_new_writes_nothing(self):
        """A Deploy of unchanged files rewrote them on 11 November 2026; the review skips them."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            club, club_path = self._club(root / "db" / "2700" / "lnc" / "all")
            review = editor.WriteReview("Deploy", [(club, club_path)], check=lambda: [])
            self.assertEqual(review.to_write, [])
            self.assertEqual(
                review.problems(),
                ["The destination files already hold these bytes, so there is nothing to write."])
            self.assertEqual(review.files[0].write_state(),
                             "not written: it already holds these bytes")
            # A working copy from elsewhere replaces the game file whole.
            work, _work_path = self._club(root / "work", self.ROWS.replace("Alpha", "Alpha W"))
            review = editor.WriteReview("Deploy", [(work, club_path)], check=lambda: [])
            item = review.files[0]
            self.assertTrue(item.writes)
            self.assertEqual(item.disk_state(),
                             "a file the editor did not open; it is replaced whole")
            archive = review.write(root / "backups")
            self.assertEqual(club_path.read_bytes(), work.baseline_bytes)
            self.assertEqual(work.path, club_path)
            self.assertTrue((archive / editor.MANIFEST_NAME).is_file())

    def test_the_review_names_the_operation_and_its_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "db"
            doc, path = self._club(
                game / "2700" / "lnc" / "all",
                self.ROWS + '"CLUB_NAME_CHANGE"\t2\t"Beta Again"\t""\n"BROKEN\n')
            editor.try_set_name(self._row(doc, "1"), "Alpha United")
            calls = []
            review = editor.WriteReview(
                "Save", [(doc, path)], game, check=lambda: calls.append(1) or [])
            self.assertEqual(review.title,
                             "Review changes: Save into the game folder, the same as Deploy")
            self.assertEqual(calls, [1])
            self.assertEqual(review.game_check(), ("Football Manager is not running.", "ok"))
            text, level = review.problem_check()
            self.assertEqual(level, "warning")
            self.assertIn("1 problem line(s) in FM27_Club_Names.lnc", text)
            text, level = review.repeated_check()
            self.assertIn("1 command, ID, and language key(s) are on more than one line; "
                          "1 with different names", text)
            self.assertIn(str(root / "backups"), review.backup_text(root / "backups"))
            unknown = editor.WriteReview("Save", [(doc, path)], game, check=lambda: None)
            self.assertEqual(unknown.game_check()[1], "warning")
            running = editor.WriteReview("Save", [(doc, path)], game, check=lambda: ["fm.exe"])
            self.assertIn("fm.exe", running.problems()[0])
            outside = editor.WriteReview(
                "Save", [(doc, path)], root / "elsewhere", check=lambda: calls.append(2) or [])
            self.assertEqual(outside.title, "Review changes: Save")
            self.assertEqual(calls, [1])                # no game file, so no process check
            self.assertEqual(outside.game_check()[1], "muted")
            deploy = editor.WriteReview("Deploy", [(doc, path)], check=lambda: [])
            self.assertEqual(deploy.title, "Review changes: Deploy to the game folder")


class Session6Undo(unittest.TestCase):
    """Release 2.3, session 6: whole operations undo and redo exactly."""

    ROWS = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t1\t"Alpha FC"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        '"CLUB_NAME_CHANGE"\t2\t"Beta"\t""\n'
        '"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""'           # the last line has no ending
    )

    @staticmethod
    def _state(doc):
        """Everything about a document that an undo must put back."""
        return (doc.to_bytes(), doc.dirty, doc.restore_pending, doc.restored_from,
                doc.encoding, [row.raw for row in doc.removed_rows],
                [(e.raw, e.eol, e.lineno, e.name, e.source, e.reason, e.profile_mark,
                  e.imported, e.orig_name, e.orig_source, e.orig_raw, e.orig_eol)
                 for e in doc.entries])

    def _club(self, folder: Path, text: str | None = None):
        path = folder / "FM27_Club_Names.lnc"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lnc(path, self.ROWS if text is None else text)
        return editor.LncDoc(path), path

    @staticmethod
    def _row(doc, id_, cmd="CLUB_NAME_CHANGE"):
        return next(e for e in doc.names() if e.id == id_ and e.cmd == cmd)

    def _operations(self, tmp):
        """Each kind of change the window records, as (label, document, change)."""
        root = Path(tmp)

        def proposal(entry, new):
            return editor.Proposal(entry.cmd, entry.id, "", new, entry, "", True)

        def cell(doc):
            editor.try_set_name(self._row(doc, "2"), "Beta Town")

        def insertion(doc):
            entity = next(e for e in editor.build_entities([doc]) if e.id == "3")
            self.assertTrue(editor.set_entity_field(entity, "short", "Gam", [doc]))

        def bulk(doc):
            edits = editor.preview_bulk(editor.build_entities([doc]), "affix")
            self.assertEqual(editor.apply_bulk(edits, [doc]), 1)

        def replace(doc):
            edits, _skipped, _error = editor.preview_replace([doc], "a$", "a Town")
            editor.apply_bulk(edits, [doc], "replace")

        def pack(doc):
            missing = editor.Proposal("CLUB_NAME_CHANGE", "9", "", "Iota", None, "", True)
            editor.apply_proposals([proposal(self._row(doc, "2"), "Beta B")], [missing],
                                   [doc], "pack")

        def older(doc):
            editor.apply_proposals([proposal(self._row(doc, "3"), "Gamma G")], [], [doc])

        def profile(doc):
            editor.apply_profile_proposals("Mine", [proposal(self._row(doc, "1"), "Alpha")],
                                           [], [doc])

        def restore(doc):
            copy = root / "backups" / "20261111-120000" / doc.path.name
            copy.parent.mkdir(parents=True, exist_ok=True)
            write_lnc(copy, self.ROWS.replace("Beta", "Beta Old").replace(
                '"CLUB_NAME_CHANGE"\t3\t"Gamma"\t""', '"CLUB_NAME_CHANGE"\t4\t"Delta"\t""\n'))
            editor.restore_into(doc, copy)

        def revert(doc):
            editor.revert_entries(doc.names())

        return (("cell edit", cell), ("insertion after a last line with no ending", insertion),
                ("bulk tool", bulk), ("replace", replace), ("name pack with an added line", pack),
                ("older files", older), ("profile", profile), ("restore", restore),
                ("revert", revert))

    def test_each_operation_undoes_and_redoes_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            for label, change in self._operations(tmp):
                with self.subTest(label):
                    doc, _path = self._club(Path(tmp) / label.replace(" ", "-"))
                    if label == "revert":       # something to revert, made beforehand
                        editor.try_set_name(self._row(doc, "1"), "Alpha United")
                        editor.try_set_name(self._row(doc, "2"), "Beta United")
                    before = self._state(doc)
                    with editor.Operation(label) as operation:
                        change(doc)
                    after = self._state(doc)
                    self.assertTrue(operation.changed)
                    self.assertNotEqual(before, after)
                    operation.undo()
                    self.assertEqual(self._state(doc), before)
                    operation.redo()
                    self.assertEqual(self._state(doc), after)
                    operation.undo()
                    self.assertEqual(self._state(doc), before)

    def test_a_person_rule_undoes_both_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "person_name_changes.lnc"
            rules = "".join(
                f'"PERSON_FIRST_NAME_END_CHANGE"\t"GREEK"\t"{ending}"\t{n}\t"{new}"\r\n'
                for ending, n, new in (("ος", 1, "ης"),
                                       ("ας", 2, "α")))
            path.write_bytes(b"\xff\xfe" + rules.encode("utf-16-le"))
            doc = editor.LncDoc(path)
            before = self._state(doc)
            rule = doc.persons()[0]
            with editor.Operation("edit rule") as operation:
                editor.try_set_source(rule, "ους")
                editor.try_set_name(rule, "ου")
            operation.undo()
            self.assertEqual(self._state(doc), before)
            self.assertEqual((rule.source, rule.name), ("ος", "ης"))
            self.assertEqual(doc.to_bytes(), path.read_bytes())
            operation.redo()
            self.assertEqual((rule.source, rule.name), ("ους", "ου"))

    def test_undoing_an_insertion_removes_the_line_and_its_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path = self._club(Path(tmp))
            gamma = self._row(doc, "3")
            entity = next(e for e in editor.build_entities([doc]) if e.id == "3")
            with editor.Operation("add short name") as insertion:
                editor.set_entity_field(entity, "short", "Gam", [doc])
            self.assertEqual(gamma.eol, "\n")           # the sibling got an ending
            insertion.undo()
            self.assertEqual(gamma.eol, "")             # and has none again
            self.assertNotIn("Gam", [e.name for e in doc.entries])
            self.assertFalse(doc.dirty)                 # memory equals the disk file again
            self.assertEqual(doc.to_bytes(), path.read_bytes())
            # With another unsaved edit open, the file stays unsaved after the undo.
            editor.try_set_name(self._row(doc, "2"), "Beta Town")
            with editor.Operation("pack") as append:
                doc.append_entry("CLUB_NAME_CHANGE", "9", "Iota", "", "pack")
            self.assertTrue(any("Imported by" in e.raw for e in doc.entries))
            append.undo()
            self.assertFalse(any("Imported by" in e.raw for e in doc.entries))
            self.assertTrue(doc.dirty)
            self.assertTrue(doc.separable)              # no heading left on its own
            # An append under a heading that is already in the file leaves the heading.
            write_lnc(path, self.ROWS + "\n#Imported by FM Name Editor\n")
            doc = editor.LncDoc(path)
            with editor.Operation("pack") as append:
                doc.append_entry("CLUB_NAME_CHANGE", "9", "Iota", "", "pack")
            append.undo()
            self.assertEqual(doc.to_bytes(), path.read_bytes())

    def test_undo_and_redo_across_a_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path = self._club(Path(tmp))
            original = path.read_bytes()
            entity = next(e for e in editor.build_entities([doc]) if e.id == "3")
            with editor.Operation("add short name") as insertion:
                editor.set_entity_field(entity, "short", "Gam", [doc])
            with editor.Operation("edit") as rename:
                editor.try_set_name(self._row(doc, "2"), "Beta Town")

            def save():
                editor.WriteReview("Save", [(doc, path)], Path(tmp) / "no-game").write(
                    Path(tmp) / "backups")

            save()
            self.assertFalse(doc.dirty)
            rename.undo()
            insertion.undo()
            rows = editor.collect_changes([doc])
            self.assertEqual(
                [(r.state, r.reason, r.id, r.on_disk, r.proposed) for r in rows],
                [("edited", "Undo or redo", "2", "Beta Town", "Beta"),
                 ("removed", "Undo or redo", "3", "Gam", "no line")])
            self.assertTrue(doc.grouped)                # a line to take out: written whole
            self.assertEqual(editor.build_payload(doc).data, original)
            save()
            self.assertEqual(path.read_bytes(), original)
            insertion.redo()
            rows = editor.collect_changes([doc])
            self.assertEqual([(r.state, r.reason, r.proposed) for r in rows],
                             [("added", "Undo or redo", "Gam")])
            self.assertTrue(doc.separable)
            save()
            rename.redo()
            self.assertEqual([(r.state, r.proposed) for r in editor.collect_changes([doc])],
                             [("edited", "Beta Town")])

    def test_a_restore_undone_after_it_was_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, path = self._club(Path(tmp))
            original = path.read_bytes()
            copy = Path(tmp) / "backups" / "20261111-120000" / path.name
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.ROWS.replace("Beta", "Beta Old"))
            with editor.Operation("restore") as restore:
                editor.restore_into(doc, copy)
            editor.WriteReview("Save", [(doc, path)], Path(tmp) / "no-game").write(
                Path(tmp) / "backups")
            self.assertEqual(path.read_bytes(), copy.read_bytes())
            restore.undo()
            self.assertEqual(doc.to_bytes(), original)
            self.assertFalse(doc.restore_pending)
            rows = editor.collect_changes([doc])
            self.assertEqual([(r.state, r.on_disk, r.proposed) for r in rows],
                             [("edited", "Beta Old", "Beta")])
            self.assertTrue(doc.separable)              # the lines line up with the disk file

    def test_an_operation_that_changes_nothing_is_not_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _path = self._club(Path(tmp))
            with editor.Operation("edit") as operation:
                editor.try_set_name(self._row(doc, "2"), "Beta")     # the same name
            self.assertFalse(operation.changed)
            with editor.Operation("edit and back") as operation:
                editor.try_set_name(self._row(doc, "2"), "Beta Town")
                editor.try_set_name(self._row(doc, "2"), "Beta")
            self.assertFalse(operation.changed)
            # Kept for another line, it still puts the named-back line exactly as it was.
            before = self._state(doc)
            with editor.Operation("edit, and edit and back") as operation:
                editor.try_set_name(self._row(doc, "1"), "Alpha Town")     # untouched so far
                editor.try_set_name(self._row(doc, "1"), "Alpha FC")
                editor.try_set_name(self._row(doc, "3"), "Gamma Town")
            self.assertTrue(operation.changed)
            operation.undo()
            self.assertEqual(self._state(doc), before)


class Session6Window(unittest.TestCase):
    """Release 2.3, session 6: the undo stack, Ctrl+Z and Ctrl+Y, and the Edit menu."""

    CLUBS = "#England\n" + "".join(
        f'"CLUB_NAME_CHANGE"\t{n}\t"Club {n} FC"\t""\n' for n in range(1, 4))

    def _window(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")
        self.addCleanup(close_window, win)
        return win

    def _open(self, win, tmp) -> Path:
        path = Path(tmp) / "mine.lnc"
        write_lnc(path, self.CLUBS)
        self.assertTrue(win.load([str(path)]))
        return path

    @staticmethod
    def _names(win):
        return [entry.name for entry in win.docs[0].names()]

    def test_ctrl_z_and_ctrl_y_undo_and_redo_a_cell_edit(self):
        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            self._open(win, tmp)
            self.assertEqual([action.text() for action in win.edit_menu.actions()],
                             ["Undo", "Redo"])
            self.assertFalse(win.undo_act.isEnabled())
            self.assertEqual(win.undo_act.shortcut().toString(), "Ctrl+Z")
            self.assertIn("Ctrl+Y", [key.toString() for key in win.redo_act.shortcuts()])
            model = win.entity_model
            row = next(n for n, entity in enumerate(model.rows) if entity.id == "1")
            self.assertTrue(model.setData(model.index(row, 2), "Club One"))
            self.assertEqual(win.undo_act.text(), "Undo edit long name: Club One")
            self.assertNotIn("Redone", win.statusBar().currentMessage())  # pushed, not re-run
            win.undo_act.trigger()
            self.assertEqual(model.rows[row].name_in("long"), "Club 1 FC")
            self.assertFalse(win.docs[0].dirty)
            self.assertIn("Undone: edit long name: Club One", win.statusBar().currentMessage())
            self.assertEqual(win.redo_act.text(), "Redo edit long name: Club One")
            win.redo_act.trigger()
            self.assertEqual(model.rows[row].name_in("long"), "Club One")
            self.assertTrue(win.docs[0].dirty)

    def test_an_added_field_is_one_step(self):
        from PySide6.QtWidgets import QApplication

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            self._open(win, tmp)
            model = win.entity_model
            row = next(n for n, entity in enumerate(model.rows) if entity.id == "1")
            column = model.columns().index("code")
            self.assertTrue(model.setData(model.index(row, column), "CLU"))
            QApplication.processEvents()                # the views reload for the new line
            self.assertEqual(win.undo_act.text(), "Undo add 3-letter code: CLU")
            self.assertEqual(win.tabs.tabText(2), "Changes (1)")
            win.undo_act.trigger()
            self.assertNotIn("CLU", [entry.name for entry in win.docs[0].entries])
            self.assertFalse(win.docs[0].dirty)
            self.assertEqual(win.tabs.tabText(2), "Changes")
            shown = next(e for e in win.entity_model.rows if e.id == "1")
            self.assertEqual(shown.name_in("code"), "")         # the grid no longer shows it
            win.redo_act.trigger()
            self.assertIn("CLU", [entry.name for entry in win.docs[0].entries])
            entity = next(e for e in win.entity_model.rows if e.id == "1")
            self.assertEqual(entity.name_in("code"), "CLU")

    def test_bulk_revert_and_restore_are_one_step_each(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            self._open(win, tmp)

            def strip(dialog):
                dialog.preview()                        # the affix stripper is the default
                dialog.apply_edits()
                return dialog.result()

            with mock.patch.object(QDialog, "exec", strip):
                win.open_bulk()
            self.assertEqual(win.undo_act.text(), "Undo bulk: strip affix (3 names)")
            self.assertEqual(self._names(win), ["Club 1", "Club 2", "Club 3"])
            win.undo_act.trigger()
            self.assertEqual(self._names(win), ["Club 1 FC", "Club 2 FC", "Club 3 FC"])
            self.assertFalse(win.docs[0].dirty)
            win.redo_act.trigger()
            win.tabs.setCurrentIndex(1)
            win.line_view.selectAll()
            win.revert_selected()
            self.assertEqual(win.undo_act.text(), "Undo revert: 3 names")
            self.assertEqual(self._names(win), ["Club 1 FC", "Club 2 FC", "Club 3 FC"])
            win.undo_act.trigger()
            self.assertEqual(self._names(win), ["Club 1", "Club 2", "Club 3"])
            backups = Path(tmp) / "backups"
            copy = backups / "20261111-120000" / "mine.lnc"
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.CLUBS.replace("Club 2 FC", "Club Two"))

            def restore(dialog):
                with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                    dialog.restore()
                return 0

            with mock.patch.object(editor, "BACKUP_ROOT", backups), \
                    mock.patch.object(QDialog, "exec", restore):
                win.open_backups()
            self.assertEqual(win.undo_act.text(), "Undo restore mine.lnc from 20261111-120000")
            self.assertTrue(win.docs[0].restore_pending)
            self.assertIn("Restore pending", win.pending_label.text())
            win.undo_act.trigger()
            self.assertFalse(win.docs[0].restore_pending)
            self.assertEqual(win.pending_label.text(), "")
            self.assertEqual(self._names(win), ["Club 1", "Club 2", "Club 3"])
            self.assertEqual([win.undo_stack.text(n) for n in range(win.undo_stack.count())],
                             ["bulk: strip affix (3 names)",
                              "restore mine.lnc from 20261111-120000"])

    def test_a_save_marks_the_clean_point_and_keeps_the_history(self):
        from PySide6.QtWidgets import QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._open(win, tmp)
            model = win.entity_model
            row = next(n for n, entity in enumerate(model.rows) if entity.id == "1")
            model.setData(model.index(row, 2), "Club One")
            with mock.patch.object(QDialog, "exec", press_write([])):
                win.save()
            self.assertIn(b'"Club One"', path.read_bytes())
            self.assertTrue(win.undo_stack.isClean())
            self.assertEqual(win.undo_stack.count(), 1)
            win.undo_act.trigger()                      # back past the write
            self.assertFalse(win.undo_stack.isClean())
            self.assertTrue(win.docs[0].dirty)          # memory differs from the file written
            self.assertEqual(win.tabs.tabText(2), "Changes (1)")
            change = editor.collect_changes(win.docs)[0]
            self.assertEqual((change.on_disk, change.proposed, change.reason),
                             ("Club One", "Club 1 FC", "Undo or redo"))
            win.redo_act.trigger()
            self.assertTrue(win.undo_stack.isClean())
            self.assertFalse(win.docs[0].dirty)
            self.assertTrue(win.load([str(path)]))       # new files, new history
            self.assertEqual(win.undo_stack.count(), 0)


class Session5Window(unittest.TestCase):
    """Release 2.3, session 5: the Changes tab, the review dialog, and the footer."""

    CLUBS = "#England\n" + "".join(
        f'"CLUB_NAME_CHANGE"\t{n}\t"Club {n}"\t""\n' for n in range(1, 7))
    CUPS = "#England\n" + "".join(
        f'"COMP_LONG_NAME_CHANGE"\t{n}\t"Cup {n}"\t""\n' for n in range(1, 5))

    def _window(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")
        self.addCleanup(close_window, win)
        return win

    def _game(self, tmp):
        """Both name files in a stand-in for lnc\\all, with the game root and backups patched."""
        root = Path(tmp)
        folder = root / "db" / "2700" / "lnc" / "all"
        folder.mkdir(parents=True)
        club, fix = folder / "FM27_Club_Names.lnc", folder / "FM27_Fix.lnc"
        write_lnc(club, self.CLUBS)
        write_lnc(fix, self.CUPS)
        roots = mock.patch.multiple(editor, GAME_DB_ROOT=root / "db", BACKUP_ROOT=root / "backups")
        roots.start()
        self.addCleanup(roots.stop)
        return club, fix

    def test_ticks_in_the_changes_tab_carry_into_the_review(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, self.CLUBS)
            self.assertTrue(win.load([str(path)]))
            model = win.entity_model
            for id_, new in (("1", "Club One"), ("2", "Club Two")):
                row = next(n for n, entity in enumerate(model.rows) if entity.id == id_)
                self.assertTrue(model.setData(model.index(row, 2), new))
            self.assertEqual(win.tabs.tabText(2), "Changes (2)")
            win.tabs.setCurrentIndex(2)
            changes = win.change_model
            self.assertEqual([changes.data(changes.index(n, changes.PROPOSED))
                              for n in range(changes.rowCount())], ["Club One", "Club Two"])
            self.assertEqual(changes.data(changes.index(0, changes.REASON)), "Manual edit")
            self.assertTrue(changes.setData(changes.index(1, changes.INCLUDE), Qt.Unchecked,
                                            Qt.CheckStateRole))
            self.assertIn("1 ticked for the next Save or Deploy, 1 left out",
                          win.change_summary.text())
            seen = []
            with mock.patch.object(QDialog, "exec", press_write(seen)):
                win.save()
            dialog = seen[0]
            self.assertEqual(dialog.windowTitle(), "Review changes: Save")
            self.assertIn("1 change(s) ticked, to be written to 1 file(s). 1 left out",
                          dialog.summary.text())
            unticked = dialog.model.data(dialog.model.index(1, dialog.model.INCLUDE),
                                         Qt.CheckStateRole)
            self.assertEqual(unticked, Qt.Unchecked)
            self.assertEqual(dialog.model.data(dialog.model.index(0, dialog.model.DEST)),
                             str(path))
            written = path.read_bytes().decode("utf-8-sig")
            self.assertIn('"Club One"', written)
            self.assertNotIn("Club Two", written)
            self.assertTrue(win.docs[0].dirty)
            self.assertEqual(win.tabs.tabText(2), "Changes (1)")
            self.assertEqual(changes.rowCount(), 1)
            self.assertEqual(changes.data(changes.index(0, changes.INCLUDE), Qt.CheckStateRole),
                             Qt.Unchecked)
            self.assertIn("1 left out, still pending", win.statusBar().currentMessage())

    def test_revert_and_find_act_on_the_changes_tab(self):
        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, self.CLUBS)
            self.assertTrue(win.load([str(path)]))
            first, second = win.docs[0].names()[:2]
            editor.try_set_name(first, "Club One")
            editor.try_set_name(second, "Club Two")
            win.reload_views()
            win.tabs.setCurrentIndex(1)
            win.line_view.selectAll()           # not what Revert should act on from Changes
            win.tabs.setCurrentIndex(2)
            win.change_view.selectRow(1)
            win.revert_selected()
            self.assertEqual((first.name, second.name), ("Club One", "Club 2"))
            self.assertEqual(win.tabs.tabText(2), "Changes (1)")
            self.assertIn("Reverted 1 name(s)", win.statusBar().currentMessage())
            with mock.patch.object(win.change_search, "setFocus") as focused:
                win.focus_find()
            focused.assert_called_once()

    def test_the_review_fits_a_1280_by_820_window_with_ten_changes(self):
        """Acceptance: destinations, backup folder, and ticked count show without scrolling."""
        from PySide6.QtWidgets import QApplication, QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            club, fix = self._game(tmp)
            win.refresh_versions()
            self.assertTrue(win.load([str(club), str(fix)]))
            for doc in win.docs:
                for entry in doc.names():
                    editor.try_set_name(entry, entry.name + " Renamed")
            self.assertEqual((win.width(), win.height()), (1280, 820))
            seen = []

            def inspect(dialog):
                dialog.resize(1180, 740)    # its size on this PC's 1920 x 1040 desktop
                dialog.show()
                QApplication.processEvents()
                seen.append(dialog)
                return 0

            with mock.patch.object(editor, "football_manager_running", return_value=[]), \
                    mock.patch.object(QDialog, "exec", inspect):
                win.deploy()
            dialog = seen[0]
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.close)
            self.assertLessEqual(dialog.width(), 1280)
            self.assertLessEqual(dialog.height(), 820)
            self.assertEqual([dialog.files_table.item(n, 1).text() for n in range(2)],
                             [str(club), str(fix)])
            self.assertIn(str(editor.BACKUP_ROOT), dialog.backup_label.text())
            self.assertIn("10 change(s) ticked, to be written to 2 file(s).", dialog.summary.text())
            self.assertEqual(dialog.proxy.rowCount(), 10)
            self.assertEqual(dialog.table.verticalScrollBar().maximum(), 0)   # no scrolling
            inside = dialog.rect()
            for widget in (dialog.summary, dialog.files_table, dialog.backup_label,
                           dialog.table, dialog.write_btn):
                self.assertTrue(widget.isVisible())
                corner = widget.mapTo(dialog, widget.rect().bottomRight())
                self.assertTrue(inside.contains(corner), widget)
            self.assertEqual(dialog.files_table.verticalScrollBar().maximum(), 0)
            self.assertEqual(club.read_bytes().decode("utf-8-sig"), self.CLUBS)  # nothing written

    def test_an_unknown_game_state_needs_the_closed_box(self):
        from PySide6.QtWidgets import QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            club, fix = self._game(tmp)
            win.refresh_versions()
            self.assertTrue(win.load([str(club), str(fix)]))
            editor.try_set_name(win.docs[0].names()[0], "Club One")
            seen = []
            with mock.patch.object(editor, "football_manager_running", return_value=None), \
                    mock.patch.object(QDialog, "exec", press_write(seen)):
                win.deploy()
            dialog = seen[0]
            self.assertEqual(dialog.result(), 0)
            self.assertIn("could not be made", dialog.game_label.text())
            self.assertTrue(dialog.closed_box.isVisibleTo(dialog))
            self.assertFalse(dialog.write_btn.isEnabled())
            self.assertEqual(club.read_bytes().decode("utf-8-sig"), self.CLUBS)
            seen = []

            def tick_then_write(dialog):
                seen.append(dialog)
                dialog.closed_box.setChecked(True)
                dialog.try_write()
                return dialog.result()

            with mock.patch.object(editor, "football_manager_running", return_value=None), \
                    mock.patch.object(QDialog, "exec", tick_then_write):
                win.deploy()
            self.assertEqual(seen[0].result(), 1)
            self.assertIn('"Club One"', club.read_bytes().decode("utf-8-sig"))
            self.assertFalse(win.docs[0].dirty)

    def test_a_game_started_while_reviewing_stops_the_write(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            club, fix = self._game(tmp)
            win.refresh_versions()
            self.assertTrue(win.load([str(club), str(fix)]))
            editor.try_set_name(win.docs[0].names()[0], "Club One")
            seen = []
            with mock.patch.object(editor, "football_manager_running",
                                   side_effect=[[], ["fm.exe"]]) as looked, \
                    mock.patch.object(QDialog, "exec", press_write(seen)), \
                    mock.patch.object(QMessageBox, "warning") as warned:
                win.deploy()
            self.assertEqual(looked.call_count, 2)          # when the review opened, and at Write
            self.assertEqual(seen[0].result(), 0)
            self.assertIn("fm.exe", warned.call_args.args[2])
            self.assertIn("fm.exe", seen[0].game_label.text())
            self.assertFalse(seen[0].write_btn.isEnabled())
            self.assertEqual(club.read_bytes().decode("utf-8-sig"), self.CLUBS)
            self.assertTrue(win.docs[0].dirty)

    def test_a_restore_shows_in_the_footer_until_it_is_written(self):
        from PySide6.QtWidgets import QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, self.CLUBS)
            copy = Path(tmp) / "backups" / "20261111-120000" / "mine.lnc"
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.CLUBS.replace("Club 3", "Club Three"))
            self.assertTrue(win.load([str(path)]))
            self.assertEqual(win.pending_label.text(), "")
            editor.restore_into(win.docs[0], copy)
            win.reload_views()
            self.assertEqual(win.pending_label.text(),
                             "Restore pending, not written yet: mine.lnc (backup 20261111-120000)")
            win.tabs.setCurrentIndex(2)
            self.assertEqual(win.change_model.data(win.change_model.index(0, 1)), "Restored")
            self.assertIn("written whole", win.change_summary.text())
            with mock.patch.object(QDialog, "exec", press_write([])):
                win.save()
            self.assertEqual(path.read_bytes(), copy.read_bytes())
            self.assertEqual(win.pending_label.text(), "")
            self.assertEqual(win.tabs.tabText(2), "Changes")

    def test_a_deploy_with_nothing_new_says_so_and_writes_nothing(self):
        from PySide6.QtWidgets import QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            club, fix = self._game(tmp)
            win.refresh_versions()
            self.assertTrue(win.load([str(club), str(fix)]))
            before = club.stat().st_mtime_ns
            with mock.patch.object(editor, "football_manager_running", return_value=[]), \
                    mock.patch.object(QMessageBox, "information") as told:
                win.deploy()
            self.assertIn("already hold these bytes", told.call_args.args[2])
            self.assertEqual(club.stat().st_mtime_ns, before)
            self.assertFalse((Path(tmp) / "backups").exists())


if __name__ == "__main__":
    unittest.main()
