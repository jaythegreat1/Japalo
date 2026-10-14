import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.emote_catalog import catalog_audit


class CatalogAuditTests(unittest.TestCase):
    def test_report_counts_observed_states_without_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = root / "candidates.json"
            runtime = root / "emotes.json"
            audit = root / "audit.json"
            candidates.write_text(
                json.dumps(
                    [
                        {
                            "name": "Rare",
                            "catalog_item_id": "rare",
                            "rarity": "rare",
                            "source_check": "verified",
                            "release_state": "available",
                            "status": "verified",
                        },
                        {
                            "name": "Future",
                            "catalog_item_id": "future",
                            "rarity": "epic",
                            "source_check": "verified",
                            "release_state": "future",
                            "status": "future",
                        },
                        {
                            "name": "Locked",
                            "catalog_item_id": "locked",
                            "rarity": "epic",
                            "source_check": "verified",
                            "release_state": "available",
                            "status": "requires_purchase",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            runtime.write_text("[]", encoding="utf-8")
            audit.write_text(
                json.dumps(
                    {
                        "checked_at": "2026-09-26T00:00:00+00:00",
                        "entries": [
                            {
                                "id": "rare",
                                "rarity": "rare",
                                "status": "verified",
                            },
                            {
                                "id": "locked",
                                "rarity": "epic",
                                "status": "requires_purchase",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(catalog_audit, "CANDIDATES_PATH", candidates), patch.object(
                catalog_audit, "RUNTIME_PATH", runtime
            ), patch.object(catalog_audit, "AUDIT_PATH", audit):
                report = catalog_audit.build_report()

        self.assertEqual(report["total_discovered"], 3)
        self.assertEqual(report["verified_real_emotes"], 1)
        self.assertEqual(report["rare"], 1)
        self.assertEqual(report["epic"], 0)
        self.assertEqual(report["future"], 1)
        self.assertEqual(report["requires_purchase"], 1)


if __name__ == "__main__":
    unittest.main()