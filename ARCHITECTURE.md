# &.events System Architecture

## 1. System Map & Component Boundaries

The `&.events` platform is an academic campus schedule and club event conflict engine designed following the AndEDU design system.

```mermaid
graph TD
    subgraph Browser ["Frontend Client (Zero-Build Vanilla SPA)"]
        UI_Nav["Mode Switcher: Radar | Planner | Organizer"]
        UI_Radar["View 1: Campus Radar (Live 24h & Overlap)"]
        UI_Planner["View 2: Student Weekly Planner (Mon-Sun Timetable)"]
        UI_Organizer["View 3: Event Organizer Lab (Conflict Inspector & Management)"]
        UI_Sidebar["Class Schedule Manager (Lecture Batch Form)"]
    end

    subgraph Backend ["FastAPI Backend (app.py)"]
        API_Events["/api/events (GET, POST, DELETE)"]
        API_Classes["/api/classes (GET, POST, DELETE)"]
        API_NowNext["/api/now-and-next (GET)"]
        API_WMEvents["/api/wm-events (GET)"]
        API_Planning_Conflicts["/api/planning/creator-conflicts (GET)"]
        API_Planning_Weekly["/api/planning/weekly-schedule (GET)"]
        Engine["Conflict & Live Calculation Engine"]
    end

    subgraph Ingestion ["Calendar Ingestion (wm_data.py, import_wm_events.py)"]
        SSRF["SSRF Guard (events.wm.edu, tribelink.wm.edu)"]
        Parser["RFC 5545 Parser (RRULE, DATE fix, Windows TZID)"]
        NormLoc["Location Normalizer (normalize_wm_location)"]
    end

    subgraph Storage ["Persistent SQLite (schedule.db)"]
        T_Events[("club_events")]
        T_Classes[("user_classes")]
        T_WMEvents[("wm_events")]
        T_WMCals[("wm_event_calendars")]
        T_Meta[("app_meta")]
    end

    UI_Radar -->|GET /api/now-and-next| API_NowNext
    UI_Radar -->|GET /api/events| API_Events
    UI_Sidebar -->|GET, POST /api/classes| API_Classes
    UI_Planner -->|GET /api/planning/weekly-schedule| API_Planning_Weekly
    UI_Organizer -->|GET /api/planning/creator-conflicts| API_Planning_Conflicts
    UI_Organizer -->|POST, DELETE /api/events| API_Events
    UI_Nav -->|GET /api/wm-events| API_WMEvents

    Ingestion -->|Strict HTTPS / Parse / Expand| T_WMEvents
    Ingestion -->|Calendar Mapping| T_WMCals

    API_NowNext --> Engine
    API_Events --> Engine
    API_Planning_Conflicts --> Engine
    API_Planning_Weekly --> Engine
    API_WMEvents --> T_WMEvents

    Engine --> T_Events
    Engine --> T_Classes
    Engine --> T_WMEvents
    Engine --> T_Meta
```

### Component Responsibilities & Data Ownership
| Component | Responsibility | Owned Data / State |
| :--- | :--- | :--- |
| **`app.py` (FastAPI Server)** | Boundary validation, schedule indexing, conflict calculations, REST endpoints | `schedule.db` connection lifecycle, business rules |
| **`wm_data.py`** | Safe RFC 5545 iCal parser, RRULE expansion, Windows TZID alias resolution, location normalization, SSRF host validation | Pure functions, parser and schema integrity |
| **`import_wm_events.py`** | Scheduled feed crawler & CLI importer for `events.wm.edu` and `tribelink.wm.edu` | Ingestion lifecycle, savepoint transactions |
| **`club_events` Table** | Authoritative store of weekly recurring club meetings | Campus events (title, club, category, day 0-6, start/end 24h, location, description) |
| **`user_classes` Table** | Authoritative store of student course commitments | User lecture sessions (course name, day 0-6, start/end 24h, location) |
| **`wm_events` Table** | Dated instances from official campus feeds and TribeLink student organizations | Dated event instances (uid, start_at, end_at, timezone, is_all_day, location, source_url, categories) |
| **`wm_event_calendars` Table** | Many-to-many calendar feed membership tracking | Feed slugs and calendar display names |
| **`app_meta` Table** | Database migrations and seed execution tracking | Migration version & seed flags |
| **`static/index.html`** | Zero-build single-page application with distraction-free 100% width Now & Soon view and collapsible Filters & Schedule modal | Local UI state: active view mode, filter modal open state, theme, preview time |

