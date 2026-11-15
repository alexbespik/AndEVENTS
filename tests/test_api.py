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
        conn = get_db()
        conn.execute(
            """INSERT OR REPLACE INTO wm_events (uid, title, summary, description, start_at, end_at, timezone, location, source_url, categories, is_all_day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-wm-art-exhibit",
                "Muscarelle Museum Art Exhibition",
                "New gallery collection opening",
                "Paintings, drawings, and sculptures.",
                "2026-11-20T10:00:00-05:00",
                "2026-11-20T18:00:00-05:00",
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

        # 2. Trigger parser execution
        run_res = client.post("/api/parser/run")
        self.assertEqual(run_res.status_code, 200)
        run_data = run_res.json()
        self.assertIn(run_data["status"], ["success", "partial"])
        self.assertIn("total_events", run_data)
        self.assertIn("feeds_succeeded", run_data)
        self.assertIn("feeds_failed", run_data)
        self.assertIn("message", run_data)

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


if __name__ == "__main__":
    unittest.main()
