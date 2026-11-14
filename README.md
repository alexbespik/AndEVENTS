<div align="center">
  <img src="static/favicon.svg" alt="" width="48" height="48">
  <h1>&amp;.events</h1>
  <p><strong>Find the campus events that fit your week.</strong></p>
  <p>FastAPI · SQLite · Vanilla JavaScript</p>
</div>

Browse club events, plan around classes, and import public William & Mary calendar feeds.

## What it does

- Browse and filter weekly club events.
- Build a class schedule and spot time conflicts.
- View dated W&amp;M events alongside your weekly plan.
- Create events and check for schedule conflicts.

## Run locally

Requires Python 3.11 or newer.

```bash
git clone https://github.com/alexbespik/AndEVENTS.git
cd AndEVENTS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Import W&amp;M calendars

```bash
python import_wm_events.py --discover
```

To import a downloaded iCalendar file instead:

```bash
python import_wm_events.py --file campus=events.ics
```

The importer reports feeds it cannot access. It imports available calendar events; recurring rules and exceptions are not expanded.

## Data

SQLite stores app data in `schedule.db`. Set `SCIEDU_CONTENT_DIR` to store it in another directory.
