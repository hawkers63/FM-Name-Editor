"""Checks for the name editor engine, and headless window tests.

Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved.
Proprietary software, not open source. See LICENSE.

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

# Offscreen windows get a screen shaped like this PC's desktop (1920 x 1040 free
# at 100% scaling), so the main window opens at the size it opens at there; the
# default offscreen screen is 800 x 800. Qt reads the file from a relative path:
# a path with a drive letter would be cut at its colon.
_SCREEN = Path(__file__).with_name("offscreen_screen.json")
if os.environ.get("QT_QPA_PLATFORM", "offscreen") == "offscreen":
    try:
        _relative = os.path.relpath(_SCREEN)
    except ValueError:                  # the tests are on another drive
        _relative = ""
    os.environ["QT_QPA_PLATFORM"] = (f"offscreen:configfile={_relative}"
                                     if _relative and ":" not in _relative else "offscreen")
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
    # Jobs (opening files, the game check, reading a backup) run at once on the
    # calling thread, so a test sees their result straight after the call. The
    # tests of the worker threads switch this off again.
    inline = mock.patch.object(editor, "JOBS_INLINE", True)
    inline.start()
    _SANDBOX.append(inline)
    # A dialog that opens without a stand-in would wait for a click that never
    # comes, and the run would hang. Make it fail the test instead.
    try:
        from PySide6.QtWidgets import QApplication, QDialog
    except ImportError:
        return
    # Made here, once, so it gets the screen set above whatever a test sets later.
    _SANDBOX.append(QApplication.instance() or QApplication([]))

    def unattended(dialog):
        raise AssertionError(f"The dialog {dialog.windowTitle()!r} opened without a stand-in.")

    guard = mock.patch.object(QDialog, "exec", unattended)
    guard.start()
    _SANDBOX.append(guard)
    # QMessageBox's static calls build their box in C++, past the guard above.
    # Unpatched, one waits for ever; with these it fails its test instead. A
    # job that ends after its test (a worker test that failed part-way) then
    # fails too, instead of hanging the run.
    from PySide6.QtWidgets import QMessageBox

    for name in ("critical", "warning", "information", "question"):
        def refuse(*args, _name=name, **_kwargs):
            text = args[2] if len(args) > 2 else ""
            raise AssertionError(f"QMessageBox.{_name} opened without a stand-in: {text!r}")

        box_guard = mock.patch.object(QMessageBox, name, refuse)
        box_guard.start()
        _SANDBOX.append(box_guard)


def tearDownModule():
    for item in reversed(_SANDBOX):
        if isinstance(item, tempfile.TemporaryDirectory):
            item.cleanup()
        elif hasattr(item, "stop"):
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
    win.jobs.wait(10)
    win.remember_on_close = False   # one test's view must not reach the next test's window
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def make_window(test):
    """A test window from run_gui([]). Only a missing PySide6 skips the test.

    Any other error while the window is built fails the test. Until Session 9
    every exception was turned into a skip, which would have hidden a window
    that no longer opens behind a green run (note 05).
    """
    import importlib.util

    if importlib.util.find_spec("PySide6") is None:
        test.skipTest("PySide6 is not installed")
    return editor.run_gui([])[1]


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
            result = editor.toggle_licence(version, rel, root / "backups", "disable")
            self.assertEqual(result, "disabled")
            self.assertFalse(src.exists())
            self.assertTrue(src.with_name(src.name + ".disabled").is_file())
            archived = list((root / "backups").rglob("fake.edt"))
            self.assertEqual(archived[0].read_bytes(), b"mask-bytes")
            self.assertEqual(editor.toggle_licence(version, rel, root / "backups", "restore"),
                             "restored")
            self.assertEqual(src.read_bytes(), b"mask-bytes")

    def test_report_only_file_is_not_toggled(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                editor.toggle_licence(Path(tmp), editor.REPORT_FILES[0], Path(tmp) / "backups",
                                      "disable")


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
        win = make_window(self)

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
        win = make_window(self)

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
        win = make_window(self)
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
            for intent in editor.LICENCE_INTENTS:
                with self.assertRaises(FileExistsError):
                    editor.toggle_licence(version, rel, root / "backups", intent)
            self.assertEqual(src.read_bytes(), b"mask-bytes")
            self.assertEqual(disabled.read_bytes(), b"older-mask")
            self.assertFalse((root / "backups").exists())
            disabled.unlink()
            self.assertEqual(editor.toggle_licence(version, rel, root / "backups", "disable"),
                             "disabled")
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
        win = make_window(self)
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
        win = make_window(self)
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
        win = make_window(self)
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
                             ["Undo", "Redo", "", "Edit cell", "Revert selected", "",
                              "Find", "Replace...", "Bulk tools..."])     # Session 7
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
        win = make_window(self)
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


class Session7Engine(unittest.TestCase):
    """Release 2.4, session 7: what the inspector says, and the grid's sort orders."""

    TEXT = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t740\t"Wolverhamption Wanderers"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t740\t"Wolves"\t""\n'
        '"CLUB_NAME_CHANGE"\t3\t"FC Barcelona"\t""\n'
        '"CLUB_NAME_CHANGE"\t3\t"FC Barcelona"\t""\n'
    )

    def _doc(self, tmp, text=None) -> editor.LncDoc:
        path = Path(tmp) / "mine.lnc"
        write_lnc(path, text or self.TEXT)
        return editor.LncDoc(path)

    @staticmethod
    def _entity(docs, id_):
        return next(e for e in editor.build_entities(docs) if e.id == id_)

    def test_a_refused_name_says_why(self):
        samples = ["", "Club", 'Say "hi"', "Line\nbreak", "Carriage\rreturn", "Tab\there",
                   "Bell\x07", "Skënderbeu"]
        for text in samples:
            self.assertEqual(editor.name_problem(text) == "", editor.name_is_legal(text), text)
        self.assertIn("cannot be empty", editor.name_problem(""))
        self.assertIn("Revert or Undo", editor.name_problem(""))
        self.assertIn("double quote", editor.name_problem('Say "hi"'))
        self.assertIn("line break", editor.name_problem("Line\nbreak"))
        self.assertIn("control character", editor.name_problem("Bell\x07"))
        self.assertTrue(editor.name_problem("", "ending").startswith("An ending cannot"))

    def test_fields_show_the_text_on_disk_beside_the_text_in_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(tmp)
            wolves = self._entity([doc], "740")
            self.assertTrue(editor.set_entity_field(wolves, "long", "Wolverhampton Wanderers",
                                                    [doc]))
            long, short, code = editor.describe_fields(wolves)
            self.assertEqual((long.state, long.on_disk, long.current),
                             ("edited", "Wolverhamption Wanderers", "Wolverhampton Wanderers"))
            self.assertEqual(long.marker, "Edited (Manual edit)")
            self.assertEqual(long.where, "mine.lnc, line 2")
            self.assertEqual((short.state, short.on_disk, short.marker),
                             ("same", "Wolves", "Unchanged"))
            self.assertEqual((code.state, code.on_disk, code.current, code.marker),
                             ("none", None, "", ""))
            self.assertEqual(code.where, "Typing a name adds a line after line 2 of mine.lnc.")
            self.assertTrue(editor.set_entity_field(wolves, "code", "WOL", [doc]))
            code = editor.describe_fields(self._entity([doc], "740"))[2]
            self.assertEqual((code.state, code.on_disk, code.current, code.where),
                             ("added", None, "WOL", "mine.lnc, line 3"))
            self.assertEqual(code.marker, "Added (Manual edit)")
            barca = editor.describe_fields(self._entity([doc], "3"))[0]
            self.assertEqual(barca.count, 2)
            self.assertEqual(barca.where, "mine.lnc, lines 5 and 6")
            self.assertEqual(barca.marker, "Unchanged, on 2 lines")
            # A profile is named while the line holds what it set; the reason follows the line.
            entry = wolves.slots["long"][0]
            entry.reason, entry.profile_mark = "profile", ("Mine", entry.name)
            self.assertEqual(editor.describe_fields(wolves)[0].reason, "Profile Mine")

    def test_an_absent_override_reads_as_absent(self):
        self.assertEqual(editor.no_override_text("club", "short"), "No short-name override")
        self.assertEqual(editor.no_override_text("club", "long"), "No long-name override")
        self.assertEqual(editor.no_override_text("club", "code"), "No code override")
        self.assertEqual(editor.no_override_text("comp", "code"), "No code override")
        self.assertEqual(editor.no_override_text("stadium", "long"), "No name override")
        self.assertEqual(editor.ENTITY_KINDS["comp"], "Competition")

    def test_sorting_ignores_accents_and_puts_empty_cells_last(self):
        text = (
            "#Norway\n"
            '"CLUB_NAME_CHANGE"\t10\t"Zeta"\t""\n'
            '"CLUB_NAME_CHANGE"\t2\t"Ålesund"\t""\n'
            '"CLUB_SHORT_NAME_CHANGE"\t33\t"Only Short"\t""\n'
            '"CLUB_NAME_CHANGE"\t4\t"beta"\t""\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(tmp, text)
            entities = editor.build_entities([doc])
            self.assertEqual([e.id for e in entities], ["2", "4", "10", "33"])  # section, then ID

            def order(key, descending=False):
                return [e.id for e in editor.sort_entities(entities, key, descending)]

            self.assertEqual(order("long"), ["2", "4", "10", "33"])        # Ålesund, beta, Zeta
            self.assertEqual(order("long", True), ["10", "4", "2", "33"])  # empty still last
            self.assertEqual(order("short"), ["33", "2", "4", "10"])
            self.assertEqual(order("id", True), ["33", "10", "4", "2"])
            self.assertEqual(order(""), ["2", "4", "10", "33"])
            lines = doc.editable()
            editor.try_set_name(lines[3], "Beta B")
            self.assertEqual([e.name for e in editor.sort_entries(lines, "name")],
                             ["Ålesund", "Beta B", "Only Short", "Zeta"])
            self.assertEqual([e.name for e in editor.sort_entries(lines, "status")],
                             ["Beta B", "Zeta", "Ålesund", "Only Short"])
            self.assertEqual(editor.sort_entries(lines, ""), lines)
            self.assertEqual([e.id for e in editor.sort_entries(lines, "id")],
                             ["2", "4", "10", "33"])


class Session7Window(unittest.TestCase):
    """Release 2.4, session 7: menus, the header row, the grid, the inspector, and keys."""

    # Lines: 1 #England, 2-3 Zulu (30), 4-5 Alpha (10), 6 #Wales, 7-8 Mike (20).
    CLUBS = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t30\t"Zulu Town"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t30\t"Zulu"\t""\n'
        '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t10\t"Alpha"\t""\n'
        "#Wales\n"
        '"CLUB_NAME_CHANGE"\t20\t"Mike Rovers"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t20\t"Aardvark"\t""\n'
    )

    def _window(self):
        from PySide6.QtWidgets import QApplication

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        win = make_window(self)
        self.addCleanup(close_window, win)
        win.show()
        win.activateWindow()
        QApplication.processEvents()
        return win

    def _open(self, win, tmp) -> Path:
        path = Path(tmp) / "mine.lnc"
        write_lnc(path, self.CLUBS)
        self.assertTrue(win.load([str(path)]))
        return path

    @staticmethod
    def _shown(win) -> list[str]:
        proxy = win.entity_proxy
        return [win.entity_model.rows[proxy.mapToSource(proxy.index(n, 0)).row()].id
                for n in range(proxy.rowCount())]

    @staticmethod
    def _select(win, id_) -> None:
        model, proxy = win.entity_model, win.entity_proxy
        row = next(n for n, entity in enumerate(model.rows) if entity.id == id_)
        win.entity_view.selectRow(proxy.mapFromSource(model.index(row, 0)).row())

    @staticmethod
    def _click_heading(view, column) -> None:
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        header = view.horizontalHeader()
        x = header.sectionViewportPosition(column) + header.sectionSize(column) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier,
                         QPoint(x, header.height() // 2))

    def test_menus_hold_the_actions_and_name_their_keys(self):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QDialog, QMessageBox, QTableWidget

        win = self._window()
        self.assertEqual([menu.title().replace("&", "") for menu in win.menus],
                         ["File", "Edit", "View", "Packs", "Backups", "Profiles",
                          "Collections", "Help"])             # Collections since Session 8
        self.assertEqual([action.text() for action in win.file_menu.actions() if action.text()],
                         ["Open files...", "Quick load", "Save...", "Deploy to FM27...",
                          "Import older edits...", "Problem lines...", "Licensing files...",
                          "Exit"])
        self.assertEqual([action.text() for action in win.profiles_menu.actions()
                          if action.text()],
                         ["Record edits", "Apply...", "Migrate from new files...",
                          "New profile...", "Rename profile...", "Delete profile..."])
        keys = {action.text(): action.shortcut().toString()
                for menu in win.menus for action in menu.actions() if action.text()}
        self.assertEqual((keys["Save..."], keys["Edit cell"], keys["Find"], keys["Changes"],
                          keys["Undo"], keys["Keyboard shortcuts"]),
                         ("Ctrl+S", "F2", "Ctrl+F", "Ctrl+Shift+C", "Ctrl+Z", "F1"))
        # Each key belongs to one action: Qt runs neither of two that share one.
        taken = [key.toString() for action in win.findChildren(QAction)
                 for key in action.shortcuts()]
        self.assertEqual(len(taken), len(set(taken)), taken)
        rows = win.shortcut_rows()
        for row in (("Ctrl+Shift+C or Ctrl+3", "View > Changes"), ("F2", "Edit > Edit cell"),
                    ("Ctrl+Z", "Edit > Undo"), ("Ctrl+Y or Ctrl+Shift+Z", "Edit > Redo")):
            self.assertIn(row, rows)
        seen = []

        def look(dialog):
            seen.append((dialog.windowTitle(), dialog.findChild(QTableWidget).rowCount()))
            return 0

        with mock.patch.object(QDialog, "exec", look):
            win.shortcuts_act.trigger()
        self.assertEqual(seen, [("Keyboard shortcuts", len(rows))])
        win.changes_act.trigger()
        self.assertEqual(win.tabs.currentIndex(), 2)
        win.entities_act.trigger()
        self.assertEqual(win.tabs.currentIndex(), 0)
        with mock.patch.object(QMessageBox, "information") as told:
            win.deploy_act.trigger()                # a menu action reaches its window method
        self.assertIn("Open the name files first", told.call_args.args[2])

    def test_the_header_row_keeps_database_profile_and_review_in_view(self):
        """Acceptance: at 1280 x 820 the database, profile, and Review changes stay visible."""
        from PySide6.QtWidgets import QDialog, QToolButton

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            self._open(win, tmp)
            self.assertEqual((win.width(), win.height()), (1280, 820))
            self.assertLessEqual(win.toolbar.sizeHint().width(), win.toolbar.width())
            overflow = win.toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
            self.assertFalse(overflow is not None and overflow.isVisible())
            inside = win.rect()
            for widget in (win.version_box, win.profile_box, win.record_btn,
                           win.apply_profile_btn, win.review_btn):
                self.assertTrue(widget.isVisible(), widget)
                corner = widget.mapTo(win, widget.rect().bottomRight())
                self.assertTrue(inside.contains(corner), widget)
            self.assertEqual(win.review_act.text(), "Review changes")
            self.assertFalse(win.review_act.isEnabled())
            model = win.entity_model
            row = next(n for n, entity in enumerate(model.rows) if entity.id == "10")
            self.assertTrue(model.setData(model.index(row, 2), "Alpha Athletic"))
            self.assertEqual(win.review_act.text(), "Review changes (1)")
            self.assertTrue(win.review_act.isEnabled())
            self.assertEqual(win.metrics.text(), "3 clubs    0 competitions    1 unsaved")
            seen = []

            def look(dialog):
                seen.append(dialog.windowTitle())
                return 0

            with mock.patch.object(QDialog, "exec", look):
                win.review_btn.click()
            self.assertEqual(seen, ["Review changes: Save"])
            self.assertTrue(win.docs[0].dirty)          # closing the review writes nothing

    def test_the_grid_sorts_by_long_name_and_gives_names_the_width(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QHeaderView

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            self._open(win, tmp)
            model, view = win.entity_model, win.entity_view
            header = view.horizontalHeader()
            columns = model.columns()
            self.assertEqual(self._shown(win), ["10", "20", "30"])     # long name, A to Z
            self.assertEqual(header.sortIndicatorSection(), columns.index("long"))
            self.assertTrue(view.isColumnHidden(columns.index("id")))
            self.assertFalse(view.isColumnHidden(columns.index("section")))
            self.assertEqual(header.sectionResizeMode(columns.index("long")), QHeaderView.Stretch)
            self._select(win, "10")
            self.assertIn("ID 10", win.inspector_meta.text())        # the ID moved here
            self._click_heading(view, columns.index("short"))          # a first click: A to Z
            self.assertEqual(self._shown(win), ["20", "10", "30"])     # Aardvark, Alpha, Zulu
            selected = [model.rows[win.entity_proxy.mapToSource(index).row()].id
                        for index in view.selectionModel().selectedRows()]
            self.assertEqual(selected, ["10"])                          # the same club
            self._click_heading(view, columns.index("long"))
            self._click_heading(view, columns.index("long"))           # a second click: Z to A
            self.assertEqual(self._shown(win), ["30", "20", "10"])
            self._click_heading(view, columns.index("long"))           # a third: the file's order
            self.assertEqual(header.sortIndicatorSection(), -1)
            self.assertEqual(self._shown(win), ["10", "30", "20"])     # file section, then ID
            wales = next(n for n in range(win.section_list.count())
                         if win.section_list.item(n).data(Qt.UserRole) == "Wales")
            win.section_list.setCurrentRow(wales)
            self.assertEqual(self._shown(win), ["20"])
            self.assertTrue(view.isColumnHidden(columns.index("section")))
            win.section_list.setCurrentRow(0)
            self.assertFalse(view.isColumnHidden(columns.index("section")))
            # Adding a field reloads the views; the club stays selected and in the inspector.
            header.setSortIndicator(columns.index("long"), Qt.AscendingOrder)
            self._select(win, "30")
            row = next(n for n, entity in enumerate(model.rows) if entity.id == "30")
            self.assertTrue(model.setData(model.index(row, columns.index("code")), "ZUL"))
            QApplication.processEvents()                # the reload runs from the event loop
            self.assertEqual(win.inspector_entity.id, "30")
            self.assertEqual(win.inspector_fields["code"]["edit"].text(), "ZUL")
            self.assertEqual(win.inspector_fields["code"]["marker"].text(), "Added (Manual edit)")
            selected = [model.rows[win.entity_proxy.mapToSource(index).row()].id
                        for index in view.selectionModel().selectedRows()]
            self.assertEqual(selected, ["30"])

    def test_a_refused_inspector_value_stays_in_view_with_the_reason(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            self._open(win, tmp)
            self._select(win, "10")
            fields = win.inspector_fields
            long, code = fields["long"], fields["code"]
            self.assertEqual(win.inspector_title.text(), "Alpha United")
            self.assertEqual((long["disk"].text(), long["marker"].text(), long["where"].text()),
                             ("Alpha United", "Unchanged", "mine.lnc, line 4"))
            self.assertEqual((code["disk"].text(), code["marker"].text()),
                             ("No line", "No code override"))
            self.assertEqual(code["where"].text(),
                             "Typing a name adds a line after line 4 of mine.lnc.")
            edit = long["edit"]
            edit.setText('Alpha "United"')
            win.commit_inspector("long", edit)
            self.assertEqual(edit.text(), 'Alpha "United"')            # kept, not put back
            self.assertTrue(long["problem"].isVisible())
            self.assertIn("double quote", long["problem"].text())
            self.assertEqual(edit.objectName(), "invalid")
            entity = next(e for e in win.entity_model.rows if e.id == "10")
            self.assertEqual(entity.name_in("long"), "Alpha United")
            self.assertFalse(win.docs[0].dirty)
            self.assertEqual(win.undo_stack.count(), 0)
            edit.setFocus()
            QTest.keyClick(edit, Qt.Key_Escape)                         # puts the name back
            self.assertEqual(edit.text(), "Alpha United")
            self.assertFalse(long["problem"].isVisible())
            QTest.keyClicks(edit, '"')                                  # said while typing
            self.assertIn("double quote", long["problem"].text())
            edit.setText("   ")
            win.commit_inspector("long", edit)
            self.assertIn("cannot be empty", long["problem"].text())
            code["edit"].setText("")
            win.commit_inspector("code", code["edit"])                  # empty stays empty
            self.assertFalse(code["problem"].isVisible())
            edit.setText("Alpha Athletic")
            win.commit_inspector("long", edit)
            self.assertFalse(long["problem"].isVisible())
            self.assertEqual(edit.objectName(), "")
            self.assertEqual(win.undo_act.text(), "Undo edit long name: Alpha Athletic")
            self.assertEqual((long["disk"].text(), long["marker"].text()),
                             ("Alpha United", "Edited (Manual edit)"))
            # The grid says why it did not take a name, instead of saying nothing.
            model = win.entity_model
            row = next(n for n, entity in enumerate(model.rows) if entity.id == "30")
            self.assertFalse(model.setData(model.index(row, model.columns().index("short")),
                                           "Zu\nlu"))
            self.assertIn("Not changed. A name cannot contain a line break",
                          win.statusBar().currentMessage())

    def test_keys_and_double_click_go_where_they_say(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QAbstractItemView, QApplication

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._open(win, tmp)
            view = win.entity_view
            self._select(win, "30")
            view.setCurrentIndex(view.currentIndex().siblingAtColumn(
                win.entity_model.columns().index("status")))       # a cell that is not edited
            view.setFocus()
            QTest.keyClick(view, Qt.Key_F2)
            self.assertEqual(view.state(), QAbstractItemView.EditingState)
            self.assertEqual(view.currentIndex().column(), win.entity_model.columns().index("long"))
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape)
            self.assertNotEqual(view.state(), QAbstractItemView.EditingState)
            names = {entry.id: entry for entry in win.docs[0].names()
                     if entry.cmd == "CLUB_NAME_CHANGE"}
            editor.try_set_name(names["10"], "Alpha One")
            editor.try_set_name(names["20"], "Mike One")
            win.reload_views()
            QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier)
            self.assertEqual(win.tabs.currentIndex(), 2)
            win.edit_cell_act.trigger()
            self.assertIn("not edited on this tab", win.statusBar().currentMessage())
            win.line_search.setText("zulu")             # hides the line the change is on
            win.apply_line_filter()
            changes = win.change_view
            point = changes.visualRect(win.change_proxy.index(1, win.change_model.PROPOSED)).center()
            # A real double-click starts with a press: Qt's views ignore one without it.
            QTest.mouseClick(changes.viewport(), Qt.LeftButton, Qt.NoModifier, point)
            QTest.mouseDClick(changes.viewport(), Qt.LeftButton, Qt.NoModifier, point)
            self.assertEqual(win.tabs.currentIndex(), 1)
            current = win.line_view.currentIndex()
            entry = win.line_model.rows[win.line_proxy.mapToSource(current).row()]
            self.assertEqual((entry.id, entry.name, entry.lineno), ("20", "Mike One", 7))
            self.assertEqual(win.line_search.text(), "")
            message = win.statusBar().currentMessage()
            self.assertIn("Line 7 of mine.lnc.", message)
            self.assertIn("filters were cleared", message)
            # A removed row is a line on disk only, so there is no line in memory to go to.
            copy = Path(tmp) / "backups" / "20261111-120000" / "mine.lnc"
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.CLUBS.replace('"CLUB_SHORT_NAME_CHANGE"\t20\t"Aardvark"\t""\n',
                                               ""))
            editor.restore_into(win.docs[0], copy)
            win.reload_views()
            win.show_changes_tab()
            rows = win.change_model.rows
            removed = next(n for n, row in enumerate(rows) if row.state == "removed")
            win.go_to_change(win.change_proxy.mapFromSource(win.change_model.index(removed, 0)))
            self.assertEqual(win.tabs.currentIndex(), 2)
            self.assertIn("next Save or Deploy takes it out", win.statusBar().currentMessage())
            self.assertEqual(path.read_bytes().decode("utf-8-sig"), self.CLUBS)  # memory only


class Session8Engine(unittest.TestCase):
    """Release 2.4, session 8: a restore read off the GUI thread, collections, and the
    remembered view."""

    TEXT = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
        '"CLUB_NAME_CHANGE"\t2\t"Bravo"\t""\n'
        '"CLUB_NAME_CHANGE"\t3\t"Charlie"\t""\n'
    )

    def test_a_restore_can_be_read_off_the_gui_thread(self):
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, self.TEXT)
            copy = Path(tmp) / "backups" / "20261111-120000" / "mine.lnc"
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.TEXT.replace("Bravo", "Bravo Two").replace(
                '"CLUB_NAME_CHANGE"\t3\t"Charlie"\t""\n', ""))
            doc = editor.LncDoc(path)
            lines, before = doc.entries, doc.to_bytes()
            found = []
            worker = threading.Thread(target=lambda: found.append(editor.prepare_restore(doc, copy)))
            worker.start()
            worker.join(10)
            prepared = found[0]
            # Reading it changed nothing: the same lines, the same bytes, nothing pending.
            self.assertIs(doc.entries, lines)
            self.assertEqual(doc.to_bytes(), before)
            self.assertFalse(doc.dirty or doc.restore_pending)
            with editor.Operation("restore") as operation:
                doc.apply_working(prepared)
            other = editor.LncDoc(path)
            editor.restore_into(other, copy)
            self.assertEqual(doc.to_bytes(), other.to_bytes())
            self.assertEqual(doc.to_bytes(), copy.read_bytes())
            self.assertEqual([row.name for row in doc.removed_rows], ["Charlie"])
            self.assertEqual((doc.restore_pending, doc.restored_from), (True, copy))
            operation.undo()                                   # one step, as before
            self.assertEqual(doc.to_bytes(), before)
            self.assertFalse(doc.restore_pending)
            bad = copy.with_name("bad.lnc")
            bad.write_bytes(b"\xff\xfe\x00\xd8")              # UTF-16 with a broken surrogate
            with self.assertRaises(UnicodeError):
                editor.prepare_restore(doc, bad)
            with self.assertRaises(FileNotFoundError):
                editor.prepare_restore(doc, copy.with_name("gone.lnc"))
            self.assertEqual(doc.to_bytes(), before)

    def test_collections_file_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            self.assertEqual(editor.load_collection_file(root).collections, [])   # no file yet
            store = editor.CollectionFile()
            mine = editor.Collection("My save")
            self.assertEqual(mine.add([("club", "740", ""), ("comp", "11", "")]), 2)
            self.assertEqual(mine.add([("club", "740", "")]), 0)
            store.add(editor.Collection("names to review", [("club", "3", "")]))
            store.add(mine)
            self.assertEqual([c.name for c in store.collections], ["My save", "names to review"])
            self.assertEqual(editor.collection_name_problem("MY SAVE", store),
                             "There is already a collection called My save.")
            self.assertEqual(editor.collection_name_problem("My save", store, own=mine), "")
            editor.save_collection_file(store, root)
            first = (root / "collections.json").read_bytes()
            editor.save_collection_file(store, root)
            self.assertEqual((root / "collections.json").read_bytes(), first)  # same bytes
            loaded = editor.load_collection_file(root)
            self.assertEqual([(c.name, c.keys) for c in loaded.collections],
                             [("My save", {("club", "740", ""), ("comp", "11", "")}),
                              ("names to review", {("club", "3", "")})])
            mine = loaded.find("my save")
            self.assertEqual((mine.count_in("club"), mine.count_in("comp")), (1, 1))
            self.assertEqual(mine.remove([("comp", "11", ""), ("comp", "99", "")]), 1)
            loaded.delete(loaded.find("names to review"))
            editor.save_collection_file(loaded, root)
            again = editor.load_collection_file(root)
            self.assertEqual([c.name for c in again.collections], ["My save"])
            self.assertEqual([item["name"] for item in again.deleted], ["names to review"])
            self.assertIn("deleted", again.deleted[0])        # kept, so it can be recovered
            for text, words in (
                ("{not json", "not readable JSON"),
                ('{"format": "fm-name-pack", "version": 1}', "not a version 1 collections file"),
                (json.dumps({"format": "fm-name-collections", "version": 1, "collections": [
                    {"name": "Odd", "members": [{"family": "player", "id": "1"}]}]}),
                 "(Odd) has a member"),
                (json.dumps({"format": "fm-name-collections", "version": 1, "collections": [
                    {"name": "Twice", "members": []}, {"name": "twice", "members": []}]}),
                 "already a collection called Twice"),
            ):
                (root / "collections.json").write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError) as caught:
                    editor.load_collection_file(root)
                self.assertIn(words, str(caught.exception))
                self.assertIn("collections.json", str(caught.exception))

    def test_saved_searches_and_the_view_keep_what_the_window_can_use(self):
        searches = editor.clean_saved_searches([
            {"name": "Welsh clubs", "family": "club", "text": "", "status": "all",
             "section": "Wales", "collection": ""},
            {"name": "welsh CLUBS", "family": "club"},                 # name taken
            {"name": "Players", "family": "player"},                   # no such family
            {"name": "Odd", "status": "unknown"},                      # no such filter
            {"name": "Numbers", "text": 42},                           # not text
            "not a search",
            {"name": "  Cups to check  ", "family": "comp", "text": "cup", "status": "edited"},
        ])
        self.assertEqual([s.to_json() for s in searches], [
            {"name": "Welsh clubs", "family": "club", "text": "", "status": "all",
             "section": "Wales", "collection": ""},
            {"name": "Cups to check", "family": "comp", "text": "cup", "status": "edited",
             "section": "", "collection": ""},
        ])
        self.assertEqual(editor.clean_saved_searches("nothing"), [])
        view = editor.clean_view({
            "tab": 2, "family": "comp", "status": "missing_code",
            "entity_sort": {"key": "short", "descending": True},
            "line_sort": {"key": "bogus", "descending": False},
            "entity_widths": {"club": {"short": 180, "bogus": 90, "code": 5, "status": True},
                              "player": {"short": 100}},
            "line_widths": {"type": 150, "name": 9999},
            "geometry": "AdnQywADAAA=", "splitter": "café", "window_state": 3,
            "extra": "ignored",
        })
        self.assertEqual(view, {
            "tab": 2, "family": "comp", "status": "missing_code",
            "entity_sort": {"key": "short", "descending": True},
            "entity_widths": {"club": {"short": 180}},
            "line_widths": {"type": 150},
            "geometry": "AdnQywADAAA=",
        })
        self.assertEqual(editor.clean_view({"tab": True, "family": "player"}), {})
        self.assertEqual(editor.clean_view(None), {})
        self.assertEqual(editor.label_problem("", kind="saved search"),
                         "Give the saved search a name.")
        self.assertEqual(editor.profile_name_problem("", []), "Give the profile a name.")


