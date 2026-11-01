import os
import tempfile
import unittest
from unittest.mock import call, patch

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


if __name__ == "__main__":
    unittest.main()