---

## 2. API Contracts & Boundary Schemas

All times are strict 24-hour zero-padded strings: `HH:MM` (`00:00` to `23:59`). Days are integers `0` to `6` (`0 = Monday`, `6 = Sunday`).

### 2.1 Event Management Contracts

#### `POST /api/events`
- **Status**: `201 Created`
- **Request Body (`EventCreate`)**:
```json
{
  "title": "Kernel & Dotfiles Workshop",
  "club_name": "Linux 1991 Club",
  "category": "Tech",
  "day_of_week": 0,
  "start_time": "17:00",
  "end_time": "18:30",
  "location": "ISC 1127",
  "description": "Customizing tiling window managers and shell configs."
}
```
- **Validation**:
  - `start_time < end_time` (raises `HTTP 400 Bad Request` if `start_time >= end_time`).
  - `day_of_week` in `0..6`.
  - Non-empty `title`, `club_name`, `category`, `location`.
- **Response**:
```json
{
  "id": 15,
  "title": "Kernel & Dotfiles Workshop",
  "club_name": "Linux 1991 Club",
  "category": "Tech",
  "day_of_week": 0,
  "start_time": "17:00",
  "end_time": "18:30",
  "location": "ISC 1127",
  "description": "Customizing tiling window managers and shell configs."
}
```

#### `DELETE /api/events/{event_id}`
- **Status**: `200 OK` (or `404 Not Found` if event does not exist)
- **Response**:
```json
{
  "status": "deleted",
  "id": 15
}
```

---

### 2.2 Planning & Conflict Contracts

#### `GET /api/planning/creator-conflicts`
Allows club organizers to test proposed event time windows against existing club events and student schedules.
- **Query Parameters**:
  - `day`: integer (`0..6`, required)
  - `start_time`: string (`HH:MM`, required)
  - `end_time`: string (`HH:MM`, required)
  - `location`: string (optional, checks for room collisions)
  - `exclude_event_id`: integer (optional, for event updates)
- **Validation**:
  - Raises `HTTP 400` if `start_time >= end_time`.
- **Response**:
```json
{
  "has_conflict": true,
  "slot": {
    "day": 0,
    "start_time": "14:00",
    "end_time": "15:30",
    "location": "McGlothlin-Street 020"
  },
  "summary": {
    "conflicting_events_count": 1,
    "conflicting_classes_count": 1,
    "has_location_clash": true
  },
  "conflicts": [
    {
      "type": "event",
      "id": 2,
      "name": "AI Paper Reading Group",
      "club_name": "AI Society",
      "location": "McGlothlin-Street 020",
      "day_of_week": 0,
      "start_time": "14:00",
      "end_time": "15:15",
      "severity": "location_clash"
    },
    {
      "type": "class",
      "id": 1,
      "name": "CSCI 241: Data Structures",
      "location": "Jones Hall 301",
      "day_of_week": 0,
      "start_time": "14:00",
      "end_time": "15:15",
      "severity": "class_conflict"
    }
  ]
}
```

#### `GET /api/planning/weekly-schedule`
Provides a single, consolidated source of truth for the 7-day academic week.
- **Query Parameters**: None (or optional `sim_day`, `sim_time` for demo parity)
- **Response**:
```json
{
  "days": [
    {
      "day": 0,
      "day_name": "Monday",
      "classes": [
        {
          "id": 1,
          "course_name": "CSCI 241: Data Structures",
          "day_of_week": 0,
          "start_time": "14:00",
          "end_time": "15:15",
          "location": "Jones Hall 301"
        }
      ],
      "events": [
        {
          "id": 2,
          "title": "AI Paper Reading Group",
          "club_name": "AI Society",
          "category": "Academic",
          "day_of_week": 0,
          "start_time": "14:00",
          "end_time": "15:15",
          "location": "McGlothlin-Street 020",
          "description": "Breaking down transformer attention optimizations.",
          "has_conflict": true,
          "conflicting_course": "CSCI 241: Data Structures"
        }
      ]
    }
  ],
  "stats": {
    "total_classes": 4,
    "total_events": 7,
    "conflicted_events": 2
  }
}
```

