import os
import json
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from wm_data import ensure_schema

# Content directory configuration matching &EDU db.py pattern
CONTENT_ROOT = Path(os.environ.get("SCIEDU_CONTENT_DIR") or Path(__file__).resolve().parent)
DB_PATH = CONTENT_ROOT / "schedule.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CAMPUS_TZ = ZoneInfo("America/New_York")

app = FastAPI(title="&.events — Campus Schedule & Planning Engine")

STATIC_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # High-concurrency WAL mode and foreign key integrity from &EDU db.py
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def time_to_minutes(t_str: str) -> int:
    h, m = map(int, t_str.split(":"))
    return h * 60 + m


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS club_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            club_name TEXT NOT NULL,
            category TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            location TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    ensure_schema(conn)

    # High performance compound indexes for range & conflict scanning
    cur.execute("CREATE INDEX IF NOT EXISTS idx_club_events_day_time ON club_events (day_of_week, start_time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_classes_day_time ON user_classes (day_of_week, start_time);")

    # Seed initial demo data once on fresh initialization
    cur.execute("SELECT value FROM app_meta WHERE key = 'initial_seeded'")
    if not cur.fetchone():
        seed_events = [
            ("Kernel & Dotfiles Workshop", "Linux 1991 Club", "Tech", 0, "17:00", "18:30", "ISC 1127", "Bring your laptop. Customizing shells and tiling window managers."),
            ("AI Paper Reading Group", "AI Society", "Academic", 0, "14:00", "15:15", "McGlothlin-Street 020", "Breaking down transformer attention optimizations."),
            ("Open Lap Swim & Water Polo", "Aquatics Club", "Sports", 1, "16:00", "17:30", "Rec Center Pool", "Open scrimmage and conditioning."),
            ("Rapid Chess Blitz Night", "Chess Club", "Gaming", 2, "18:00", "20:00", "Sadler Center 202", "10+0 and 3+2 brackets, open to all ratings."),
            ("3D Printing & CAD Clinic", "Makerspace Guild", "Tech", 2, "13:00", "14:30", "Small Hall Makerspace", "Slicer tuning, multi-color purge calibration, and OpenSCAD."),
            ("Embedded Mesh Networking Lab", "Robotics & Hardware", "Tech", 3, "15:00", "16:30", "ISC 2011", "Testing off-grid packet relays and microcontrollers."),
            ("Tabletop Lore & Painting", "Wargaming Guild", "Gaming", 4, "19:00", "22:00", "Campus Center 104", "2000pt matches and miniature painting station."),
        ]
        cur.executemany("""
            INSERT INTO club_events (title, club_name, category, day_of_week, start_time, end_time, location, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, seed_events)

        seed_classes = [
            ("CSCI 241: Data Structures", 0, "14:00", "15:15", "Jones Hall 301"),
            ("CSCI 241: Data Structures", 2, "14:00", "15:15", "Jones Hall 301"),
            ("MATH 211: Linear Algebra", 1, "15:30", "16:50", "Jones Hall 202"),
            ("MATH 211: Linear Algebra", 3, "15:30", "16:50", "Jones Hall 202"),
        ]
        cur.executemany("""
            INSERT INTO user_classes (course_name, day_of_week, start_time, end_time, location)
            VALUES (?, ?, ?, ?, ?)
        """, seed_classes)

        cur.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('initial_seeded', '1')")

    conn.commit()
    conn.close()


init_db()


# --- Pydantic Data Models ---

class ClassBatchCreate(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=120)
    days: List[int] = Field(..., min_length=1, max_length=7)
    start_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    end_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    location: Optional[str] = Field(default="TBA", max_length=120)


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    club_name: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="Tech", min_length=1, max_length=60)
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    end_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    location: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(default="", max_length=1000)


# --- Core Web Routes ---

@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg")
@app.get("/favicon.ico")
def serve_favicon():
    fav = STATIC_DIR / "favicon.svg"
    if fav.exists():
        return FileResponse(fav, media_type="image/svg+xml")
    return FileResponse(STATIC_DIR / "index.html")


# --- Event Routes ---

@app.get("/api/events")
def get_events(
    day: Optional[int] = Query(None, ge=0, le=6),
    category: Optional[str] = None,
    club_name: Optional[str] = None,
    search: Optional[str] = None,
    hide_conflicts: bool = False,
    only_now: bool = False,
    sim_day: Optional[int] = Query(None, ge=0, le=6),
    sim_time: Optional[str] = Query(None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$"),
):
    now = datetime.now()
    current_day = sim_day if sim_day is not None else now.weekday()
    current_time = sim_time if sim_time else now.strftime("%H:%M")
    curr_mins = time_to_minutes(current_time)

    conn = get_db()
    cur = conn.cursor()

    # Fetch all classes for conflict checking
    cur.execute("SELECT * FROM user_classes")
    classes = [dict(r) for r in cur.fetchall()]

    query = "SELECT * FROM club_events WHERE 1=1"
    params = []

    if day is not None:
        query += " AND day_of_week = ?"
        params.append(day)
    if category and category != "ALL":
        query += " AND category = ?"
        params.append(category)
    if club_name:
        query += " AND LOWER(club_name) LIKE ?"
        params.append(f"%{club_name.strip().lower()}%")
    if search:
        query += " AND (LOWER(title) LIKE ? OR LOWER(club_name) LIKE ? OR LOWER(location) LIKE ?)"
        s = f"%{search.lower()}%"
        params.extend([s, s, s])

    query += " ORDER BY day_of_week ASC, start_time ASC"
    cur.execute(query, params)
    events = [dict(r) for r in cur.fetchall()]
    conn.close()

    enriched = []
    for ev in events:
        # Conflict check: event.day_of_week == class.day_of_week AND event.start_time < class.end_time AND event.end_time > class.start_time
        conflict_course = None
        for cl in classes:
            if cl["day_of_week"] == ev["day_of_week"]:
                if ev["start_time"] < cl["end_time"] and ev["end_time"] > cl["start_time"]:
                    conflict_course = cl["course_name"]
                    break

        ev["has_conflict"] = conflict_course is not None
        ev["conflicting_course"] = conflict_course

        ev_start_mins = time_to_minutes(ev["start_time"])
        ev_end_mins = time_to_minutes(ev["end_time"])

        ev["is_happening_now"] = (
            ev["day_of_week"] == current_day and ev_start_mins <= curr_mins <= ev_end_mins
        )
        ev["starts_soon"] = (
            ev["day_of_week"] == current_day and 0 < (ev_start_mins - curr_mins) <= 60
        )
        ev["can_attend_now"] = (ev["is_happening_now"] or ev["starts_soon"]) and not ev["has_conflict"]

        if hide_conflicts and ev["has_conflict"]:
            continue
        if only_now and not ev["can_attend_now"]:
            continue

        enriched.append(ev)

    return enriched


@app.get("/api/wm-events")
def get_wm_events(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search: Optional[str] = None,
):
    conn = get_db()
    cur = conn.cursor()

    query = """
        SELECT e.*, c.calendar_slug, c.calendar_name
        FROM wm_events AS e
        LEFT JOIN wm_event_calendars AS c ON c.uid = e.uid
        WHERE 1=1
    """
    params: List[Any] = []
    if start_date is not None:
        query += " AND substr(e.start_at, 1, 10) >= ?"
        params.append(start_date.isoformat())
    if end_date is not None:
        query += " AND substr(e.start_at, 1, 10) <= ?"
        params.append(end_date.isoformat())
    if search and search.strip():
        query += " AND (LOWER(e.title) LIKE ? OR LOWER(e.summary) LIKE ? OR LOWER(e.description) LIKE ? OR LOWER(e.location) LIKE ? OR LOWER(e.categories) LIKE ?)"
        term = f"%{search.strip().lower()}%"
        params.extend([term, term, term, term, term])
    query += " ORDER BY e.start_at ASC, e.uid ASC, c.calendar_name ASC"

    cur.execute(query, params)
    rows = cur.fetchall()

    cur.execute("SELECT day_of_week, start_time, end_time, course_name FROM user_classes")
    classes = [dict(row) for row in cur.fetchall()]
    conn.close()

    events: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        uid = row["uid"]
        if uid not in events:
            event = {key: row[key] for key in row.keys() if key not in ("calendar_slug", "calendar_name")}
            try:
                categories = json.loads(event["categories"] or "[]")
                event["categories"] = categories if isinstance(categories, list) else []
            except (TypeError, json.JSONDecodeError):
                event["categories"] = []

            event["is_all_day"] = bool(event["is_all_day"])
            event["source_calendars"] = []
            event["has_conflict"] = False
            event["conflicting_course"] = None

            if not event["is_all_day"] and event["end_at"]:
                try:
                    starts_raw = event["start_at"].replace("Z", "+00:00")
                    ends_raw = event["end_at"].replace("Z", "+00:00")
                    starts = datetime.fromisoformat(starts_raw)
                    ends = datetime.fromisoformat(ends_raw)
                    if starts.tzinfo is not None:
                        starts = starts.astimezone(CAMPUS_TZ)
                    if ends.tzinfo is not None:
                        ends = ends.astimezone(CAMPUS_TZ)

                    if starts.date() == ends.date():
                        event_start = starts.strftime("%H:%M")
                        event_end = ends.strftime("%H:%M")
                        for class_row in classes:
                            if (
                                class_row["day_of_week"] == starts.weekday()
                                and event_start < class_row["end_time"]
                                and event_end > class_row["start_time"]
                            ):
                                event["has_conflict"] = True
                                event["conflicting_course"] = class_row["course_name"]
                                break
                except (TypeError, ValueError):
                    pass

            events[uid] = event

        if row["calendar_slug"] is not None:
            events[uid]["source_calendars"].append({
                "slug": row["calendar_slug"],
                "name": row["calendar_name"],
            })

    return list(events.values())


@app.post("/api/events", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate):
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="start_time must be earlier than end_time")
    if not payload.title.strip() or not payload.club_name.strip() or not payload.location.strip():
        raise HTTPException(status_code=422, detail="title, club_name, and location must not be blank")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO club_events (title, club_name, category, day_of_week, start_time, end_time, location, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.title.strip(),
            payload.club_name.strip(),
            payload.category.strip() or "General",
            payload.day_of_week,
            payload.start_time,
            payload.end_time,
            payload.location.strip(),
            (payload.description or "").strip(),
        ),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"status": "ok", "id": new_id, "message": "Event successfully created"}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM club_events WHERE id = ?", (event_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Club event not found")

    cur.execute("DELETE FROM club_events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "id": event_id}


# --- Class Routes ---

@app.get("/api/classes")
def get_classes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_classes ORDER BY day_of_week ASC, start_time ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.post("/api/classes/batch")
def add_classes_batch(payload: ClassBatchCreate):
    if not payload.course_name.strip():
        raise HTTPException(status_code=422, detail="course_name must not be blank")
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="start_time must be earlier than end_time")
    invalid_days = sorted(set(payload.days) - set(range(7)))
    if invalid_days:
        raise HTTPException(status_code=422, detail="days must contain values from 0 through 6")

    conn = get_db()
    cur = conn.cursor()
    for d in sorted(set(payload.days)):
        cur.execute(
            """
            INSERT INTO user_classes (course_name, day_of_week, start_time, end_time, location)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.course_name.strip(), d, payload.start_time, payload.end_time, (payload.location or "TBA").strip() or "TBA"),
        )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.delete("/api/classes/{class_id}")
