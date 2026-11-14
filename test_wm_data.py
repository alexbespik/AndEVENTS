"""Focused regression tests for W&M feed parsing and idempotent imports."""

import json
import sqlite3
import unittest

import wm_data


FEED = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-1
SUMMARY:Test\\, event with a folded 
 title
DESCRIPTION:Line one\\nLine two
DTSTART;TZID=America/New_York:20261114T090000
DTEND;TZID=America/New_York:20261114T100000
LOCATION:Campus\\; room 1
CATEGORIES:Talks,Community
URL:https://events.wm.edu/event/1
END:VEVENT
BEGIN:VEVENT
UID:event-day
SUMMARY:All day
DTSTART;VALUE=DATE:20261115
DTEND;VALUE=DATE:20261116
END:VEVENT
BEGIN:VEVENT
UID:event-cancelled
SUMMARY:Cancelled
STATUS:CANCELLED
DTSTART:20261115T120000Z
END:VEVENT
END:VCALENDAR
"""


class WmDataTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys=ON")
        wm_data.ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_parse_unfold_escapes_dates_and_cancelled_events(self):
        events = wm_data.parse_ical(FEED)
        self.assertEqual([event["uid"] for event in events], ["event-1", "event-day"])
        self.assertEqual(events[0]["title"], "Test, event with a folded title")
        self.assertEqual(events[0]["description"], "Line one\nLine two")
        self.assertEqual(events[0]["location"], "Campus; room 1")
        self.assertEqual(events[0]["timezone"], "America/New_York")
        self.assertEqual(events[0]["source_url"], "https://events.wm.edu/event/1")
        self.assertEqual(events[0]["categories"], ["Talks", "Community"])
        self.assertEqual(events[1]["start_at"], "2026-11-15")
        self.assertEqual(events[1]["end_at"], "2026-11-16")
        self.assertTrue(events[1]["is_all_day"])

    def test_import_is_idempotent_and_deduplicates_memberships(self):
        first = wm_data.import_calendar(self.conn, "student-life", "Student Life", FEED)
        again = wm_data.import_calendar(self.conn, "student-life", "Student Life", FEED)
        other = wm_data.import_calendar(self.conn, "campus", "Campus", FEED)
        self.assertEqual(first["inserted"], 2)
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(other["inserted"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM wm_events").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM wm_event_calendars").fetchone()[0], 4)
        self.assertEqual(json.loads(self.conn.execute("SELECT categories FROM wm_events WHERE uid='event-1'").fetchone()[0]), ["Talks", "Community"])

    def test_failed_parse_does_not_remove_existing_memberships(self):
        wm_data.import_calendar(self.conn, "student-life", "Student Life", FEED)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.import_calendar(self.conn, "student-life", "Student Life", "not an iCalendar feed")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM wm_event_calendars").fetchone()[0], 2)

    def test_successful_import_removes_stale_memberships(self):
        wm_data.import_calendar(self.conn, "student-life", "Student Life", FEED)
        one_event = FEED[:FEED.index("BEGIN:VEVENT\nUID:event-day")]+"END:VCALENDAR\n"
        result = wm_data.import_calendar(self.conn, "student-life", "Student Life", one_event)
        self.assertEqual(result["memberships_removed"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM wm_events").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
