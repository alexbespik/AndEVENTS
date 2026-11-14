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

    def test_parse_quoted_parameters_and_escaped_category_commas(self):
        feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:quoted-params
SUMMARY;LANGUAGE="en;US":Quoted parameter
DTSTART;TZID="America/New_York":20261115T090000
DTEND;TZID="America/New_York":20261115T100000
X-DETAIL;X-NOTE="left:right;middle":ignored
CATEGORIES:Food\\,Drink,Music
END:VEVENT
END:VCALENDAR
"""
        event = wm_data.parse_ical(feed)[0]
        self.assertEqual(event["title"], "Quoted parameter")
        self.assertEqual(event["start_at"], "2026-11-15T09:00:00-05:00")
        self.assertEqual(event["categories"], ["Food,Drink", "Music"])

    def test_duration_end_times_respect_local_calendar_and_elapsed_time(self):
        feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:elapsed-across-fall-back
SUMMARY:Elapsed duration
DTSTART;TZID=America/New_York:20261101T003000
DURATION:PT2H
END:VEVENT
BEGIN:VEVENT
UID:nominal-day-across-spring-forward
SUMMARY:Nominal day duration
DTSTART;TZID=America/New_York:20260307T090000
DURATION:P1DT2H
END:VEVENT
BEGIN:VEVENT
UID:all-day-duration
SUMMARY:All day duration
DTSTART;VALUE=DATE:20260308
DURATION:P1D
END:VEVENT
BEGIN:VEVENT
UID:implicit-date-time-end
SUMMARY:Implicit date-time end
DTSTART;TZID=America/New_York:20261115T090000
END:VEVENT
BEGIN:VEVENT
UID:implicit-date-end
SUMMARY:Implicit all-day end
DTSTART;VALUE=DATE:20260308
END:VEVENT
END:VCALENDAR
"""
        events = {event["uid"]: event for event in wm_data.parse_ical(feed)}
        self.assertEqual(events["elapsed-across-fall-back"]["end_at"], "2026-11-01T01:30:00-05:00")
        self.assertEqual(events["nominal-day-across-spring-forward"]["end_at"], "2026-03-08T11:00:00-04:00")
        self.assertEqual(events["all-day-duration"]["end_at"], "2026-03-09")
        self.assertEqual(events["implicit-date-time-end"]["end_at"], "2026-11-15T09:00:00-05:00")
        self.assertEqual(events["implicit-date-end"]["end_at"], "2026-03-09")

    def test_rejects_conflicting_or_invalid_event_end_definitions(self):
        overflowing_implicit_end = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:overflowing-implicit-end
SUMMARY:Overflowing implicit end
DTSTART;VALUE=DATE:99991231
END:VEVENT
END:VCALENDAR
"""
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(overflowing_implicit_end)

        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(" " * (wm_data.MAX_ICAL_BYTES + 1))
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical("x\n" * (wm_data.MAX_ICAL_LINES + 1))

        conflicting = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:both-end-and-duration
SUMMARY:Conflicting end definitions
DTSTART:20261115T090000Z
DTEND:20261115T100000Z
DURATION:PT1H
END:VEVENT
END:VCALENDAR
"""
        invalid_duration = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:zero-duration
SUMMARY:Zero duration
DTSTART:20261115T090000Z
DURATION:PT0S
END:VEVENT
END:VCALENDAR
"""
        reversed_end = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:reversed-end
SUMMARY:Reversed end
DTSTART:20261115T100000Z
DTEND:20261115T090000Z
END:VEVENT
END:VCALENDAR
"""
        mismatched_end_type = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:mismatched-end-type
SUMMARY:Mismatched end type
DTSTART;VALUE=DATE:20261115
DTEND:20261116T000000Z
END:VEVENT
END:VCALENDAR
"""
        duplicate_duration = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:duplicate-duration
SUMMARY:Duplicate duration
DTSTART:20261115T090000Z
DURATION:PT1H
DURATION:PT2H
END:VEVENT
END:VCALENDAR
"""
        oversized_duration = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:oversized-duration
