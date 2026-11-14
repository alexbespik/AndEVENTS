"""Focused tests for bounded local W&M calendar file reads."""

from pathlib import Path
import tempfile
import unittest

from import_wm_events import _read_local_feed


class LocalFeedReadTests(unittest.TestCase):
    def test_reads_within_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.ics"
            path.write_bytes(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
            self.assertEqual(_read_local_feed(path, max_bytes=64), "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")

    def test_rejects_file_over_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.ics"
            path.write_bytes(b"12345")
            with self.assertRaisesRegex(ValueError, "exceeded 4 bytes"):
                _read_local_feed(path, max_bytes=4)


if __name__ == "__main__":
    unittest.main()
