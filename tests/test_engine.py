"""Release 2.2 checks for the name editor engine and headless window tests.

The Steam database is only read, and only when it is present. Writes use
temporary copies.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fm_name_editor as editor

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
    """Close a test window without the unsaved-changes prompt."""
    for doc in win.docs:
        doc.mark_clean()
    win.close()


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
        from PySide6.QtWidgets import QMessageBox

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
                # With the game closed, Save asks once, names the file, then writes.
                with patch.object(editor, "football_manager_running", return_value=[]):
                    win.save()
                self.assertEqual(asked.call_count, 1)
                self.assertIn(str(path), asked.call_args.args[2])
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
        from PySide6.QtWidgets import QMessageBox

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
                with patch.object(editor, "football_manager_running", return_value=[]), \
                        patch.object(QMessageBox, "question",
                                     return_value=QMessageBox.Yes) as asked, \
                        patch.object(QMessageBox, "critical") as shown, \
                        patch.object(editor.os, "replace", side_effect=failing_replace(fix)):
                    win.deploy()
            self.assertIn("one at a time", asked.call_args.args[2])
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
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        win = self._window()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mine.lnc"
            write_lnc(path, Session3Writes.CLUB)
            self.assertTrue(win.load([str(path)]))
            editor.try_set_name(win.docs[0].names()[0], "Alpha United")
            write_lnc(path, Session3Writes.CLUB.replace("Alpha", "Changed elsewhere"))
            outside = path.read_bytes()
            with patch.object(QMessageBox, "warning") as warned:
                win.save()
            self.assertEqual(warned.call_count, 1)
            self.assertIn("changed on disk", warned.call_args.args[2])
            self.assertIn(str(path), warned.call_args.args[2])
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


if __name__ == "__main__":
    unittest.main()
