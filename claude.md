# Master Engineering & Refactoring Plan for Claude: `&.events`

> **Target Audience**: Incoming Lead Engineer / AI Agent (Claude 3.7 Sonnet / Claude 3.5 Sonnet).  
> **Repository**: `&.events` (AndEVENTS)  
> **Destination**: To be merged into `&.edu` (AndEDU - [github.com/alexbespik/AndEDU](https://github.com/alexbespik/AndEDU)).  
> **Local Server**: `http://127.0.0.1:8000` (`python3 -m uvicorn app:app --reload --port 8000`).

---

## 1. Executive Project Overview & Mission

`&.events` is a high-performance, single-workspace campus event intelligence engine and academic planning tool built specifically for the **College of William & Mary**. It bridges the gap between student schedules (classes, study blocks) and live campus life (student organizations/RSOs, department talks, athletic events, and public campus calendars).

### Core Philosophy
1. **Zero AI Slop / Anti-Slop**:
   - No generic cyberpunk dashboards, glowing neon borders, pulsing badges, or oversized AI template cards.
   - Everything must look like an authentic, refined academic publication tool matching `&.edu`.
2. **Zero Build Tooling**:
   - Pure Vanilla HTML5, CSS3 (`static/lab.css`), and standard asynchronous Vanilla JavaScript (`fetch` API).
   - **No npm, Vite, Webpack, React runtime, or bundler overhead.**
3. **Rock-Solid Backend**:
   - Python 3.11+, FastAPI, Uvicorn, and high-concurrency standard library `sqlite3` with Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and compound indexes.
4. **Time & Schedule Standards**:
   - **Internal canonical format**: Strict 24-hour zero-padded `HH:MM` strings (`00:00`–`23:59`) and ISO-8601 timestamps in `America/New_York` (Eastern Time).
   - **User-facing presentation**: Clean, readable 12-hour format (`4:00 PM – 8:00 PM`).

---

## 2. Chronological Log of User Requests & Pain Points

Before making any changes, Claude **must** read and understand every user request and complaint in chronological order:

| # | User Request | Context & What Happened | Key Takeaway / Lesson |
|---|---|---|---|
| **1** | *"AND ALSO FIX THE FONTS and different colors should work in NOW and SOON font shoud be from the &EDU why its so hard just take the fucking same css"* | User noticed that fonts and department badge colors were mismatched or not inheriting the official `&.edu` styling tokens. | Strictly use `--font-display: "IBM Plex Mono"` for labels/mono and `--font-body: "IBM Plex Sans"` for readable text. Department badges must follow the 7 canonical color tints. |
| **2** | *"And your week is still using the filler schedule. Make whole site use an actuall schedule"* | The weekly planner view was showing synthetic dummy classes instead of authentic William & Mary course blocks. | Implemented real W&M student course presets (CSCI 141, DATA 141, CSCI 241, PHIL 201, MATH 211) across MWF and TR time bands in `schedule.db`. |
| **3** | *"AND THE FREAKING AI FONT IS STILL THERE DO SOMETHING WITH IT IT TOLD YOU MANY TIMES &EDU FONT WHY IS IT So HARD"* | The card headings and section titles were styled with generic monospace clamps (`font-size: clamp(1.7rem, 3vw, 2.3rem); font-family: var(--font-display);`), giving the app an ugly, bloated "AI generated prototype" feel. | Switched `.live-event-title` to `var(--font-body)` (`IBM Plex Sans`), weight 600, size 1.05rem, balance wrapped. Avoid using wide monospace for article/card titles. |
| **4** | *"also make those events clickable and addable to the personal schedule also while you click on it it should expand. the freaking font... it still there... here is the &EDU fonts and also give summary for the gemeni"* | User provided exact CSS token definitions from `&.edu` root stylesheets and requested interactive expandable cards that can be added to personal weekly schedules. | Added accordion event expansion (`toggleCardExpand`), save toggle with bookmark buttons, and dynamic personal schedule sync. |
| **5** | *"give summary of project for argon"* | User needed an executive technical summary for stakeholders/collaborators. | Generated executive briefing detailing data pipelines, multi-model categorization, conflict detection, and `&.edu` integration. |
| **6** | *"also give more info it can make presentation for that"* | User requested a presentation deck structure. | Delivered 12-slide presentation kit with speaker notes, slide layouts, and demo sequences. |
| **7** | *"and add the update button which starts parser again"* | User wanted a manual "Update / Refresh Feeds" button in the UI to trigger calendar re-parsing on demand. | Implemented `POST /api/parser/run` and `GET /api/parser/status` with synchronized UI buttons in the masthead and directory view. |
| **8** | *`Screenshot.png`: visual bugs and also update spinnign endlessly* | User uploaded a screenshot showing: (a) update button stuck in infinite loading spinner, (b) duplicate `iREP` cards from cross-feed scraping, (c) ugly time labels reading `"Sat Sat, Nov 14, 2026, 16:00 – Sat, Nov 14, 2026, 20:00"`. | Fixed parser timeout (`discover_directory=False` on web syncs), deduplicated cards across feeds by `(normalized_title, start_datetime)`, cleaned time chips to `[ Sat, Nov 14 ] [ 4:00 PM – 8:00 PM ]`. |
| **9** | *"I think also problem could be that the model you are using is not supported try Gemini 3.5 Flash Lite or Gemini 3.1 Flash Lite as fallback"* | User noticed model errors or deprecation warnings on legacy Gemini model names. | Built automatic fallback chain: `gemini-3.5-flash-lite` -> `gemini-3.1-flash-lite` -> `gemini-2.5-flash` -> `gemini-2.0-flash-lite` -> `gemini-1.5-flash` with dynamic working model caching. |
| **10** | *"also site is not loading rn"* | Browser appeared stuck or failed to connect when loading `http://localhost:8000`. | Root cause was a waterfall of blocking sequential awaits in `loadAll()` fetching 1MB of JSON before rendering Now & Soon, coupled with macOS IPv6 `[::1]` resolution delays on `localhost`. Decoupled initial paint from background preloading. |
| **11** | *(Current)*: *"Start writing plan for the claude: Add that he needs to add more resources to parse, fix all of the visual bugs, match visual style with &EDU, remove interface clumsiness and AI look... use vision to complete that... light theme button is becoming dark in some reason... parse all of the rso names for the faster input in site and all of the room numbers... check whole project"* | Claude must take over to eliminate clumsiness, expand data sources, build autocomplete for RSOs and rooms, fix theme button behavior, and audit the entire system using vision. | **This document (`claude.md`) is Claude's master execution blueprint.** |

---

## 3. &EDU Design System Tokens & Anti-AI Visual Standards

Claude **must** strictly enforce the `&.edu` aesthetic.

### Official Typography Rules
```css
:root {
  --font-display: "IBM Plex Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --font-body: "IBM Plex Sans", "Segoe UI", -apple-system, Roboto, sans-serif;
  --font-mono: "IBM Plex Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --font-ui: var(--font-mono);
}
```
- **Page Titles & Major Section Headings**: `font-family: var(--font-display); font-weight: 600; letter-spacing: -0.02em;`
- **Card Titles & Article Headers**: `font-family: var(--font-body); font-weight: 600; font-size: 1.05rem; line-height: 1.35;`  
  *(Never use wide monospace clamps like `clamp(1.7rem, 3vw, 2.3rem)` for card titles — that is what made it look like a clumsy AI mockup).*
- **Timestamps, Room Numbers, Course Codes, Badges, Tabs, Counters**: `font-family: var(--font-mono); font-feature-settings: "tnum" 1;`

### Official Color Tokens
```css
/* Light Mode */
:root {
  color-scheme: light;
  --brand: #0b0f0d;
  --brand-strong: #000000;
  --brand-ink: #ffffff;
  --brand-ink-soft: #c4ccc7;
  --brand-hover: rgba(255, 255, 255, 0.08);
  --brand-line: rgba(201, 162, 74, 0.45);
  --side-bg: #0b3b2c;        /* Deep William & Mary Griffin Green */
  --side-ink: #ffffff;
  --side-muted: #b3c9bd;
  --side-hover: rgba(255, 255, 255, 0.08);
  --side-active: #155540;
  --side-field: rgba(243, 241, 234, 0.08);
  --side-field-line: rgba(243, 241, 234, 0.24);
  --accent: #0e4a37;
  --accent-hover: #093526;
  --accent-press: #062519;
  --accent-tint: #e2ebe5;
  --accent-tint-2: #c6d8cd;
  --on-accent: #ffffff;
  --gold: #c9a24a;          /* Caslon / Cypher Gold */
  --gold-text: #6f5114;
  --gold-tint: #f7eed6;
  --gold-rule: #d9bf7c;
  --on-gold: #0b0f0d;
  --paper: #f1f0ea;         /* Stone Paper Canvas */
  --surface: #ffffff;
  --sunk: #e9e7df;
  --code-bg: #f4f3ee;
  --ink: #0b0f0d;
  --ink-soft: #2b3430;
  --muted: #4f5953;
  --rule: #cbc7b9;
  --rule-strong: #8f8a7c;
  --ok: #0e4a37;
  --ok-tint: #e2ebe5;
  --ok-ink: #082f22;
  --bad: #9a2b2b;
  --bad-tint: #f6e6e3;
  --bad-ink: #6b1b1b;
  --bad-rule: #deb3ab;
  --info: #2c5a78;
  --info-tint: #e5edf2;
  --grid: rgba(11, 15, 13, 0.045);
  --radius: 4px;
  --radius-sm: 3px;
}

/* Dark Mode */
:root[data-theme="dark"] {
  color-scheme: dark;
  --brand: #000000;
  --brand-strong: #000000;
  --brand-ink: #ffffff;
  --brand-ink-soft: #b9c2bd;
  --side-bg: #07140f;
  --side-ink: #f2f5f3;
  --side-muted: #8ea49a;
  --side-active: #163428;
  --accent: #5aae8b;
  --accent-hover: #6fbf9c;
  --accent-press: #4a9a79;
  --accent-tint: #142a21;
  --on-accent: #06140e;
  --gold: #e0bb62;
  --gold-text: #e8c877;
  --gold-tint: #2a2416;
  --paper: #050806;
  --surface: #0e1411;
  --sunk: #090e0b;
  --code-bg: #0b110e;
  --ink: #f4f7f5;
  --ink-soft: #cfd9d3;
  --muted: #9eada5;
  --rule: #2b3b34;
  --rule-strong: #4a5f55;
  --ok: #5fb390;
  --ok-tint: #142a21;
  --bad: #e27f72;
  --bad-tint: #2c1714;
  --bad-ink: #f3bdb4;
  --grid: rgba(230, 235, 231, 0.035);
}
```

---

## 4. Specific Bug Diagnoses & Fixes

### Bug A: Light Theme Button Becoming Dark
- **Root Cause**: In `static/lab.css`, the default selector `.theme-switch button[aria-pressed="true"]` styles the active button with `background: var(--brand-strong); color: var(--brand-ink);`.
- In light mode, `--brand-strong` is `#000000` (pure black) and `--brand-ink` is `#ffffff`.
- When the user opened the top-right menu and selected "Light", the button turned solid black. To the user, clicking "Light" made the button itself look like a dark block.
- **The Fix**: Explicitly override menu-nested theme switches so the active state uses `--accent` (`#0e4a37` in light mode, `#5aae8b` in dark mode) and `--on-accent`:
  ```css
  #cornerMenuDropdown .theme-switch button[aria-pressed="true"] {
    background: var(--accent) !important;
    color: var(--on-accent) !important;
  }
  ```
- **Claude Action Item**: Audit all modals and submenus to ensure any other theme switches or toggle pills use `--accent` / `--on-accent` rather than `--brand-strong`.

### Bug B: Endless Parser Spinner
- **Root Cause**: The web button called `POST /api/parser/run`, which was invoking `discover_and_import()` without arguments. This crawled all 140+ sub-calendar URLs sequentially across `https://events.wm.edu/search/all_calendars`, taking over 4 minutes and hitting browser timeouts.
- **The Fix**: 
  - Added `discover_directory: bool = False` flag to `discover_and_import()`.
  - Web sync requests only re-fetch the core feeds (`wm-main` and `tribelink`), completing in ~1.5 seconds.
  - Full discovery is reserved for CLI usage (`python import_wm_events.py --discover`) or scheduled background worker crons.

### Bug C: Duplicate Event Cards & Time String Clutter
- **Root Cause**: TribeLink publishes campus events in UTC time, while the W&M Master Calendar publishes in local America/New_York time with slightly varied titles (e.g. `iREP, The Royal Journey`). They were rendered as separate cards, and dates were displayed with double day strings (`Sat Sat, Nov 14, 2026, 16:00 – Sat, Nov 14, 2026, 20:00`).
- **The Fix**:
  - Implemented event signature normalization in `app.py`:
    ```python
    sig = (re.sub(r"[^a-z0-9]", "", ev["title"].lower())[:24], ev.get("campus_start_datetime") or ev.get("start_time"))
    ```
  - Formatted time chips cleanly as: `[ W&M Campus ] [ Sat, Nov 14 ] [ 4:00 PM – 8:00 PM ] 📍 Sadler Commonwealth`.

---

## 5. Gemini Integration & AI Multi-Model Architecture

In [app.py](file:///Users/svintus/%20&EVENTS/app.py#L1490-L1605), the app automatically categorizes raw campus events into the **7 canonical &EDU departments**:
1. `tech` (Computer Science, Robotics, Cyber, Coding, Makerspace)
2. `math` (Data Science, Mathematics, Probability, Algorithms)
3. `arts` (Music, Theatre, Studio Art, Film, Dance, Exhibitions)
4. `humanities` (Philosophy, History, Literature, Languages, Ethics)
5. `science` (Physics, Biology, Chemistry, Neuroscience, Pre-Med, Environmental)
6. `business` (Finance, Consulting, Entrepreneurship, Economics, Marketing)
7. `wellness` (Club Sports, Rec Center, Yoga, Meditation, Outdoors, Nutrition)

### Multi-Model Fallback Chain
Because model support and rate limits vary, `_query_gemini_categorization()` implements the following fallback order:
```python
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]
```
- When a model returns HTTP 200, `_WORKING_GEMINI_MODEL` caches that model name.
- If the Gemini API is unreachable, offline, or returns 404/429, the app smoothly falls back to a deterministic, keyword-based regex classifier (`_fallback_heuristic_categorize()`), guaranteeing that the app **never crashes or hangs**.

---

## 6. Actionable Implementation Plan for Claude

Claude must execute the following four major phases:

### Phase 1: Expand Parsed Resources & Feeds
Currently, the database has 142 known calendar slugs in `wm_event_calendars`, but only 2 feeds (`wm-main` and `tribelink`) are actively synced on quick refresh.
Claude must expand active parsing to include:
1. **Cohen Career Center**: `https://events.wm.edu/calendar/upcoming_ical/career` (Internship fairs, resume labs, employer meetups).
2. **Swem Library**: `https://events.wm.edu/calendar/upcoming_ical/swem` (Workshops, research clinics, makerspace hours).
3. **Sadler Center & Student Happenings**: `https://events.wm.edu/calendar/upcoming_ical/studenthappenings`.
4. **W&M Athletics**: `https://tribeathletics.com/calendar.ashx/calendar.ics` (Basketball, football, soccer, gymnastics).
5. **Academic Calendar**: Key registration deadlines, add/drop dates, final exams, breaks.
6. **Implementation Architecture**:
   - Store feed definitions in `DEFAULT_DISCOVERY_FEEDS` in `import_wm_events.py`.
   - Add asynchronous background worker cron or non-blocking scheduled task so heavy parsing never blocks FastAPI HTTP responses.

### Phase 2: RSO Names & Campus Room Numbers Autocomplete Engine
To eliminate interface clumsiness and allow lightning-fast student scheduling:
1. **Registered Student Organizations (RSOs)**:
   - Compile a canonical database/JSON of all 300+ W&M RSOs (ACM, LUG, Tribe Cyber, WiC, AMP, Flat Hat, SASA, BSO, LASU, Chess Club, etc.).
   - Create an endpoint `GET /api/presets/rsos` returning `{ "rsos": [...] }`.
   - Add `<datalist id="rsoList">` and instant-search suggestion dropdown to the event organizer form (`clubName` input).
2. **Campus Buildings & Room Numbers**:
   - Compile a canonical list of campus buildings and standard room numbers:
     - **Sadler Center**: `Sadler Commonwealth`, `Sadler Tidewater AB`, `Sadler Lodge One`, `Sadler Chesapeake`, `Sadler 202`, `Sadler Atrium`.
     - **Integrated Science Center (ISC)**: `ISC 1127`, `ISC 1221`, `ISC 2000`, `ISC Atrium`.
     - **Blow Memorial Hall**: `Blow 201`, `Blow 332`, `Blow 333`.
     - **Small Hall**: `Small Hall 110`, `Small Hall 111`, `Small Hall Makerspace`.
     - **McGlothlin-Street Hall**: `McGlothlin 020`, `McGlothlin 101`.
     - **Jones Hall**: `Jones 301`, `Jones 202`, `Jones 101`.
     - **Wren Building**: `Wren Chapel`, `Great Hall`, `Wren 200`.
     - **Swem Library**: `Swem Read & Relax`, `Swem Ford Classroom`, `Swem Makerspace`.
     - **Campus Center**: `Campus Center Trinkle Hall`, `Little Theatre`.
     - **Student Rec Center**: `Rec Center Pool`, `Rec Center Gymnasium`.
     - **Outdoors**: `Sunken Garden`, `Crim Dell Meadow`, `Martha Wren Briggs Amphitheatre`.
   - Create an endpoint `GET /api/presets/locations` returning `{ "locations": [...] }`.
   - Bind `<datalist id="locationList">` to `classLoc` (in sidebar) and `eventLocation` (in organizer).

### Phase 3: Visual Polish & De-Clumsification with Vision
Claude must use screenshot inspection (via headless browser, Puppeteer, or local capture tool) to evaluate visual balance:
1. **Layout & Alignment**:
   - Verify sidebar width (`--sidebar-w: 280px`), padding, and border contrast.
   - Verify that event cards have crisp 3px/4px border radii, subtle borders (`var(--rule)`), and no awkward text overlap.
2. **Accordion Expansion State**:
   - Clicking an event card smoothly expands full event description, location map link, source calendar tag, and an `[+ Add to Week]` button.
   - Expanded state must not distort the card grid or cause horizontal page scrolling.
3. **Contrast & Themes**:
   - Check both Light Theme (`data-theme="light"`) and Dark Theme (`data-theme="dark"`).
   - Ensure all badge text conforms to WCAG AA contrast against its tint background.
   - Verify the Light theme button stays emerald green (`--accent`) when active, never black.

### Phase 4: Full Project Health & Security Audit
1. **Test Coverage**:
   - Maintain 100% pass rate on all 27 unit tests:
     ```bash
     python3 -m unittest discover tests
     python3 -m unittest test_wm_data.py
     python3 -m unittest test_import_wm_events.py
     ```
2. **Security Guardrails**:
   - **Zero Secret Exposure**: `.env` and API keys must never be committed to git or echoed into logs.
   - **XSS Prevention**: All user inputs, event descriptions, and titles must pass through `escapeHtml()` before insertion into innerHTML.
   - **SQL Injection Prevention**: Every database query must use parameterized queries (`?`), never string interpolation.
3. **Git Hygiene**:
   - Clean, descriptive commit messages.

---

## 7. Reference Dataset: W&M RSOs & Room Numbers

Claude can immediately load and expose the following structured datasets into the backend and frontend:

### Canonical Campus Rooms
```json
[
  "Sadler Commonwealth",
  "Sadler Tidewater AB",
  "Sadler Lodge One",
  "Sadler Chesapeake",
  "Sadler Center 202",
  "Sadler Atrium",
  "ISC 1127",
  "ISC 1221",
  "ISC 2000",
  "ISC Atrium",
  "Small Hall Makerspace",
  "Small Hall 110",
  "Small Hall 111",
  "Blow Memorial Hall 201",
  "Blow Memorial Hall 332",
  "McGlothlin-Street Hall 020",
  "McGlothlin-Street Hall 101",
  "Jones Hall 301",
  "Jones Hall 202",
  "Wren Chapel",
  "Wren Building Great Hall",
  "Wren Building 200",
  "Swem Library Read & Relax",
  "Swem Library Ford Classroom",
  "Swem Library Makerspace",
  "Campus Center Trinkle Hall",
  "Campus Center Little Theatre",
  "Student Rec Center Pool",
  "Student Rec Center Gym",
  "Sunken Garden",
  "Crim Dell Meadow",
  "Martha Wren Briggs Amphitheatre"
]
```

### Canonical Student Organizations (RSOs)
```json
[
  "W&M Linux Users Group (LUG)",
  "Association for Computing Machinery (ACM)",
  "Machine Learning & AI Club",
  "Tribe Cyber",
  "Women in Computing (WiC)",
  "Robotics & IoT Club",
  "Makerspace Guild",
  "Google Developer Student Club (GDSC)",
  "W&M Chess Club",
  "Tabletop Gaming Society",
  "Alma Mater Productions (AMP)",
  "The Flat Hat",
  "WCWM 90.9 FM",
  "Student Assembly (SA)",
  "International Relations Club (IRC)",
  "Debate Society",
  "Model United Nations",
  "Black Student Organization (BSO)",
  "Latin American Student Union (LASU)",
  "Asian American Student Initiative (AASI)",
  "South Asian Student Association (SASA)",
  "Club Swim & Water Polo",
  "Tribe Triathlon",
  "Rock Climbing Club",
  "Society of Physics Students (SPS)",
  "Chemistry Club",
  "Philosophy Club",
  "Pre-Med American Medical Student Association (AMSA)",
  "Women in Science and Engineering (WISE)",
  "Salsa & Latin Dance Club"
]
```

---

## 8. Summary Checklist for Claude

- [ ] Inspect `claude.md` and read all previous user requests.
- [ ] Add the 4 new calendar resources (`career`, `swem`, `studenthappenings`, `athletics`) to `import_wm_events.py`.
- [ ] Add the preset endpoints `GET /api/presets/rsos` and `GET /api/presets/locations`.
- [ ] Connect HTML `<datalist>` elements for instant autocomplete on club names and room numbers.
- [ ] Verify Light theme toggle button remains emerald green (`--accent`), not black.
- [ ] Inspect visual styling with screenshots (Vision); remove any remaining clumsy spacing, mismatched fonts, or AI artifacts.
- [ ] Run full test suite: `python3 -m unittest discover tests && python3 -m unittest test_wm_data.py && python3 -m unittest test_import_wm_events.py`.
- [ ] Run security audit check before committing.
