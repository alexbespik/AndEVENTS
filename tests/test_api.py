import os
import tempfile
os.environ["TESTING"] = "1"
if "SCIEDU_CONTENT_DIR" not in os.environ:
    os.environ["SCIEDU_CONTENT_DIR"] = tempfile.mkdtemp(prefix="andevents-test-")
import socket
import unittest
from datetime import datetime, timedelta, timezone as dt_tz
from unittest import mock
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
import import_wm_events
from app import app, init_db, get_db

client = TestClient(app)
CAMPUS_TZ = ZoneInfo("America/New_York")

_network_guard = None


def setUpModule():
    """Fail loudly if any test tries to open a real network connection (feeds, Gemini)."""
    global _network_guard

    def _refuse(self, address, *args, **kwargs):
        raise AssertionError(f"tests must not open network connections (attempted {address!r})")

    _network_guard = mock.patch.object(socket.socket, "connect", _refuse)
    _network_guard.start()


def tearDownModule():
    if _network_guard is not None:
        _network_guard.stop()


def _insert_wm_event(uid, title, start_at, end_at, is_all_day=0, description="", location="ISC 1127", categories='["Academic"]'):
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, title, "", description, start_at, end_at, "America/New_York", location,
         "https://events.wm.edu", categories, is_all_day),
    )
    conn.commit()
    conn.close()


def _delete_by_uid_prefix(prefix):
    conn = get_db()
    for table in ("user_ai_alerts", "user_saved_events", "wm_events"):
        conn.execute(f"DELETE FROM {table} WHERE uid LIKE ?", (prefix + "%",))
    conn.commit()
    conn.close()


class TestCampusScheduleAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        # Monday 17:00-18:30 club fixture at ISC 1127 used by the conflict, timetable,
        # now-and-next and department tests (not part of the init_db seed list).
        conn = get_db()
        if not conn.execute("SELECT id FROM club_events WHERE title = ?", ("Kernel & Dotfiles Workshop",)).fetchone():
            conn.execute(
                """INSERT INTO club_events (club_name, title, description, day_of_week, start_time, end_time, location, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("W&M Linux Users Group", "Kernel & Dotfiles Workshop",
                 "Hands-on compilation, config tweaking, and terminal setups.",
                 0, "17:00", "18:30", "ISC 1127", "Technology"),
            )
            conn.commit()
        conn.close()

    def test_01_static_and_favicon(self):
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("&amp;.events", res.text)
        self.assertIn("favicon.svg", res.text)
        self.assertIn("academicPriorityHero", res.text)
        self.assertIn("coursePresetChips", res.text)
        self.assertIn("slotPresetPills", res.text)
        self.assertIn("majorThemeSelect", res.text)
        self.assertIn("modalMajorThemeSelect", res.text)

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

        # Test simulated day query parameter and is_today
        sim_res = client.get("/api/planning/weekly-schedule?sim_day=0")
        self.assertEqual(sim_res.status_code, 200)
        sim_data = sim_res.json()
        self.assertTrue(sim_data["days"][0]["is_today"])
        self.assertFalse(sim_data["days"][1]["is_today"])

        # Test timeline and 12h formatting
        sim_mon = sim_data["days"][0]
        self.assertIn("timeline", sim_mon)
        self.assertIn("total_commitments", sim_mon)
        self.assertEqual(sim_mon["total_commitments"], len(sim_mon["timeline"]))
        self.assertGreater(len(sim_mon["timeline"]), 0)

        # Verify items have type, 12h time formatting, and are sorted chronologically
        timeline = sim_mon["timeline"]
        for item in timeline:
            self.assertIn(item["type"], ["class", "event"])
            self.assertIn("start_time_12h", item)
            self.assertIn("end_time_12h", item)
            self.assertIn("time_range_12h", item)
            if not item.get("is_all_day"):
                self.assertTrue("AM" in item["start_time_12h"] or "PM" in item["start_time_12h"])
                self.assertTrue("AM" in item["end_time_12h"] or "PM" in item["end_time_12h"])
                self.assertIn(" – ", item["time_range_12h"])
            else:
                self.assertEqual(item["start_time_12h"], "All Day")

        # Verify chronological order
        for i in range(len(timeline) - 1):
            curr_sort_key = (timeline[i]["start_time"], timeline[i]["end_time"], 0 if timeline[i]["type"] == "class" else 1)
            next_sort_key = (timeline[i + 1]["start_time"], timeline[i + 1]["end_time"], 0 if timeline[i + 1]["type"] == "class" else 1)
            self.assertLessEqual(curr_sort_key, next_sort_key)

    def test_06_wm_events_endpoint(self):
        # Insert a sample wm event on the next upcoming Monday (Directory hides ended events)
        today = datetime.now(CAMPUS_TZ).date()
        next_mon = today + timedelta(days=(7 - today.weekday()))
        conn = get_db()
        conn.execute(
            """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-wm-ev-1",
                "W&M Research Symposium",
                "Annual research gathering",
                "All disciplines present.",
                datetime(next_mon.year, next_mon.month, next_mon.day, 14, 30, tzinfo=CAMPUS_TZ).isoformat(),  # Monday 14:30 (overlaps Monday CSCI 241 14:00-15:15)
                datetime(next_mon.year, next_mon.month, next_mon.day, 16, 0, tzinfo=CAMPUS_TZ).isoformat(),
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

    def test_09_academic_schedule_framework(self):
        """
        Comprehensive test for the Academic Schedule Framework:
        1. Presets endpoint: courses & standard time slots.
        2. Now & Next resolution: in-session, between classes, and post-class all-clear.
        3. Backward compatibility with active_class.
        4. Academic summary counters.
        5. Conflict detection against enrolled classes.
        """
        # 1. Test GET /api/classes/presets
        pres_res = client.get("/api/classes/presets")
        self.assertEqual(pres_res.status_code, 200)
        pres_data = pres_res.json()
        self.assertIn("courses", pres_data)
        self.assertIn("slots", pres_data)

        course_names = [c["course_name"] for c in pres_data["courses"]]
        self.assertTrue(any("CSCI 141" in c for c in course_names))
        self.assertTrue(any("CSCI 241" in c for c in course_names))
        self.assertTrue(any("CSCI 303" in c for c in course_names))
        self.assertTrue(any("DATA 141" in c for c in course_names))
        self.assertTrue(any("MATH 211" in c for c in course_names))
        self.assertTrue(any("PHIL 201" in c for c in course_names))
        self.assertTrue(any("BIOL 204" in c for c in course_names))

        slot_names = [s["name"] for s in pres_data["slots"]]
        self.assertTrue(any("MWF 50m" in s for s in slot_names))
        self.assertTrue(any("MW / TR 75m" in s for s in slot_names))

        # Check preset course fields
        sample_course = pres_data["courses"][0]
        for key in ["course_name", "department", "days", "days_label", "start_time", "end_time", "location", "time_range_12h"]:
            self.assertIn(key, sample_course)

        # 2. Reset classes and enroll Monday schedule
        client.delete("/api/classes")
        batch_1 = {
            "course_name": "CSCI 241: Data Structures",
            "days": [0],
            "start_time": "14:00",
            "end_time": "15:15",
            "location": "Jones Hall 301",
        }
        batch_2 = {
            "course_name": "MATH 211: Linear Algebra",
            "days": [0],
            "start_time": "15:30",
            "end_time": "16:45",
            "location": "Jones Hall 202",
        }
        res1 = client.post("/api/classes/batch", json=batch_1)
        res2 = client.post("/api/classes/batch", json=batch_2)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)

        # 3. Time 14:30 (In Session for CSCI 241, upcoming MATH 211 in 60m)
        res_active = client.get("/api/now-and-next?sim_day=0&sim_time=14:30")
        self.assertEqual(res_active.status_code, 200)
        data_active = res_active.json()

        curr = data_active["current_class"]
        self.assertIsNotNone(curr)
        self.assertEqual(curr["course_name"], "CSCI 241: Data Structures")
        self.assertEqual(curr["minutes_remaining"], 45)
        self.assertEqual(curr["status"], "current")
        self.assertEqual(curr["status_label"], "In Session · 45m left")
        self.assertEqual(curr["start_time_12h"], "2:00 PM")
        self.assertEqual(curr["end_time_12h"], "3:15 PM")
        self.assertEqual(curr["time_range_12h"], "2:00 PM – 3:15 PM")

        # Backward compatibility check
        self.assertEqual(data_active["active_class"]["course_name"], "CSCI 241: Data Structures")

        # Next class check
        nxt = data_active["next_class"]
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["course_name"], "MATH 211: Linear Algebra")
        self.assertEqual(nxt["status"], "upcoming")
        self.assertEqual(nxt["minutes_until_start"], 60)
        self.assertEqual(nxt["status_label"], "Starts in 1h")
        self.assertEqual(nxt["start_time_12h"], "3:30 PM")

        # Summary check
        self.assertEqual(len(data_active["today_classes"]), 2)
        summary = data_active["academic_summary"]
        self.assertEqual(summary["total_today"], 2)
        self.assertEqual(summary["completed_count"], 0)
        self.assertTrue(summary["has_current"])
        self.assertTrue(summary["has_upcoming"])

        # 4. Time 15:20 (Between classes: CSCI 241 finished, MATH 211 starts in 10m)
        res_between = client.get("/api/now-and-next?sim_day=0&sim_time=15:20")
        self.assertEqual(res_between.status_code, 200)
        data_between = res_between.json()
        self.assertIsNone(data_between["current_class"])
        self.assertIsNone(data_between["active_class"])
        nxt_between = data_between["next_class"]
        self.assertIsNotNone(nxt_between)
        self.assertEqual(nxt_between["course_name"], "MATH 211: Linear Algebra")
        self.assertEqual(nxt_between["minutes_until_start"], 10)
        self.assertEqual(nxt_between["status_label"], "Starts in 10m")
        self.assertFalse(data_between["academic_summary"]["has_current"])
        self.assertTrue(data_between["academic_summary"]["has_upcoming"])
        self.assertEqual(data_between["academic_summary"]["completed_count"], 1)

        # 5. Time 17:00 (All classes completed for today)
        res_evening = client.get("/api/now-and-next?sim_day=0&sim_time=17:00")
        self.assertEqual(res_evening.status_code, 200)
        data_evening = res_evening.json()
        self.assertIsNone(data_evening["current_class"])
        self.assertIsNone(data_evening["next_class"])
        self.assertEqual(len(data_evening["today_classes"]), 2)
        for cl in data_evening["today_classes"]:
            self.assertEqual(cl["status"], "completed")
        self.assertEqual(data_evening["academic_summary"]["completed_count"], 2)
        self.assertFalse(data_evening["academic_summary"]["has_current"])
        self.assertFalse(data_evening["academic_summary"]["has_upcoming"])

        # 6. Conflict detection with newly enrolled Monday classes
        # At 15:45-16:15, MATH 211 (15:30-16:45) is in session and no club events are scheduled
        conflict_res = client.get("/api/planning/creator-conflicts?day=0&start_time=15:45&end_time=16:15")
        self.assertEqual(conflict_res.status_code, 200)
        conflict_data = conflict_res.json()
        self.assertEqual(conflict_data["feasibility"], "CLASS_OVERLAP")
        self.assertEqual(conflict_data["conflicting_classes_count"], 1)
        self.assertEqual(conflict_data["conflicting_classes"][0]["course_name"], "MATH 211: Linear Algebra")

    def test_10_department_enrichment_on_endpoints(self):
        """
        Verify canonical 7-department taxonomy enrichment across:
        - GET /api/events
        - GET /api/now-and-next
        - GET /api/wm-events
        - GET /api/planning/weekly-schedule
        """
        # 1. /api/events
        res = client.get("/api/events")
        self.assertEqual(res.status_code, 200)
        events = res.json()
        self.assertGreater(len(events), 0)
        for ev in events:
            self.assertIn("department_id", ev)
            self.assertIn("department_name", ev)
            self.assertIn("department_color", ev)
            self.assertTrue(ev["department_id"].startswith("dept-"))
            self.assertTrue(ev["department_color"].startswith("#"))

        # Check specific expected seed event classifications
        kernel_ev = next((e for e in events if "Kernel" in e["title"]), None)
        self.assertIsNotNone(kernel_ev)
        self.assertEqual(kernel_ev["department_id"], "dept-cs")
        self.assertEqual(kernel_ev["department_color"], "#2c6eb5")

        swim_ev = next((e for e in events if "Swim" in e["title"]), None)
        self.assertIsNotNone(swim_ev)
        self.assertEqual(swim_ev["department_id"], "dept-sports")

        # 2. /api/now-and-next
        res_now = client.get("/api/now-and-next?sim_day=0&sim_time=17:15")
        self.assertEqual(res_now.status_code, 200)
        data_now = res_now.json()
        for ev in data_now.get("happening_now", []):
            self.assertIn("department_id", ev)
            self.assertIn("department_name", ev)
            self.assertIn("department_color", ev)

        # 3. /api/wm-events
        art_day = datetime.now(CAMPUS_TZ).date() + timedelta(days=5)
        conn = get_db()
        conn.execute(
            """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-wm-art-exhibit",
                "Muscarelle Museum Art Exhibition",
                "New gallery collection opening",
                "Paintings, drawings, and sculptures.",
                datetime(art_day.year, art_day.month, art_day.day, 10, 0, tzinfo=CAMPUS_TZ).isoformat(),
                datetime(art_day.year, art_day.month, art_day.day, 18, 0, tzinfo=CAMPUS_TZ).isoformat(),
                "America/New_York",
                "Muscarelle Hall",
                "https://events.wm.edu",
                '["Exhibition", "Arts"]',
                0,
            ),
        )
        conn.commit()
        conn.close()

        def cleanup_test_wm():
            c = get_db()
            c.execute("DELETE FROM wm_events WHERE uid = ?", ("test-wm-art-exhibit",))
            c.commit()
            c.close()

        self.addCleanup(cleanup_test_wm)

        wm_res = client.get("/api/wm-events?search=Muscarelle")
        self.assertEqual(wm_res.status_code, 200)
        wm_events = wm_res.json()
        self.assertGreater(len(wm_events), 0)
        art_ev = next(e for e in wm_events if e["uid"] == "test-wm-art-exhibit")
        self.assertEqual(art_ev["department_id"], "dept-arts")
        self.assertEqual(art_ev["department_name"], "Arts & Museum Exhibitions")
        self.assertEqual(art_ev["department_color"], "#8b3ab8")

        # 4. /api/planning/weekly-schedule
        plan_res = client.get("/api/planning/weekly-schedule")
        self.assertEqual(plan_res.status_code, 200)
        plan_data = plan_res.json()
        for day in plan_data["days"]:
            for item in day["events"]:
                self.assertIn("department_id", item)
                self.assertIn("department_name", item)
                self.assertIn("department_color", item)

    def test_11_ai_department_categorize(self):
        """
        Verify /api/ai/department-categorize endpoint:
        - GET and POST requests
        - Response structure (department_id, department_name, department_color, source)
        - Deterministic fallback when no GEMINI_API_KEY
        """
        # GET with query params for CS
        get_res = client.get("/api/ai/department-categorize?title=Hackathon%20Coding%20Sprint&category=Tech")
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.json()
        self.assertEqual(get_data["department_id"], "dept-cs")
        self.assertEqual(get_data["department_name"], "Computer Science & Technology")
        self.assertIn("source", get_data)

        # POST with JSON for Arts
        post_arts = client.post(
            "/api/ai/department-categorize",
            json={
                "title": "Symphony Orchestra Concert",
                "club_name": "Music Ensemble",
                "category": "Performance",
                "location": "PBK Hall",
                "description": "Classical overtures and string quartets."
            }
        )
        self.assertEqual(post_arts.status_code, 200)
        arts_data = post_arts.json()
        self.assertEqual(arts_data["department_id"], "dept-arts")

        # POST with JSON for Athletics/Sports
        post_sports = client.post(
            "/api/ai/department-categorize",
            json={
                "title": "Intramural Basketball Tournament",
                "location": "Rec Center Gym",
                "description": "5v5 bracket tournament."
            }
        )
        self.assertEqual(post_sports.status_code, 200)
        sports_data = post_sports.json()
        self.assertEqual(sports_data["department_id"], "dept-sports")

        # POST with Biology/Marine
        post_biol = client.post(
            "/api/ai/department-categorize",
            json={
                "title": "Marine Biodiversity Field Study",
                "location": "VIMS Gloucester Point",
                "description": "Estuarine sampling and oyster reef ecology."
            }
        )
        self.assertEqual(post_biol.status_code, 200)
        biol_data = post_biol.json()
        self.assertEqual(biol_data["department_id"], "dept-biol")

        # POST with Civics
        post_civics = client.post(
            "/api/ai/department-categorize",
            json={
                "title": "Constitutional Law & Civil Rights Forum",
                "location": "Wren Chapel",
                "description": "Public debate and dialogue."
            }
        )
        self.assertEqual(post_civics.status_code, 200)
        civics_data = post_civics.json()
        self.assertEqual(civics_data["department_id"], "dept-civics")

        # POST batch matching ARCHITECTURE.md contract
        batch_res = client.post(
            "/api/ai/department-categorize",
            json={
                "events": [
                    {"title": "Algorithms & Operating Systems", "category": "CS"},
                    {"title": "Varsity Swimming Championship", "location": "Rec Center Pool"}
                ]
            }
        )
        self.assertEqual(batch_res.status_code, 200)
        batch_data = batch_res.json()
        self.assertIn("source", batch_data)
        self.assertEqual(batch_data["count"], 2)
        self.assertEqual(len(batch_data["events"]), 2)
        self.assertEqual(batch_data["events"][0]["department_id"], "dept-cs")
        self.assertEqual(batch_data["events"][1]["department_id"], "dept-sports")

    def test_12_escape_and_special_character_safety(self):
        """
        Verify events with quotes, apostrophes, and HTML special chars
        are properly handled and categorized without syntax errors or crashes.
        """
        payload = {
            "title": "Dean's Reception & Women's Rugby Match",
            "club_name": "Tribe Athletics & Dean's Council",
            "category": "Sports",
            "day_of_week": 2,
            "start_time": "18:00",
            "end_time": "19:30",
            "location": "Kaplan Arena",
            "description": "Celebrating women's rugby season opener.",
        }
        res = client.post("/api/events", json=payload)
        self.assertEqual(res.status_code, 201)
        ev_id = res.json()["id"]

        ev_res = client.get("/api/events?search=Dean%27s")
        self.assertEqual(ev_res.status_code, 200)
        events = ev_res.json()
        self.assertGreater(len(events), 0)
        ev = next(e for e in events if e["id"] == ev_id)
        self.assertEqual(ev["department_id"], "dept-sports")
        self.assertIn("department_color", ev)

        # Clean up
        del_res = client.delete(f"/api/events/{ev_id}")
        self.assertEqual(del_res.status_code, 200)

    def test_13_parser_run_and_status_endpoints(self):
        """
        Verify the calendar feed parser trigger and status endpoints.
        """
        # 1. Initial status check
        status_res = client.get("/api/parser/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertIn("total_events", status_data)
        self.assertGreaterEqual(status_data["total_events"], 0)

        # 2. Trigger parser execution (feed fetching is mocked: no network in tests)
        with mock.patch.object(import_wm_events, "discover_and_import", return_value=(3, 0)) as fake_sync:
            run_res = client.post("/api/parser/run")
        fake_sync.assert_called_once()
        self.assertEqual(run_res.status_code, 200)
        run_data = run_res.json()
        self.assertIn(run_data["status"], ["success", "partial"])
        self.assertIn("total_events", run_data)
        self.assertIn("feeds_succeeded", run_data)
        self.assertIn("feeds_failed", run_data)
        self.assertIn("message", run_data)
        self.assertEqual(run_data["feeds_succeeded"], 3)
        self.assertEqual(run_data["feeds_failed"], 0)
        self.assertIn("ai_new_alerts", run_data)
        self.assertIn("ai_auto_added", run_data)

        # 3. Status check after sync reflects updated state
        after_res = client.get("/api/parser/status")
        self.assertEqual(after_res.status_code, 200)
        after_data = after_res.json()
        self.assertIsNotNone(after_data["last_sync"])

    def test_14_daily_sync_status_fields(self):
        """
        Verify the enhanced /api/parser/status payload containing
        auto_sync_enabled, sync_interval_hours, and next_auto_sync.
        """
        res = client.get("/api/parser/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_events", data)
        self.assertIn("last_sync", data)
        self.assertIn("auto_sync_enabled", data)
        self.assertTrue(data["auto_sync_enabled"])
        self.assertEqual(data["sync_interval_hours"], 24)
        self.assertIn("next_auto_sync", data)
        if data["last_sync"]:
            self.assertIsNotNone(data["next_auto_sync"])

    def test_15_calendar_export_ics(self):
        """
        Verify /api/calendar/export.ics endpoint:
        - 400 error when no target parameter is specified
        - 404 error when invalid/unknown target ID is supplied
        - Valid RFC 5545 iCalendar payload for single club event (event_id)
        - Valid RFC 5545 iCalendar payload for class session (class_id)
        - Valid RFC 5545 iCalendar payload for scope (scope=my)
        """
        # 1. Missing all params -> 400 Bad Request
        res_empty = client.get("/api/calendar/export.ics")
        self.assertEqual(res_empty.status_code, 400)
        self.assertIn("At least one export parameter", res_empty.json()["detail"])

        # 2. Non-existent item -> 404 Not Found
        res_not_found = client.get("/api/calendar/export.ics?event_id=999999")
        self.assertEqual(res_not_found.status_code, 404)

        # 3. Export single club event
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, title, location FROM club_events LIMIT 1")
        club_row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(club_row)
        club_id = club_row["id"]
        res_club = client.get(f"/api/calendar/export.ics?event_id={club_id}")
        self.assertEqual(res_club.status_code, 200)
        self.assertIn("text/calendar", res_club.headers["content-type"])
        self.assertIn(".ics", res_club.headers.get("content-disposition", ""))
        club_ics = res_club.text
        self.assertTrue(club_ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(club_ics.endswith("END:VCALENDAR\r\n"))
        self.assertIn("VERSION:2.0\r\n", club_ics)
        self.assertIn("PRODID:-//AndEDU//AndEVENTS//EN\r\n", club_ics)
        self.assertIn("BEGIN:VEVENT\r\n", club_ics)
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=", club_ics)
        self.assertIn(f"UID:club-{club_id}@andedu.events\r\n", club_ics)

        # 4. Export single user class
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, course_name FROM user_classes LIMIT 1")
        class_row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(class_row)
        class_id = class_row["id"]
        res_class = client.get(f"/api/calendar/export.ics?class_id={class_id}")
        self.assertEqual(res_class.status_code, 200)
        self.assertIn("text/calendar", res_class.headers["content-type"])
        class_ics = res_class.text
        self.assertIn("BEGIN:VCALENDAR\r\n", class_ics)
        self.assertIn(f"UID:class-{class_id}@andedu.events\r\n", class_ics)
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=", class_ics)

        # 5. Export scope=my schedule
        res_scope = client.get("/api/calendar/export.ics?scope=my")
        self.assertEqual(res_scope.status_code, 200)
        self.assertIn("wm_my_schedule.ics", res_scope.headers.get("content-disposition", ""))
        self.assertIn("BEGIN:VCALENDAR\r\n", res_scope.text)

    def test_16_planner_refinements_and_uid_hardening(self):
        """
        Verify Weekly Planner DOM elements & defensive UID CRLF hardening.
        """
        from app import _format_wm_vevent
        dtstamp = "20261115T000000Z"

        # 1. Defense-in-depth: UID with newline is sanitized to single line
        tainted_ev = {
            "uid": "event-1234\r\nATTACK:INJECTION",
            "title": "Clean Title",
            "start_at": "2026-11-15T14:00:00",
            "end_at": "2026-11-15T15:00:00",
        }
        lines = _format_wm_vevent(tainted_ev, dtstamp)
        self.assertIn("UID:event-1234", lines)
        for line in lines:
            self.assertNotIn("ATTACK:INJECTION", line)
            self.assertNotIn("\r", line)
            self.assertNotIn("\n", line)

        # 2. Frontend index.html verification
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("plannerDeptFilterGroup", res.text)
        self.assertIn("clusterModal", res.text)
        self.assertIn("openClusterModal", res.text)
        self.assertIn("cal-overflow-card", res.text)
        self.assertIn("cal-gutter-all-day", res.text)

        # 3. CSS styles verification
        css_res = client.get("/static/lab.css")
        self.assertEqual(css_res.status_code, 200)
        self.assertIn(".cal-gutter-all-day", css_res.text)
        self.assertIn(".cal-overflow-card", css_res.text)
        self.assertIn(".cal-dept-pill", css_res.text)

    def test_17_ai_concierge_intent_and_alerts(self):
        """Verify AI Concierge intent persistence, auto-scheduling, and alerts."""
        def _cleanup():
            conn = get_db()
            cur = conn.cursor()
            cur.execute("DELETE FROM user_ai_alerts WHERE uid LIKE 'test-cs-hackathon%'")
            cur.execute("DELETE FROM user_saved_events WHERE uid LIKE 'test-cs-hackathon%'")
            cur.execute("DELETE FROM wm_events WHERE uid LIKE 'test-cs-hackathon%'")
            conn.commit()
            conn.close()

        _cleanup()
        self.addCleanup(_cleanup)

        # 1. Default intent query
        res = client.get("/api/ai/intent")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("prompt", data)
        self.assertIn("auto_add", data)

        # 2. Set new intent with auto_add enabled
        set_res = client.post("/api/ai/intent", json={
            "prompt": "computer science hackathon coding robotics research seminar",
            "auto_add": True,
            "notify": True
        })
        self.assertEqual(set_res.status_code, 200)
        set_data = set_res.json()
        self.assertEqual(set_data["status"], "ok")
        self.assertTrue(set_data["auto_add"])

        # 3. Insert an upcoming mock event (only future events are matched)
        hack_start = (datetime.now(CAMPUS_TZ) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO wm_events (
                uid, title, description, summary, start_at, end_at, timezone, is_all_day, location, categories, source_url
            ) VALUES (
                'test-cs-hackathon-2026',
                'Tribe Hacks: Autonomous AI & Robotics Sprint',
                'Join us for a 24-hour coding sprint with autonomous robotics and machine learning research.',
                'Robotics hackathon for CS students.',
                ?,
                ?,
                'America/New_York',
                0,
                'ISC 1127',
                '["Technology", "Colloquium"]',
                'https://events.wm.edu/event/test-hackathon'
            )
        """, (hack_start.isoformat(), (hack_start + timedelta(hours=8)).isoformat()))
        conn.commit()
        conn.close()

        # Re-trigger intent matching
        client.post("/api/ai/intent", json={
            "prompt": "robotics hackathon coding",
            "auto_add": True,
            "notify": True
        })

        # 4. Check alerts endpoint
        alerts_res = client.get("/api/ai/alerts")
        self.assertEqual(alerts_res.status_code, 200)
        alerts_data = alerts_res.json()
        self.assertIn("alerts", alerts_data)
        matches = [a for a in alerts_data["alerts"] if a["uid"] == "test-cs-hackathon-2026"]
        self.assertTrue(len(matches) > 0)
        alert_id = matches[0]["id"]

        # 5. Check user-saved-events
        saved_res = client.get("/api/user-saved-events")
        self.assertEqual(saved_res.status_code, 200)
        saved_data = saved_res.json()
        saved_uids = [e["uid"] for e in saved_data["saved_events"]]
        self.assertIn("test-cs-hackathon-2026", saved_uids)

        # 6. Test dismiss action
        action_res = client.post("/api/ai/alerts/action", json={
            "alert_id": alert_id,
            "action": "dismiss"
        })
        self.assertEqual(action_res.status_code, 200)

        # 7. Frontend integration check
        html_res = client.get("/")
        self.assertEqual(html_res.status_code, 200)
        self.assertIn("aiConciergeModal", html_res.text)
        self.assertIn("openAiConciergeModal", html_res.text)
        self.assertIn("saveAiIntentAndMatch", html_res.text)
        self.assertIn("loadAiAlerts", html_res.text)
        self.assertIn("eventModalSaveBtn", html_res.text)

    def test_18_now_and_next_strict_temporal_scoping(self):
        """Task F: live feed holds only today's single-day sessions; soon = starts within 3h today."""
        self.addCleanup(_delete_by_uid_prefix, "tf-")
        now_campus = datetime.now(CAMPUS_TZ)
        mon = now_campus.date() - timedelta(days=now_campus.weekday())

        def at(day_offset, hh, mm=0):
            d = mon + timedelta(days=day_offset)
            return datetime(d.year, d.month, d.day, hh, mm, tzinfo=CAMPUS_TZ).isoformat()

        def day(day_offset):
            return (mon + timedelta(days=day_offset)).isoformat()

        # Simulated "now" is Monday 12:00 of the current campus week.
        _insert_wm_event("tf-exhibit-months", "Months Long Museum Exhibition", day(-90), day(30), is_all_day=1)
        _insert_wm_event("tf-exhibit-opens-today", "Exhibition Opening Today For A Week", day(0), day(5), is_all_day=1)
        _insert_wm_event("tf-allday-from-yesterday", "Two Day Registration Window", day(-1), day(1), is_all_day=1)
        _insert_wm_event("tf-allday-today", "Single Day Open House", day(0), day(1), is_all_day=1)
        _insert_wm_event("tf-past-10d", "Registration For Continuing Students", at(-10, 9), at(-10, 17))
        _insert_wm_event("tf-timed-from-yesterday", "Overnight Program From Yesterday", at(-1, 10), at(0, 20))
        _insert_wm_event("tf-timed-into-tomorrow", "Starts Today Ends Tomorrow", at(0, 11), at(1, 11))
        _insert_wm_event("tf-active", "Midday Lecture In Session", at(0, 11, 30), at(0, 13))
        _insert_wm_event("tf-soon", "Afternoon Talk In Two Hours", at(0, 14), at(0, 15))
        _insert_wm_event("tf-overnight-soon", "Late Show Past Midnight", at(0, 14, 30), at(1, 1))
        _insert_wm_event("tf-later-4h", "Evening Talk In Four Hours", at(0, 16), at(0, 17))
        _insert_wm_event("tf-tomorrow", "Tomorrow Lunch Talk", at(1, 12, 30), at(1, 13, 30))

        res = client.get("/api/now-and-next?sim_day=0&sim_time=12:00")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        now_uids = {e.get("uid") for e in data["happening_now"] if e.get("uid", "").startswith("tf-")}
        soon_uids = {e.get("uid") for e in data["starting_soon"] if e.get("uid", "").startswith("tf-")}

        self.assertEqual(now_uids, {"tf-active", "tf-allday-today"})
        self.assertEqual(soon_uids, {"tf-soon"})

        for ev in data["happening_now"] + data["starting_soon"]:
            self.assertNotEqual(ev.get("status_label"), "Ongoing")
            if ev.get("is_wm_event"):
                self.assertEqual(ev["date_display"], data["today_display"])
            if ev.get("starts_in_minutes") is not None:
                self.assertLessEqual(ev["starts_in_minutes"], 180)

        allday = next(e for e in data["happening_now"] if e.get("uid") == "tf-allday-today")
        self.assertEqual(allday["status_label"], "All Day Today")

    def test_19_ai_interest_pipeline_after_parser_runs(self):
        """Interest prompt -> keyword match after each parser run -> deduped alerts -> auto-added schedule."""
        self.addCleanup(_delete_by_uid_prefix, "aip-")
        self.addCleanup(client.post, "/api/ai/intent", json={"prompt": "", "auto_add": False})
        now_campus = datetime.now(CAMPUS_TZ)
        future = (now_campus + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0)
        past = now_campus - timedelta(days=10)

        # Gemini must never be contacted in TESTING, even with a key configured.
        import app as app_module
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-not-real"}), \
                mock.patch.object(app_module, "_query_gemini_intent_keywords") as gem_kw:
            self.assertEqual(app_module._gemini_api_key(), "")
            set_res = client.post("/api/ai/intent", json={
                "prompt": "I want to go to astronomy stargazing nights", "auto_add": True, "notify": True,
            })
            gem_kw.assert_not_called()
        self.assertEqual(set_res.status_code, 200)
        set_data = set_res.json()
        self.assertEqual(set_data["keyword_source"], "keyword")
        self.assertIn("astronomy", set_data["keywords"])
        self.assertNotIn("want", set_data["keywords"])
        self.assertTrue(set_data["auto_add"])

        stored = client.get("/api/ai/intent").json()
        self.assertEqual(stored["prompt"], "I want to go to astronomy stargazing nights")
        self.assertTrue(stored["auto_add"])

        future_ev = ("aip-astro-future", "Astronomy Club Stargazing Night", future.isoformat(),
                     (future + timedelta(hours=2)).isoformat())
        past_ev = ("aip-astro-past", "Astronomy Lecture Archive", past.isoformat(),
                   (past + timedelta(hours=1)).isoformat())
        unrelated_ev = ("aip-unrelated", "Accounting Office Hours", future.isoformat(),
                        (future + timedelta(hours=1)).isoformat())

        def fake_sync(conn, delay=0.0, timeout=0.0, discover_directory=False):
            for uid, title, st, en in (future_ev, past_ev, unrelated_ev):
                conn.execute(
                    """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
                       VALUES (?, ?, '', '', ?, ?, 'America/New_York', 'Small Hall Roof', 'https://events.wm.edu', '["Science"]', 0)""",
                    (uid, title, st, en),
                )
            return 1, 0

        # Two parser runs: the second must not duplicate alerts.
        for _ in range(2):
            with mock.patch.object(import_wm_events, "discover_and_import", side_effect=fake_sync):
                run_res = client.post("/api/parser/run")
            self.assertEqual(run_res.status_code, 200)
            if _ == 0:
                self.assertEqual(run_res.json()["ai_new_alerts"], 1)
                self.assertEqual(run_res.json()["ai_auto_added"], 1)
            else:
                self.assertEqual(run_res.json()["ai_new_alerts"], 0)
                self.assertEqual(run_res.json()["ai_auto_added"], 0)

        alerts = [a for a in client.get("/api/ai/alerts").json()["alerts"] if a["uid"].startswith("aip-")]
        self.assertEqual([a["uid"] for a in alerts], ["aip-astro-future"])  # past + unrelated never matched
        self.assertTrue(alerts[0]["is_added"])
        self.assertIn("astronomy", alerts[0]["match_reason"])

        saved = [e for e in client.get("/api/user-saved-events").json()["saved_events"] if e["uid"].startswith("aip-")]
        self.assertEqual(len(saved), 1)
        sv = saved[0]
        self.assertEqual(sv["uid"], "aip-astro-future")
        self.assertEqual(sv["title"], "Astronomy Club Stargazing Night")
        self.assertEqual(sv["start_at"], future.isoformat())
        self.assertEqual(sv["end_at"], (future + timedelta(hours=2)).isoformat())
        self.assertEqual(sv["location"], "Small Hall Roof")
        self.assertFalse(sv["is_all_day"])
        self.assertEqual(sv["source"], "ai_auto")
        self.assertEqual(sv["time_range_12h"], "3:00 PM – 5:00 PM")
        for key in ("department_id", "department_color", "date_display", "categories", "is_wm_event", "is_ai_scheduled"):
            self.assertIn(key, sv)

        # `since` returns only alerts created after a timestamp.
        self.assertEqual(client.get("/api/ai/alerts", params={"since": datetime.now(CAMPUS_TZ).isoformat()}).json()["alerts"], [])

        # Removing the saved event dismisses its alert so later syncs don't re-add it.
        del_res = client.delete("/api/user-saved-events/aip-astro-future")
        self.assertEqual(del_res.status_code, 200)
        with mock.patch.object(import_wm_events, "discover_and_import", side_effect=fake_sync):
            self.assertEqual(client.post("/api/parser/run").json()["ai_new_alerts"], 0)
        self.assertFalse(any(e["uid"].startswith("aip-") for e in client.get("/api/user-saved-events").json()["saved_events"]))
        self.assertEqual(client.delete("/api/user-saved-events/aip-astro-future").status_code, 404)
        conn = get_db()
        alert_row = conn.execute("SELECT id, is_added, is_dismissed FROM user_ai_alerts WHERE uid = 'aip-astro-future'").fetchone()
        conn.close()
        self.assertEqual((alert_row["is_added"], alert_row["is_dismissed"]), (0, 1))
        self.assertNotIn("aip-astro-future", {a["uid"] for a in client.get("/api/ai/alerts").json()["alerts"]})

        # The student can still re-add it manually: "add" un-dismisses and saves again.
        readd = client.post("/api/ai/alerts/action", json={"alert_id": alert_row["id"], "action": "add"})
        self.assertEqual(readd.status_code, 200)
        conn = get_db()
        alert_row = conn.execute("SELECT is_added, is_dismissed FROM user_ai_alerts WHERE uid = 'aip-astro-future'").fetchone()
        conn.close()
        self.assertEqual((alert_row["is_added"], alert_row["is_dismissed"]), (1, 0))
        readded = [e for e in client.get("/api/user-saved-events").json()["saved_events"] if e["uid"] == "aip-astro-future"]
        self.assertEqual(len(readded), 1)
        self.assertEqual(readded[0]["source"], "ai_alert")

    def test_20_ai_alert_actions_without_auto_add(self):
        """Without auto_add, alerts stay pending until the student adds or dismisses them."""
        self.addCleanup(_delete_by_uid_prefix, "aia-")
        self.addCleanup(client.post, "/api/ai/intent", json={"prompt": "", "auto_add": False})
        future = (datetime.now(CAMPUS_TZ) + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        allday = (datetime.now(CAMPUS_TZ) + timedelta(days=2)).date()
        _insert_wm_event("aia-pottery", "Pottery Wheel Workshop", future.isoformat(), (future + timedelta(hours=1)).isoformat())
        _insert_wm_event("aia-pottery-fair", "Campus Pottery Fair", allday.isoformat(), (allday + timedelta(days=1)).isoformat(), is_all_day=1)

        res = client.post("/api/ai/intent", json={"prompt": "pottery", "auto_add": False}).json()
        self.assertEqual(res["new_alerts"], 2)
        self.assertEqual(res["auto_added_count"], 0)
        self.assertFalse(any(e["uid"].startswith("aia-") for e in client.get("/api/user-saved-events").json()["saved_events"]))

        alerts = {a["uid"]: a for a in client.get("/api/ai/alerts", params={"unread_only": True}).json()["alerts"] if a["uid"].startswith("aia-")}
        self.assertEqual(set(alerts), {"aia-pottery", "aia-pottery-fair"})

        add = client.post("/api/ai/alerts/action", json={"alert_id": alerts["aia-pottery-fair"]["id"], "action": "add"})
        self.assertEqual(add.status_code, 200)
        dismiss = client.post("/api/ai/alerts/action", json={"alert_id": alerts["aia-pottery"]["id"], "action": "dismiss"})
        self.assertEqual(dismiss.status_code, 200)
        self.assertEqual(client.post("/api/ai/alerts/action", json={"alert_id": alerts["aia-pottery"]["id"], "action": "bogus"}).status_code, 400)
        self.assertEqual(client.post("/api/ai/alerts/action", json={"alert_id": 99999999, "action": "add"}).status_code, 404)

        saved = [e for e in client.get("/api/user-saved-events").json()["saved_events"] if e["uid"].startswith("aia-")]
        self.assertEqual([e["uid"] for e in saved], ["aia-pottery-fair"])
        self.assertTrue(saved[0]["is_all_day"])
        self.assertEqual(saved[0]["time_range_12h"], "All Day")
        self.assertEqual(saved[0]["source"], "ai_alert")

        visible = {a["uid"] for a in client.get("/api/ai/alerts").json()["alerts"]}
        self.assertNotIn("aia-pottery", visible)
        # Re-matching never resurrects a dismissed alert.
        self.assertEqual(client.post("/api/ai/match-intent", json={"prompt": "pottery"}).json()["new_alerts"], 0)
        self.assertNotIn("aia-pottery", {a["uid"] for a in client.get("/api/ai/alerts").json()["alerts"]})

    def test_21_keyword_fallback_matching(self):
        from app import _keyword_fallback
        kws = _keyword_fallback("I would like to join tech and food events")
        self.assertIn("tech", kws)
        self.assertIn("hackathon", kws)
        self.assertIn("pizza", kws)
        for stop in ("like", "join", "events", "and"):
            self.assertNotIn(stop, kws)

    def test_22_enabling_auto_add_schedules_pending_alerts(self):
        self.addCleanup(_delete_by_uid_prefix, "aup-")
        self.addCleanup(client.post, "/api/ai/intent", json={"prompt": "", "auto_add": False})
        future = (datetime.now(CAMPUS_TZ) + timedelta(days=2)).replace(hour=13, minute=0, second=0, microsecond=0)
        _insert_wm_event("aup-origami", "Origami Folding Circle", future.isoformat(), (future + timedelta(hours=1)).isoformat())

        first = client.post("/api/ai/intent", json={"prompt": "origami", "auto_add": False}).json()
        self.assertEqual(first["new_alerts"], 1)
        self.assertEqual(first["auto_added_count"], 0)
        self.assertFalse(any(e["uid"] == "aup-origami" for e in client.get("/api/user-saved-events").json()["saved_events"]))

        second = client.post("/api/ai/intent", json={"prompt": "origami", "auto_add": True}).json()
        self.assertEqual(second["new_alerts"], 0)
        self.assertEqual(second["auto_added_count"], 1)
        saved = [e for e in client.get("/api/user-saved-events").json()["saved_events"] if e["uid"] == "aup-origami"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["source"], "ai_auto")
        alert = next(a for a in client.get("/api/ai/alerts").json()["alerts"] if a["uid"] == "aup-origami")
        self.assertTrue(alert["is_added"])
        # Already scheduled: a further run adds nothing.
        self.assertEqual(client.post("/api/ai/match-intent", json={"prompt": "origami", "auto_add": True}).json()["auto_added_count"], 0)

    def test_23_alerts_hide_past_events_and_validate_since(self):
        self.addCleanup(_delete_by_uid_prefix, "apx-")
        now_campus = datetime.now(CAMPUS_TZ)
        before = client.get("/api/ai/alerts").json()["unread_count"]
        conn = get_db()
        rows = [
            ("apx-yesterday", (now_campus - timedelta(days=1)).isoformat(), (now_campus - timedelta(days=1) + timedelta(hours=1)).isoformat()),
            ("apx-ended", (now_campus - timedelta(minutes=2)).isoformat(), (now_campus - timedelta(minutes=1)).isoformat()),
            ("apx-old-allday", (now_campus.date() - timedelta(days=5)).isoformat(), None),
            ("apx-upcoming", (now_campus + timedelta(days=1)).isoformat(), (now_campus + timedelta(days=1, hours=1)).isoformat()),
        ]
        for uid, st, en in rows:
            conn.execute(
                """INSERT INTO user_ai_alerts (uid, title, start_datetime, end_datetime, location, match_reason, score, is_added, is_dismissed, created_at)
                   VALUES (?, ?, ?, ?, '', 'Matched: test', 0.5, 0, 0, ?)""",
                (uid, uid, st, en, now_campus.isoformat()),
            )
        conn.commit()
        conn.close()

        data = client.get("/api/ai/alerts").json()
        uids = {a["uid"] for a in data["alerts"]}
        self.assertIn("apx-upcoming", uids)
        for gone in ("apx-yesterday", "apx-ended", "apx-old-allday"):
            self.assertNotIn(gone, uids)
        self.assertEqual(data["unread_count"], before + 1)

        earlier_z = (now_campus - timedelta(hours=1)).astimezone(dt_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        later_z = (now_campus + timedelta(hours=1)).astimezone(dt_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertIn("apx-upcoming", {a["uid"] for a in client.get("/api/ai/alerts", params={"since": earlier_z}).json()["alerts"]})
        self.assertNotIn("apx-upcoming", {a["uid"] for a in client.get("/api/ai/alerts", params={"since": later_z}).json()["alerts"]})
        self.assertEqual(client.get("/api/ai/alerts", params={"since": "not-a-date"}).status_code, 400)

    def test_24_gemini_failures_cached_and_network_errors_stop(self):
        import urllib.error
        import app as app_module
        app_module._INTENT_KEYWORD_CACHE.clear()
        self.addCleanup(app_module._INTENT_KEYWORD_CACHE.clear)
        with mock.patch.object(app_module, "_gemini_api_key", return_value="test-key-not-real"), \
                mock.patch.object(app_module, "_query_gemini_intent_keywords", return_value=None) as gem:
            for _ in range(3):
                kws, src = app_module._intent_keywords("chess tournaments")
                self.assertEqual(src, "keyword")
                self.assertIn("chess", kws)
            gem.assert_called_once()

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")) as fake_open:
            self.assertIsNone(app_module._query_gemini_intent_keywords("test-key-not-real", "chess"))
            self.assertEqual(fake_open.call_count, 1)

    def test_25_directory_hides_ended_and_sorts_ongoing_last(self):
        self.addCleanup(_delete_by_uid_prefix, "dir-")
        now_campus = datetime.now(CAMPUS_TZ)
        today = now_campus.date()

        def at(days, hh, mm=0):
            d = today + timedelta(days=days)
            return datetime(d.year, d.month, d.day, hh, mm, tzinfo=CAMPUS_TZ).isoformat()

        def day(days):
            return (today + timedelta(days=days)).isoformat()

        tag = "Zqxdirtest"
        _insert_wm_event("dir-past-10d", f"{tag} Registration Ten Days Ago", at(-10, 9), at(-10, 17))
        _insert_wm_event("dir-past-allday", f"{tag} Old Single Day", day(-3), day(-2), is_all_day=1)
        _insert_wm_event("dir-past-exhibit", f"{tag} Closed Exhibition", day(-120), day(-1), is_all_day=1)
        _insert_wm_event("dir-ongoing-exhibit", f"{tag} Founding Exhibition Still Running", day(-280), day(60), is_all_day=1)
        _insert_wm_event("dir-ongoing-timed", f"{tag} Online Program", at(-20, 9), at(10, 17))
        _insert_wm_event("dir-upcoming-2", f"{tag} Concert In Two Days", at(2, 19), at(2, 21))
        _insert_wm_event("dir-upcoming-1", f"{tag} Talk Tomorrow", at(1, 12), at(1, 13))
        _insert_wm_event("dir-future-exhibit", f"{tag} Exhibition Opening Next Week", day(7), day(40), is_all_day=1)

        res = client.get("/api/wm-events", params={"search": tag})
        self.assertEqual(res.status_code, 200)
        events = [e for e in res.json() if e["uid"].startswith("dir-")]
        uids = [e["uid"] for e in events]
        self.assertEqual(uids, [
            "dir-upcoming-1", "dir-upcoming-2", "dir-future-exhibit",
            "dir-ongoing-exhibit", "dir-ongoing-timed",
        ])
        by_uid = {e["uid"]: e for e in events}
        self.assertTrue(by_uid["dir-ongoing-exhibit"]["is_ongoing"])
        self.assertTrue(by_uid["dir-ongoing-timed"]["is_ongoing"])
        self.assertFalse(by_uid["dir-upcoming-1"]["is_ongoing"])
        self.assertFalse(by_uid["dir-future-exhibit"]["is_ongoing"])
        self.assertTrue(by_uid["dir-future-exhibit"]["is_multi_day"])
        self.assertFalse(by_uid["dir-upcoming-1"]["is_multi_day"])

        all_res = client.get("/api/wm-events", params={"search": tag, "include_past": "true"}).json()
        self.assertIn("dir-past-10d", {e["uid"] for e in all_res})

    def test_26_directory_collapses_cross_feed_duplicates(self):
        """The same event published by two feeds (different UID / UTC offset / entity noise) lists once."""
        from app import classify_department
        _delete_by_uid_prefix("dup-")
        self.addCleanup(_delete_by_uid_prefix, "dup-")
        start_local = (datetime.now(CAMPUS_TZ) + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(hours=1)
        tag = "Zzdupcheck"
        _insert_wm_event("dup-a", f"{tag} Class:&nbsp;Yoga Night", start_local.isoformat(), end_local.isoformat())
        _insert_wm_event("dup-b", f"{tag} Class: Yoga Night",
                         start_local.astimezone(dt_tz.utc).isoformat(), end_local.astimezone(dt_tz.utc).isoformat(),
                         location="Somewhere Else")
        # Same title an hour later is a different session and must survive.
        _insert_wm_event("dup-c", f"{tag} Class: Yoga Night",
                         (start_local + timedelta(hours=1)).isoformat(), (end_local + timedelta(hours=1)).isoformat())
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO wm_event_calendars (uid, calendar_slug, calendar_name) VALUES ('dup-a', 'dup-feed-a', 'Feed A')")
        conn.execute("INSERT OR REPLACE INTO wm_event_calendars (uid, calendar_slug, calendar_name) VALUES ('dup-b', 'dup-feed-b', 'Feed B')")
        conn.commit()
        conn.close()

        def _drop_calendars():
            c = get_db()
            c.execute("DELETE FROM wm_event_calendars WHERE uid LIKE 'dup-%'")
            c.commit()
            c.close()
        self.addCleanup(_drop_calendars)

        res = client.get("/api/wm-events", params={"search": tag}).json()
        self.assertEqual([e["uid"] for e in res], ["dup-a", "dup-c"])
        self.assertEqual({c["slug"] for c in res[0]["source_calendars"]}, {"dup-feed-a", "dup-feed-b"})
        self.assertEqual(res[0]["alt_uids"], ["dup-b"])

        # Fitness classes land in Athletics & Recreation whichever feed carried them.
        yoga = classify_department({"title": "FitWell Class: Candlelight Yoga", "location": "McLeod Tyler Wellness Center, Studio A"})
        self.assertEqual(yoga["department_id"], "dept-sports")


if __name__ == "__main__":
    unittest.main()
