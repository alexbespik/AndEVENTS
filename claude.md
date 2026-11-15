# Master Engineering & Refactoring Plan for Claude: `&.events`

> **Target Audience**: Incoming Lead Engineer / AI Agent (Claude 3.7 Sonnet / Claude 3.5 Sonnet).  
> **Repository**: `&.events` (AndEVENTS)  
> **Destination**: To be merged into `&.edu` (AndEDU - [github.com/alexbespik/AndEDU](https://github.com/alexbespik/AndEDU)).  
> **Local Server**: `http://127.0.0.1:8000` (`python3 -m uvicorn app:app --reload --port 8000`).  
> **Time Limit**: **CRITICAL ~30-MINUTE DEADLINE**.

---

## ⚡ URGENT EXECUTION MANDATE FOR CLAUDE: SPAWN MULTIPLE AGENTS IN PARALLEL

> [!CAUTION]
> **DO NOT WORK SEQUENTIALLY**. The user has approximately **30 minutes total** to complete the entire overhaul.  
> You MUST fan out and leverage multiple parallel subagents immediately (`coder`, `reviewer`, `tester`, `researcher`):
> - **Agent 1 (`coder`)**: Visual De-clumsification & Layout (Remove awkward margins, fix card paddings, verify `IBM Plex Sans` on all titles, audit mobile responsiveness).
> - **Agent 2 (`coder`)**: Feed Parser Expansion (Add the 4 new W&M feeds in `import_wm_events.py`: Cohen Career Center, Swem Library, Student Happenings, Athletics).
> - **Agent 3 (`tester`)**: Continuous test runner (`python3 -m unittest discover tests && python3 -m unittest test_wm_data.py && python3 -m unittest test_import_wm_events.py`).
> - **Agent 4 (`reviewer` / Vision)**: Take/inspect screenshots using vision models to verify pixel-perfection against `&.edu`.

---

## 🚨 CRITICAL WARNING ON TYPOGRAPHY: STOP RETURNING "THE FREAKING AI / RETARDED FONT"

> [!WARNING]
> **READ THIS BEFORE TOUCHING ANY CSS OR HTML.**  
> The user has repeatedly screamed in ALL CAPS across multiple turns about the font. Here is why previous agents kept failing and infuriating the user:
>
> 1. **Mistake #1 (The Monospace AI / Terminal Slop)**:  
>    The first agent set `--font-display: "IBM Plex Mono"` and put it on `h1, h2`. This rendered all page titles (`Who's up?`, `Your week`, `Organize events`) and card headers in a wide, blocky monospace code font. It looked like a terminal hacker prototype or a cheap AI mockup.
> 2. **Mistake #2 (The Archaic Serif Newspaper Slop)**:  
>    The next agent tried to fix it by setting `--font-display: "Libre Caslon Text"`. This slapped curly, old-fashioned serif letters (like Times New Roman) all over modern UI panels. The user hated this just as much!
>
> ### THE EXACT FONT SPECIFICATION:
> - **ALL Headings (`h1`, `h2`, `h3`, `h4`)**: MUST be **`IBM Plex Sans`** (`font-weight: 700; letter-spacing: -0.02em;`).  
> - **ALL Card Titles, Section Titles, Modal Titles, and Subtitles**: MUST be **`IBM Plex Sans`** (`font-weight: 600;`).  
> - **Body Text, Navigation, Descriptions, and Form Labels**: MUST be **`IBM Plex Sans`** (`16px / 1.55`).  
> - **MONOSPACE (`IBM Plex Mono`) IS EXCLUSIVELY FOR**: Timestamps (`14:00`), course codes (`CSCI 241`), room numbers (`ISC 1127`), counter badges (`583 events`), and code snippets. **NEVER FOR TITLES OR HEADINGS.**  
> - **SERIF FONTS (`Libre Caslon Text`) MUST NEVER BE USED FOR HEADINGS OR UI TEXT.**

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

Claude **must** read and understand every user request and complaint in chronological order:

| # | User Request | Context & What Happened | Key Takeaway / Lesson |
|---|---|---|---|
| **1** | *"AND ALSO FIX THE FONTS and different colors should work in NOW and SOON font shoud be from the &EDU why its so hard just take the fucking same css"* | User noticed that fonts and department badge colors were mismatched or not inheriting official `&.edu` tokens. | Use `IBM Plex Sans` for readable UI and text. Department badges must follow the 7 canonical color tints. |
| **2** | *"And your week is still using the filler schedule. Make whole site use an actuall schedule"* | Weekly planner view was showing synthetic dummy classes instead of authentic William & Mary course blocks. | Implemented real W&M student course presets (CSCI 141, DATA 141, CSCI 241, PHIL 201, MATH 211) across MWF and TR time bands. |
| **3** | *"AND THE FREAKING AI FONT IS STILL THERE DO SOMETHING WITH IT IT TOLD YOU MANY TIMES &EDU FONT WHY IS IT So HARD"* | Card headings and section titles were styled with generic monospace clamps (`font-size: clamp(1.7rem, 3vw, 2.3rem); font-family: var(--font-display);`), giving an AI-prototype feel. | Switched `.live-event-title` to `var(--font-body)` (`IBM Plex Sans`), weight 600, size 1.05rem. Avoid wide monospace on card titles. |
| **4** | *"also make those events clickable and addable to the personal schedule also while you click on it it should expand. the freaking font... it still there... here is the &EDU fonts and also give summary for the gemeni"* | User provided exact CSS token definitions from `&.edu` stylesheets and requested interactive expandable cards that sync to personal weekly schedule. | Added accordion event expansion (`toggleCardExpand`), save toggle with bookmark buttons, and dynamic personal schedule sync. |
| **5** | *"give summary of project for argon"* | User needed an executive technical summary for stakeholders/collaborators. | Generated executive briefing detailing data pipelines, multi-model categorization, conflict detection, and `&.edu` integration. |
| **6** | *"also give more info it can make presentation for that"* | User requested a presentation deck structure. | Delivered 12-slide presentation kit with speaker notes, slide layouts, and demo sequences. |
| **7** | *"and add the update button which starts parser again"* | User wanted a manual "Update / Refresh Feeds" button in the UI to trigger calendar re-parsing on demand. | Implemented `POST /api/parser/run` and `GET /api/parser/status` with synchronized UI buttons in masthead and directory view. |
| **8** | *`Screenshot.png`: visual bugs and also update spinnign endlessly* | Screenshot showing: (a) update button stuck in infinite loading spinner, (b) duplicate `iREP` cards from cross-feed scraping, (c) ugly time labels reading `"Sat Sat, Nov 14, 2026, 16:00 – Sat, Nov 14, 2026, 20:00"`. | Fixed parser timeout (`discover_directory=False` on web syncs), deduplicated cards across feeds by `(normalized_title, start_datetime)`, cleaned time chips to `[ Sat, Nov 14 ] [ 4:00 PM – 8:00 PM ]`. |
| **9** | *"I think also problem could be that the model you are using is not supported try Gemini 3.5 Flash Lite or Gemini 3.1 Flash Lite as fallback"* | User noticed model errors or deprecation warnings on legacy Gemini model names. | Built automatic fallback chain: `gemini-3.5-flash-lite` -> `gemini-3.1-flash-lite` -> `gemini-2.5-flash` -> `gemini-2.0-flash-lite` -> `gemini-1.5-flash` with dynamic working model caching. |
| **10** | *"also site is not loading rn"* | Browser appeared stuck or failed to connect when loading `http://localhost:8000`. | Root cause was a waterfall of blocking sequential awaits in `loadAll()` fetching 1MB of JSON before rendering Now & Soon, coupled with macOS IPv6 `[::1]` resolution delays on `localhost`. Decoupled initial paint from background preloading. |
| **11** | *"Start writing plan for the claude: Add that he needs to add more resources to parse, fix all of the visual bugs, match visual style with &EDU... light theme button is becoming dark... parse rso names and room numbers"* | Initial plan created. Light theme button fixed (`var(--accent)`). Canonical RSO and room number presets created with `/api/presets/locations` and `/api/presets/rsos`. | Initial blueprint saved to `claude.md`. |
| **12** | *Screenshots: Datalist covering screen, event didn't appear in schedule, classes only showing Monday, Now & Soon rebrand* | (a) Browser `<datalist>` rendered massive ugly dark popup; (b) Created event wasn't auto-saved to personal schedule; (c) Class scheduler only had Monday classes; (d) Rebrand Now & Soon to "Who's up?". | Replaced `<datalist>` with custom in-place dropdown; auto-saved created events with `is_user_created: True`; restored 5-day authentic schedule with `POST /api/classes/reset-default`; renamed tab to "Who's up?". |
| **13** | *(Current)*: *"really empasithe that claude should use as much agents as possible to do the task fast because I will have like 30 min on everything... also recommend for you giving nothing out... if you click the logo you will get to now and soon... AND ALSO WHY THE FUCK YOU RETURNED THAT RETARDED FONT"* | (a) Claude must parallelize with subagents for 30m deadline; (b) "Recommended for You" gave nothing out because `loadNowAndNext` never called `matchClientTags`; (c) Logo click must reset and open Who's up; (d) All headings MUST be `IBM Plex Sans`, never serif or monospace. | **This document is Claude's emergency master plan.** |

---

## 3. The "Recommended for You" Bug & Fix

### Bug Diagnosis:
- In `loadNowAndNext()`, `data.happening_now` and `data.starting_soon` were filtered by:
  ```javascript
  if (recommendedOnly) {
    happening = happening.filter(ev => ev.matched_tags && ev.matched_tags.length > 0);
    soon = soon.filter(ev => ev.matched_tags && ev.matched_tags.length > 0);
  }
  ```
- **The Catch**: Unlike `loadEvents()` and `loadWmEvents()`, `loadNowAndNext()` **never called `matchClientTags()`**!
- As a result, `ev.matched_tags` was `undefined` on every single live event. Clicking "★ Recommended for You" immediately wiped the entire screen to 0 events!
- **The Fix Applied**:
  ```javascript
  const studentTags = getStudentTags();
  let happening = (data.happening_now || []).map(ev => ({
    ...ev,
    matched_tags: matchClientTags(ev, studentTags)
  }));
  let soon = (data.starting_soon || []).map(ev => ({
    ...ev,
    matched_tags: matchClientTags(ev, studentTags)
  }));
  ```

---

## 4. Logo Navigation Requirement

- Clicking the `.brand` button (`&.events`) must smoothly navigate to the "Who's up?" page and reset any active search filters:
  ```javascript
  function handleBrandLogoClick() {
    const searchInput = document.getElementById("searchInput");
    if (searchInput) searchInput.value = "";
    recommendedOnly = false;
    const btns = [document.getElementById("recommendedOnlyBtn"), document.getElementById("dirRecommendedOnlyBtn")];
    btns.forEach(b => { if (b) { b.classList.remove("btn-gold"); b.classList.add("btn-quiet"); } });
    switchMode('live');
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  ```

---

## 5. &EDU Design System Tokens

```css
:root {
  --font-display: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-body: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "IBM Plex Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --font-ui: "IBM Plex Sans", -apple-system, sans-serif;
}

/* Light Mode */
:root {
  color-scheme: light;
  --brand: #0b0f0d;
  --brand-strong: #000000;
  --brand-ink: #ffffff;
  --brand-ink-soft: #c4ccc7;
  --side-bg: #0b3b2c;        /* Deep W&M Griffin Green */
  --side-ink: #ffffff;
  --side-muted: #b3c9bd;
  --side-active: #155540;
  --accent: #0e4a37;
  --accent-hover: #093526;
  --accent-tint: #e2ebe5;
  --gold: #c9a24a;          /* Caslon / Cypher Gold */
  --gold-text: #6f5114;
  --gold-tint: #f7eed6;
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
  --bad: #9a2b2b;
  --bad-tint: #f6e6e3;
  --grid: rgba(11, 15, 13, 0.045);
  --radius: 4px;
  --radius-sm: 3px;
}

/* Dark Mode */
:root[data-theme="dark"] {
  color-scheme: dark;
  --brand: #000000;
  --side-bg: #07140f;
  --side-ink: #f2f5f3;
  --side-muted: #8ea49a;
  --side-active: #163428;
  --accent: #5aae8b;
  --accent-hover: #6fbf9c;
  --accent-tint: #142a21;
  --gold: #e0bb62;
  --gold-text: #e8c877;
  --gold-tint: #2a2416;
  --paper: #050806;
  --surface: #0e1411;
  --sunk: #090e0b;
  --ink: #f4f7f5;
  --ink-soft: #cfd9d3;
  --muted: #9eada5;
  --rule: #2b3b34;
  --ok: #5fb390;
  --bad: #e27f72;
  --grid: rgba(230, 235, 231, 0.035);
}
```

---

## 6. Actionable Tasks for Claude's Parallel Subagents

### Task A (Agent 1): Feed & Resource Expansion
Add these 4 feeds into `import_wm_events.py`:
1. `career`: `https://events.wm.edu/calendar/upcoming_ical/career` (Cohen Career Center)
2. `swem`: `https://events.wm.edu/calendar/upcoming_ical/swem` (Swem Library)
3. `studenthappenings`: `https://events.wm.edu/calendar/upcoming_ical/studenthappenings` (Sadler & Campus Happenings)
4. `athletics`: `https://tribeathletics.com/calendar.ashx/calendar.ics` (W&M Tribe Athletics)

### Task B (Agent 2): Visual Polish & Vision Inspection
1. Use screenshot capture tools or vision review to check:
   - Clean margins and consistent padding on all cards.
   - Accordion expansion states (`[+ Add to Week]` button, source calendar badge, location link).
   - Custom in-place autocomplete dropdown position and dismiss behavior.
   - Ensure the Light theme toggle button stays green (`--accent`), not black.

### Task C (Agent 3): Continuous Verification
Run tests after every change:
```bash
python3 -m unittest discover tests && python3 -m unittest test_wm_data.py && python3 -m unittest test_import_wm_events.py
```
*(All 27 tests must stay green at all times).*
