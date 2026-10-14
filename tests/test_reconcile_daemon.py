import os
import unittest
from unittest.mock import MagicMock, patch

from tools.emote_catalog import reconcile_daemon


class _StopLoop(Exception):
    """Raised from the mocked time.sleep() to escape the daemon's
    otherwise-infinite retry loop after exactly one cycle."""


class ReconcileDaemonEnvTests(unittest.TestCase):
    def test_probe_subprocess_always_gets_verify_and_prune_enabled(self) -> None:
        env = {
            "EMOTE_RECONCILE_ENABLED": "true",
            "EMOTE_RECONCILE_CONFIRM": "DEDICATED_TEST_ROOM",
            "EMOTE_RECONCILE_ROOM_ID": "test-verification-room",
            "EMOTE_RECONCILE_BOT_TOKEN": "test-token",
            "HIGHRISE_ROOM_ID": "prod-room",
            "EMOTE_RECONCILE_INTERVAL_SECONDS": "900",
        }
        completed = MagicMock(returncode=0)

        with patch.dict(os.environ, env, clear=True), patch.object(
            reconcile_daemon.subprocess, "run", return_value=completed
        ) as mock_run, patch.object(
            reconcile_daemon.time, "sleep", side_effect=_StopLoop
        ):
            with self.assertRaises(_StopLoop):
                reconcile_daemon.main()

        # First call is the source refresh, second is the live probe that
        # actually re-checks/prunes the runtime catalog.
        self.assertEqual(mock_run.call_count, 2)
        _, probe_kwargs = mock_run.call_args_list[1]
        probe_env = probe_kwargs["env"]

        # This is the regression this test exists for: these two flags are
        # what makes the daemon re-verify the existing catalog and prune
        # entries Highrise now rejects, instead of silently no-op'ing on
        # everything already in config/emotes.json.
        self.assertEqual(probe_env["EMOTE_VERIFY_EXISTING"], "true")
        self.assertEqual(probe_env["EMOTE_VERIFY_PRUNE_INVALID"], "true")

        # And it must never flip on auto-buy as a side effect of that.
        self.assertEqual(probe_env["EMOTE_VERIFY_AUTO_BUY"], "false")

    def test_auto_merge_is_off_by_default(self) -> None:
        env = {
            "EMOTE_RECONCILE_ENABLED": "true",
            "EMOTE_RECONCILE_CONFIRM": "DEDICATED_TEST_ROOM",
            "EMOTE_RECONCILE_ROOM_ID": "test-verification-room",
            "EMOTE_RECONCILE_BOT_TOKEN": "test-token",
            "HIGHRISE_ROOM_ID": "prod-room",
            "EMOTE_RECONCILE_INTERVAL_SECONDS": "900",
        }
        completed = MagicMock(returncode=0)

        with patch.dict(os.environ, env, clear=True), patch.object(
            reconcile_daemon.subprocess, "run", return_value=completed
        ) as mock_run, patch.object(
            reconcile_daemon.time, "sleep", side_effect=_StopLoop
        ):
            with self.assertRaises(_StopLoop):
                reconcile_daemon.main()

        # No EMOTE_RECONCILE_AUTO_MERGE set: only refresh + probe run, same
        # as before this feature existed. The daemon must not start writing
        # to config/emotes.json unless an operator explicitly opts in.
        self.assertEqual(mock_run.call_count, 2)

    def test_auto_merge_runs_merge_catalog_after_a_clean_probe(self) -> None:
        env = {
            "EMOTE_RECONCILE_ENABLED": "true",
            "EMOTE_RECONCILE_CONFIRM": "DEDICATED_TEST_ROOM",
            "EMOTE_RECONCILE_ROOM_ID": "test-verification-room",
            "EMOTE_RECONCILE_BOT_TOKEN": "test-token",
            "HIGHRISE_ROOM_ID": "prod-room",
            "EMOTE_RECONCILE_INTERVAL_SECONDS": "900",
            "EMOTE_RECONCILE_AUTO_MERGE": "true",
        }
        completed = MagicMock(returncode=0)

        with patch.dict(os.environ, env, clear=True), patch.object(
            reconcile_daemon.subprocess, "run", return_value=completed
        ) as mock_run, patch.object(
            reconcile_daemon.time, "sleep", side_effect=_StopLoop
        ):
            with self.assertRaises(_StopLoop):
                reconcile_daemon.main()

        # refresh, probe, and now merge_catalog.py too.
        self.assertEqual(mock_run.call_count, 3)
        merge_args, merge_kwargs = mock_run.call_args_list[2]
        self.assertIn("merge_catalog.py", str(merge_args[0][-1]))
        self.assertEqual(
            merge_kwargs["env"]["EMOTE_MERGE_CANDIDATES_PATH"],
            str(reconcile_daemon.FRESH_CANDIDATES),
        )

    def test_auto_merge_is_skipped_when_probe_fails(self) -> None:
        env = {
            "EMOTE_RECONCILE_ENABLED": "true",
            "EMOTE_RECONCILE_CONFIRM": "DEDICATED_TEST_ROOM",
            "EMOTE_RECONCILE_ROOM_ID": "test-verification-room",
            "EMOTE_RECONCILE_BOT_TOKEN": "test-token",
            "HIGHRISE_ROOM_ID": "prod-room",
            "EMOTE_RECONCILE_INTERVAL_SECONDS": "900",
            "EMOTE_RECONCILE_AUTO_MERGE": "true",
        }
        refresh_ok = MagicMock(returncode=0)
        probe_failed = MagicMock(returncode=1)

        with patch.dict(os.environ, env, clear=True), patch.object(
            reconcile_daemon.subprocess,
            "run",
            side_effect=[refresh_ok, probe_failed],
        ) as mock_run, patch.object(
            reconcile_daemon.time, "sleep", side_effect=_StopLoop
        ):
            with self.assertRaises(_StopLoop):
                reconcile_daemon.main()

        # A failed probe must never be followed by a merge - a bad run
        # should not touch config/emotes.json.
        self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
