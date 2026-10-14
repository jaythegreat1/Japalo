import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.emote_catalog import fetch_catalog
from tools.emote_catalog.fetch_catalog import (
    EXCLUDED_EMOTE_NAMES,
    _filter_by_known_id_prefix,
    _find_category_field,
    _is_available,
    _known_id_prefixes,
    _normalize_name,
    _release_state,
)


class FetchCatalogTests(unittest.TestCase):
    def test_missing_release_metadata_is_not_treated_as_unreleased(self) -> None:
        self.assertTrue(_is_available({"item_id": "emote-wave"}))

    def test_explicit_unavailable_flag_is_excluded(self) -> None:
        self.assertFalse(_is_available({"available": False}))
        self.assertFalse(_is_available({"is_released": False}))

    def test_future_release_date_is_excluded(self) -> None:
        now = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
        self.assertFalse(
            _is_available(
                {"release_date": "2026-10-01T00:00:00+00:00"},
                now=now,
            )
        )

    def test_past_release_date_is_available(self) -> None:
        now = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
        self.assertTrue(
            _is_available(
                {"release_date": "2026-09-01T00:00:00+00:00"},
                now=now,
            )
        )

    def test_release_state_preserves_unknown_metadata(self) -> None:
        now = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
        self.assertEqual(
            _release_state({"item_id": "emote-wave"}, now=now), "unknown"
        )

    def test_release_state_distinguishes_future_and_explicit_unreleased(self) -> None:
        now = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
        self.assertEqual(
            _release_state(
                {"release_date": "2026-10-01T00:00:00+00:00"}, now=now
            ),
            "future",
        )
        self.assertEqual(_release_state({"available": False}, now=now), "unreleased")

    def test_category_field_detection_prefers_documented_field(self) -> None:
        self.assertEqual(
            _find_category_field(
                [
                    {"category": "watch", "type": "clothing"},
                    {"category": "emote", "type": "clothing"},
                ]
            ),
            "category",
        )

    def test_only_the_supplied_legendary_names_are_excluded(self) -> None:
        self.assertIn("hero entrance", EXCLUDED_EMOTE_NAMES)
        self.assertEqual(_normalize_name("  Hero   Entrance "), "hero entrance")
        self.assertNotIn("some other legendary", EXCLUDED_EMOTE_NAMES)

    def _with_known_catalog(self, entries):
        tmp_dir = tempfile.mkdtemp()
        path = Path(tmp_dir) / "emotes.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return patch.object(fetch_catalog, "KNOWN_CATALOG_PATH", path)

    def test_known_id_prefixes_handles_hyphen_and_underscore_ids(self) -> None:
        with self._with_known_catalog(
            [
                {"id": "emoji-angry"},
                {"id": "dance-macarena"},
                {"id": "idle_zombie"},
            ]
        ):
            self.assertEqual(
                _known_id_prefixes(), {"emoji", "dance", "idle"}
            )

    def test_known_id_prefixes_empty_when_no_catalog(self) -> None:
        with self._with_known_catalog([]):
            self.assertEqual(_known_id_prefixes(), set())

    def test_filter_by_known_id_prefix_matches_both_separator_styles(self) -> None:
        with self._with_known_catalog([{"id": "idle-sad"}, {"id": "emoji-angry"}]):
            items = [
                {"item_id": "idle-newpose", "name": "New Pose"},
                {"item_id": "idle_newpose2", "name": "New Pose 2"},
                {"item_id": "emoji-mindblown", "name": "Mind Blown"},
                {"item_id": "shirt-red", "name": "Red Shirt"},
                {"name": "no id field"},
            ]
            matched = _filter_by_known_id_prefix(items)
            self.assertEqual(
                {item["item_id"] for item in matched},
                {"idle-newpose", "idle_newpose2", "emoji-mindblown"},
            )

    def test_filter_by_known_id_prefix_returns_nothing_without_known_catalog(
        self,
    ) -> None:
        with self._with_known_catalog([]):
            items = [{"item_id": "emoji-angry"}]
            self.assertEqual(_filter_by_known_id_prefix(items), [])


if __name__ == "__main__":
    unittest.main()