#### `GET /api/now-and-next`
Returns currently active sessions and upcoming events within 3 hours across both student club events and official W&M / TribeLink campus calendar feeds.
- **Query Parameters**:
  - `sim_day`: integer (`0..6`, optional)
  - `sim_time`: string (`HH:MM`, optional)
- **Response**:
```json
{
  "current_day": 0,
  "current_day_name": "Monday",
  "current_time": "17:15",
  "is_simulated": false,
  "active_class": null,
  "next_class": null,
  "happening_now": [
    {
      "id": 1,
      "title": "Kernel & Dotfiles Workshop",
      "club_name": "Linux 1991 Club",
      "category": "Tech",
      "day_of_week": 0,
      "start_time": "17:00",
      "end_time": "18:30",
      "location": "ISC 1127",
      "description": "Customizing tiling window managers and shell configs.",
      "has_conflict": false,
      "conflicting_course": null,
      "minutes_remaining": 75,
      "status_label": "In Session · 75m left",
      "is_all_day": false,
      "is_ongoing": false
    },
    {
      "id": "fresh-start-2026::2026-11-14",
      "title": "Fresh Start Orientation",
      "club_name": "STEP & Campus Life",
      "category": "Orientation",
      "day_of_week": 0,
      "start_time": "00:00",
      "end_time": "23:59",
      "location": "Sadler Center",
      "description": "Multi-day welcome and campus transition activities.",
      "has_conflict": false,
      "conflicting_course": null,
      "minutes_remaining": null,
      "status_label": "All Day Today",
      "is_all_day": true,
      "is_ongoing": true
    }
  ],
  "starting_soon": [],
  "upcoming_today": []
}
```

---

## 3. Database Schema & Indexing

```sql
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
);

CREATE TABLE IF NOT EXISTS user_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    location TEXT
);

CREATE TABLE IF NOT EXISTS wm_events (
    uid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT NOT NULL,
    end_at TEXT,
    timezone TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '[]',
    is_all_day INTEGER NOT NULL DEFAULT 0 CHECK (is_all_day IN (0, 1))
);

CREATE TABLE IF NOT EXISTS wm_event_calendars (
    uid TEXT NOT NULL REFERENCES wm_events(uid) ON DELETE CASCADE,
    calendar_slug TEXT NOT NULL,
    calendar_name TEXT NOT NULL,
    PRIMARY KEY (uid, calendar_slug)
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Compound indexes for zero-latency temporal lookups
CREATE INDEX IF NOT EXISTS idx_club_events_day_time ON club_events (day_of_week, start_time);
CREATE INDEX IF NOT EXISTS idx_user_classes_day_time ON user_classes (day_of_week, start_time);
CREATE INDEX IF NOT EXISTS idx_wm_events_start_at ON wm_events(start_at);
CREATE INDEX IF NOT EXISTS idx_wm_event_calendars_slug ON wm_event_calendars(calendar_slug, uid);
```

### Overlap Rule
Two periods $(S_1, E_1)$ and $(S_2, E_2)$ on day $D_1 = D_2$ overlap if and only if:
$$S_1 < E_2 \quad \text{AND} \quad E_1 > S_2$$

---

## 4. Frontend Architecture & Design System

The frontend is implemented strictly as a zero-build single page application in `static/index.html`.

### 4.1 Mode State Machine & Distraction-Free Layout
```mermaid
stateDiagram-v2
    [*] --> NowAndSoon: Default Load (100% Width Uncluttered)
    NowAndSoon --> Directory: Click "Directory" Tab
    NowAndSoon --> WeeklyPlanner: Click "Weekly Planner" Tab
    NowAndSoon --> OrganizerLab: Click "Organize" Tab
    Directory --> NowAndSoon: Click "Now & Soon" Tab
    WeeklyPlanner --> NowAndSoon: Click "Now & Soon" Tab
    OrganizerLab --> NowAndSoon: Click "Now & Soon" Tab
```