def delete_class(class_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_classes WHERE id = ?", (class_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.delete("/api/classes")
def clear_classes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_classes")
    conn.commit()
    conn.close()
    return {"status": "cleared"}


# --- Planning Engine Routes ---

@app.get("/api/planning/creator-conflicts")
def check_creator_conflicts(
    day: int = Query(..., ge=0, le=6),
    start_time: str = Query(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$"),
    end_time: str = Query(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$"),
    location: Optional[str] = None,
    exclude_event_id: Optional[int] = None,
):
    """
    Creator Planning Mode Endpoint:
    Checks a proposed timeslot on a given day against existing student classes and competing club events.
    Returns overlapping classes count, competing clubs, room clash flag, and feasibility recommendation.
    """
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time must be earlier than end_time")

    conn = get_db()
    cur = conn.cursor()

    # 1. Overlapping student classes: startA < endB AND endA > startB
    cur.execute(
        """
        SELECT * FROM user_classes
        WHERE day_of_week = ? AND start_time < ? AND end_time > ?
        ORDER BY start_time ASC
        """,
        (day, end_time, start_time),
    )
    conflicting_classes = [dict(r) for r in cur.fetchall()]

    # 2. Overlapping existing club events
    event_query = """
        SELECT * FROM club_events
        WHERE day_of_week = ? AND start_time < ? AND end_time > ?
    """
    params: List[Any] = [day, end_time, start_time]
    if exclude_event_id is not None:
        event_query += " AND id != ?"
        params.append(exclude_event_id)
    event_query += " ORDER BY start_time ASC"

    cur.execute(event_query, params)
    competing_events = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Room collision detection
    loc_clash = False
    clash_event_title = None
    if location and location.strip():
        loc_clean = location.strip().lower()
        for ev in competing_events:
            if ev.get("location") and ev["location"].strip().lower() == loc_clean:
                loc_clash = True
                clash_event_title = ev["title"]
                break

    # Feasibility advice calculation
    class_count = len(conflicting_classes)
    event_count = len(competing_events)

    if loc_clash:
        status_code = "ROOM_CLASH"
        advice = f"Room collision: {clash_event_title} is already booked in {location.strip()} during this slot."
    elif class_count == 0 and event_count == 0:
        status_code = "CLEAR"
        advice = "Optimal time slot: zero student class conflicts and zero competing club events."
    elif class_count > 0 and event_count == 0:
        status_code = "CLASS_OVERLAP"
        advice = f"Caution: {class_count} registered student class(es) overlap with this time window."
    elif class_count == 0 and event_count > 0:
        status_code = "CLUB_OVERLAP"
        advice = f"Caution: {event_count} other club event(s) already scheduled during this slot."
    else:
        status_code = "HEAVY_OVERLAP"
        advice = f"High conflict window: {class_count} student class(es) and {event_count} competing club event(s) overlap."

    return {
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "conflicting_classes_count": class_count,
        "competing_events_count": event_count,
        "has_location_clash": loc_clash,
        "feasibility": status_code,
        "advice": advice,
        "conflicting_classes": conflicting_classes,
        "competing_events": competing_events,
    }


@app.get("/api/planning/weekly-schedule")
def get_weekly_schedule():
    """
    Non-Creator / Student Weekly Planner Endpoint:
    Constructs a 7-day schedule matrix pairing each day's classes with club events.
    Overlapping club events are marked as soft planning considerations (not blocked)
    so students can visualize trade-offs and plan their week.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM user_classes ORDER BY day_of_week ASC, start_time ASC")
    classes = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM club_events ORDER BY day_of_week ASC, start_time ASC")
    events = [dict(r) for r in cur.fetchall()]
    conn.close()

    days_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_data = []

    total_classes = len(classes)
    total_events = len(events)
    conflicted_events = 0

    for d in range(7):
        day_classes = [c for c in classes if c["day_of_week"] == d]
        day_events_raw = [e for e in events if e["day_of_week"] == d]

        enriched_events = []
        for ev in day_events_raw:
            conflicts = []
            for cl in day_classes:
                if ev["start_time"] < cl["end_time"] and ev["end_time"] > cl["start_time"]:
                    conflicts.append(cl)

            has_conf = len(conflicts) > 0
            if has_conf:
                conflicted_events += 1

            enriched_events.append({
                **ev,
                "has_conflict": has_conf,
                "conflicting_course": conflicts[0]["course_name"] if has_conf else None,
                "conflicting_classes": conflicts,
            })

        days_data.append({
            "day_index": d,
            "day_name": days_names[d],
            "classes": day_classes,
            "events": enriched_events,
        })

    return {
        "stats": {
            "total_classes": total_classes,
            "total_events": total_events,
            "conflicted_events": conflicted_events,
            "free_events": total_events - conflicted_events,
        },
        "days": days_data,
    }


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host=host, port=port, reload=True)
