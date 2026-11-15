"""Focused tests for bounded local W&M calendar file reads."""

from pathlib import Path
import tempfile
import unittest

from import_wm_events import DEFAULT_DISCOVERY_FEEDS, _read_local_feed
from wm_data import is_allowed_feed_url


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


class DefaultFeedTests(unittest.TestCase):
    def test_task_a_feeds_present_and_allowed(self):
        feeds = {slug: url for slug, _name, url in DEFAULT_DISCOVERY_FEEDS}
        self.assertEqual(feeds["career"], "https://events.wm.edu/calendar/upcoming_ical/career")
        self.assertEqual(feeds["swem"], "https://events.wm.edu/calendar/upcoming_ical/swem")
        self.assertEqual(feeds["studenthappenings"], "https://events.wm.edu/calendar/upcoming_ical/studenthappenings")
        self.assertEqual(feeds["tribeathletics"], "https://tribeathletics.com/calendar.ashx/calendar.ics")
        self.assertEqual(len(feeds), len(DEFAULT_DISCOVERY_FEEDS), "duplicate feed slugs")
        for url in feeds.values():
            self.assertTrue(is_allowed_feed_url(url), url)


if __name__ == "__main__":
    unittest.main()
