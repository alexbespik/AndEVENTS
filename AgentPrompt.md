# ROLE & OBJECTIVE
Act as an autonomous code-generation agent for Antigravity (AGY) and OpenAI Codex CLI. Do not ask clarifying questions, do not suggest alternative stacks, and do not use build steps (no Webpack/Vite/npm). Implement the exact specification below.

# DESIGN SYSTEM & AESTHETIC (AndEDU Specification)
All UI components, typography, and styling must follow the **&.edu / AndEDU engineering design system** (https://github.com/alexbespik/AndEDU):
- Typography:
  - Heading & Display: `Libre Caslon Text`, Georgia, serif
  - Code, Badges, 24h Times, Numbers & Tabs: `IBM Plex Mono`, monospace (with tabular-nums)
  - Body & Reading: `IBM Plex Sans`, -apple-system, sans-serif
- Color Palette & Tokens:
  - Deep Griffin Green Frame: `--side-bg: #0b3b2c` (Light) / `#07140f` (Dark)
  - Stone Paper / Surface: `--paper: #f1f0ea` / `#050806`, `--surface: #ffffff` / `#0e1411`
  - Caslon Gold Accents: `--gold: #c9a24a` / `#e0bb62`, `--gold-text: #6f5114` / `#e8c877`
  - Interactive Green: `--accent: #0e4a37` / `#5aae8b`
  - Status Indicators: Available `--ok: #0e4a37` / `#5fb390`, Conflict `--bad: #9a2b2b` / `#e27f72`
- Geometry: Crisp, square-ish corners (`--radius-sm: 3px`, `--radius-md: 6px`), faint engineering grid background (`24px 24px`), no generic glowing gradients or oversized border-radius cards.

# TECH STACK & FILE TREE
- Backend: Python 3.11+, FastAPI, Uvicorn, Pydantic, built-in `sqlite3` (no SQLAlchemy).
- Frontend: Single-file Vanilla HTML5 + CSS (AndEDU Design System) + Vanilla JS (`fetch` API).
- Time Format: Strict 24-hour `HH:MM` zero-padded strings (`00:00` to `23:59`).
- Directory Structure:
  .
  ├── app.py
  ├── requirements.txt
  ├── AGENTS.md
  ├── .gitignore
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
      └── index.html

# STEP 1: DATABASE SCHEMA (`schedule.db` in `app.py`)
Create two tables on startup if they do not exist:

1. `club_events`
   - `id` INTEGER PRIMARY KEY AUTOINCREMENT
   - `title` TEXT NOT NULL
   - `club_name` TEXT NOT NULL
   - `category` TEXT NOT NULL  -- e.g., 'Tech', 'Sports', 'Academic', 'Gaming', 'Social'
   - `day_of_week` INTEGER NOT NULL -- 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
   - `start_time` TEXT NOT NULL -- Strict 'HH:MM' 24h format
   - `end_time` TEXT NOT NULL   -- Strict 'HH:MM' 24h format
   - `location` TEXT NOT NULL
   - `description` TEXT

2. `user_classes`
   - `id` INTEGER PRIMARY KEY AUTOINCREMENT
   - `course_name` TEXT NOT NULL
   - `day_of_week` INTEGER NOT NULL -- 0=Mon .. 6=Sun
   - `start_time` TEXT NOT NULL -- Strict 'HH:MM' 24h format
   - `end_time` TEXT NOT NULL   -- Strict 'HH:MM' 24h format
   - `location` TEXT

# STEP 2: CONFLICT & "RIGHT NOW" LOGIC
1. Overlap Rule: A club event conflicts with a user class if and only if:
   `event.day_of_week == class.day_of_week` AND `event.start_time < class.end_time` AND `event.end_time > class.start_time`.
2. Every returned event from `GET /api/events` must compute:
   - `has_conflict`: boolean (true if overlapping with any row in `user_classes`)
   - `conflicting_course`: string or null (the `course_name` of the overlapping class)
   - `is_happening_now`: boolean (true if `event.day_of_week == current_day` AND `event.start_time <= current_time <= event.end_time`)
   - `starts_soon`: boolean (true if `event.day_of_week == current_day` AND `event.start_time > current_time` AND within 60 minutes of `current_time`)
   - `can_attend_now`: boolean (true if `(is_happening_now OR starts_soon) AND NOT has_conflict`)

# STEP 3: REST API ENDPOINTS (`app.py`)
- `GET /`: Serve `static/index.html`.
- `GET /api/events`:
  - Query params: `day` (optional int 0-6), `category` (optional str), `club_name` (optional str), `search` (optional str), `hide_conflicts` (bool, default false), `only_now` (bool, default false), `sim_day` (optional int 0-6), `sim_time` (optional str 'HH:MM').
  - Returns JSON list of events sorted by `day_of_week ASC, start_time ASC` with computed conflict and live status flags.
- `GET /api/classes`:
  - Returns all rows from `user_classes` sorted by `day_of_week ASC, start_time ASC`.
- `POST /api/classes/batch`:
  - Accepts JSON `{ "course_name": str, "days": list[int], "start_time": "HH:MM", "end_time": "HH:MM", "location": str }`.
  - Validates `start_time < end_time` and `days` within 0-6. Inserts one row per day in `days`.
- `DELETE /api/classes/{class_id}`:
  - Deletes a single class entry by `id`.
- `DELETE /api/classes`:
  - Clears all user classes.

# STEP 4: FRONTEND SPECIFICATION (`static/index.html`)
Build a high-contrast AndEDU academic dashboard:
1. Masthead:
   - Caslon Gold ampersand `&` + `.events` mark.
   - Live 24-hour clock (`HH:MM:SS`) + Day indicator with pulsing green live dot.
   - "Hackathon Demo Override" toggle: allows manual selection of simulated Day (Mon-Sun) and Time (`HH:MM`) passed as `sim_day` and `sim_time` to `/api/events`.
   - Theme toggle (Light / Dark) storing preference in `localStorage('andedu_lab_theme')`.
2. Left Column (Class Schedule Manager):
   - Background in Griffin Green (`--side-bg`).
   - Comfortable Batch Form: Course Name input, Day pills (`Mon`–`Sun` toggle chips), 24h Start/End time inputs, and Location.
   - Submit button (`.btn-gold`) saving to `POST /api/classes/batch`.
   - Grouped active classes list with tabular time ranges, room pins, individual `×` delete buttons, and a "Clear All" action.
3. Right Column (Radar & Club Events):
   - "Attend Right Now / Starting in 60m" Hero Banner: styled as an engineering lab status readout highlighting conflict-free events where `is_happening_now` or `starts_soon` is true.
   - Filter Bar: Search input (matches title/club/location), Day selector (All or Mon-Sun), Category dropdown, "Can Attend Right Now" toggle, and "Hide Class Conflicts" toggle.
   - Daily Schedule Cards: Displays `start_time - end_time`, category tag, club badge, location, and either a green "Available" badge or a red "Conflicts with [Course Name]" badge.