class Session8Window(unittest.TestCase):
    """Release 2.4, session 8: the remembered view, saved searches, section search, and
    collections."""

    # Lines: 1 #England, 2-3 Zulu (30), 4 Alpha (10), 5 #Wales, 6 Mike (20),
    # 7 #Northern Ireland, 8 Linfield (40), 9 a competition.
    CLUBS = (
        "#England\n"
        '"CLUB_NAME_CHANGE"\t30\t"Zulu Town"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t30\t"Zulu"\t""\n'
        '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'
        "#Wales\n"
        '"CLUB_NAME_CHANGE"\t20\t"Mike Rovers"\t""\n'
        "#Northern Ireland\n"
        '"CLUB_NAME_CHANGE"\t40\t"Linfield"\t""\n'
        '"COMP_LONG_NAME_CHANGE"\t1\t"Irish Premiership"\t""\n'
    )

    def _window(self, tmp):
        from PySide6.QtWidgets import QApplication

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        win = make_window(self)
        self.addCleanup(close_window, win)
        win.show()
        QApplication.processEvents()
        return win

    def _roots(self, tmp) -> Path:
        state = Path(tmp) / "state"
        self.enterContext(mock.patch.multiple(
            editor, STATE_ROOT=state, PROFILE_ROOT=Path(tmp) / "profiles"))
        return state

    def _open(self, win, tmp) -> Path:
        path = Path(tmp) / "mine.lnc"
        write_lnc(path, self.CLUBS)
        self.assertTrue(win.load([str(path)]))
        return path

    @staticmethod
    def _shown(win) -> list[str]:
        proxy = win.entity_proxy
        return [win.entity_model.rows[proxy.mapToSource(proxy.index(n, 0)).row()].id
                for n in range(proxy.rowCount())]

    @staticmethod
    def _name(name: str, problems: list | None = None):
        """A stand-in for QDialog.exec: type a name into the name dialog and press OK."""
        def run(dialog):
            dialog.name_edit.setText(name)
            dialog.try_accept()
            if problems is not None:
                problems.append(dialog.problem.text())
            return dialog.result()
        return run

    @staticmethod
    def _select(win, *ids) -> None:
        from PySide6.QtCore import QItemSelectionModel

        model, proxy = win.entity_model, win.entity_proxy
        selection = win.entity_view.selectionModel()
        selection.clearSelection()
        for id_ in ids:
            row = next(n for n, entity in enumerate(model.rows) if entity.id == id_)
            index = proxy.mapFromSource(model.index(row, 2))
            selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)

    @staticmethod
    def _section(win, name: str) -> None:
        from PySide6.QtCore import Qt

        row = next(n for n in range(win.section_list.count())
                   if win.section_list.item(n).data(Qt.UserRole) == name)
        win.section_list.setCurrentRow(row)

    def test_the_view_is_remembered_between_runs(self):
        from PySide6.QtCore import Qt

        with tempfile.TemporaryDirectory() as tmp:
            state = self._roots(tmp)
            first = self._window(tmp)
            self.assertEqual((first.width(), first.height()), (1280, 820))   # the default
            path = self._open(first, tmp)
            first.resize(1100, 700)
            header = first.entity_view.horizontalHeader()
            short = first.entity_model.columns().index("short")
            header.setSortIndicator(short, Qt.DescendingOrder)
            header.resizeSection(short, 150)                    # as a drag on the header would
            next(b for b in first.status_buttons if b.property("mode") == "missing_code").click()
            first.entity_splitter.setSizes([150, 800, 320])
            first.line_view.horizontalHeader().setSortIndicator(3, Qt.AscendingOrder)
            next(b for b in first.family_buttons if b.property("family") == "comp").click()
            first.tabs.setCurrentIndex(1)
            first.remember_on_close = True
            first.close()
            view = editor.load_state(state)["view"]
            self.assertEqual((view["tab"], view["family"], view["status"]), (1, "comp", "missing_code"))
            self.assertEqual(view["entity_sort"], {"key": "short", "descending": True})
            self.assertEqual(view["line_sort"], {"key": "name", "descending": False})
            self.assertEqual(view["entity_widths"], {"club": {"short": 150}})
            second = self._window(tmp)
            self.assertEqual((second.width(), second.height()), (1100, 700))
            self.assertEqual(second.tabs.currentIndex(), 1)
            self.assertEqual(second.entity_splitter.sizes()[0], 150)
            self.assertTrue(next(b for b in second.status_buttons
                                 if b.property("mode") == "missing_code").isChecked())
            self.assertTrue(second.load([str(path)]))
            self.assertEqual(second.family, "comp")             # opening files keeps the family
            header = second.entity_view.horizontalHeader()
            self.assertEqual((header.sortIndicatorSection(), header.sortIndicatorOrder()),
                             (short, Qt.DescendingOrder))
            next(b for b in second.family_buttons if b.property("family") == "club").click()
            self.assertEqual(second.entity_view.columnWidth(short), 150)   # the club width
            self.assertEqual([e.name for e in second.line_model.rows][:2],
                             ["Alpha United", "Irish Premiership"])          # name, A to Z
            # A broken view in the settings file is ignored, not fatal.
            editor.save_state({"view": {"tab": "two", "family": 7, "geometry": ["x"]}}, state)
            third = self._window(tmp)
            self.assertEqual((third.width(), third.height(), third.family), (1280, 820, "club"))

    def test_saved_searches_and_the_section_search(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            state = self._roots(tmp)
            win = self._window(tmp)
            self._open(win, tmp)
            win.section_search.setText("IRELAND")                # accents and capitals ignored
            shown = [win.section_list.item(n).data(Qt.UserRole)
                     for n in range(win.section_list.count())
                     if not win.section_list.item(n).isHidden()]
            self.assertEqual(shown, ["", "Northern Ireland"])   # All sections always shows
            win.section_search.clear()
            self._section(win, "Wales")
            win.entity_search.setText("rovers")
            win.apply_entity_filter()
            with mock.patch.object(QDialog, "exec", self._name("Welsh rovers")):
                win.save_search()
            self.assertEqual(editor.load_state(state)["saved_searches"], [
                {"name": "Welsh rovers", "family": "club", "text": "rovers", "status": "all",
                 "section": "Wales", "collection": ""}])
            problems = []
            with mock.patch.object(QDialog, "exec", self._name("WELSH rovers", problems)):
                win.save_search()                               # the name is taken
            self.assertEqual(problems, ["There is already a saved search called Welsh rovers."])
            self.assertEqual(len(win.saved_searches), 1)
            next(b for b in win.family_buttons if b.property("family") == "comp").click()
            win.entity_search.clear()
            win.apply_entity_filter()                   # the box itself waits 200 ms for typing
            self.assertEqual(self._shown(win), ["1"])
            win.fill_searches_menu()
            named = {action.text(): action for action in win.searches_menu.actions()}
            self.assertIn("Clubs; words: rovers; file section: Wales",
                          named["Welsh rovers"].toolTip())
            named["Welsh rovers"].trigger()
            self.assertEqual((win.family, win.section_filter, win.entity_search.text()),
                             ("club", "Wales", "rovers"))
            self.assertEqual(self._shown(win), ["20"])
            self.assertIn("Welsh rovers: 1 shown.", win.statusBar().currentMessage())
            win.fill_searches_menu()
            forget = next(a for a in win.searches_menu.actions()
                          if a.text() == "Delete a saved search").menu()
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                forget.actions()[0].trigger()
            self.assertEqual(editor.load_state(state)["saved_searches"], [])

    def test_collections_in_the_window(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            state = self._roots(tmp)
            win = self._window(tmp)
            self._open(win, tmp)
            self.assertFalse(win.collection_list.isVisible())
            self.assertIn("None yet", win.collection_hint.text())
            self.assertFalse(win.remove_from_collection_act.isEnabled())
            self._select(win, "10", "30")
            win.fill_add_to_menu()
            make = win.add_to_collection_menu.actions()[-1]
            self.assertEqual(make.text(), "New collection with the selection...")
            with mock.patch.object(QDialog, "exec", self._name("My save")):
                make.trigger()
            self.assertEqual(win.collection_list.item(0).text(), "★ My save (2)")
            self.assertTrue(win.collection_list.isVisible())
            self.assertEqual(editor.load_collection_file(state).find("My save").keys,
                             {("club", "10", ""), ("club", "30", "")})
            win.collection_list.setCurrentRow(0)                # show the collection
            self.assertEqual(self._shown(win), ["10", "30"])
            self.assertEqual(win.section_filter, "")
            self.assertTrue(win.remove_from_collection_act.isEnabled())
            self._select(win, "30")
            win.remove_from_collection_act.trigger()
            self.assertEqual(self._shown(win), ["10"])
            self.assertIn("Took 1 out of My save, which now holds 1.",
                          win.statusBar().currentMessage())
            self._section(win, "Wales")                         # a file section replaces it
            self.assertEqual((win.collection_filter, self._shown(win)), ("", ["20"]))
            win.collection_list.setCurrentRow(0)
            with mock.patch.object(QDialog, "exec", self._name("Names to review")):
                win.rename_collection_act.trigger()
            self.assertEqual(win.collection_list.item(0).text(), "★ Names to review (1)")
            self.assertEqual([action.text() for action in win.grid_menu().actions()],
                             ["Add selected to", "Remove selected from this collection",
                              "", "Edit cell", "Revert selected",
                              "", "Show overrides across files..."])
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as asked:
                win.delete_collection_act.trigger()
            self.assertIn("recovered by hand", asked.call_args.args[2])
            stored = editor.load_collection_file(state)
            self.assertEqual((stored.collections, [item["name"] for item in stored.deleted]),
                             ([], ["Names to review"]))
            self.assertEqual(self._shown(win), ["10", "40", "20", "30"])   # every club again
            # A damaged collections file is named and left alone.
            (state / "collections.json").write_text("{bad", encoding="utf-8")
            again = self._window(tmp)
            self.assertIn("not readable JSON", again.collection_hint.text())
            self.assertFalse(again.new_collection_act.isEnabled())
            self.assertFalse(again.new_collection())
            self.assertEqual((state / "collections.json").read_text(encoding="utf-8"), "{bad")

    def test_ticks_and_keyboard_focus_can_be_seen(self):
        """The scaling pass found the include box and keyboard focus nearly invisible."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QApplication

        def near(colour: QColor, wanted: str) -> bool:
            target = QColor(wanted)
            return all(abs(a - b) <= 24 for a, b in ((colour.red(), target.red()),
                                                    (colour.green(), target.green()),
                                                    (colour.blue(), target.blue())))

        def colours(image, rect) -> list:
            return [image.pixelColor(x, y) for x in range(rect.left(), rect.right())
                    for y in range(rect.top(), rect.bottom())]

        with tempfile.TemporaryDirectory() as tmp:
            self._roots(tmp)
            win = self._window(tmp)
            self._open(win, tmp)
            for entry in win.docs[0].names()[:2]:
                editor.try_set_name(entry, entry.name + " Renamed")
            win.reload_views()
            win.show_changes_tab()
            changes = win.change_model
            changes.setData(changes.index(1, changes.INCLUDE), Qt.Unchecked, Qt.CheckStateRole)
            QApplication.processEvents()
            image = win.change_view.viewport().grab().toImage()
            proxy = win.change_proxy
            ticked = colours(image, win.change_view.visualRect(proxy.index(0, changes.INCLUDE)))
            unticked = colours(image, win.change_view.visualRect(proxy.index(1, changes.INCLUDE)))
            self.assertTrue(any(near(colour, "#8b5cf6") for colour in ticked))   # accent fill
            self.assertTrue(any(near(colour, "#ffffff") for colour in ticked))   # the tick
            self.assertTrue(any(near(colour, "#8a94a6") for colour in unticked))  # a clear border
            button = next(b for b in win.family_buttons if b.property("family") == "comp")
            button.setFocus(Qt.TabFocusReason)
            QApplication.processEvents()
            image = button.grab().toImage()
            self.assertTrue(any(near(colour, "#06b6d4") for colour in colours(image, button.rect())))


class Session8Workers(unittest.TestCase):
    """Release 2.4, session 8: opening files, the game check, and reading a backup run on
    worker threads; the window's conflicting actions are off until each ends."""

    TEXT = '"CLUB_NAME_CHANGE"\t1\t"Club 1"\t""\n"CLUB_NAME_CHANGE"\t2\t"Club 2"\t""\n'

    def setUp(self):
        self.enterContext(mock.patch.object(editor, "JOBS_INLINE", False))

    def _window(self):
        from PySide6.QtWidgets import QApplication

        win = make_window(self)
        self.addCleanup(close_window, win)
        win.show()
        QApplication.processEvents()
        return win

    def assert_busy(self, win, busy: bool) -> None:
        for action in (win.open_act, win.quick_load_act, win.save_act, win.deploy_act,
                       win.backups_act, win.bulk_act):
            self.assertEqual(action.isEnabled(), not busy, action.text())
        self.assertEqual(win.centralWidget().isEnabled(), not busy)
        self.assertEqual(bool(win.jobs.pending), busy)

    def test_a_load_on_a_worker_that_fails_leaves_the_workspace_unchanged(self):
        import threading
        from PySide6.QtWidgets import QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            good, other, bad = (Path(tmp) / name for name in ("good.lnc", "other.lnc", "bad.lnc"))
            write_lnc(good, self.TEXT)
            write_lnc(other, self.TEXT.replace("Club", "Team"))
            bad.write_bytes(b"\xff\xfe\x00\xd8")          # UTF-16 with a broken surrogate
            self.assertTrue(win.load([str(good)]))
            docs = list(win.docs)
            gate, threads = threading.Event(), []
            self.addCleanup(gate.set)       # a failed test must not leave the worker waiting
            real = editor.open_documents

            def slow(paths):
                threads.append(threading.current_thread())
                gate.wait(10)
                return real(paths)

            with mock.patch.object(editor, "open_documents", slow), \
                    mock.patch.object(QMessageBox, "critical") as told:
                win.load_in_background([str(other), str(bad)])
                self.assert_busy(win, True)                 # drawn, with its actions off
                self.assertEqual(win.statusBar().currentMessage(),
                                 "Opening other.lnc, bad.lnc...")
                gate.set()
                self.assertTrue(win.jobs.wait(10))
            self.assertIsNot(threads[0], threading.main_thread())
            self.assertIn("bad.lnc", told.call_args.args[2])
            self.assertIn("The current files are unchanged", told.call_args.args[2])
            self.assertEqual(win.docs, docs)
            self.assertEqual([e.name for e in win.line_model.rows], ["Club 1", "Club 2"])
            self.assert_busy(win, False)
            win.load_in_background([str(other)])            # a good one replaces the workspace
            self.assertTrue(win.jobs.wait(10))
            self.assertEqual([doc.path for doc in win.docs], [other])
            self.assertEqual([e.name for e in win.line_model.rows], ["Team 1", "Team 2"])
            # The actions come back as they were, then follow the new files: an
            # edit made before a load cannot be undone after it.
            model = win.entity_model
            self.assertTrue(model.setData(model.index(0, 2), "Team One"))
            self.assertTrue(win.undo_act.isEnabled())
            win.load_in_background([str(good)])
            self.assertTrue(win.jobs.wait(10))
            self.assertFalse(win.undo_act.isEnabled() or win.undo_tool.isEnabled())

    def test_a_game_check_that_breaks_counts_as_unknown(self):
        from PySide6.QtWidgets import QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            club = root / "db" / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            club.parent.mkdir(parents=True)
            write_lnc(club, self.TEXT)
            self.enterContext(mock.patch.multiple(
                editor, GAME_DB_ROOT=root / "db", BACKUP_ROOT=root / "backups"))
            self.assertTrue(win.load([str(club)]))
            editor.try_set_name(win.docs[0].names()[0], "Club One")
            seen = []

            def look(dialog):
                seen.append((dialog.game_label.text(), dialog.closed_box.isVisibleTo(dialog),
                             dialog.write_btn.isEnabled()))
                return 0

            with mock.patch.object(editor, "football_manager_running",
                                   side_effect=RuntimeError("tasklist broke")), \
                    mock.patch.object(QDialog, "exec", look):
                win.save()
                self.assertTrue(win.jobs.wait(10))
            text, box_shown, write_on = seen[0]
            self.assertIn("could not be made", text)        # unknown, never "closed"
            self.assertTrue(box_shown)
            self.assertFalse(write_on)
            self.assertEqual(club.read_bytes().decode("utf-8-sig"), self.TEXT)

    def test_the_game_check_runs_on_a_worker_while_the_window_waits(self):
        import threading
        from PySide6.QtWidgets import QDialog

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            club = root / "db" / "2700" / "lnc" / "all" / "FM27_Club_Names.lnc"
            club.parent.mkdir(parents=True)
            write_lnc(club, self.TEXT)
            self.enterContext(mock.patch.multiple(
                editor, GAME_DB_ROOT=root / "db", BACKUP_ROOT=root / "backups"))
            self.assertTrue(win.load([str(club)]))
            editor.try_set_name(win.docs[0].names()[0], "Club One")
            win.reload_views()
            gate, threads, dialogs = threading.Event(), [], []
            self.addCleanup(gate.set)       # a failed test must not leave the worker waiting

            def check():
                threads.append(threading.current_thread())
                gate.wait(10)
                return []

            def press(dialog):
                dialogs.append(dialog)
                dialog.try_write()                          # the check at Write, on a worker too
                self.assertFalse(dialog.write_btn.isEnabled())
                win.jobs.wait(10)
                return dialog.result()

            with mock.patch.object(editor, "football_manager_running", check), \
                    mock.patch.object(QDialog, "exec", press):
                win.save()
                self.assertEqual(dialogs, [])               # the review waits for the check
                self.assert_busy(win, True)
                self.assertEqual(win.statusBar().currentMessage(),
                                 "Checking whether Football Manager is running...")
                gate.set()
                self.assertTrue(win.jobs.wait(10))
            self.assertEqual(len(dialogs), 1)
            self.assertEqual(len(threads), 2)               # when the review opened, and at Write
            self.assertTrue(all(thread is not threading.main_thread() for thread in threads))
            self.assertIn(b'"Club One"', club.read_bytes())
            self.assertFalse(win.docs[0].dirty)
            self.assert_busy(win, False)

    def test_a_backup_is_read_on_a_worker_and_restored_as_one_step(self):
        import threading
        from PySide6.QtWidgets import QDialog, QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, self.TEXT)
            backups = Path(tmp) / "backups"
            copy = backups / "20261111-120000" / "mine.lnc"
            copy.parent.mkdir(parents=True)
            write_lnc(copy, self.TEXT.replace("Club 2", "Club Two"))
            self.enterContext(mock.patch.object(editor, "BACKUP_ROOT", backups))
            self.assertTrue(win.load([str(path)]))
            threads = []
            real = editor.prepare_restore

            def recorded(doc, archive):
                threads.append(threading.current_thread())
                return real(doc, archive)

            def restore(dialog):
                with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                    dialog.restore()
                self.assertFalse(dialog.close_btn.isEnabled())     # waiting for the worker
                self.assertTrue(win.jobs.wait(10))
                self.assertTrue(dialog.close_btn.isEnabled())
                return 0

            with mock.patch.object(editor, "prepare_restore", recorded), \
                    mock.patch.object(QDialog, "exec", restore):
                win.open_backups()
            self.assertIsNot(threads[0], threading.main_thread())
            self.assertTrue(win.docs[0].restore_pending)
            self.assertEqual(win.undo_act.text(), "Undo restore mine.lnc from 20261111-120000")
            win.undo_act.trigger()
            self.assertFalse(win.docs[0].restore_pending)
            self.assertEqual(path.read_bytes().decode("utf-8-sig"), self.TEXT)  # memory only


class Session8Scaling(unittest.TestCase):
    """Release 2.4, session 8: at 125% and 150% Windows scaling on a 1920 x 1080 screen the
    window fits the screen's free area and its top row does not overflow.

    Each scale needs its own Qt screen, so each runs in a process of its own.
    """

    SCRIPT = (
        "import json, sys, tempfile\n"
        "from pathlib import Path\n"
        "from unittest import mock\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import fm_name_editor as editor\n"
        "root = Path(tempfile.mkdtemp())\n"
        "for name in ('BACKUP_ROOT', 'PROFILE_ROOT', 'STATE_ROOT'):\n"
        "    mock.patch.object(editor, name, root / name).start()\n"
        "from PySide6.QtWidgets import QApplication, QToolButton\n"
        "app, win = editor.run_gui([])\n"
        "QApplication.processEvents()\n"
        "free = app.primaryScreen().availableGeometry()\n"
        "overflow = win.toolbar.findChild(QToolButton, 'qt_toolbar_ext_button')\n"
        "print(json.dumps({'free': [free.width(), free.height()],\n"
        "                  'window': [win.width(), win.height()],\n"
        "                  'toolbar': [win.toolbar.sizeHint().width(), win.toolbar.width()],\n"
        "                  'overflow': bool(overflow is not None and overflow.isVisible()),\n"
        "                  'ratio': app.primaryScreen().devicePixelRatio()}))\n"
        "win.close()\n"
    )

    def test_the_window_fits_at_125_and_150_percent(self):
        import subprocess
        import sys

        project = str(Path(__file__).resolve().parent.parent)
        # A 1920 x 1080 screen with the taskbar taken off, in Qt's logical pixels.
        for ratio, width, height in ((1.25, 1536, 824), (1.5, 1280, 688)):
            with self.subTest(ratio=ratio), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "screen.json").write_text(json.dumps({"screens": [{
                    "name": "Desktop", "x": 0, "y": 0, "width": width, "height": height,
                    "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": ratio}]}), encoding="utf-8")
                (Path(tmp) / "probe.py").write_text(self.SCRIPT, encoding="utf-8")
                env = dict(os.environ, QT_QPA_PLATFORM="offscreen:configfile=screen.json")
                run = subprocess.run([sys.executable, "probe.py", project], cwd=tmp, env=env,
                                     capture_output=True, text=True, timeout=120)
                self.assertEqual(run.returncode, 0, run.stderr)
                found = json.loads(run.stdout.strip().splitlines()[-1])
                self.assertEqual((found["free"], found["ratio"]), ([width, height], ratio))
                window_width, window_height = found["window"]
                self.assertLessEqual(window_width, width)
                self.assertLessEqual(window_height + 40, height)   # room for the title bar
                self.assertLessEqual(found["toolbar"][0], found["toolbar"][1])
                self.assertFalse(found["overflow"])


