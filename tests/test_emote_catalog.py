import json
import tempfile
import unittest
from pathlib import Path

from highrise_bot.emotes import load_catalog


class EmoteCatalogTests(unittest.TestCase):
    def test_catalog_numbers_entries_in_file_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emotes.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Wave",
                            "id": "emote-wave",
                            "rarity": "common",
                            "duration_seconds": 2.5,
                        },
                        {
                            "name": "Dance",
                            "id": "dance-one",
                            "rarity": "epic",
                            "duration_seconds": 10,
                        },
                    ]
                ),
                encoding="utf-8",
            )
            catalog = load_catalog(path)

        self.assertEqual(len(catalog), 2)
        self.assertEqual(catalog.get_by_number(1).emote_id, "emote-wave")
        self.assertEqual(catalog.get_by_number(2).name, "Dance")
        self.assertEqual(catalog.known_ids(), frozenset({"emote-wave", "dance-one"}))

    def test_legendary_and_missing_duration_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emotes.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Paid",
                            "id": "paid-emote",
                            "rarity": "legendary",
                            "duration_seconds": 3,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_catalog(path)

    def test_none_rarity_from_highrise_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emotes.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Tired",
                            "id": "emote-tired",
                            "rarity": "none_",
                            "duration_seconds": 4.4,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            catalog = load_catalog(path)

        self.assertEqual(catalog.get_by_number(1).rarity, "none_")

    def test_unknown_rarity_marker_is_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emotes.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Unresolved",
                            "id": "emote-unresolved",
                            "rarity": "unknown",
                            "duration_seconds": 3,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            catalog = load_catalog(path)

        self.assertEqual(catalog.get_by_number(1).rarity, "unknown")

    def test_pages_keep_duration_hidden_from_users(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emotes.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Wave",
                            "id": "emote-wave",
                            "rarity": "common",
                            "duration_seconds": 2.5,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            page = load_catalog(path).pages()[0]

        self.assertEqual(page, "1. Wave [common]")
        self.assertNotIn("2.5", page)

    def test_filter_and_search_keep_original_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emotes.json"
            path.write_text(
                json.dumps(
                    [
                        {"name": "Wave", "id": "emote-wave", "rarity": "common", "duration_seconds": 2},
                        {"name": "Rare Wave", "id": "emote-rare-wave", "rarity": "rare", "duration_seconds": 3},
                    ]
                ),
                encoding="utf-8",
            )
            catalog = load_catalog(path)

        self.assertEqual(catalog.filter(rarity="rare"), [(2, catalog.get_by_number(2))])
        self.assertEqual(catalog.filter(query="wave")[0][0], 1)

if __name__ == "__main__":
    unittest.main()