1. **Now & Soon (`live`)**:
   - 100% width, uncluttered campus pulse.
   - Shows "Happening Right Now" (including active all-day and ongoing multi-day campus & TribeLink events) and "Starting in the next 3 hours".
   - The permanent left-hand planning sidebar is completely collapsed into a neat "Filters" modal/drawer button.
2. **Filters & Schedule Modal (`#filtersModal`)**:
   - Accessible via the "Filters" button in the masthead/header.
   - Houses event search, quick day pills (`All`, `Mon`..`Sun`), category filter, conflict toggle, and student course manager.
   - Closes cleanly via Escape, backdrop click, or Close button so planning controls never compromise the live view.
3. **Directory Mode (`directory`)**:
   - Comprehensive searchable view combining imported W&M dated feeds and student club schedules.
4. **Student Weekly Planner (`planner`)**:
   - Mon–Sun 7-day grid view comparing academic classes and club events with overlap badges.
5. **Event Organizer Lab (`organizer`)**:
   - Propose event time and location; checks for class overlap and room collisions using canonicalized building names.

### 4.2 AndEDU Design System Tokens
- **Palette**:
  - Griffin Green Frame: `--side-bg: #0b3b2c` (Light) / `#07140f` (Dark)
  - Stone Paper / Surface: `--paper: #f1f0ea` / `#050806`, `--surface: #ffffff` / `#0e1411`
  - Caslon Gold Accents: `--gold: #c9a24a` / `#e0bb62`, `--gold-text: #6f5114` / `#e8c877`
  - Interactive Accent: `--accent: #0e4a37` / `#5aae8b`
  - Available Status: `--ok: #0e4a37` / `#5fb390`
  - Conflict Status: `--bad: #9a2b2b` / `#e27f72`
- **Typography**:
  - Headings: `Libre Caslon Text`, Georgia, serif
  - Code, Badges, 24h Times: `IBM Plex Mono`, monospace (tabular-nums)
  - Body: `IBM Plex Sans`, -apple-system, sans-serif
- **Geometry**:
  - Corners: `--radius-sm: 3px`, `--radius-md: 6px`
  - Engineering grid background: `24px 24px`

---

## 5. Reliability, Performance & Security

1. **SSRF Guard & Network Perimeter**:
   - Host allowlist strictly restricted to `{"events.wm.edu", "tribelink.wm.edu"}`.
   - Enforces HTTPS scheme, port 443 (or default HTTPS port), and forbids embedded user/password credentials.
   - Protects crawler and feed imports against private subnet probing and redirect hijacking.
2. **Deterministic RFC 5545 iCalendar Parsing**:
   - Recurrence Expansion (`RRULE:FREQ=DAILY|WEEKLY`, `INTERVAL`, `BYDAY`, `UNTIL`, `COUNT`, `EXDATE`) over `[now - 2 days, now + 45 days]`.
   - Generates deterministic instance UIDs: `{master_uid}::{occ_start}`.
   - Canonicalizes Windows/Exchange time zones (`"Eastern Standard Time"`, `"EST"`, `"US/Eastern"`) to `"America/New_York"`.
   - Resolves `VALUE=DATE` all-day bounds: missing or non-positive `DTEND` defaults to `DTSTART + 1 day`.
3. **Location Normalization & Conflict Accuracy**:
   - `normalize_wm_location()` canonicalizes building variants (e.g. `"Integrated Science Center"`, `"ISC"`, `"Sadler Center"`, `"Jones Hall"`) and strips extraneous `"Room"` / `"Rm."` noise.
   - Guarantees room collision detection (`ROOM_CLASH`) regardless of minor differences in address spelling.
4. **Performance & Concurrency**:
   - Compound indexes `(day_of_week, start_time)` and `(start_at)` eliminate table scans.
   - SQLite WAL mode and foreign key integrity.
   - Zero-build vanilla JS ensures instant page load (<50ms) with zero bundle bloat.
5. **Security**:
   - Parameterized SQL queries (`?` placeholders) prevent SQL injection across all endpoints.
   - HTML sanitization (`escapeHtml`) on the client prevents Cross-Site Scripting (XSS).
   - Strict 127.0.0.1 default binding for development.