@unittest.skipUnless(all((LIVE_DIR / name).is_file() for name in editor.NAME_FILES),
                     "the FM27 name files are not on this machine")
class Session7Speed(unittest.TestCase):
    """Release 2.4, session 7: with both FM27 files open, the window answers within a second.

    The live files are only read; the window works on copies in a temporary folder.
    """

    def test_both_live_files_load_reload_edit_and_save_within_a_second(self):
        import time
        from PySide6.QtWidgets import QApplication, QDialog

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        win = make_window(self)
        self.addCleanup(close_window, win)
        before = {name: (LIVE_DIR / name).read_bytes() for name in editor.NAME_FILES}

        def measure() -> dict:
            """Run every step in a fresh temp folder and return the timings."""
            with tempfile.TemporaryDirectory() as tmp:
                paths = []
                for name in editor.NAME_FILES:
                    copy = Path(tmp) / name
                    copy.write_bytes(before[name])
                    paths.append(str(copy))
                win.show()
                QApplication.processEvents()
                timings: dict = {}

                def timed(label, step):
                    start = time.perf_counter()
                    step()
                    QApplication.processEvents()
                    timings[label] = time.perf_counter() - start

                timed("load", lambda: win.load(paths))
                self.assertEqual(win.entity_model.rowCount(), 4297)
                timed("reload", win.reload_views)
                model = win.entity_model
                row = next(n for n, entity in enumerate(model.rows) if entity.id == "740")
                timed("cell edit",
                      lambda: model.setData(model.index(row, 2), "Wolverhampton Wanderers"))
                timed("undo", win.undo_act.trigger)
                code = model.columns().index("code")
                row = next(n for n, entity in enumerate(model.rows) if not entity.slots.get("code"))
                timed("added line", lambda: model.setData(model.index(row, code), "ZZZ"))
                timed("undo added line", win.undo_act.trigger)
                timed("redo added line", win.redo_act.trigger)
                with mock.patch.object(QDialog, "exec", press_write([])):
                    timed("save", win.save)
                self.assertIn(b'"ZZZ"', (Path(tmp) / "FM27_Club_Names.lnc").read_bytes())
            return timings

        # A single step breaching the 1 s cap is re-measured in a fresh temp
        # folder; a real regression breaches both runs, while a single spike
        # from CPU contention on a loaded machine does not fail the run. The
        # 1 s cap itself is unchanged, so the check is not weakened.
        timings = measure()
        slow = {label: round(seconds, 2) for label, seconds in timings.items()
                if seconds >= 1.0}
        if slow:
            timings = measure()
            slow = {label: round(seconds, 2) for label, seconds in timings.items()
                    if seconds >= 1.0}
        self.assertEqual(slow, {}, timings)
        for name in editor.NAME_FILES:
            self.assertEqual((LIVE_DIR / name).read_bytes(), before[name])


