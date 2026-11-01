import contextlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import companion
from experiments.key_mask_bridge import MaskTracker


class CompanionTests(unittest.TestCase):
    def test_background_reporting_writes_rotating_log_without_console(self):
        old_handlers = list(companion.LOGGER.handlers)
        companion.LOGGER.handlers.clear()
        temporary = tempfile.TemporaryDirectory()
        try:
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": temporary.name}),
                patch.object(companion.sys, "stdout", None),
            ):
                log_path = companion.configure_logging()
                companion.report("background test")
                for handler in companion.LOGGER.handlers:
                    handler.flush()

                self.assertIsNotNone(log_path)
                self.assertIn("background test", log_path.read_text(encoding="utf-8"))
        finally:
            for handler in companion.LOGGER.handlers:
                handler.close()
            companion.LOGGER.handlers[:] = old_handlers
            temporary.cleanup()

    def test_cleanup_releases_every_held_key(self):
        tracker = MaskTracker()
        tracker.update((1 << 0) | (1 << 3) | (1 << 11))

        with patch("companion.inject_key") as inject:
            companion.release_injected_keys(tracker)

        self.assertEqual(
            inject.call_args_list,
            [
                call(companion.F_VKS[1], False),
                call(companion.F_VKS[4], False),
                call(companion.F_VKS[12], False),
            ],
        )
        self.assertEqual(tracker.held, 0)

    def test_observer_cleanup_updates_state_without_injecting(self):
        tracker = MaskTracker()
        tracker.update(1)

        with patch("companion.inject_key") as inject:
            companion.release_injected_keys(tracker, observe=True)

        inject.assert_not_called()
        self.assertEqual(tracker.held, 0)

    def test_named_mutex_rejects_a_second_instance(self):
        name = rf"Local\HP460CompanionTest-{os.getpid()}"
        with patch.object(companion, "INSTANCE_MUTEX_NAME", name):
            first = companion.acquire_instance_lock()
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(companion.acquire_instance_lock())
            finally:
                kernel32, handle = first
                kernel32.CloseHandle(handle)

    def test_absent_keyboard_does_not_check_or_close_hpac_and_logs_once(self):
        args = SimpleNamespace(device_index=0, reconnect_seconds=3.0)
        missing = RuntimeError("No connected HP 460 control interface was found.")
        with (
            patch("companion.hp460.open_selected_device",
                  side_effect=[missing, missing, KeyboardInterrupt()]),
            patch("companion.close_hpac_if_running") as close_hpac,
            patch("companion.time.sleep") as sleep,
            patch("companion.report") as report,
        ):
            self.assertEqual(companion.run(args), 0)

        close_hpac.assert_not_called()
        self.assertEqual(sleep.call_count, 2)
        report.assert_called_once_with(
            "Device not ready: No connected HP 460 control interface was found.",
            error=True,
        )

    def test_busy_interface_closes_running_hpac_and_retries_immediately(self):
        args = SimpleNamespace(device_index=0, reconnect_seconds=3.0)
        busy = companion.hp460.ControlInterfaceBusyError("control interface is busy")
        with (
            patch("companion.hp460.open_selected_device",
                  side_effect=[busy, KeyboardInterrupt()]),
            patch("companion.close_hpac_if_running", return_value=True) as close_hpac,
            patch("companion.time.sleep") as sleep,
            patch("companion.report") as report,
        ):
            self.assertEqual(companion.run(args), 0)

        close_hpac.assert_called_once_with()
        sleep.assert_not_called()
        self.assertEqual(
            report.call_args_list,
            [
                call("Device not ready: control interface is busy", error=True),
                call("Closed HP Accessory Center; retrying the keyboard now."),
            ],
        )

    def test_busy_interface_without_hpac_waits_and_logs_once(self):
        args = SimpleNamespace(device_index=0, reconnect_seconds=3.0)
        busy = companion.hp460.ControlInterfaceBusyError("control interface is busy")
        with (
            patch("companion.hp460.open_selected_device",
                  side_effect=[busy, busy, KeyboardInterrupt()]),
            patch("companion.close_hpac_if_running", return_value=False) as close_hpac,
            patch("companion.time.sleep") as sleep,
            patch("companion.report") as report,
        ):
            self.assertEqual(companion.run(args), 0)

        self.assertEqual(close_hpac.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        report.assert_called_once_with(
            "Device not ready: control interface is busy", error=True
        )

    def test_hpac_lookup_avoids_taskkill_when_process_is_absent(self):
        with (
            patch("companion.find_process_ids", return_value=[]),
            patch("companion.subprocess.run") as run,
        ):
            self.assertFalse(companion.close_hpac_if_running())
        run.assert_not_called()

    def test_hpac_taskkill_is_hidden(self):
        completed = Mock(returncode=0, stderr="")
        with (
            patch("companion.find_process_ids", return_value=[1234]),
            patch("companion.subprocess.run", return_value=completed) as run,
        ):
            self.assertTrue(companion.close_hpac_if_running())

        self.assertEqual(
            run.call_args.kwargs["creationflags"],
            getattr(companion.subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_no_kill_hpac_option_was_removed(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            companion.build_parser().parse_args(["--no-kill-hpac"])


if __name__ == "__main__":
    unittest.main()
