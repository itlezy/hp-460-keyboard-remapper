import json
import tempfile
import unittest
from pathlib import Path

from hpac_dev_mode import DEV_KEYS, read_settings, split_json_trailer, write_settings


class HpacSettingsTests(unittest.TestCase):
    def test_split_preserves_binary_trailer(self) -> None:
        data = b'{"text":"brace } in string","dev":false}\x00\xfftrailer}'
        json_bytes, trailer = split_json_trailer(data)
        self.assertEqual(json.loads(json_bytes), {"text": "brace } in string", "dev": False})
        self.assertEqual(trailer, b"\x00\xfftrailer}")

    def test_write_preserves_trailer_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "HPAC.settings")
            original = b'{"dev":false}\x00opaque'
            path.write_bytes(original)
            settings, trailer = read_settings(path)
            for key in DEV_KEYS:
                settings[key] = True
            backup = write_settings(path, settings, trailer)

            updated, updated_trailer = read_settings(path)
            self.assertTrue(all(updated[key] is True for key in DEV_KEYS))
            self.assertEqual(updated_trailer, b"\x00opaque")
            self.assertEqual(backup.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
