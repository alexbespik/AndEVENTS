import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = Path(__file__).resolve().parent / "schedule.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Club & Class Conflict Engine")

STATIC_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


class ClassBatchCreate(BaseModel):
    course_name: str = Field(..., min_length=1, max_length=120)
    days: List[int] = Field(..., min_length=1, max_length=7)
    start_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    end_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    location: Optional[str] = Field(default="TBA", max_length=120)


@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
