import os
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from wm_data import ensure_schema, normalize_wm_location

TAG_KEYWORDS: dict[str, list[str]] = {
    "CS": ["cs", "csci", "computer", "software", "code", "coding", "linux", "kernel", "ai", "machine learning", "hardware", "robotics", "cybersecurity", "web", "hackathon"],
    "DATA": ["data", "analytics", "statistics", "math", "datascience", "dataset", "database", "sql"],
    "PHIL": ["phil", "philosophy", "ethics", "logic", "socrates", "epistemology"],
    "ART": ["art", "arts", "painting", "drawing", "music", "theater", "theatre", "design", "creative", "craft", "choir", "band", "orchestra"],
    "BIOL": ["biol", "biology", "bio", "wildlife", "botany", "genetics", "ecology", "pre-med"],
    "BUSINESS": ["business", "finance", "economics", "econ", "consulting", "marketing", "entrepreneurship", "management", "mba"],
    "SPORTS": ["sports", "recreation", "rec", "swim", "polo", "soccer", "basketball", "volleyball", "running", "fitness", "climbing", "tennis"],
    "WELLNESS": ["wellness", "mindfulness", "health", "meditation", "yoga", "stress", "mental health"],
}


def match_tags(event_data: dict[str, Any], student_tags: list[str]) -> list[str]:
    if not student_tags:
        return []
    cats = event_data.get("categories") or []
    if isinstance(cats, str):
        try:
            cats = json.loads(cats)
        except Exception:
            cats = [cats]
    corpus = " ".join([
        str(event_data.get("title") or ""),
        str(event_data.get("club_name") or ""),
        str(event_data.get("category") or ""),
        str(event_data.get("summary") or ""),
        str(event_data.get("description") or ""),
        str(event_data.get("location") or ""),
        " ".join(cats) if isinstance(cats, list) else str(cats),
    ]).lower()

    matched: list[str] = []
    for tag in student_tags:
        tag_clean = tag.strip().lstrip("#").upper()
        if not tag_clean:
            continue
        tag_lower = tag_clean.lower()
        if re.search(r"\b" + re.escape(tag_lower) + r"\b", corpus):
            matched.append(f"#{tag_clean}")
            continue
        keywords = TAG_KEYWORDS.get(tag_clean, [])
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", corpus):
                matched.append(f"#{tag_clean}")
                break
    return matched

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


def format_12h(time_str: str) -> str:
    """Converts '14:00' -> '2:00 PM', '09:30' -> '9:30 AM'."""
    if not time_str or ":" not in time_str:
        return time_str
    try:
        h, m = map(int, time_str.split(":")[:2])
        period = "PM" if h >= 12 else "AM"
        hour_12 = h % 12 or 12
        return f"{hour_12}:{m:02d} {period}"
    except (ValueError, TypeError):
        return time_str


def format_duration(minutes: int) -> str:
    """Converts 36 -> '36m', 75 -> '1h 15m', 120 -> '2h'."""
    minutes = max(0, int(minutes))
    h = minutes // 60
    m = minutes % 60
    if h > 0 and m > 0:
        return f"{h}h {m}m"
    elif h > 0:
        return f"{h}h"
    else:
        return f"{m}m"


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