SUMMARY:Oversized duration
DTSTART:20261115T090000Z
DURATION:PT999999999999999999999999999999999999999999H
END:VEVENT
END:VCALENDAR
"""
        duration_overflowing_event_date = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:duration-overflowing-event-date
SUMMARY:Duration overflows event date
DTSTART;VALUE=DATE:20261115
DURATION:P9999999D
END:VEVENT
END:VCALENDAR
"""
        overlong_duration_integer = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:overlong-duration
SUMMARY:Overlong duration
DTSTART:20261115T090000Z
DURATION:PT""" + ("9" * 5000) + """H
END:VEVENT
END:VCALENDAR
"""
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(conflicting)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(invalid_duration)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(reversed_end)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(mismatched_end_type)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(duplicate_duration)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(oversized_duration)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(duration_overflowing_event_date)
        with self.assertRaises(wm_data.ICalendarError):
            wm_data.parse_ical(overlong_duration_integer)

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

    def test_all_day_date_duration_adjustment(self):
        feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:all-day-same-day
SUMMARY:Same Day Event
DTSTART;VALUE=DATE:20261120
DTEND;VALUE=DATE:20261120
END:VEVENT
BEGIN:VEVENT
UID:all-day-no-end
SUMMARY:No End Event
DTSTART;VALUE=DATE:20261125
END:VEVENT
END:VCALENDAR
"""
        events = {e["uid"]: e for e in wm_data.parse_ical(feed)}
        self.assertEqual(events["all-day-same-day"]["start_at"], "2026-11-20")
        self.assertEqual(events["all-day-same-day"]["end_at"], "2026-11-21")
        self.assertTrue(events["all-day-same-day"]["is_all_day"])

        self.assertEqual(events["all-day-no-end"]["start_at"], "2026-11-25")
        self.assertEqual(events["all-day-no-end"]["end_at"], "2026-11-26")
        self.assertTrue(events["all-day-no-end"]["is_all_day"])

    def test_windows_timezone_mapping(self):
        self.assertEqual(wm_data.resolve_tzid("Eastern Standard Time"), "America/New_York")
        self.assertEqual(wm_data.resolve_tzid("eastern daylight time"), "America/New_York")
        self.assertEqual(wm_data.resolve_tzid("US/Eastern"), "America/New_York")
        self.assertEqual(wm_data.resolve_tzid("EST"), "America/New_York")
        self.assertEqual(wm_data.resolve_tzid("EDT"), "America/New_York")
        self.assertEqual(wm_data.resolve_tzid("UTC"), "UTC")
        self.assertEqual(wm_data.resolve_tzid("GMT"), "UTC")
        self.assertEqual(wm_data.resolve_tzid("America/New_York"), "America/New_York")

        feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:win-tz-test
SUMMARY:Windows TZ Event
DTSTART;TZID="Eastern Standard Time":20261114T100000
DTEND;TZID="Eastern Standard Time":20261114T110000
END:VEVENT
END:VCALENDAR
"""
        events = wm_data.parse_ical(feed)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["timezone"], "America/New_York")
        self.assertEqual(events[0]["start_at"], "2026-11-14T10:00:00-05:00")
        self.assertEqual(events[0]["end_at"], "2026-11-14T11:00:00-05:00")

    def test_rrule_expansion_weekly_and_daily(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        fixed_now = datetime(2026, 11, 14, 12, 0, tzinfo=ZoneInfo("America/New_York"))

        # Weekly event on Tuesday and Thursday with count 4
        weekly_feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:weekly-recurring
SUMMARY:Weekly Study Group
DTSTART;TZID=America/New_York:20261117T180000
DTEND;TZID=America/New_York:20261117T193000
RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4
EXDATE;TZID=America/New_York:20261119T180000
END:VEVENT
END:VCALENDAR
"""
        events = wm_data.parse_ical(weekly_feed, now=fixed_now)
        # Nov 17 is Tue (#1). Nov 19 is Thu (excluded by EXDATE, but counts against total).
        # Nov 24 is Tue (#3). Nov 26 is Thu (#4). Total generated: 3 instances (1 excluded).
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["uid"], "weekly-recurring::20261117T1800")
        self.assertEqual(events[0]["start_at"], "2026-11-17T18:00:00-05:00")
        self.assertEqual(events[1]["uid"], "weekly-recurring::20261124T1800")
        self.assertEqual(events[2]["uid"], "weekly-recurring::20261126T1800")

        # Daily event with interval=2 and UNTIL
        daily_feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:daily-recurring
