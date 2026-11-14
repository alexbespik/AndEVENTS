import unittest
from fastapi.testclient import TestClient
from app import app, init_db, get_db

client = TestClient(app)


class TestCampusScheduleAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_01_static_and_favicon(self):
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("&amp;.events", res.text)
        self.assertIn("favicon.svg", res.text)

        fav_res = client.get("/favicon.svg")
        self.assertEqual(fav_res.status_code, 200)
        self.assertIn("<svg", fav_res.text)

    def test_02_class_batch_and_clear(self):
        # Clear all classes
        del_res = client.delete("/api/classes")
        self.assertEqual(del_res.status_code, 200)

        # Batch add classes
        batch_payload = {
            "course_name": "CSCI 241: Data Structures",
            "days": [0, 2],
            "start_time": "14:00",
            "end_time": "15:15",
            "location": "Jones Hall 301",
        }
        post_res = client.post("/api/classes/batch", json=batch_payload)
        self.assertEqual(post_res.status_code, 200)

        # Add second class
        batch_payload_2 = {
            "course_name": "MATH 211: Linear Algebra",
            "days": [1, 3],
            "start_time": "15:30",
            "end_time": "16:50",
            "location": "Jones Hall 202",
        }
        client.post("/api/classes/batch", json=batch_payload_2)

        classes = client.get("/api/classes").json()
        self.assertEqual(len(classes), 4)

    def test_03_event_creation_and_deletion(self):
        # Create a new club event
        ev_payload = {
            "title": "Quantum Computing Reading Group",
            "club_name": "Physics & CS Society",
            "category": "Academic",
            "day_of_week": 4,
            "start_time": "16:00",
            "end_time": "17:30",
            "location": "Small Hall 110",
            "description": "Discussing NISQ algorithms and entanglement.",
        }
        res = client.post("/api/events", json=ev_payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        event_id = data["id"]

        # Inverted time should fail with 400
        bad_payload = dict(ev_payload, start_time="18:00", end_time="17:00")
        bad_res = client.post("/api/events", json=bad_payload)
        self.assertEqual(bad_res.status_code, 400)

        # Delete the created event
        del_res = client.delete(f"/api/events/{event_id}")
        self.assertEqual(del_res.status_code, 200)

        # Deleting again should return 404
        del_again = client.delete(f"/api/events/{event_id}")
        self.assertEqual(del_again.status_code, 404)

    def test_04_creator_planning_conflict_inspector(self):
        # Check slot overlapping with Monday class CSCI 241 (14:00-15:15)
        res = client.get("/api/planning/creator-conflicts?day=0&start_time=14:30&end_time=15:30")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(data["conflicting_classes_count"], 0)
        self.assertIn("CSCI 241", data["conflicting_classes"][0]["course_name"])

        # Check room collision with existing event
        # (Kernel workshop is on Monday 17:00-18:30 at ISC 1127)
        clash_res = client.get("/api/planning/creator-conflicts?day=0&start_time=17:30&end_time=18:00&location=ISC%201127")
        self.assertEqual(clash_res.status_code, 200)
        clash_data = clash_res.json()
        self.assertTrue(clash_data["has_location_clash"])
        self.assertEqual(clash_data["feasibility"], "ROOM_CLASH")

        # Check clear slot on Sunday
        clear_res = client.get("/api/planning/creator-conflicts?day=6&start_time=10:00&end_time=11:00&location=Sadler%20202")
        self.assertEqual(clear_res.status_code, 200)
        self.assertEqual(clear_res.json()["feasibility"], "CLEAR")

    def test_05_weekly_schedule_matrix(self):
        res = client.get("/api/planning/weekly-schedule")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("stats", data)
        self.assertIn("days", data)
        self.assertEqual(len(data["days"]), 7)

        # Monday should have classes and events
        mon = data["days"][0]
        self.assertEqual(mon["day_name"], "Monday")
        self.assertGreater(len(mon["classes"]), 0)
        self.assertGreater(len(mon["events"]), 0)

    def test_06_wm_events_endpoint(self):
        # Insert a sample wm event with ISO timestamp into wm_events table
        conn = get_db()
        conn.execute(
            """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-wm-ev-1",
                "W&M Research Symposium",
                "Annual research gathering",
                "All disciplines present.",
                "2026-11-16T14:30:00-05:00",  # Monday 14:30 EST (overlaps with Monday CSCI 241 class 14:00-15:15)
                "2026-11-16T16:00:00-05:00",
                "America/New_York",
                "Sadler Center",
                "https://events.wm.edu",
                '["Symposium", "Academic"]',
                0,
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO wm_event_calendars (uid, calendar_slug, calendar_name)
               VALUES (?, ?, ?)""",
            ("test-wm-ev-1", "featured", "Featured Events"),
        )
        conn.commit()
        conn.close()

        res = client.get("/api/wm-events?search=Symposium")
        self.assertEqual(res.status_code, 200)
        events = res.json()
        self.assertGreater(len(events), 0)
        symp = next(e for e in events if e["uid"] == "test-wm-ev-1")
        self.assertTrue(symp["has_conflict"])
        self.assertEqual(symp["conflicting_course"], "CSCI 241: Data Structures")

        # Clean up test event
        conn = get_db()
        conn.execute("DELETE FROM wm_events WHERE uid = ?", ("test-wm-ev-1",))
        conn.commit()
        conn.close()

    def test_07_now_and_next_endpoint(self):
        # Monday 17:15 should have Linux Kernel Workshop happening now (17:00-18:30)
        res = client.get("/api/now-and-next?sim_day=0&sim_time=17:15")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["current_day_name"], "Monday")
        self.assertEqual(data["current_time"], "17:15")
        self.assertGreaterEqual(len(data["happening_now"]), 1)
        now_titles = [e["title"] for e in data["happening_now"]]
        self.assertTrue(any("Kernel" in t for t in now_titles))

    def test_08_now_and_next_with_tags_and_wm_events(self):
        from datetime import datetime, timedelta, timezone as dt_tz
        from zoneinfo import ZoneInfo
        campus_tz = ZoneInfo("America/New_York")
        now_campus = datetime.now(campus_tz)
        mon_date = now_campus.date() + timedelta(days=(0 - now_campus.weekday()))
        st_utc = datetime(mon_date.year, mon_date.month, mon_date.day, 17, 0, tzinfo=campus_tz).astimezone(dt_tz.utc).isoformat()
        en_utc = datetime(mon_date.year, mon_date.month, mon_date.day, 18, 30, tzinfo=campus_tz).astimezone(dt_tz.utc).isoformat()

        conn = get_db()
        conn.execute(
            """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-wm-utc-now",
                "Machine Learning & Data Science Colloquium",
                "Advanced AI seminar",
                "Neural networks and transformers.",
                st_utc,
                en_utc,
                "UTC",
                "ISC 1127",
                "https://events.wm.edu",
                '["Technology", "Computer Science"]',
                0,
            ),
        )
        conn.commit()
        conn.close()

        # Query with sim time matching Monday 17:15 EST and student tags CS,DATA
        res = client.get("/api/now-and-next?sim_day=0&sim_time=17:15&tags=CS,DATA")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Should match our UTC event despite stored +00:00 offset
        happening = data["happening_now"]
        ml_ev = next((e for e in happening if e.get("uid") == "test-wm-utc-now"), None)
        self.assertIsNotNone(ml_ev)
        self.assertEqual(ml_ev["status_label"], "In Session · 75m left")
        self.assertIn("#CS", ml_ev["matched_tags"])
        self.assertIn("#DATA", ml_ev["matched_tags"])

        # Clean up
        conn = get_db()
        conn.execute("DELETE FROM wm_events WHERE uid = ?", ("test-wm-utc-now",))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