@app.get("/api/now-and-next")
def get_now_and_next(
    sim_day: Optional[int] = Query(None, ge=0, le=6),
    sim_time: Optional[str] = Query(None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$"),
    tags: Optional[str] = Query(None),
):
    now_campus = datetime.now(CAMPUS_TZ)
    current_day = sim_day if sim_day is not None else now_campus.weekday()
    current_time = sim_time if sim_time else now_campus.strftime("%H:%M")
    curr_mins = time_to_minutes(current_time)

    # Date anchor for dated W&M events:
    day_diff = current_day - now_campus.weekday()
    current_date = now_campus.date() + timedelta(days=day_diff)
    today_d = current_date
    today_iso = current_date.isoformat()

    h, m = map(int, current_time.split(":"))
    now_dt = datetime(current_date.year, current_date.month, current_date.day, h, m, 0, tzinfo=CAMPUS_TZ)
    now_iso = now_dt.isoformat()
    in_3h_dt = now_dt + timedelta(hours=3)
    in_3h_iso = in_3h_dt.isoformat()

    student_tags: list[str] = []
    if tags:
        for t in re.split(r"[,\s]+", tags):
            clean = t.strip().lstrip("#").upper()
            if clean:
                student_tags.append(clean)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM user_classes WHERE day_of_week = ? ORDER BY start_time ASC",
        (current_day,),
    )
    classes = [dict(r) for r in cur.fetchall()]

    today_classes = []
    current_class = None
    next_class = None

    for cl in classes:
        cl_start = time_to_minutes(cl["start_time"])
        cl_end = time_to_minutes(cl["end_time"])

        enriched_cl = dict(cl)
        start_12h = format_12h(cl["start_time"])
        end_12h = format_12h(cl["end_time"])
        enriched_cl["start_time_12h"] = start_12h
        enriched_cl["end_time_12h"] = end_12h
        enriched_cl["time_range_12h"] = f"{start_12h} – {end_12h}"

        if curr_mins > cl_end:
            enriched_cl["status"] = "completed"
            enriched_cl["minutes_remaining"] = None
            enriched_cl["minutes_until_start"] = None
            enriched_cl["status_label"] = "Completed"
        elif cl_start <= curr_mins <= cl_end:
            enriched_cl["status"] = "current"
            m_rem = cl_end - curr_mins
            enriched_cl["minutes_remaining"] = m_rem
            enriched_cl["minutes_until_start"] = None
            enriched_cl["status_label"] = f"In Session · {format_duration(m_rem)} left"
            if current_class is None:
                current_class = enriched_cl
        else:
            enriched_cl["status"] = "upcoming"
            m_start = cl_start - curr_mins
            enriched_cl["minutes_remaining"] = None
            enriched_cl["minutes_until_start"] = m_start
            enriched_cl["status_label"] = f"Starts in {format_duration(m_start)}"
            if next_class is None:
                next_class = enriched_cl

        today_classes.append(enriched_cl)

    academic_summary = {
        "total_today": len(today_classes),
        "completed_count": sum(1 for c in today_classes if c["status"] == "completed"),
        "has_current": current_class is not None,
        "has_upcoming": next_class is not None,
    }

    cur.execute(
        "SELECT * FROM club_events WHERE day_of_week = ? ORDER BY start_time ASC",
        (current_day,),
    )
    events = [dict(r) for r in cur.fetchall()]

    # Query dated wm_events
    cur.execute("SELECT * FROM wm_events ORDER BY start_at ASC")
    all_wm_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    happening_now = []
    starting_soon = []
    upcoming_today = []
    wm_processed = []

    for ev in events:
        ev_start = time_to_minutes(ev["start_time"])
        ev_end = time_to_minutes(ev["end_time"])

        conflict_course = None
        for cl in classes:
            if ev["start_time"] < cl["end_time"] and ev["end_time"] > cl["start_time"]:
                conflict_course = cl["course_name"]
                break
        ev["has_conflict"] = conflict_course is not None
        ev["conflicting_course"] = conflict_course
        ev["matched_tags"] = match_tags(ev, student_tags)

        if ev_start <= curr_mins <= ev_end:
            ev["minutes_remaining"] = ev_end - curr_mins
            ev["status_label"] = f"In Session · {ev_end - curr_mins}m left"
            happening_now.append(ev)
        elif 0 < (ev_start - curr_mins) <= 180:
            ev["starts_in_minutes"] = ev_start - curr_mins
            ev["status_label"] = f"Starts in {ev_start - curr_mins}m"
            starting_soon.append(ev)
        elif ev_start > curr_mins:
            ev["starts_in_minutes"] = ev_start - curr_mins
            ev["status_label"] = f"Starts in {ev_start - curr_mins}m"
            upcoming_today.append(ev)

    for r in all_wm_rows:
        try:
            r["categories"] = json.loads(r["categories"]) if isinstance(r["categories"], str) else (r["categories"] or [])
        except Exception:
            r["categories"] = []
        r["is_all_day"] = bool(r["is_all_day"])

        if r["is_all_day"]:
            try:
                ev_start_d = date.fromisoformat(r["start_at"][:10])
                ev_end_d = date.fromisoformat(r["end_at"][:10]) if r.get("end_at") else (ev_start_d + timedelta(days=1))
                if not (ev_start_d <= today_d < ev_end_d):
                    continue
            except Exception:
                continue
            r["status_label"] = "All Day Today"
            r["is_wm_event"] = True
            r["has_conflict"] = False
            r["conflicting_course"] = None
            r["matched_tags"] = match_tags(r, student_tags)
            happening_now.append(r)
            wm_processed.append(r)
        else:
            try:
                st = datetime.fromisoformat(r["start_at"].replace("Z", "+00:00")).astimezone(CAMPUS_TZ)
                en = datetime.fromisoformat(r["end_at"].replace("Z", "+00:00")).astimezone(CAMPUS_TZ) if r.get("end_at") else st
            except Exception:
                continue

            is_active = (st <= now_dt < en)
            is_soon = (st > now_dt and (st - now_dt).total_seconds() <= 3 * 3600 and st.date() == today_d)
            if not (is_active or is_soon):
                continue

            r["is_wm_event"] = True
            r["matched_tags"] = match_tags(r, student_tags)

            # Conflict check with today's classes
            r["has_conflict"] = False
            r["conflicting_course"] = None
            ev_start_str = st.strftime("%H:%M")
            ev_end_str = en.strftime("%H:%M")
            for cl in classes:
                if ev_start_str < cl["end_time"] and ev_end_str > cl["start_time"]:
                    r["has_conflict"] = True
                    r["conflicting_course"] = cl["course_name"]
                    break

            if is_active:
                if (en.date() - st.date()).days >= 1:
                    r["status_label"] = "Ongoing"
                else:
                    m_left = max(0, int((en - now_dt).total_seconds() / 60))
                    r["status_label"] = f"In Session · {m_left}m left"
                    r["minutes_remaining"] = m_left
                happening_now.append(r)
            elif is_soon:
                m_start = max(0, int((st - now_dt).total_seconds() / 60))
                r["status_label"] = f"Starts in {m_start}m"
                r["starts_in_minutes"] = m_start
                starting_soon.append(r)

            wm_processed.append(r)

    # Prioritize events: matched student tags first, then ending soonest (for in-session) or starting soonest
    happening_now.sort(key=lambda ev: (
        0 if ev.get("matched_tags") else 1,
        ev.get("minutes_remaining") if ev.get("minutes_remaining") is not None else 999999
    ))
    starting_soon.sort(key=lambda ev: (
        0 if ev.get("matched_tags") else 1,
        ev.get("starts_in_minutes") if ev.get("starts_in_minutes") is not None else 999999
    ))

    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return {
        "current_day": current_day,
        "current_day_name": days_of_week[current_day],
        "current_time": current_time,
        "is_simulated": sim_day is not None or sim_time is not None,
        "current_class": current_class,
        "next_class": next_class,
        # active_class is retained as an alias to current_class for backward compatibility with legacy clients
        "active_class": current_class,
        "today_classes": today_classes,
        "academic_summary": academic_summary,
        "happening_now": happening_now,
        "starting_soon": starting_soon,
        "upcoming_today": upcoming_today,
        "wm_events": wm_processed,
    }


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