SUMMARY:Alternate Day Workshop
DTSTART;TZID=America/New_York:20261114T090000
DTEND;TZID=America/New_York:20261114T100000
RRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261119T000000Z
END:VEVENT
END:VCALENDAR
"""
        d_events = wm_data.parse_ical(daily_feed, now=fixed_now)
        # Nov 14 (within window), Nov 16, Nov 18. (Nov 20 is past UNTIL 20261119)
        self.assertEqual(len(d_events), 3)
        self.assertEqual(d_events[0]["uid"], "daily-recurring::20261114T0900")
        self.assertEqual(d_events[1]["uid"], "daily-recurring::20261116T0900")
        self.assertEqual(d_events[2]["uid"], "daily-recurring::20261118T0900")

        # Single occurrence RRULE maintains deterministic timestamp UID
        single_feed = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:single-rrule
SUMMARY:Single Remaining
DTSTART;TZID=America/New_York:20261114T150000
DTEND;TZID=America/New_York:20261114T160000
RRULE:FREQ=DAILY;COUNT=1
END:VEVENT
END:VCALENDAR
"""
        s_events = wm_data.parse_ical(single_feed, now=fixed_now)
        self.assertEqual(len(s_events), 1)
        self.assertEqual(s_events[0]["uid"], "single-rrule::20261114T1500")

    def test_normalize_wm_location(self):
        self.assertEqual(wm_data.normalize_wm_location("Jones Hall, Room 202"), "Jones 202")
        self.assertEqual(wm_data.normalize_wm_location("Integrated Science Center 1127"), "ISC 1127")
        self.assertEqual(wm_data.normalize_wm_location("Sadler Center 298"), "Sadler 298")
        self.assertEqual(wm_data.normalize_wm_location("Blow Memorial Hall 101"), "Blow 101")
        self.assertEqual(wm_data.normalize_wm_location("Rec Center Pool"), "Rec Center Pool")
        self.assertEqual(wm_data.normalize_wm_location("Small Hall Makerspace"), "Small Makerspace")
        self.assertEqual(wm_data.normalize_wm_location("Swem Library, Ground Floor"), "Swem Ground Floor")
        self.assertEqual(wm_data.normalize_wm_location("Tucker Hall 127A"), "Tucker 127A")
        self.assertEqual(wm_data.normalize_wm_location("Off-campus Coffee Shop"), "Off-campus Coffee Shop")

    def test_is_allowed_feed_url_ssrf_checks(self):
        # Allowed
        self.assertTrue(wm_data.is_allowed_feed_url("https://events.wm.edu/calendar/upcoming_ical/wm"))
        self.assertTrue(wm_data.is_allowed_feed_url("https://tribelink.wm.edu/events.ics"))
        self.assertTrue(wm_data.is_allowed_feed_url("https://events.wm.edu:443/feed.ics"))

        # Blocked
        self.assertFalse(wm_data.is_allowed_feed_url("http://events.wm.edu/calendar/upcoming_ical/wm"))
        self.assertFalse(wm_data.is_allowed_feed_url("https://events.wm.edu:8080/feed.ics"))
        self.assertFalse(wm_data.is_allowed_feed_url("https://user:pass@events.wm.edu/feed.ics"))
        self.assertFalse(wm_data.is_allowed_feed_url("https://malicious.com/events.ics"))
        self.assertFalse(wm_data.is_allowed_feed_url("https://events.wm.edu.attacker.com/events.ics"))
        self.assertFalse(wm_data.is_allowed_feed_url("https://localhost/events.ics"))
        self.assertFalse(wm_data.is_allowed_feed_url("ftp://events.wm.edu/events.ics"))
        self.assertFalse(wm_data.is_allowed_feed_url(""))
        self.assertFalse(wm_data.is_allowed_feed_url(None))


if __name__ == "__main__":
    unittest.main()
