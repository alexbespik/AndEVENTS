<div align="center">
  <img src="static/favicon.svg" alt="" width="48" height="48">
  <h1>&amp;.events</h1>
  <p><strong>Make room for what matters this week.</strong></p>
  <p>Campus events · Class planning · William &amp; Mary calendars</p>
</div>

&.events brings campus events and your class schedule into one weekly view. Browse student events, add your classes, and check for conflicts.

## What you can do

- Find and filter weekly club events.
- Plan around classes and spot schedule conflicts.
- Browse dated William &amp; Mary events beside your weekly plan.
- Add events and see how they fit.

## Where it’s going

&.events is planned to merge with [&amp;EDU](https://github.com/alexbespik/AndEDU), a visual learning workspace for guided study tracks and interactive programming practice. The goal is to bring campus planning and learning tools together in one place.

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

Discover and import available public calendars:

```bash
python import_wm_events.py --discover
```

Or import a downloaded iCalendar file:

```bash
python import_wm_events.py --file campus=events.ics
```

Recurring rules and exceptions are not expanded.

## Data

App data is stored in `schedule.db`. Set `SCIEDU_CONTENT_DIR` to use another data directory.