# --- Class Routes & Presets ---

WM_COURSE_PRESETS = [
    {
        "course_name": "CSCI 141: Computational Problem Solving",
        "department": "CSCI",
        "days": [0, 2, 4],
        "days_label": "MWF",
        "start_time": "10:00",
        "end_time": "10:50",
        "location": "Jones 100",
        "time_range_12h": "10:00 AM – 10:50 AM",
    },
    {
        "course_name": "CSCI 241: Data Structures",
        "department": "CSCI",
        "days": [0, 2],
        "days_label": "MW",
        "start_time": "14:00",
        "end_time": "15:15",
        "location": "Jones 301",
        "time_range_12h": "2:00 PM – 3:15 PM",
    },
    {
        "course_name": "CSCI 303: Algorithms",
        "department": "CSCI",
        "days": [1, 3],
        "days_label": "TR",
        "start_time": "11:00",
        "end_time": "12:15",
        "location": "McGlothlin 020",
        "time_range_12h": "11:00 AM – 12:15 PM",
    },
    {
        "course_name": "DATA 141: Programming for Data Science",
        "department": "DATA",
        "days": [0, 2, 4],
        "days_label": "MWF",
        "start_time": "13:00",
        "end_time": "13:50",
        "location": "Blow 332",
        "time_range_12h": "1:00 PM – 1:50 PM",
    },
    {
        "course_name": "MATH 211: Linear Algebra",
        "department": "MATH",
        "days": [1, 3],
        "days_label": "TR",
        "start_time": "15:30",
        "end_time": "16:50",
        "location": "Jones 202",
        "time_range_12h": "3:30 PM – 4:50 PM",
    },
    {
        "course_name": "PHIL 201: Introduction to Philosophy",
        "department": "PHIL",
        "days": [1, 3],
        "days_label": "TR",
        "start_time": "09:30",
        "end_time": "10:50",
        "location": "Wren 200",
        "time_range_12h": "9:30 AM – 10:50 AM",
    },
    {
        "course_name": "BIOL 204: Introduction to Biology",
        "department": "BIOL",
        "days": [0, 2, 4],
        "days_label": "MWF",
        "start_time": "09:00",
        "end_time": "09:50",
        "location": "ISC 1127",
        "time_range_12h": "9:00 AM – 9:50 AM",
    },
]

