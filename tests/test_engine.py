"""Release 2.1 checks for the name editor engine and a headless window smoke test.

The Steam database is only read, and only when it is present. Writes use
temporary copies.
"""
from __future__ import annotations

import os
import tempfile
import unittest
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
            stored.write_bytes(path.read_bytes())
            editor.try_set_name(doc.names()[0], "Beta")
            self.assertEqual(editor.list_archives(root / "backups"), [archive])
            diff = editor.diff_documents(doc, editor.LncDoc(stored))
            self.assertEqual(len(diff), 1)
            self.assertEqual(diff[0]["working"], "Beta")
            self.assertEqual(diff[0]["archived"], "Alpha")
            editor.restore_into(doc, stored)
            self.assertEqual(doc.path, path)
            self.assertTrue(doc.dirty)
            self.assertEqual(doc.names()[0].name, "Alpha")
            self.assertEqual(path.read_bytes(), stored.read_bytes())


class WindowSmoke(unittest.TestCase):
    def test_entity_tab_edit_and_cancelled_bulk(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            _app, win = editor.run_gui([])
        except Exception as exc:
            self.skipTest(f"Qt window could not be created: {exc}")

        def close_without_prompt():
            for doc in win.docs:
                doc.dirty = False
            win.close()

        self.addCleanup(close_without_prompt)
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


if __name__ == "__main__":
    unittest.main()