class Session9Licensing(unittest.TestCase):
    """Release 2.5, session 9: the licensing toggle looks for a running game again after the
    confirmation, runs one toggle at a time, drops a toggle when its dialog closes, and
    renames only in the direction confirmed (note 05, findings 1 and 2)."""

    def _tree(self, tmp) -> Path:
        """A temporary db\\2700 holding one name-mask file, for the database selector."""
        root = Path(tmp)
        mask = root / "db" / "2700" / editor.MASK_FILES[-1]      # edt/permanent/fake.edt
        mask.parent.mkdir(parents=True)
        mask.write_bytes(b"mask-bytes")
        self.enterContext(mock.patch.multiple(
            editor, GAME_DB_ROOT=root / "db", BACKUP_ROOT=root / "backups"))
        return mask

    def _window(self):
        from PySide6.QtWidgets import QApplication

        win = make_window(self)
        self.addCleanup(close_window, win)
        win.refresh_versions()                  # read the patched game folder
        win.show()
        QApplication.processEvents()
        return win

    @staticmethod
    def _pick(dialog) -> int:
        """Select the name-mask file's row in the licensing dialog."""
        name = editor.MASK_FILES[-1].as_posix()
        number = next(n for n, row in enumerate(dialog.rows) if row["name"] == name)
        dialog.table.setCurrentCell(number, 0)
        return number

    def test_the_rename_follows_the_intent_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = root / "2700"
            rel = editor.MASK_FILES[-1]
            src = version / rel
            src.parent.mkdir(parents=True)
            src.write_bytes(b"mask-bytes")
            disabled = src.with_name(src.name + ".disabled")
            self.assertEqual([editor.licence_intent(state)
                              for state in ("present", "disabled", "missing", "both")],
                             ["disable", "restore", "", ""])
            with self.assertRaises(FileNotFoundError) as caught:   # restore, while present
                editor.toggle_licence(version, rel, root / "backups", "restore")
            self.assertIn("fake.edt.disabled is not in", str(caught.exception))
            self.assertIn("Nothing was renamed", str(caught.exception))
            self.assertTrue(src.is_file())
            self.assertFalse(disabled.exists())
            self.assertFalse((root / "backups").exists())          # refused before the copy
            with self.assertRaises(ValueError):
                editor.toggle_licence(version, rel, root / "backups", "toggle")
            self.assertEqual(editor.toggle_licence(version, rel, root / "backups", "disable"),
                             "disabled")
            with self.assertRaises(FileNotFoundError):              # disable, once disabled
                editor.toggle_licence(version, rel, root / "backups", "disable")
            self.assertTrue(disabled.is_file())                     # not restored instead
            self.assertFalse(src.exists())
            self.assertEqual(len(editor.list_archives(root / "backups")), 1)

    def test_a_game_started_during_the_confirmation_stops_the_rename(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            mask = self._tree(tmp)
            win = self._window()
            running, checks = [], []

            def check():
                checks.append(list(running))
                return list(running)

            def answer(*_args, **_kwargs):
                if asked.call_count == 1:
                    running.append("fm.exe")    # started while the first question was open
                return QMessageBox.Yes

            refused = []

            def toggle_twice(dialog):
                self._pick(dialog)
                dialog.toggle_btn.click()
                refused.append((dialog.toggle_btn.isEnabled(), dialog.pending, mask.exists(),
                                (Path(tmp) / "backups").exists()))
                running.clear()                 # the game is closed again
                dialog.toggle_btn.click()       # the same dialog takes another toggle
                return 0

            with mock.patch.object(editor, "football_manager_running", check), \
                    mock.patch.object(QMessageBox, "question", side_effect=answer) as asked, \
                    mock.patch.object(QMessageBox, "warning",
                                      return_value=QMessageBox.Ok) as warned, \
                    mock.patch.object(QDialog, "exec", toggle_twice):
                win.open_licensing()
            self.assertEqual(checks[:2], [[], ["fm.exe"]])  # before the question, and after it
            self.assertEqual(refused, [(True, 0, True, False)])    # refused, nothing touched
            self.assertIn("This will disable the file below", asked.call_args_list[0].args[2])
            self.assertEqual(warned.call_count, 1)
            self.assertIn("fm.exe", warned.call_args.args[2])
            self.assertIn("Nothing was renamed", warned.call_args.args[2])
            self.assertEqual((checks[2:], asked.call_count), ([[], []], 2))
            self.assertFalse(mask.exists())                 # the second toggle went ahead
            self.assertEqual(mask.with_name("fake.edt.disabled").read_bytes(), b"mask-bytes")

    def test_each_answer_ends_the_toggle_and_a_failed_check_asks_again(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            mask = self._tree(tmp)
            disabled = mask.with_name("fake.edt.disabled")
            win = self._window()
            results: list = []
            after: list = []

            def check():
                found = results.pop(0)
                if isinstance(found, Exception):
                    raise found
                return found

            def toggle(dialog):
                self._pick(dialog)
                dialog.toggle_selected()
                after.append((dialog.toggle_btn.isEnabled(), dialog.pending))
                return 0

            yes, no = QMessageBox.Yes, QMessageBox.No
            for answers, found, verb, ends in (
                    ([no], [[]], "disable", "present"),             # No to the confirmation
                    ([yes, no], [[], None], "disable", "present"),  # unknown just before
                    ([yes, no], [[], RuntimeError("tasklist broke")], "disable", "present"),
                    ([yes, yes], [[], None], "disable", "disabled"),
                    ([yes], [[], []], "restore", "present")):
                with self.subTest(answers=answers, found=found):
                    results[:] = found
                    after.clear()
                    with mock.patch.object(editor, "football_manager_running", check), \
                            mock.patch.object(QMessageBox, "question",
                                              side_effect=answers) as asked, \
                            mock.patch.object(QDialog, "exec", toggle):
                        win.open_licensing()
                    self.assertEqual(results, [])
                    self.assertEqual(asked.call_count, len(answers))
                    self.assertIn(f"This will {verb} the file below",
                                  asked.call_args_list[0].args[2])
                    if verb == "restore":
                        self.assertIn(str(disabled), asked.call_args_list[0].args[2])
                    if found[-1] is None or isinstance(found[-1], Exception):
                        question = asked.call_args_list[1].args   # an earlier Yes is not reused
                        self.assertIn("could not be made", question[2])
                        self.assertIn("Have you closed Football Manager?", question[2])
                        self.assertEqual(question[4], QMessageBox.No)   # No is the default
                    self.assertEqual(after, [(True, 0)])            # over, however it ended
                    self.assertEqual((mask.exists(), disabled.exists()),
                                     (ends == "present", ends == "disabled"))

    def test_closing_during_the_check_after_yes_renames_nothing(self):
        import threading
        import time
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

        self.enterContext(mock.patch.object(editor, "JOBS_INLINE", False))
        with tempfile.TemporaryDirectory() as tmp:
            mask = self._tree(tmp)
            win = self._window()
            gate, calls = threading.Event(), []
            self.addCleanup(gate.set)       # a failed test must not leave the worker waiting

            def check():
                calls.append(threading.current_thread())
                if len(calls) == 2:
                    gate.wait(10)           # the check after Yes is held
                return []

            def toggle_then_close(dialog):
                dialog.show()
                QApplication.processEvents()
                self._pick(dialog)
                dialog.toggle_btn.click()
                deadline = time.monotonic() + 10
                while len(calls) < 2 and time.monotonic() < deadline:
                    QApplication.processEvents()    # the first check, then the question
                    time.sleep(0.005)
                self.assertEqual((len(calls), asked.call_count), (2, 1))
                dialog.reject()                     # Esc, Close, or the title bar
                gate.set()
                self.assertTrue(win.jobs.wait(10))
                return dialog.result()

            with mock.patch.object(editor, "football_manager_running", check), \
                    mock.patch.object(QMessageBox, "question",
                                      return_value=QMessageBox.Yes) as asked, \
                    mock.patch.object(QDialog, "exec", toggle_then_close):
                win.open_licensing()
            self.assertEqual(asked.call_count, 1)
            self.assertEqual(mask.read_bytes(), b"mask-bytes")
            self.assertFalse((Path(tmp) / "backups").exists())
            self.assertTrue(win.open_act.isEnabled())

    def test_one_toggle_at_a_time_and_none_after_the_dialog_closes(self):
        import threading
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

        self.enterContext(mock.patch.object(editor, "JOBS_INLINE", False))
        with tempfile.TemporaryDirectory() as tmp:
            mask = self._tree(tmp)
            win = self._window()
            for route in ("Close", "Esc", "title bar"):
                with self.subTest(route=route):
                    gate, threads = threading.Event(), []
                    self.addCleanup(gate.set)   # a failed test must not leave the worker waiting

                    def held():
                        threads.append(threading.current_thread())
                        gate.wait(10)
                        return []

                    def toggle_twice_then_close(dialog):
                        dialog.show()
                        QApplication.processEvents()
                        self._pick(dialog)
                        dialog.toggle_btn.click()
                        self.assertFalse(dialog.toggle_btn.isEnabled())
                        dialog.toggle_btn.click()           # off: nothing
                        dialog.toggle_selected()            # and refused when called
                        self.assertEqual(len(win.jobs.pending), 1)
                        if route == "Close":
                            dialog.close_btn.click()
                        elif route == "Esc":
                            QTest.keyClick(dialog, Qt.Key_Escape)
                        else:
                            dialog.close()                  # as the title bar's button does
                        self.assertFalse(dialog.isVisible())
                        gate.set()                          # the check comes back afterwards
                        self.assertTrue(win.jobs.wait(10))
                        return dialog.result()

                    with mock.patch.object(editor, "football_manager_running", held), \
                            mock.patch.object(QMessageBox, "question") as asked, \
                            mock.patch.object(QDialog, "exec", toggle_twice_then_close):
                        win.open_licensing()
                    self.assertEqual(len(threads), 1)
                    self.assertIsNot(threads[0], threading.main_thread())
                    self.assertEqual(asked.call_count, 0)   # no question after the dialog closed
                    self.assertEqual(mask.read_bytes(), b"mask-bytes")
                    self.assertFalse((Path(tmp) / "backups").exists())
                    self.assertTrue(win.open_act.isEnabled())   # the window is not left busy

    def test_a_file_renamed_meanwhile_is_not_renamed_back(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            mask = self._tree(tmp)
            disabled = mask.with_name("fake.edt.disabled")
            win = self._window()
            shown = []

            def renamed_elsewhere(*_args, **_kwargs):
                mask.rename(disabled)           # disabled by hand while the question was open
                return QMessageBox.Yes

            def toggle(dialog):
                self._pick(dialog)
                dialog.toggle_selected()
                shown.append(dialog.rows[self._pick(dialog)]["state"])
                return 0

            with mock.patch.object(editor, "football_manager_running", return_value=[]), \
                    mock.patch.object(QMessageBox, "question",
                                      side_effect=renamed_elsewhere) as asked, \
                    mock.patch.object(QMessageBox, "critical") as told, \
                    mock.patch.object(QDialog, "exec", toggle):
                win.open_licensing()
            self.assertIn("This will disable", asked.call_args.args[2])
            self.assertIn("nothing to disable", told.call_args.args[2])
            self.assertIn("Nothing was renamed", told.call_args.args[2])
            self.assertTrue(disabled.is_file())             # still disabled, not restored
            self.assertFalse(mask.exists())
            self.assertEqual(shown, ["disabled"])           # the list shows the folder as it is
            self.assertFalse((Path(tmp) / "backups").exists())


class Session9Profiles(unittest.TestCase):
    """Release 2.5, session 9: Apply looks at every line of a repeated key before it ticks a
    proposal, whatever their order (note 05, finding 3)."""

    KEY = ("CLUB_NAME_CHANGE", "1", "")

    def _profile(self, source: Path, name: str = "Mine", spelling: str = "My spelling"):
        profile = editor.Profile(name)
        profile.rows[self.KEY] = {
            "command": "CLUB_NAME_CHANGE", "id": "1", "language": "", "name": spelling,
            "baseline": "Original", "source": str(source), "source_sha256": "",
            "recorded": ""}
        return profile

    @staticmethod
    def _doc(path: Path, *names) -> editor.LncDoc:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lnc(path, "".join(f'"CLUB_NAME_CHANGE"\t1\t"{name}"\t""\n' for name in names))
        return editor.LncDoc(path)

    def test_a_changed_baseline_or_an_unsaved_edit_on_any_line_unticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FM27_Club_Names.lnc"
            profile = self._profile(path)
            for names in (("Official Changed", "Original"), ("Original", "Official Changed")):
                with self.subTest(order=names):
                    changes, _missing, stats = editor.apply_profile(
                        profile, [self._doc(path, *names)])
                    line = names.index("Official Changed") + 1
                    self.assertFalse(changes[0].checked)
                    self.assertIn("Baseline changed: the file says Official Changed; when "
                                  f"recorded it said Original (FM27_Club_Names.lnc, line {line})",
                                  changes[0].note)
                    self.assertIn("Duplicate id (2 rows)", changes[0].note)
                    self.assertEqual((stats["ticked"], stats["review"]), (0, 1))
            for edited in (0, 1):
                with self.subTest(edited=edited):
                    doc = self._doc(path, "Original", "Original")
                    editor.try_set_name(doc.names()[edited], "Other unsaved edit")
                    changes, missing, _stats = editor.apply_profile(profile, [doc])
                    self.assertFalse(changes[0].checked)
                    self.assertIn("Unsaved edit Other unsaved edit would be replaced "
                                  f"(FM27_Club_Names.lnc, line {edited + 1})", changes[0].note)
                    editor.apply_profile_proposals(profile.name, changes, missing, [doc])
                    self.assertEqual(doc.names()[edited].name, "Other unsaved edit")  # kept

    def test_lines_in_two_files_are_looked_at_in_either_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            club = self._doc(Path(tmp) / "a" / "FM27_Club_Names.lnc", "Official Changed")
            fix = self._doc(Path(tmp) / "b" / "FM27_Fix.lnc", "Original")
            profile = self._profile(club.path)
            for docs in ([club, fix], [fix, club]):
                with self.subTest(order=[doc.path.name for doc in docs]):
                    changes, _missing, _stats = editor.apply_profile(profile, docs)
                    self.assertEqual(len(changes), 1)
                    self.assertFalse(changes[0].checked)
                    self.assertIn("(FM27_Club_Names.lnc, line 1)", changes[0].note)

    def test_an_earlier_line_another_profile_set_unticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FM27_Club_Names.lnc"
            doc = self._doc(path, "Original", "Original")
            other = self._profile(path, "Modern names", "Modern")
            changes, missing, _stats = editor.apply_profile(other, [doc])
            changes[0].target_rows = changes[0].target_rows[:1]    # it set the first line only
            editor.apply_profile_proposals(other.name, changes, missing, [doc])
            self.assertEqual([entry.name for entry in doc.names()], ["Modern", "Original"])
            changes, _missing, _stats = editor.apply_profile(self._profile(path), [doc])
            self.assertFalse(changes[0].checked)
            self.assertIn("Competes with profile Modern names, which set Modern in this "
                          "session (FM27_Club_Names.lnc, line 1)", changes[0].note)

    def test_identical_clean_lines_stay_ticked_and_apply_as_one_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FM27_Club_Names.lnc"
            doc = self._doc(path, "Original", "Original")
            on_disk, before = path.read_bytes(), doc.to_bytes()
            changes, missing, stats = editor.apply_profile(self._profile(path), [doc])
            self.assertTrue(changes[0].checked)
            self.assertEqual(changes[0].note, "Duplicate id (2 rows)")
            self.assertEqual((stats["ticked"], stats["review"]), (1, 0))
            operation = editor.Operation("profile Mine")
            with operation:
                editor.apply_profile_proposals("Mine", changes, missing, [doc])
            self.assertEqual([entry.name for entry in doc.names()], ["My spelling"] * 2)
            operation.undo()
            self.assertEqual(doc.to_bytes(), before)
            self.assertFalse(doc.dirty)
            operation.redo()
            self.assertEqual([entry.name for entry in doc.names()], ["My spelling"] * 2)
            self.assertEqual(path.read_bytes(), on_disk)            # memory only
            # A line that already reads the spelling is left alone; the other is shown.
            doc = self._doc(path, "Original", "Original")
            editor.try_set_name(doc.names()[1], "My spelling")
            changes, _missing, _stats = editor.apply_profile(self._profile(path), [doc])
            self.assertTrue(changes[0].checked)
            self.assertIs(changes[0].target, doc.names()[0])


class Session9Settings(unittest.TestCase):
    """Release 2.5, session 9: a value of the wrong type in the settings or collections file
    cannot stop the window opening, and a damaged settings file is named and never written
    over (note 05, findings 4 and 5)."""

    WRONG = ([], {}, None, True, 7, 2.5)

    def test_values_of_the_wrong_type_are_dropped_not_fatal(self):
        for value in self.WRONG:
            with self.subTest(value=value):
                for field in ("tab", "family", "status", "entity_sort", "line_sort",
                              "entity_widths", "line_widths", "geometry", "window_state",
                              "splitter"):
                    self.assertEqual(editor.clean_view({field: value}), {}, field)
                self.assertEqual(editor.clean_view({"entity_widths": {"club": value}}), {})
                self.assertEqual(editor.clean_view(value), {})
                for field in ("name", *editor.SavedSearch.FIELDS):
                    self.assertEqual(
                        editor.clean_saved_searches([{"name": "Broken", field: value}]), [],
                        field)
                self.assertEqual(editor.clean_saved_searches([value]), [])
                self.assertEqual(editor.clean_saved_searches(value), [])
        # A field that is missing still takes its default.
        self.assertEqual([s.to_json() for s in editor.clean_saved_searches([{"name": "Plain"}])],
                         [{"name": "Plain", "family": "club", "text": "", "status": "all",
                           "section": "", "collection": ""}])

    def test_a_damaged_settings_file_is_named_and_never_written_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            path = root / "settings.json"
            self.assertEqual(editor.read_state(root), ({}, ""))         # missing: no settings
            editor.save_state({"active_profile_file": "mine.json"}, root)   # and made as before
            self.assertEqual(editor.read_state(root), ({"active_profile_file": "mine.json"}, ""))
            path.write_bytes(BOM + b'{"active_profile_file": "bom.json"}')
            self.assertEqual(editor.read_state(root), ({"active_profile_file": "bom.json"}, ""))
            for data, words in ((b"{broken", "is not readable JSON"),
                                (b'{"view": "\xff"}', "is not UTF-8 text"),
                                (b"[1, 2]", "should be one JSON object"),
                                (b'"text"', "should be one JSON object"),
                                (b"null", "should be one JSON object"),
                                (b"", "is not readable JSON")):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    settings, problem = editor.read_state(root)
                    self.assertEqual(settings, {})
                    self.assertIn(str(path), problem)
                    self.assertIn(words, problem)
                    self.assertEqual(editor.load_state(root), {})
                    with self.assertRaises(editor.DamagedFileError) as caught:
                        editor.save_state({"active_profile_file": "example.json"}, root)
                    self.assertIsInstance(caught.exception, OSError)
                    self.assertEqual(caught.exception.path, path)
                    self.assertEqual(str(caught.exception), problem)
                    self.assertEqual(path.read_bytes(), data)          # byte for byte
            self.assertEqual(staging_files(root), [])
            path.unlink()
            path.mkdir()                                              # a folder in its place
            self.assertIn("could not be read", editor.read_state(root)[1])
            with self.assertRaises(editor.DamagedFileError):
                editor.save_state({}, root)

    def test_a_collections_file_with_wrong_types_is_damaged_not_fatal(self):
        head = {"format": "fm-name-collections", "version": 1}
        member = {"family": "club", "id": "1", "language": ""}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for body, words in (
                    ({**head, "collections": 5}, "damaged list of collections"),
                    ({**head, "collections": {"name": "A"}}, "damaged list of collections"),
                    ({**head, "collections": [{"name": "A", "members": 7}]},
                     "damaged list of members"),
                    ({**head, "collections": [{"name": "A", "members": [
                        dict(member, family=[])]}]}, "has a member that is not"),
                    ({**head, "collections": [{"name": "A", "members": [
                        dict(member, family={})]}]}, "has a member that is not"),
                    ({**head, "collections": [{"name": 7}]}, "has no name"),
                    ({**head, "deleted": 3}, "damaged list of deleted")):
                with self.subTest(body=body):
                    (root / "collections.json").write_text(json.dumps(body), encoding="utf-8")
                    with self.assertRaises(ValueError) as caught:
                        editor.load_collection_file(root)
                    self.assertIn(words, str(caught.exception))
                    self.assertIn("collections.json", str(caught.exception))


class Session9Window(unittest.TestCase):
    """Release 2.5, session 9: the settings file in the window, refused text in the inspector,
    and the actions a job switches off (note 05, findings 4, 5, and 6)."""

    def _roots(self, tmp) -> Path:
        state = Path(tmp) / "state"
        self.enterContext(mock.patch.multiple(
            editor, STATE_ROOT=state, PROFILE_ROOT=Path(tmp) / "profiles"))
        return state

    def _window(self):
        from PySide6.QtWidgets import QApplication

        win = make_window(self)
        self.addCleanup(close_window, win)
        win.show()
        win.activateWindow()
        QApplication.processEvents()
        return win

    def test_wrong_types_in_the_settings_file_open_with_the_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._roots(tmp)
            state.mkdir()
            (state / "settings.json").write_text(json.dumps({
                "view": {"family": [], "status": {}, "tab": None, "entity_sort": 7,
                         "entity_widths": {"club": []}, "geometry": True},
                "saved_searches": [{"name": "Broken", "family": []},
                                   {"name": "Odd", "status": {}},
                                   {"name": "Cups", "family": "comp"}],
                "active_profile_file": []}), encoding="utf-8")
            win = self._window()
            self.assertEqual((win.family, win.status_mode, win.tabs.currentIndex()),
                             ("club", "all", 0))
            self.assertEqual([search.name for search in win.saved_searches], ["Cups"])
            self.assertEqual(win.profile_box.currentText(), "No profile")
            self.assertTrue(win.settings_label.isHidden())   # a usable file, used as far as it can be

    def test_a_damaged_settings_file_is_named_and_left_alone(self):
        from PySide6.QtWidgets import QDialog, QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            state = self._roots(tmp)
            state.mkdir()
            path = state / "settings.json"
            profile = editor.create_profile("Mine", "", editor.PROFILE_ROOT)
            for data in (b"{broken", b'{"view": "\xff"}', b"[1, 2]"):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    win = self._window()
                    self.assertFalse(win.settings_label.isHidden())
                    self.assertEqual(win.settings_label.text(),
                                     f"Settings not saved: {path} could not be read")
                    self.assertIn("leaves the file as it is", win.settings_label.toolTip())
                    # A profile chosen is used, not remembered, and the status bar says so.
                    win.profile_box.setCurrentIndex(win.profile_box.findData(profile.path.name))
                    self.assertEqual(win.current_profile().name, "Mine")
                    self.assertIn("The chosen profile is not remembered",
                                  win.statusBar().currentMessage())
                    self.assertIn(str(path), win.statusBar().currentMessage())
                    # A saved search is refused, with a warning naming the file.
                    with mock.patch.object(QDialog, "exec", Session8Window._name("Kept")), \
                            mock.patch.object(QMessageBox, "warning") as warned:
                        win.save_search()
                    self.assertIn("The saved searches were not changed", warned.call_args.args[2])
                    self.assertIn(str(path), warned.call_args.args[2])
                    self.assertEqual(win.saved_searches, [])
                    # Closing remembers the view, but not into this file.
                    win.remember_on_close = True
                    win.close()
                    self.assertEqual(path.read_bytes(), data)
                    self.assertEqual(staging_files(state), [])

    def test_a_settings_file_damaged_while_the_window_runs_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._roots(tmp)
            profile = editor.create_profile("Mine", "", editor.PROFILE_ROOT)
            win = self._window()
            self.assertTrue(win.settings_label.isHidden())
            win.profile_box.setCurrentIndex(win.profile_box.findData(profile.path.name))
            self.assertEqual(editor.read_state(state), ({"active_profile_file": "mine.json"}, ""))
            (state / "settings.json").write_bytes(b"{broken later")
            win.profile_box.setCurrentIndex(0)                  # No profile
            self.assertEqual((state / "settings.json").read_bytes(), b"{broken later")
            self.assertFalse(win.settings_label.isHidden())
            self.assertIn("not remembered", win.statusBar().currentMessage())
            # Put right by hand while the window runs: this run still leaves it alone,
            # rather than replace it with what this window holds.
            fixed = b'{"active_profile_file": "", "saved_searches": []}\n'
            (state / "settings.json").write_bytes(fixed)
            win.profile_box.setCurrentIndex(win.profile_box.findData(profile.path.name))
            win.remember_view()
            self.assertEqual((state / "settings.json").read_bytes(), fixed)

    def test_refused_text_stays_while_another_field_is_edited(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        with tempfile.TemporaryDirectory() as tmp:
            self._roots(tmp)
            win = self._window()
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, Session7Window.CLUBS)               # club 10: Alpha United, Alpha
            self.assertTrue(win.load([str(path)]))
            Session7Window._select(win, "10")
            long, short = win.inspector_fields["long"], win.inspector_fields["short"]
            code = win.inspector_fields["code"]
            long["edit"].setText('Alpha "United"')
            win.commit_inspector("long", long["edit"])
            self.assertIn("double quote", long["problem"].text())
            short["edit"].setText("Alpha FC")
            win.commit_inspector("short", short["edit"])
            entity = win.inspector_entity
            self.assertEqual((entity.name_in("long"), entity.name_in("short")),
                             ("Alpha United", "Alpha FC"))
            self.assertEqual(win.undo_stack.count(), 1)
            self.assertEqual(win.undo_act.text(), "Undo edit short name: Alpha FC")
            self.assertEqual(short["marker"].text(), "Edited (Manual edit)")   # brought up to date

            def assert_refused_text_kept():
                self.assertEqual(long["edit"].text(), 'Alpha "United"')
                self.assertTrue(long["problem"].isVisible())
                self.assertIn("double quote", long["problem"].text())
                self.assertEqual(long["edit"].objectName(), "invalid")

            assert_refused_text_kept()
            code["edit"].setText("ALP")                         # an added line reloads the views
            win.commit_inspector("code", code["edit"])
            QApplication.processEvents()                        # the reload runs from the event loop
            self.assertEqual(code["marker"].text(), "Added (Manual edit)")
            assert_refused_text_kept()
            win.undo_act.trigger()                              # the added code
            win.undo_act.trigger()                              # the short name
            entity = win.inspector_entity
            self.assertEqual((entity.name_in("long"), entity.name_in("short"),
                              entity.name_in("code")), ("Alpha United", "Alpha", ""))
            self.assertFalse(win.docs[0].dirty)
            assert_refused_text_kept()                          # Undo took the valid edits only
            long["edit"].setFocus()
            QTest.keyClick(long["edit"], Qt.Key_Escape)         # Esc puts back the name in memory
            self.assertEqual(long["edit"].text(), "Alpha United")
            self.assertFalse(long["problem"].isVisible())
            self.assertEqual(long["edit"].objectName(), "")
            long["edit"].setText("")
            win.commit_inspector("long", long["edit"])
            self.assertIn("cannot be empty", long["problem"].text())
            Session7Window._select(win, "30")                   # another club clears it
            Session7Window._select(win, "10")
            self.assertEqual(long["edit"].text(), "Alpha United")
            self.assertFalse(long["problem"].isVisible())

    def test_actions_that_write_local_files_wait_for_a_job(self):
        import threading

        self.enterContext(mock.patch.object(editor, "JOBS_INLINE", False))
        with tempfile.TemporaryDirectory() as tmp:
            self._roots(tmp)
            profile = editor.create_profile("Mine", "", editor.PROFILE_ROOT)
            win = self._window()
            win.profile_box.setCurrentIndex(win.profile_box.findData(profile.path.name))
            actions = (win.export_act, win.new_profile_act, win.rename_profile_act,
                       win.delete_profile_act, win.add_to_collection_menu.menuAction())
            self.assertEqual([action.isEnabled() for action in actions], [True] * 5)
            gate = threading.Event()
            self.addCleanup(gate.set)       # a failed test must not leave the worker waiting
            win.jobs.start("Waiting...", lambda: gate.wait(10), lambda _result: None)
            self.assertEqual([action.isEnabled() for action in actions], [False] * 5)
            gate.set()
            self.assertTrue(win.jobs.wait(10))
            self.assertEqual([action.isEnabled() for action in actions], [True] * 5)


class Session10Branding(unittest.TestCase):
    """Session 10, Release 2.6: the public-ready release."""

    def test_the_copyright_matches_LICENSE_and_the_README(self):
        """The one copyright line the About dialog, the status bar and the file
        headers all point at. Changing it belongs in LICENSE, so this test keeps
        the application copy in step."""
        self.assertEqual(
            editor.COPYRIGHT_FULL,
            "Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). "
            "All rights reserved.")
        self.assertIn("Proprietary", editor.COPYRIGHT_NOTE)
        self.assertIn("LICENSE", editor.COPYRIGHT_NOTE)
        here = Path(editor.__file__).resolve().parent
        self.assertIn(editor.COPYRIGHT_FULL, (here / "LICENSE").read_text(encoding="utf-8"))
        self.assertIn(editor.COPYRIGHT_FULL, (here / "README.md").read_text(encoding="utf-8"))

    def test_project_root_from_source_is_the_project_folder(self):
        """Running from source, the backups, profiles, and state folders sit
        under C:\\FM Name Editor. The test suite patches them to a temporary
        folder for the run; this covers the frozen-or-not choice itself."""
        with mock.patch.object(editor.sys, "frozen", False, create=True):
            self.assertEqual(editor.project_root(), Path(r"C:\FM Name Editor"))

    def test_project_root_when_frozen_is_the_folder_that_holds_the_exe(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "FM Name Editor.exe"
            exe.write_bytes(b"")
            with mock.patch.object(editor.sys, "frozen", True, create=True), \
                 mock.patch.object(editor.sys, "executable", str(exe)):
                self.assertEqual(editor.project_root(), Path(folder).resolve())

    def test_the_backups_profiles_and_state_folders_sit_beside_the_exe_when_frozen(self):
        """Keeps BACKUP_ROOT / PROFILE_ROOT / STATE_ROOT aligned with project_root(): a
        frozen build uses the folder the exe is in, so it works wherever it is unpacked."""
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "FM Name Editor.exe"
            exe.write_bytes(b"")
            with mock.patch.object(editor.sys, "frozen", True, create=True), \
                 mock.patch.object(editor.sys, "executable", str(exe)):
                root = editor.project_root()
                self.assertEqual(root / "backups", Path(folder).resolve() / "backups")
                self.assertEqual(root / "profiles", Path(folder).resolve() / "profiles")
                self.assertEqual(root / "state", Path(folder).resolve() / "state")

    def test_resource_path_finds_the_shipped_icon_from_source(self):
        icon = editor.resource_path(editor.ICON_FILE)
        self.assertIsNotNone(icon)
        self.assertTrue(icon.is_file())
        self.assertEqual(icon.name.lower(), "football.ico")

    def test_resource_path_finds_a_data_file_under_MEIPASS_when_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "icon").mkdir()
            icon_file = base / "icon" / "football.ico"
            icon_file.write_bytes(b"")
            exe = base / "FM Name Editor.exe"
            exe.write_bytes(b"")
            with mock.patch.object(editor.sys, "frozen", True, create=True), \
                 mock.patch.object(editor.sys, "_MEIPASS", str(base), create=True), \
                 mock.patch.object(editor.sys, "executable", str(exe)):
                found = editor.resource_path(editor.ICON_FILE)
            self.assertEqual(found, icon_file)

    def test_resource_path_returns_none_for_a_missing_file_without_raising(self):
        # The window must open even when the icon has been removed from the folder.
        self.assertIsNone(editor.resource_path("icon/does-not-exist.ico"))

    def test_the_short_copyright_line_is_in_the_status_bar(self):
        win = make_window(self)
        try:
            self.assertEqual(win.copyright_label.text(), editor.COPYRIGHT_SHORT)
            self.assertIn("Mark Hawksworth", win.copyright_label.text())
            self.assertIn("2026", win.copyright_label.text())
            self.assertTrue(win.copyright_label.isVisible() or not win.isVisible())
            tip = win.copyright_label.toolTip()
            self.assertIn(editor.COPYRIGHT_FULL, tip)
            self.assertIn("LICENSE", tip)
        finally:
            close_window(win)


class Session10About(unittest.TestCase):

    def test_About_names_the_application_version_and_exact_copyright(self):
        from PySide6.QtWidgets import QDialog, QLabel

        win = make_window(self)
        try:
            seen = []

            def catch(dialog):
                seen.append(dialog)
                # Show the dialog so findChildren walks the built labels.
                return 0

            with mock.patch.object(QDialog, "exec", catch):
                win.show_about()
            self.assertEqual(len(seen), 1, "About should open exactly one dialog")
            dialog = seen[0]
            self.assertEqual(dialog.windowTitle(), f"About {editor.APP_NAME}")
            texts = [child.text() for child in dialog.findChildren(QLabel)]
            self.assertIn(editor.APP_NAME, texts)
            self.assertIn(f"Version {editor.VERSION}", texts)
            self.assertIn(editor.COPYRIGHT_FULL, texts)
            self.assertTrue(
                any("proprietary" in text.lower() and "open source" in text.lower()
                    for text in texts),
                f"a line calling the software proprietary should be shown: {texts!r}")
            self.assertTrue(any("LICENSE" in text for text in texts),
                            f"a pointer to LICENSE should be shown: {texts!r}")
        finally:
            close_window(win)

    def test_About_is_in_the_Help_menu(self):
        win = make_window(self)
        try:
            actions = [action for action in win.help_menu.actions() if not action.isSeparator()]
            labels = [action.text() for action in actions]
            self.assertIn(f"About {editor.APP_NAME}", labels)
            # The About entry has no shortcut, so it stays out of the shortcut list.
            about = win.about_act
            self.assertEqual(about.shortcuts(), [])
        finally:
            close_window(win)


class Session11Repository(unittest.TestCase):
    """Session 11, Release 2.6.1: the public repository link in About and the status bar."""

    REPOSITORY_URL = "https://github.com/hawkers63/FM-Name-Editor"

    def test_the_repository_URL_is_held_in_one_constant(self):
        """One constant, so About, the status bar, and future callers agree."""
        self.assertEqual(editor.REPOSITORY_URL, self.REPOSITORY_URL)

    def test_the_status_bar_tooltip_names_the_repository_under_the_copyright(self):
        from PySide6.QtCore import Qt

        win = make_window(self)
        try:
            tip = win.copyright_label.toolTip()
            self.assertIn(editor.COPYRIGHT_FULL, tip)
            self.assertIn(self.REPOSITORY_URL, tip)
            # The URL sits below the full copyright line so the tooltip reads
            # top-down: name, then source, then the proprietary note.
            self.assertLess(tip.index(editor.COPYRIGHT_FULL),
                            tip.index(self.REPOSITORY_URL))
            self.assertLess(tip.index(self.REPOSITORY_URL),
                            tip.index(editor.COPYRIGHT_NOTE))
            # The label text itself keeps to the short line; the Qt tooltip
            # handles the longer three-line text on hover.
            self.assertEqual(win.copyright_label.text(), editor.COPYRIGHT_SHORT)
            del Qt
        finally:
            close_window(win)

    def test_About_shows_the_repository_URL_directly_beneath_the_copyright(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog, QLabel

        win = make_window(self)
        try:
            seen = []
            with mock.patch.object(QDialog, "exec", lambda d: seen.append(d) or 0):
                win.show_about()
            self.assertEqual(len(seen), 1)
            dialog = seen[0]
            labels = dialog.findChildren(QLabel)
            texts = [label.text() for label in labels]
            # The dialog carries exactly one label whose text is the URL,
            # and it sits directly beneath the copyright label.
            copyright_index = next(i for i, text in enumerate(texts)
                                   if text == editor.COPYRIGHT_FULL)
            self.assertLess(copyright_index + 1, len(labels),
                            f"no label after the copyright: {texts!r}")
            repo_label = labels[copyright_index + 1]
            self.assertIn(self.REPOSITORY_URL, repo_label.text())
            # The link opens in the default browser (rich text + external links).
            self.assertEqual(repo_label.textFormat(), Qt.RichText)
            self.assertTrue(repo_label.openExternalLinks())
            # The URL sits directly beneath the copyright, with the
            # proprietary note after it; the dialog has no second anchor.
            self.assertLess(texts.index(editor.COPYRIGHT_FULL),
                            copyright_index + 1)   # trivially true, kept for clarity
            self.assertIn(editor.COPYRIGHT_NOTE, texts)
            self.assertLess(copyright_index + 1, texts.index(editor.COPYRIGHT_NOTE))
            # The exact URL is in the HTML of the link, as an href the browser
            # opens unchanged.
            html = repo_label.text()
            self.assertIn(f'href="{self.REPOSITORY_URL}"', html)
        finally:
            close_window(win)

    def test_the_README_names_the_public_repository(self):
        """The README's own wording points at the same URL the application does."""
        here = Path(editor.__file__).resolve().parent
        readme = (here / "README.md").read_text(encoding="utf-8")
        self.assertIn(self.REPOSITORY_URL, readme)


class Session12Identity(unittest.TestCase):
    """Session 12, Release 3.0: the database folder's own XML identity."""

    XML = (
        '<?xml version="1.0"?>\n'
        '<record>\n'
        '  <string id="name" value="Football Manager 27"/>\n'
        '  <string id="version" value="27.0.0" translate="false"/>\n'
        '  <string id="author" value="Sports Interactive"/>\n'
        '  <string id="date" value="14/10/2026 12:30"/>\n'
        '</record>\n'
    )

    def _version_tree(self, root: Path, folder_name: str, xml: str | None,
                      names: bool = True) -> Path:
        """Build a <version>/lnc/all/<FM27 files> plus <version>/<version>_fm/<version>_fm.xml."""
        version = root / folder_name
        (version / "lnc" / "all").mkdir(parents=True)
        if names:
            for name in editor.NAME_FILES:
                (version / "lnc" / "all" / name).write_bytes(b"\xef\xbb\xbf")
        if xml is not None:
            fm_folder = version / f"{folder_name}_fm"
            fm_folder.mkdir()
            (fm_folder / f"{folder_name}_fm.xml").write_text(xml, encoding="utf-8")
        return version

    def test_short_database_name_handles_the_shapes_the_game_uses(self):
        # "Football Manager 27" -> "FM27"; "Football Manager 2024" -> "FM2024"; and the
        # empty-string fallback returns itself so the selector always shows something.
        self.assertEqual(editor.short_database_name("Football Manager 27"), "FM27")
        self.assertEqual(editor.short_database_name("Football Manager 2024"), "FM2024")
        self.assertEqual(editor.short_database_name("Football Manager"), "FM")
        self.assertEqual(editor.short_database_name(""), "")

    def test_read_database_identity_reads_the_name_and_version_from_the_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), "2700", self.XML)
            identity = editor.read_database_identity(version)
            self.assertIsNotNone(identity)
            self.assertEqual((identity.name, identity.version),
                             ("Football Manager 27", "27.0.0"))

    def test_read_database_identity_is_None_for_a_missing_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), "2730", xml=None)
            self.assertIsNone(editor.read_database_identity(version))

    def test_read_database_identity_is_None_for_a_malformed_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), "2740", xml="<not valid xml")
            self.assertIsNone(editor.read_database_identity(version))

    def test_read_database_identity_is_None_when_name_or_version_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(
                Path(tmp), "2750",
                '<record><string id="name" value="Only a Name"/></record>')
            self.assertIsNone(editor.read_database_identity(version))
            version = self._version_tree(
                Path(tmp), "2760",
                '<record><string id="version" value="99.0.0"/></record>')
            self.assertIsNone(editor.read_database_identity(version))

    def test_version_label_names_the_database_when_the_xml_is_there(self):
        """Acceptance: 'FM27 27.0.0 (2700)' appears in the database selector."""
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), "2700", self.XML, names=True)
            self.assertEqual(editor.version_label(version), "FM27 27.0.0 (2700)")

    def test_version_label_falls_back_to_the_folder_name_without_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), "2700", xml=None, names=True)
            self.assertEqual(editor.version_label(version), "2700")

    def test_version_label_keeps_the_no_name_files_trailer(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), "2700", self.XML, names=False)
            self.assertEqual(editor.version_label(version), "FM27 27.0.0 (2700) (no name files)")
            version = self._version_tree(Path(tmp), "2601", xml=None, names=False)
            self.assertEqual(editor.version_label(version), "2601 (no name files)")


