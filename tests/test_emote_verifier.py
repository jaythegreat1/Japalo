import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.emote_catalog import verify_emotes


class EmoteVerifierStateTests(unittest.TestCase):
    def test_runtime_catalog_entries_are_added_to_probe_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "emotes.json"
            runtime_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Wave",
                            "id": "emote-wave",
                            "rarity": "common",
                            "duration_seconds": 2.7,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with patch.object(verify_emotes, "VERIFY_EXISTING", True), patch.object(
                verify_emotes, "RUNTIME_CATALOG_PATH", runtime_path
            ):
                result = verify_emotes._include_runtime_catalog([])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["catalog_item_id"], "emote-wave")
        self.assertEqual(result[0]["source"], "runtime_catalog")
        self.assertEqual(result[0]["duration_seconds"], 2.7)

    def test_existing_runtime_entries_are_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "emotes.json"
            runtime_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Wave",
                            "id": "emote-wave",
                            "rarity": "common",
                            "duration_seconds": 2.7,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            candidates = [
                {
                    "name": "Wave",
                    "rarity": "common",
                    "catalog_item_id": "emote-wave",
                    "status": "id_confirmed",
                    "runtime_check": "accepted",
                }
            ]
            with patch.object(verify_emotes, "VERIFY_EXISTING", True), patch.object(
                verify_emotes, "RUNTIME_CATALOG_PATH", runtime_path
            ):
                result = verify_emotes._include_runtime_catalog(candidates)

        self.assertEqual(result[0]["status"], "pending_verification")
        self.assertEqual(result[0]["runtime_check"], "not_checked")

    def test_unknown_error_text_is_not_treated_as_an_invalid_id(self) -> None:
        self.assertFalse(verify_emotes._looks_explicitly_invalid("connection timeout"))
        self.assertFalse(verify_emotes._looks_purchase_related("unknown item"))

    def test_only_explicit_invalid_runtime_ids_are_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "emotes.json"
            runtime_path.write_text(
                json.dumps(
                    [
                        {"id": "keep", "name": "Keep"},
                        {"id": "remove", "name": "Remove"},
                    ]
                ),
                encoding="utf-8",
            )
            candidates = [
                {
                    "catalog_item_id": "remove",
                    "source": "runtime_catalog",
                    "status": "id_invalid",
                },
                {
                    "catalog_item_id": "keep",
                    "source": "runtime_catalog",
                    "status": "requires_purchase",
                },
            ]
            with patch.object(
                verify_emotes, "RUNTIME_CATALOG_PATH", runtime_path
            ):
                removed = verify_emotes._prune_invalid_runtime_entries(candidates)
            remaining = json.loads(runtime_path.read_text(encoding="utf-8"))

        self.assertEqual(removed, 1)
        self.assertEqual([entry["id"] for entry in remaining], ["keep"])


if __name__ == "__main__":
    unittest.main()