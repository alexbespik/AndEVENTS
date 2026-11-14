# ROLE & OBJECTIVE
Act as an autonomous code-generation agent for Antigravity (AGY) and OpenAI Codex CLI. Do not ask clarifying questions, do not suggest alternative stacks, and do not use build steps (no Webpack/Vite/npm). Implement the exact specification below.

# ANTI-SLOP & DESIGN SYSTEM GUIDELINES (&EDU & Hallmark)
All UI components, typography, and styling strictly follow the **&.edu / AndEDU engineering design system** (https://github.com/alexbespik/AndEDU) and **anti-slop principles**:
- **Zero AI Slop**: No cheesy sci-fi buzzwords (no "Campus Radar"), no blinking/pulsing animations, no glowing neon buttons, no giant rounded cards.
- **Typography**:
  - Headings & Mark: `Libre Caslon Text`, Georgia, serif
  - Code, Badges, 24h Times, Numbers & Tabs: `IBM Plex Mono`, monospace (with tabular-nums)
  - Body & Reading: `IBM Plex Sans`, -apple-system, sans-serif
- **Color Palette & Design Tokens**:
  - Deep Griffin Green Frame: `--side-bg: #0b3b2c` (Light) / `#07140f` (Dark)
  - Stone Paper / Surface: `--paper: #f1f0ea` / `#050806`, `--surface: #ffffff` / `#0e1411`
  - Caslon Gold Accents: `--gold: #c9a24a` / `#e0bb62`, `--gold-text: #6f5114` / `#e8c877`
  - Interactive Green: `--accent: #0e4a37` / `#5aae8b`
  - Status Indicators: Available `--ok: #0e4a37` / `#5fb390`, Planning Note `--gold: #c9a24a`, Warning `--bad: #9a2b2b` / `#e27f72`
- **Browser Favicon**: Browser icon uses the Caslon Gold ampersand on dark background (`static/favicon.svg`).
- **Geometry**: Crisp, square-ish corners (`--radius-sm: 3px`, `--radius-md: 6px`), faint engineering grid background (`24px 24px`).

# TECH STACK & FILE TREE
- Backend: Python 3.11+, FastAPI, Uvicorn, Pydantic, built-in `sqlite3` (no SQLAlchemy).
- Persistence: High-concurrency SQLite with WAL mode (`PRAGMA journal_mode = WAL;`) and compound indexes.
- Frontend: Single-file Vanilla HTML5 + CSS + Vanilla JS (`fetch` API). Zero build steps.
- Time Format: Strict 24-hour `HH:MM` zero-padded strings (`00:00` to `23:59`).
- Directory Structure:
  .
  ├── app.py
  ├── requirements.txt
  ├── AGENTS.md
  ├── .gitignore
  ├── .env.example
  ├── tests/
  │   └── test_api.py
  ├── .codex/
  │   ├── config.toml
  │   └── agents/
  │       ├── researcher.toml
  │       ├── architect.toml
  │       ├── overseer.toml
  │       ├── coder.toml
  │       ├── tester.toml
  │       ├── reviewer.toml
  │       ├── security.toml
  │       ├── explorer.toml
  │       └── bookkeeper.toml
  └── static/
      ├── favicon.svg
      └── index.html

# STEP 1: DATABASE SCHEMA (`schedule.db` in `app.py`)
Tables:
1. `club_events`
   - `id` INTEGER PRIMARY KEY AUTOINCREMENT
   - `title` TEXT NOT NULL
   - `club_name` TEXT NOT NULL
   - `category` TEXT NOT NULL
   - `day_of_week` INTEGER NOT NULL (0=Mon .. 6=Sun)
   - `start_time` TEXT NOT NULL (Strict 'HH:MM')
   - `end_time` TEXT NOT NULL (Strict 'HH:MM')
   - `location` TEXT NOT NULL
   - `description` TEXT
2. `user_classes`
   - `id` INTEGER PRIMARY KEY AUTOINCREMENT
   - `course_name` TEXT NOT NULL
   - `day_of_week` INTEGER NOT NULL (0=Mon .. 6=Sun)
   - `start_time` TEXT NOT NULL
   - `end_time` TEXT NOT NULL
   - `location` TEXT
3. `app_meta`
   - `key` TEXT PRIMARY KEY
   - `value` TEXT
Indexes:
- `idx_club_events_day_time ON club_events (day_of_week, start_time)`
- `idx_user_classes_day_time ON user_classes (day_of_week, start_time)`

# STEP 2: REST API ENDPOINTS (`app.py`)
- `GET /`: Serve `static/index.html`.
- `GET /favicon.svg` & `GET /favicon.ico`: Serve `static/favicon.svg`.
- `GET /api/events`:
  - Query params: `day` (optional 0-6), `category`, `club_name`, `search`, `hide_conflicts` (bool), `only_now` (bool), `sim_day`, `sim_time`.
  - Returns list of events with computed `has_conflict`, `conflicting_course`, `is_happening_now`, `starts_soon`, `can_attend_now`.
- `POST /api/events` (HTTP 201):
  - Accepts JSON `{ "title": str, "club_name": str, "category": str, "day_of_week": int, "start_time": "HH:MM", "end_time": "HH:MM", "location": str, "description": str }`.
  - Validates `start_time < end_time` and non-blank fields. Inserts into `club_events`.
- `DELETE /api/events/{event_id}`:
  - Deletes event by `id`. Returns 404 if not found.
- `GET /api/classes`:
  - Returns all user classes sorted by `day_of_week ASC, start_time ASC`.
- `POST /api/classes/batch`:
  - Accepts JSON `{ "course_name": str, "days": list[int], "start_time": "HH:MM", "end_time": "HH:MM", "location": str }`.
  - Inserts one row per day.
- `DELETE /api/classes/{class_id}`:
  - Deletes class entry by `id`.
- `DELETE /api/classes`:
  - Clears all user classes (persists across restarts via `app_meta`).
- `GET /api/planning/creator-conflicts`:
  - Creator Planning Endpoint: parameters `day`, `start_time`, `end_time`, `location`.
  - Analyzes overlapping student classes and competing club meetings. Checks room collision. Returns feasibility report and scheduling advice.
- `GET /api/planning/weekly-schedule`:
  - Non-Creator / Student Planning Endpoint: returns 7-day chronological timetable pairing classes with club events, marking conflicts gently as planning notes.

# STEP 3: FRONTEND USER EXPERIENCE (`static/index.html`)
Three distinct modes toggled via masthead navigation tabs:
1. `Directory` (`&.directory`):
   - Daily schedule stream of club events and meetings with search, day, category, and conflict filters.
2. `Weekly Planner` (`&.planner`):
   - 7-day chronological timetable matrix for attendees.
   - Shows registered student lectures alongside scheduled club events.
   - Highlights class overlaps as gentle planning notes (`⚡ Planning note: overlaps with [Course]`), allowing students to weigh trade-offs without blocking.
3. `Organizer Lab` (`&.organizer`):
   - Event creation form for club leaders with a live timeslot conflict inspector.
   - Real-time room collision alerts and competing event detection.
   - Published event management directory with deletion controls.
4. Left Sidebar:
   - Dedicated Class Schedule Manager with day pills (`Mon`–`Sun`), 24h start/end time inputs, and active class directory with deletion controls.