class Session12Migration(unittest.TestCase):
    """Session 12: three-way migration against the newly installed name files.

    Reuses Session 4's profile shape: baseline (what the old files said when
    recorded), preferred (the spelling the user wants), upstream (what the
    newly loaded files say now).
    """

    OLD = (
        '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'
        '"CLUB_NAME_CHANGE"\t20\t"Beta Rovers"\t""\n'
        '"CLUB_NAME_CHANGE"\t30\t"Gamma Town"\t""\n'
        '"CLUB_SHORT_NAME_CHANGE"\t40\t"Delta FC"\t""\n'
    )

    def _recorded(self, tmp: Path):
        """A profile with four spellings, recorded from an OLD-content club file."""
        work = tmp / "work"
        work.mkdir()
        club = work / "FM27_Club_Names.lnc"
        write_lnc(club, self.OLD)
        doc = editor.LncDoc(club)
        rows = {entry.id: entry for entry in doc.names()
                if entry.cmd == "CLUB_NAME_CHANGE"}
        short_rows = {entry.id: entry for entry in doc.names()
                      if entry.cmd == "CLUB_SHORT_NAME_CHANGE"}
        editor.try_set_name(rows["10"], "Alpha United FC")         # changed; kept preferred
        editor.try_set_name(rows["20"], "Beta Wanderers")          # changed; preferred differs from old
        editor.try_set_name(rows["30"], "Gamma")                   # changed; preferred
        editor.try_set_name(short_rows["40"], "Delta")             # changed
        doc.append_entry("CLUB_3LETTER_NAME_CHANGE", "10", "ALP", "")  # recorded addition
        profile = editor.create_profile("Mine", "", tmp / "profiles")
        editor.record_edits(profile, [doc])
        return profile

    def _upstream_doc(self, tmp: Path, text: str) -> "editor.LncDoc":
        """A newly loaded FM27_Club_Names.lnc for the migration to compare against."""
        upstream = tmp / "new" / "FM27_Club_Names.lnc"
        upstream.parent.mkdir(parents=True, exist_ok=True)
        write_lnc(upstream, text)
        return editor.LncDoc(upstream)

    def test_unchanged_key_is_pre_ticked(self):
        """Acceptance: an unchanged key between 'versions' is pre-ticked."""
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # Club 10's baseline was "Alpha United"; the new files still have it.
            upstream = self._upstream_doc(Path(tmp), self.OLD)
            changes, missing, stats = editor.migrate_profile(profile, [upstream])
            row = next(p for p in changes if p.id == "10")
            self.assertTrue(row.checked)
            self.assertIn("Carries forward", row.note)
            # Four open lines carry forward, plus the recorded 3-letter addition
            # for club 10 (still absent upstream), so all five rows are ticked.
            self.assertEqual(stats["eligible"], 5)
            self.assertEqual(stats["conflict"], 0)
            self.assertEqual(stats["missing"], 0)

    def test_stock_rename_between_versions_is_never_pre_ticked(self):
        """Acceptance: a stock rename between the versions is never pre-ticked."""
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # The game renames club 20 upstream; baseline "Beta Rovers" -> "Beta Athletic"
            # (neither baseline nor our preferred "Beta Wanderers"), so this is a conflict.
            upstream_text = self.OLD.replace("Beta Rovers", "Beta Athletic")
            upstream = self._upstream_doc(Path(tmp), upstream_text)
            changes, _missing, stats = editor.migrate_profile(profile, [upstream])
            row = next(p for p in changes if p.id == "20")
            self.assertFalse(row.checked)
            self.assertIn("Upstream changed since recorded", row.note)
            self.assertIn("Beta Athletic", row.note)
            self.assertIn("Beta Rovers", row.note)
            self.assertEqual(stats["conflict"], 1)

    def test_an_already_preferred_upstream_is_counted_as_same_and_not_in_the_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # The game now ships club 30 as "Gamma" (the preferred name).
            upstream_text = self.OLD.replace("Gamma Town", "Gamma")
            upstream = self._upstream_doc(Path(tmp), upstream_text)
            changes, missing, stats = editor.migrate_profile(profile, [upstream])
            self.assertEqual(stats["already_preferred"], 1)
            self.assertFalse(any(p.id == "30" for p in changes),
                             "already-preferred rows are not in the preview")
            self.assertFalse(any(p.id == "30" for p in missing))

    def test_a_key_missing_upstream_is_unticked_with_the_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # The new files drop club 40's short name altogether.
            upstream_text = (
                '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'
                '"CLUB_NAME_CHANGE"\t20\t"Beta Rovers"\t""\n'
                '"CLUB_NAME_CHANGE"\t30\t"Gamma Town"\t""\n'
            )
            upstream = self._upstream_doc(Path(tmp), upstream_text)
            _changes, missing, stats = editor.migrate_profile(profile, [upstream])
            row = next(p for p in missing
                       if p.cmd == "CLUB_SHORT_NAME_CHANGE" and p.id == "40")
            self.assertFalse(row.checked)
            self.assertIn("Not present in the new files", row.note)
            self.assertEqual(stats["missing"], 1)

    def test_a_recorded_addition_still_carries_forward_as_an_addition(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # Club 10's 3-letter code was added by the user; the new files
            # don't have one either, so this still proposes to add it, ticked.
            upstream = self._upstream_doc(Path(tmp), self.OLD)
            _changes, missing, _stats = editor.migrate_profile(profile, [upstream])
            row = next(p for p in missing if p.cmd == "CLUB_3LETTER_NAME_CHANGE" and p.id == "10")
            self.assertTrue(row.checked)
            self.assertEqual(row.new, "ALP")
            self.assertIn("Added line", row.note)

    def test_an_unsaved_edit_on_the_upstream_line_leaves_the_proposal_unticked(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            upstream = self._upstream_doc(Path(tmp), self.OLD)
            # Mark edits club 10 in the new file before Migrate; the unsaved
            # edit would be overwritten, so the migration leaves it unticked.
            editor.try_set_name(
                next(e for e in upstream.names() if e.id == "10" and e.cmd == "CLUB_NAME_CHANGE"),
                "Alpha Something")
            changes, _missing, stats = editor.migrate_profile(profile, [upstream])
            row = next(p for p in changes if p.id == "10")
            self.assertFalse(row.checked)
            self.assertIn("Unsaved edit", row.note)
            self.assertGreaterEqual(stats["blocked"], 1)

    def test_a_repeated_key_is_classified_from_every_line_in_any_order(self):
        """A key on more than one line fails the whole proposal if any line is in conflict,
        whatever the order of the lines (reuses the Session 9 rule)."""
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # Two "20" lines upstream, in both orders; the second has drifted.
            doubled = (
                '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'
                '"CLUB_NAME_CHANGE"\t20\t"Beta Rovers"\t""\n'
                '"CLUB_NAME_CHANGE"\t20\t"Beta Athletic"\t""\n'
                '"CLUB_NAME_CHANGE"\t30\t"Gamma Town"\t""\n'
                '"CLUB_SHORT_NAME_CHANGE"\t40\t"Delta FC"\t""\n'
            )
            upstream = self._upstream_doc(Path(tmp), doubled)
            changes, _missing, _stats = editor.migrate_profile(profile, [upstream])
            row = next(p for p in changes if p.id == "20")
            self.assertFalse(row.checked)
            self.assertIn("Upstream changed since recorded", row.note)

            # Reverse the duplicate order; still unticked.
            reversed_text = (
                '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'
                '"CLUB_NAME_CHANGE"\t20\t"Beta Athletic"\t""\n'
                '"CLUB_NAME_CHANGE"\t20\t"Beta Rovers"\t""\n'
                '"CLUB_NAME_CHANGE"\t30\t"Gamma Town"\t""\n'
                '"CLUB_SHORT_NAME_CHANGE"\t40\t"Delta FC"\t""\n'
            )
            upstream2 = self._upstream_doc(Path(tmp) / "r", reversed_text)
            changes2, _missing2, _stats2 = editor.migrate_profile(profile, [upstream2])
            row2 = next(p for p in changes2 if p.id == "20")
            self.assertFalse(row2.checked)
            self.assertIn("Upstream changed since recorded", row2.note)

    def test_describe_profile_migration_counts_every_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            # Mix: one unchanged, one conflict, one already-preferred, one missing.
            upstream_text = (
                '"CLUB_NAME_CHANGE"\t10\t"Alpha United"\t""\n'       # unchanged
                '"CLUB_NAME_CHANGE"\t20\t"Beta Athletic"\t""\n'      # conflict
                '"CLUB_NAME_CHANGE"\t30\t"Gamma"\t""\n'              # already preferred
                # Club 40 short omitted -> missing
            )
            upstream = self._upstream_doc(Path(tmp), upstream_text)
            _changes, _missing, stats = editor.migrate_profile(profile, [upstream])
            summary = editor.describe_profile_migration(profile, stats)
            self.assertIn("5 spelling(s) in Mine", summary)
            self.assertIn("ticked to carry forward", summary)
            self.assertIn("Nothing is written until you Save or Deploy", summary)

    def test_apply_the_ticked_migration_is_one_undo_step(self):
        """The migration applies as one Operation, so Undo takes it back as one step."""
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._recorded(Path(tmp))
            upstream = self._upstream_doc(Path(tmp), self.OLD)
            changes, missing, _stats = editor.migrate_profile(profile, [upstream])
            with editor.Operation("migrate") as op:
                before = [(entry.id, entry.cmd, entry.name) for entry in upstream.names()]
                editor.apply_profile_proposals(profile.name, changes, missing, [upstream])
                after = [(entry.id, entry.cmd, entry.name) for entry in upstream.names()]
            self.assertNotEqual(before, after)
            op.undo()
            restored = [(entry.id, entry.cmd, entry.name) for entry in upstream.names()]
            self.assertEqual(before, restored)
            op.redo()
            re_applied = [(entry.id, entry.cmd, entry.name) for entry in upstream.names()]
            self.assertEqual(after, re_applied)


class Session12Window(unittest.TestCase):
    """Session 12 window glue: the Migrate action, the selector label, the dialog."""

    def test_the_version_selector_shows_the_xml_identity_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_root = Path(tmp)
            for folder_name in ("2600", "2700"):
                version = db_root / folder_name
                (version / "lnc" / "all").mkdir(parents=True)
                for name in editor.NAME_FILES:
                    (version / "lnc" / "all" / name).write_bytes(b"\xef\xbb\xbf")
                fm_folder = version / f"{folder_name}_fm"
                fm_folder.mkdir()
                (fm_folder / f"{folder_name}_fm.xml").write_text(
                    f'<record>'
                    f'  <string id="name" value="Football Manager '
                    f'{27 if folder_name == "2700" else 26}"/>'
                    f'  <string id="version" value='
                    f'"{27 if folder_name == "2700" else 26}.0.0"/>'
                    f'</record>', encoding="utf-8")
            with mock.patch.object(editor, "GAME_DB_ROOT", db_root):
                win = make_window(self)
                try:
                    win.refresh_versions()
                    texts = [win.version_box.itemText(i)
                             for i in range(win.version_box.count())]
                    self.assertEqual(texts, ["FM26 26.0.0 (2600)", "FM27 27.0.0 (2700)"])
                finally:
                    close_window(win)

    def test_migrate_from_new_files_opens_the_preview(self):
        from PySide6.QtWidgets import QDialog

        with tempfile.TemporaryDirectory() as tmp:
            # A profile with baselines matching the upstream so Migrate has
            # something to show as ticked ("Carries forward").
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            club = work / "FM27_Club_Names.lnc"
            write_lnc(club, Session12Migration.OLD)
            doc = editor.LncDoc(club)
            rows = {entry.id: entry for entry in doc.names()
                    if entry.cmd == "CLUB_NAME_CHANGE"}
            editor.try_set_name(rows["10"], "Alpha United FC")
            with mock.patch.object(editor, "PROFILE_ROOT", root / "profiles"):
                profile = editor.create_profile("Mine", "", root / "profiles")
                editor.record_edits(profile, [doc])
                editor.save_profile(profile, root / "profiles")
                win = make_window(self)
                try:
                    win.refresh_profiles(select_file=profile.path.name)
                    # Load the "new" files (same bytes as the recorded source).
                    upstream = root / "upstream" / "FM27_Club_Names.lnc"
                    upstream.parent.mkdir()
                    write_lnc(upstream, Session12Migration.OLD)
                    win.load([str(upstream)])
                    seen = []
                    with mock.patch.object(QDialog, "exec",
                                           lambda d: seen.append(d) or 0):
                        win.migrate_act.trigger()
                    self.assertEqual(len(seen), 1)
                    dialog = seen[0]
                    self.assertEqual(dialog.windowTitle(), "Migrate profile: Mine")
                    self.assertIn("ticked to carry forward",
                                  dialog.summary.text())
                finally:
                    close_window(win)

    def test_migrate_tells_the_user_to_open_the_new_files_first_when_none_are_open(self):
        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            work.mkdir()
            club = work / "FM27_Club_Names.lnc"
            write_lnc(club, Session12Migration.OLD)
            doc = editor.LncDoc(club)
            with mock.patch.object(editor, "PROFILE_ROOT", root / "profiles"):
                profile = editor.create_profile("Mine", "", root / "profiles")
                editor.record_edits(profile, [doc])
                editor.save_profile(profile, root / "profiles")
                win = make_window(self)
                try:
                    win.refresh_profiles(select_file=profile.path.name)
                    with mock.patch.object(QMessageBox, "information") as told:
                        win.migrate_act.trigger()
                    self.assertIn("Open the new files first",
                                  told.call_args.args[2])
                finally:
                    close_window(win)

    def test_the_migrate_action_waits_for_a_job(self):
        """Migrate writes no files itself but opens docs; it belongs with the
        other profile actions in busy_actions, so it is switched off while
        a load or game check runs."""
        win = make_window(self)
        try:
            self.assertIn(win.migrate_act, win.busy_actions)
        finally:
            close_window(win)


class Session13ReviewHints(unittest.TestCase):
    """Session 13: local list of suspicious baselines, shown in the inspector."""

    def test_the_wolverhamption_hint_names_the_disk_spelling_and_the_typo(self):
        note = editor.review_hint("CLUB_NAME_CHANGE", "740", "")
        self.assertTrue(note)
        self.assertIn("Wolverhamption", note)
        self.assertIn("Wolverhampton", note)
        self.assertIn("never applies hints automatically", note)

    def test_review_hint_is_empty_for_a_key_with_no_hint(self):
        self.assertEqual(editor.review_hint("CLUB_NAME_CHANGE", "1", ""), "")
        self.assertEqual(editor.review_hint("COMP_LONG_NAME_CHANGE", "740", ""), "")

    def test_describe_fields_carries_the_hint_through_to_the_inspector(self):
        """The hint lives on FieldView, so show_inspector reads it alongside
        the usual field metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            club = Path(tmp) / "FM27_Club_Names.lnc"
            write_lnc(club, '"CLUB_NAME_CHANGE"\t740\t"Wolverhamption Wanderers"\t""\n')
            doc = editor.LncDoc(club)
            entity = editor.build_entities([doc])[0]
            views = editor.describe_fields(entity)
            long_view = next(view for view in views if view.slot == "long")
            self.assertIn("Wolverhampton", long_view.hint)


class Session13Overrides(unittest.TestCase):
    """Session 13: the cross-file override inspector.

    find_overrides scans every .lnc under <version>/lnc/ and groups matching
    rows by (command, language), marking a group competing when the values
    disagree.
    """

    def _version_tree(self, root: Path, files: dict[str, str]) -> Path:
        """A <version>/lnc/all/<...lnc> fixture. ``files`` is {name: text}."""
        version = root / "db" / "2700"
        (version / "lnc" / "all").mkdir(parents=True)
        for name, text in files.items():
            write_lnc(version / "lnc" / "all" / name, text)
        return version

    def test_find_overrides_lists_identical_values_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), {
                "FM27_Club_Names.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolves"\t""\n',
                "chinese.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolves"\t""\n',
            })
            overrides = editor.find_overrides("club", "740", version)
            self.assertEqual(len(overrides), 2)
            for override in overrides:
                self.assertEqual(override.state, "identical")
                self.assertEqual(override.command, "CLUB_NAME_CHANGE")
                self.assertEqual(override.name, "Wolves")

    def test_find_overrides_flags_competing_values_in_the_same_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), {
                "FM27_Club_Names.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolverhampton Wanderers"\t""\n',
                "unofficial.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolves FC"\t""\n',
            })
            overrides = editor.find_overrides("club", "740", version)
            self.assertEqual(len(overrides), 2)
            states = {override.state for override in overrides}
            self.assertEqual(states, {"competing"})
            names = sorted(override.name for override in overrides)
            self.assertEqual(names, ["Wolverhampton Wanderers", "Wolves FC"])

    def test_find_overrides_groups_by_command_and_language(self):
        """Different commands (long vs short) are separate groups; a long-name
        disagreement does not make the short name competing."""
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), {
                "FM27_Club_Names.lnc":
                    '"CLUB_NAME_CHANGE"\t10\t"Alpha Alpha"\t""\n'
                    '"CLUB_SHORT_NAME_CHANGE"\t10\t"Alpha"\t""\n',
                "extra.lnc":
                    '"CLUB_NAME_CHANGE"\t10\t"Alpha Beta"\t""\n'
                    '"CLUB_SHORT_NAME_CHANGE"\t10\t"Alpha"\t""\n',
            })
            overrides = editor.find_overrides("club", "10", version)
            long_rows = [o for o in overrides if o.command == "CLUB_NAME_CHANGE"]
            short_rows = [o for o in overrides if o.command == "CLUB_SHORT_NAME_CHANGE"]
            self.assertEqual({o.state for o in long_rows}, {"competing"})
            self.assertEqual({o.state for o in short_rows}, {"identical"})

    def test_find_overrides_ignores_ids_that_do_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), {
                "FM27_Club_Names.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolves"\t""\n'
                    '"CLUB_NAME_CHANGE"\t1\t"Arsenal"\t""\n',
            })
            overrides = editor.find_overrides("club", "740", version)
            self.assertEqual([o.id for o in overrides], ["740"])

    def test_find_overrides_skips_files_that_cannot_be_decoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), {
                "FM27_Club_Names.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolves"\t""\n',
            })
            bad = version / "lnc" / "all" / "broken.lnc"
            bad.write_bytes(b"\xff\xfe\xff\xff")   # looks UTF-16, truncated
            overrides = editor.find_overrides("club", "740", version)
            # The broken file is skipped; the readable one still contributes.
            self.assertEqual(len(overrides), 1)
            self.assertEqual(overrides[0].name, "Wolves")

    def test_find_overrides_returns_empty_for_an_unknown_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            version = self._version_tree(Path(tmp), {
                "FM27_Club_Names.lnc":
                    '"CLUB_NAME_CHANGE"\t740\t"Wolves"\t""\n',
            })
            self.assertEqual(editor.find_overrides("no-such-family", "740", version), [])

    def test_the_grid_menu_carries_the_overrides_action(self):
        win = make_window(self)
        try:
            self.assertIn(win.overrides_act, win.grid_menu().actions())
            self.assertIn(win.overrides_act, win.busy_actions)
        finally:
            close_window(win)

    def test_show_overrides_opens_the_dialog_on_the_selected_entity(self):
        from PySide6.QtWidgets import QDialog, QTableWidget

        with tempfile.TemporaryDirectory() as tmp:
            version = Session13Overrides._version_tree(
                self, Path(tmp), {
                    "FM27_Club_Names.lnc":
                        '"CLUB_NAME_CHANGE"\t740\t"Wolverhampton"\t""\n',
                    "other.lnc":
                        '"CLUB_NAME_CHANGE"\t740\t"Wolves FC"\t""\n',
                })
            # Load the club file so the selection has an entity to run on.
            club = version / "lnc" / "all" / "FM27_Club_Names.lnc"
            with mock.patch.object(editor, "GAME_DB_ROOT", version.parent):
                win = make_window(self)
                try:
                    win.load([str(club)])
                    self.assertTrue(win.entity_model.rows)
                    # Refresh once GAME_DB_ROOT is pointed at the fixture.
                    win.refresh_versions()
                    win.version_box.setCurrentIndex(
                        win.version_box.findData(str(version)))
                    index = win.entity_proxy.index(0, 0)
                    win.entity_view.setCurrentIndex(index)
                    seen = []
                    with mock.patch.object(QDialog, "exec",
                                           lambda d: seen.append(d) or 0):
                        win.show_overrides()
                    self.assertEqual(len(seen), 1)
                    dialog = seen[0]
                    table = dialog.findChild(QTableWidget)
                    self.assertIsNotNone(table)
                    # The scan runs on self.jobs; with JOBS_INLINE it finishes
                    # before exec returns in the test, so the table is filled.
                    self.assertEqual(table.rowCount(), 2)
                    self.assertIn("disagree", dialog.summary.text())
                finally:
                    close_window(win)


class Session13Rules(unittest.TestCase):
    """Session 13: saved bulk-tool rules in state/rules.json."""

    def test_default_rules_hold_the_built_in_sponsor_and_small_word_lists(self):
        rules = editor.Rules()
        self.assertEqual(tuple(rules.sponsors), editor.STARTER_SPONSORS)
        self.assertEqual(sorted(rules.small_words), sorted(editor.SMALL_WORDS))

    def test_round_trip_through_save_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = editor.Rules(sponsors=["My Sponsor"], small_words=["de"])
            editor.save_rules(saved, root)
            loaded, problem = editor.read_rules(root)
            self.assertEqual(problem, "")
            self.assertEqual(loaded.sponsors, ["My Sponsor"])
            self.assertEqual(loaded.small_words, ["de"])
            self.assertEqual(saved.to_bytes(),
                             (root / editor.RULES_FILE).read_bytes())

    def test_read_rules_missing_file_returns_defaults_and_no_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules, problem = editor.read_rules(Path(tmp))
            self.assertEqual(problem, "")
            self.assertEqual(tuple(rules.sponsors), editor.STARTER_SPONSORS)

    def test_read_rules_names_a_damaged_file_and_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / editor.RULES_FILE
            path.write_bytes(b"not json at all")
            rules, problem = editor.read_rules(root)
            self.assertTrue(problem)
            self.assertIn(str(path), problem)
            self.assertIn("not readable JSON", problem)
            self.assertEqual(tuple(rules.sponsors), editor.STARTER_SPONSORS)
            # The file is not written over.
            self.assertEqual(path.read_bytes(), b"not json at all")

    def test_read_rules_accepts_a_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / editor.RULES_FILE).write_bytes(
                b"\xef\xbb\xbf" + b'{"format":"fm-name-rules","version":1,'
                                  b'"sponsors":["Alpha"],"small_words":[]}\n')
            rules, problem = editor.read_rules(root)
            self.assertEqual(problem, "")
            self.assertEqual(rules.sponsors, ["Alpha"])

    def test_save_rules_refuses_to_write_over_a_damaged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / editor.RULES_FILE).write_bytes(b"not json")
            with self.assertRaises(editor.DamagedFileError) as ctx:
                editor.save_rules(editor.Rules(sponsors=["X"]), root)
            self.assertEqual(ctx.exception.path, root / editor.RULES_FILE)
            # And the byte content is still as it was.
            self.assertEqual((root / editor.RULES_FILE).read_bytes(), b"not json")

    def test_window_loads_saved_rules_on_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            editor.save_rules(editor.Rules(sponsors=["MyBrand"]), root)
            with mock.patch.object(editor, "STATE_ROOT", root):
                win = make_window(self)
                try:
                    self.assertEqual(win.rules.sponsors, ["MyBrand"])
                    self.assertEqual(win.rules_problem, "")
                    self.assertFalse(win.rules_label.isVisible())
                finally:
                    close_window(win)

    def test_window_names_a_damaged_rules_file_in_the_status_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / editor.RULES_FILE).write_bytes(b"not json")
            with mock.patch.object(editor, "STATE_ROOT", root):
                win = make_window(self)
                try:
                    self.assertTrue(win.rules_problem)
                    self.assertTrue(win.rules_label.isVisible())
                    self.assertIn("Rules not saved", win.rules_label.text())
                    # And keep_rules refuses to save for the rest of the run,
                    # so a hand-fix meanwhile does not get silently replaced.
                    msg = win.keep_rules(editor.Rules(sponsors=["X"]))
                    self.assertTrue(msg)
                finally:
                    close_window(win)

    def test_bulk_dialog_reads_the_saved_sponsor_list(self):
        from PySide6.QtWidgets import QDialog

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            editor.save_rules(editor.Rules(sponsors=["Mega Sponsor"]), root)
            # Open a club to give BulkDialog something to operate on.
            club = Path(tmp) / "FM27_Club_Names.lnc"
            write_lnc(club, '"CLUB_NAME_CHANGE"\t1\t"Alpha FC"\t""\n')
            with mock.patch.object(editor, "STATE_ROOT", root):
                win = make_window(self)
                try:
                    win.load([str(club)])
                    seen = []
                    with mock.patch.object(QDialog, "exec",
                                           lambda d: seen.append(d) or 0):
                        win.open_bulk()
                    dialog = seen[0]
                    # The Bulk dialog's sponsor box starts from the saved list.
                    self.assertEqual(
                        dialog.sponsor_box.toPlainText().splitlines(),
                        ["Mega Sponsor"])
                    # The Save-as-default button is on, so the user can keep
                    # whatever they type here for next time.
                    self.assertTrue(dialog.save_rules_btn.isEnabled())
                finally:
                    close_window(win)


class Session13Responsiveness(unittest.TestCase):
    """Session 13: ImportDialog.compare runs on the window's worker.

    The reading and build_proposals step was timed at 773 ms on this PC for
    both FM27 files; moving it off the GUI thread keeps the window drawn.
    """

    def test_import_dialog_runs_compare_through_the_window_jobs(self):
        from PySide6.QtWidgets import QDialog

        with tempfile.TemporaryDirectory() as tmp:
            club = Path(tmp) / "FM27_Club_Names.lnc"
            write_lnc(club,
                      '"CLUB_NAME_CHANGE"\t1\t"Alpha"\t""\n'
                      '"CLUB_NAME_CHANGE"\t2\t"Beta"\t""\n')
            older = Path(tmp) / "older" / "FM27_Club_Names.lnc"
            older.parent.mkdir()
            write_lnc(older,
                      '"CLUB_NAME_CHANGE"\t1\t"Alpha United"\t""\n'
                      '"CLUB_NAME_CHANGE"\t2\t"Beta Rovers"\t""\n')
            win = make_window(self)
            try:
                win.load([str(club)])
                seen = []
                with mock.patch.object(QDialog, "exec",
                                       lambda d: seen.append(d) or 0):
                    win.import_old()
                dialog = seen[0]
                self.assertIsNotNone(dialog.jobs)
                # Point the dialog at the older file and click Compare.
                dialog.old_paths = [str(older)]
                dialog.compare_btn.setEnabled(True)
                dialog.compare()
                # JOBS_INLINE in setUpModule runs the work at once, so the
                # table is filled by the time compare() returns.
                self.assertTrue(dialog.compare_btn.isEnabled())   # re-enabled
                self.assertTrue(dialog.apply_btn.isEnabled())
                self.assertEqual(dialog.change_model.rowCount(), 2)
                self.assertIn("read from the older files", dialog.summary.text())
            finally:
                close_window(win)


if __name__ == "__main__":
    unittest.main()
