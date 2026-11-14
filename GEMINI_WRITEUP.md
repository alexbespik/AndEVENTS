# &.events (AndEVENTS) — Complete System Architecture & Agent Specification

> **Engineering Reference & Agent Guide for Google Gemini & Antigravity Multi-Agent Systems**
> **Repository**: [https://github.com/alexbespik/AndEVENTS](https://github.com/alexbespik/AndEVENTS)
> **Design Ancestry**: Inspired by &EDU ([https://github.com/alexbespik/AndEDU](https://github.com/alexbespik/AndEDU))
> **Aesthetic Standard**: Hallmark Anti-Slop ([https://github.com/nutlope/hallmark](https://github.com/nutlope/hallmark))

---

## 1. Project Overview & Mission

`&.events` is an academic extracurricular scheduling engine designed for university students and student organizations.

### The Problem It Solves
University campuses suffer from severe information fragmentation:
1. **Student Clubs** publish recurring weekly meetings across Instagram, Discord, and flyers.
2. **Academic Courses** take precedence in a student's weekly routine; students constantly ask: *"What can I actually attend right now without skipping my physics lecture or data structures lab?"*
3. **University Departments** publish dated public lectures, symposia, and athletic games via official university calendar feeds (e.g. William & Mary events directory).
4. **Club Organizers** schedule meetings blindly without knowing when student classes peak or whether a specific room (e.g. `ISC 1127` or `Small Hall 110`) is already occupied.

### The Solution
`&.events` unifies all campus activities into an ultra-fast, local-first web application:
- **Default "Now & Soon" Live View**: Answers the student's immediate question without cognitive clutter: *What is happening on campus right now? What starts in the next 1–3 hours? Am I free right now?*
- **Browser Event Notifications**: Uses the native Web Notification API (`Notification.requestPermission()`) to alert students 15 minutes before sessions begin.
- **Student Class Schedule Manager**: Allows students to input their weekly class schedule with course name, days of the week, start/end times, and room location.
- **Creator Feasibility & Room Clash Inspector**: Real-time conflict engine for student organizers to evaluate time slots for student class density and direct room collisions before publishing.
- **Weekly Schedule Matrix**: A 7-day chronological planner pairing classes with club meetings, treating overlaps as soft planning notes rather than blockers.
- **Automated Public Feed Importer**: Scrapes and synchronizes hundreds of official William & Mary iCalendar feeds into SQLite with timezone-aware conflict detection.

---

## 2. Technology Stack & Zero-Build Philosophy

| Layer | Technology | Key Architectural Decisions |
| :--- | :--- | :--- |
| **Backend** | Python 3.11+ / FastAPI | High-performance asynchronous REST endpoints, Pydantic data validation. |
| **Database** | SQLite 3 (`schedule.db`) | WAL mode (`PRAGMA journal_mode = WAL;`), foreign keys enabled, compound B-tree indexes. |
| **Data Importer** | Python standard library | `urllib.request`, `html.parser`, `zoneinfo.ZoneInfo`, custom unfolding RFC 5545 parser. |
| **Frontend** | Vanilla HTML5, CSS3, JS | **Zero build step** (no Node.js, Vite, Webpack, or npm runtime dependencies). Single fast deliverable. |
| **Design System** | `static/lab.css` | Authentic &EDU design tokens (Deep Griffin Green `#0b3b2c`, Warm Stone Paper `#f1f0ea`, Caslon Gold `#c9a24a`). |
| **Typography** | Google Fonts | `Libre Caslon Text` (editorial serif headings), `IBM Plex Mono` (tabular metadata & controls), `IBM Plex Sans` (reading copy). |

---

## 3. Database Architecture & Schema

The database runs in SQLite with Write-Ahead Logging (`WAL`) mode enabled to permit concurrent read queries without blocking write transactions.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. Weekly recurring club meetings
CREATE TABLE IF NOT EXISTS club_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    club_name TEXT NOT NULL,
    category TEXT NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time TEXT NOT NULL, -- Format: 'HH:MM' (24-hour)
    end_time TEXT NOT NULL,   -- Format: 'HH:MM' (24-hour)
    location TEXT NOT NULL,
    description TEXT
);

-- 2. Student enrolled classes
CREATE TABLE IF NOT EXISTS user_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time TEXT NOT NULL, -- Format: 'HH:MM' (24-hour)
    end_time TEXT NOT NULL,   -- Format: 'HH:MM' (24-hour)
    location TEXT
);

-- 3. University public dated events (W&M iCal importer)
CREATE TABLE IF NOT EXISTS wm_events (
    uid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT NOT NULL,   -- ISO-8601 string: 'YYYY-MM-DDTHH:MM:SS-05:00'
    end_at TEXT,             -- ISO-8601 string: 'YYYY-MM-DDTHH:MM:SS-05:00'
    timezone TEXT NOT NULL,  -- e.g. 'America/New_York'
    location TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '[]', -- JSON array of strings
    is_all_day INTEGER NOT NULL DEFAULT 0 CHECK (is_all_day IN (0, 1))
);

-- 4. Many-to-many relationship mapping events to calendar feeds
CREATE TABLE IF NOT EXISTS wm_event_calendars (
    uid TEXT NOT NULL REFERENCES wm_events(uid) ON DELETE CASCADE,
    calendar_slug TEXT NOT NULL,
    calendar_name TEXT NOT NULL,
    PRIMARY KEY (uid, calendar_slug)
);

-- 5. Persistent seeding metadata table (prevents cleared classes from resurrecting)
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- High-performance compound indexes for interval scanning
CREATE INDEX IF NOT EXISTS idx_club_events_day_time ON club_events (day_of_week, start_time);
CREATE INDEX IF NOT EXISTS idx_user_classes_day_time ON user_classes (day_of_week, start_time);
CREATE INDEX IF NOT EXISTS idx_wm_events_start_at ON wm_events (start_at);
CREATE INDEX IF NOT EXISTS idx_wm_event_calendars_slug ON wm_event_calendars (calendar_slug, uid);
```

---

## 4. Conflict Detection Algorithm

Interval collisions between student classes $[S_c, E_c)$ and club events $[S_e, E_e)$ are computed using closed-open interval overlap math:
$$\text{Conflict} \iff (D_c = D_e) \land (S_e < E_c) \land (E_e > S_c)$$

In Python (`app.py`), 24-hour strings (`"14:00"`) are converted into minutes from midnight:
```python
def time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 60 + m
```

### Conflict Categories
1. **Live Attendance Filtering (`/api/events?only_now=true`)**: Checks if current campus time is between event start and end, and filters out events that overlap with an active class.
2. **Organizer Feasibility Inspector (`/api/planning/creator-conflicts`)**:
   - `ROOM_CLASH`: Another event is scheduled in the exact same room at the same time.
   - `CLEAR`: Zero overlapping student classes and zero competing club events.
   - `CLASS_OVERLAP`: Students have classes at that time.
   - `CLUB_OVERLAP`: Another club is hosting an event at the same time.
   - `HEAVY_OVERLAP`: Both classes and clubs conflict.

---

## 5. Live W&M Calendar Scraping Engine

The importer module (`import_wm_events.py` and `wm_data.py`) features:
1. **Live Feed Discovery**: Starts at `https://events.wm.edu/search/all_calendars`, parses HTML using `HTMLParser`, and identifies all active department calendar links.
2. **SSRF Guard**: Strict `SameHostRedirects` handler ensuring redirects never leave `events.wm.edu` and use standard HTTPS (port 443).
3. **Robust iCalendar Parser**: Handles RFC 5545 line unfolding (folded whitespace continuation lines), escaped semicolons/commas, cancelled event filtering, all-day date instances (`VALUE=DATE`), and timezone offsets.
4. **Timezone Normalization**: All timestamps are converted to `zoneinfo.ZoneInfo("America/New_York")` before checking against class schedules.
5. **Idempotent Upsert**: Events are inserted or updated using atomic SQLite transactions with savepoints.

---

## 6. Frontend Design Architecture

The UI strictly follows the authentic **&EDU** design system and the **Hallmark Anti-Slop** manifesto:

### The "L-Frame" Layout
- **Top Masthead**: Background `#0b0f0d` (near black), Caslon Gold `&` monogram, `.events` mark, active mode indicator with gold bottom bar (`height: 2px; background: var(--gold)`), live campus clock, preview time toggle, and System/Light/Dark theme switcher.
- **Left Sidebar**: Full-height Dark Griffin Green (`#0b3b2c`), containing the student's enrolled class schedule and quick filters.
- **Main Canvas**: Warm stone paper (`#f1f0ea` in light, `#050806` in dark) with a faint 32px engineering grid pattern (`linear-gradient(var(--grid) 1px, transparent 1px)`).
- **Page Head**: Signature breadcrumbs prefixed with `~/` and academic serif `h1` underscored by a 48px gold bar (`h1::after`).

### Four Focused Modes
1. **Now & Soon (`#viewLive`)**: Default front page. Shows:
   - Student real-time status banner (*"Free right now. Next class is MATH 211 at 15:30 in Jones 202"*).
   - Events currently in session with countdown timers.
   - Events starting in the next 3 hours with a one-click *"Notify me"* button.
2. **Campus Directory (`#viewDirectory`)**: Full catalog with fast search, day pills, category dropdown, and W&M public calendar feeds.
3. **Weekly Schedule Matrix (`#viewPlanner`)**: 7-day chronological planner pairing classes with club meetings.
4. **Organizer Lab (`#viewOrganizer`)**: Form for club leaders to publish meetings with live feasibility and room collision diagnostics.

---

## 7. Instructions for Google Gemini & Multi-Agent Teams

When continuing development on this codebase, adhere strictly to the following agent protocols:

1. **Task Sizing**:
   - Small edits (<30 lines, single file) may be executed directly with test verification.
   - Large or architectural features must invoke `researcher` → `architect` → `overseer` (PLAN) → `coder` → `tester` + `reviewer` → `security` → `overseer` (DONE).
2. **Security Invariant**:
   - Never print or commit secrets, tokens, or environment files.
   - Always run the `security` subagent before committing changes.
   - Ensure all dynamic HTML interpolations use `escapeHtml()` and avoid inline attribute string evaluation.
3. **Empirical Verification**:
   - Never claim tests pass without running `python3 -m unittest discover -s tests` and reporting actual terminal output.
4. **Anti-Slop Discipline**:
   - Avoid glowing neon effects, artificial radar sweeps, vibrating buttons, and pulsing dots.
   - Maintain the understated, editorial aesthetic of William & Mary and &EDU.