WM_SLOT_PATTERNS = [
    {
        "name": "MWF 50m",
        "days": [0, 2, 4],
        "days_label": "MWF",
        "slots": [
            {"start_time": "09:00", "end_time": "09:50", "label": "09:00–09:50"},
            {"start_time": "10:00", "end_time": "10:50", "label": "10:00–10:50"},
            {"start_time": "11:00", "end_time": "11:50", "label": "11:00–11:50"},
            {"start_time": "13:00", "end_time": "13:50", "label": "13:00–13:50"},
            {"start_time": "14:00", "end_time": "14:50", "label": "14:00–14:50"},
        ],
    },
    {
        "name": "MW / TR 75m",
        "days_label": "MW / TR",
        "slots": [
            {"start_time": "09:30", "end_time": "10:50", "label": "09:30–10:50"},
            {"start_time": "11:00", "end_time": "12:15", "label": "11:00–12:15"},
            {"start_time": "12:30", "end_time": "13:45", "label": "12:30–13:45"},
            {"start_time": "14:00", "end_time": "15:15", "label": "14:00–15:15"},
            {"start_time": "15:30", "end_time": "16:45", "label": "15:30–16:45"},
        ],
    },
]


@app.get("/api/classes/presets")
def get_class_presets():
    return {
        "courses": WM_COURSE_PRESETS,
        "slots": WM_SLOT_PATTERNS,
    }


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
    Checks a proposed event time against scheduled classes, club events, and room conflicts.
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
        norm_requested = normalize_wm_location(location).strip().lower()
        for ev in competing_events:
            ev_loc = ev.get("location") or ""
            norm_ev_loc = normalize_wm_location(ev_loc).strip().lower()
            if norm_ev_loc and norm_ev_loc == norm_requested:
                loc_clash = True
                clash_event_title = ev["title"]
                break

    # Summarize schedule conflicts.
    class_count = len(conflicting_classes)
    event_count = len(competing_events)

    if loc_clash:
        status_code = "ROOM_CLASH"
        advice = f"{clash_event_title} already uses this room at that time."
    elif class_count == 0 and event_count == 0:
        status_code = "CLEAR"
        advice = "No class or club event conflicts found."
    elif class_count > 0 and event_count == 0:
        status_code = "CLASS_OVERLAP"
        advice = "Your class schedule overlaps this time."
    elif class_count == 0 and event_count > 0:
        status_code = "CLUB_OVERLAP"
        advice = "Another club event overlaps this time."
    else:
        status_code = "HEAVY_OVERLAP"
        advice = "Classes and club events overlap this time."

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
def get_weekly_schedule(sim_day: Optional[int] = Query(None, ge=0, le=6)):
    """
    Build a seven-day view of classes and recurring club events.
    Overlaps are reported for planning and do not block event creation.
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM user_classes ORDER BY day_of_week ASC, start_time ASC")
    classes = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM club_events ORDER BY day_of_week ASC, start_time ASC")
    events = [dict(r) for r in cur.fetchall()]
    conn.close()

    current_day = sim_day if sim_day is not None else datetime.now(CAMPUS_TZ).weekday()
    days_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_data = []

    total_classes = len(classes)
    total_events = len(events)
    conflicted_events = 0

    for d in range(7):
        day_classes = [c for c in classes if c["day_of_week"] == d]
        day_events_raw = [e for e in events if e["day_of_week"] == d]

        enriched_classes = []
        for cl in day_classes:
            st_12h = format_12h(cl["start_time"])
            et_12h = format_12h(cl["end_time"])
            enriched_classes.append({
                **cl,
                "type": "class",
                "start_time_12h": st_12h,
                "end_time_12h": et_12h,
                "time_range_12h": f"{st_12h} – {et_12h}",
            })

        enriched_events = []
        for ev in day_events_raw:
            conflicts = []
            for cl in day_classes:
                if ev["start_time"] < cl["end_time"] and ev["end_time"] > cl["start_time"]:
                    conflicts.append(cl)

            has_conf = len(conflicts) > 0
            if has_conf:
                conflicted_events += 1

            st_12h = format_12h(ev["start_time"])
            et_12h = format_12h(ev["end_time"])
            enriched_events.append({
                **ev,
                "type": "event",
                "start_time_12h": st_12h,
                "end_time_12h": et_12h,
                "time_range_12h": f"{st_12h} – {et_12h}",
                "has_conflict": has_conf,
                "conflicting_course": conflicts[0]["course_name"] if has_conf else None,
                "conflicting_classes": conflicts,
            })

        timeline = sorted(
            enriched_classes + enriched_events,
            key=lambda item: (item["start_time"], item["end_time"], 0 if item.get("type") == "class" else 1),
        )

        days_data.append({
            "day_index": d,
            "day_name": days_names[d],
            "is_today": (d == current_day),
            "total_commitments": len(timeline),
            "timeline": timeline,
            "classes": enriched_classes,
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
