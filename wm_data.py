"""Import public William & Mary calendar feeds into the local SQLite database.

The app's ``club_events`` table models weekly recurring events. W&M calendar
items are dated instances, so this module stores them separately.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/New_York"


class ICalendarError(ValueError):
    """Raised when an iCalendar feed cannot be safely parsed."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the dated event tables used by the importer and API."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
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
        CREATE INDEX IF NOT EXISTS idx_wm_events_start_at ON wm_events(start_at);
        CREATE INDEX IF NOT EXISTS idx_wm_event_calendars_slug
            ON wm_event_calendars(calendar_slug, uid);
        """
    )
    cols = [row[1] for row in conn.execute("PRAGMA table_info(wm_events)").fetchall()]
    if "source_url" not in cols:
        conn.execute("ALTER TABLE wm_events ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
        if "url" in cols:
            conn.execute("UPDATE wm_events SET source_url = url WHERE source_url = '' AND url != ''")
        conn.commit()


def _unfold_lines(text: str) -> list[str]:
    physical = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    logical: list[str] = []
    for line in physical:
        if line.startswith((" ", "\t")):
            if not logical:
                raise ICalendarError("Feed starts with an orphan folded line")
            logical[-1] += line[1:]
        elif line:
            logical.append(line)
    return logical


def _split_content_line(line: str) -> tuple[str, dict[str, str], str]:
    """Split an iCalendar property line, respecting quoted parameter values."""
    quoted = False
    escaped = False
    separator = -1
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            separator = index
            break
    if separator < 1:
        raise ICalendarError(f"Malformed content line: {line[:80]!r}")

    left, value = line[:separator], line[separator + 1 :]
    parts = left.split(";")
    name = parts[0].split(".")[-1].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, equals, raw = part.partition("=")
        if equals:
            params[key.upper()] = raw.strip().strip('"')
    return name, params, value


def _unescape_text(value: str) -> str:
    value = re.sub(r"\\[nN]", "\n", value)
    return re.sub(r"\\([\\,;:])", r"\1", value)


def _parse_datetime(value: str, params: dict[str, str]) -> tuple[str, str, bool]:
    """Return (ISO value, timezone name, is_all_day) for DTSTART/DTEND."""
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        try:
            parsed_date = datetime.strptime(value, "%Y%m%d").date()
        except ValueError as exc:
            raise ICalendarError(f"Invalid iCalendar date: {value!r}") from exc
        return parsed_date.isoformat(), params.get("TZID", DEFAULT_TIMEZONE), True

    if not re.fullmatch(r"\d{8}T\d{4}(?:\d{2})?Z?", value):
        raise ICalendarError(f"Unsupported iCalendar date-time: {value!r}")

    is_utc = value.endswith("Z")
    raw = value[:-1] if is_utc else value
    fmt = "%Y%m%dT%H%M%S" if len(raw) == 15 else "%Y%m%dT%H%M"
    try:
        parsed = datetime.strptime(raw, fmt)
    except ValueError as exc:
        raise ICalendarError(f"Invalid iCalendar date-time: {value!r}") from exc

    tz_name = "UTC" if is_utc else params.get("TZID", DEFAULT_TIMEZONE)
    try:
        timezone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ICalendarError(f"Unknown time zone {tz_name!r}") from exc
    return parsed.replace(tzinfo=timezone).isoformat(), tz_name, False


def _event_from_properties(properties: dict[str, list[tuple[dict[str, str], str]]]) -> dict[str, Any] | None:
    def first(name: str) -> tuple[dict[str, str], str] | None:
        values = properties.get(name)
        return values[0] if values else None

    status = first("STATUS")
    if status and status[1].strip().upper() == "CANCELLED":
        return None

    uid_item = first("UID")
    title_item = first("SUMMARY")
    start_item = first("DTSTART")
    if not uid_item or not uid_item[1].strip():
        raise ICalendarError("VEVENT is missing UID")
    if not title_item or not _unescape_text(title_item[1]).strip():
        raise ICalendarError(f"VEVENT {uid_item[1]!r} is missing SUMMARY")
    if not start_item:
        raise ICalendarError(f"VEVENT {uid_item[1]!r} is missing DTSTART")

    start_at, timezone, is_all_day = _parse_datetime(start_item[1], start_item[0])
    end_item = first("DTEND")
    end_at = _parse_datetime(end_item[1], end_item[0])[0] if end_item else None
    categories: list[str] = []
    for _, raw_categories in properties.get("CATEGORIES", []):
        categories.extend(
            item.strip()
            for item in re.split(r"(?<!\\),", raw_categories)
            if item.strip()
        )

    def text_value(name: str) -> str:
        item = first(name)
        return _unescape_text(item[1]).strip() if item else ""

    return {
        "uid": _unescape_text(uid_item[1]).strip(),
        "title": _unescape_text(title_item[1]).strip(),
        "summary": text_value("SUMMARY"),
        "description": text_value("DESCRIPTION"),
        "start_at": start_at,
        "end_at": end_at,
        "timezone": timezone,
        "is_all_day": is_all_day,
        "location": text_value("LOCATION"),
        "source_url": text_value("URL"),
        "categories": categories,
    }


def parse_ical(text: str) -> list[dict[str, Any]]:
    """Parse VEVENT records from a UTF-8 iCalendar feed.

    The parser supports folded lines, escaped text, all-day dates, UTC values,
    and TZID-local values. RRULE expansion and RECURRENCE-ID exception merging
    are not performed; feeds with recurrence rules may therefore lose series
    expansion or exception semantics.
    """
    if not isinstance(text, str):
        raise ICalendarError("Feed must be text")
    lines = _unfold_lines(text)
    markers = {line.upper() for line in lines}
    if "BEGIN:VCALENDAR" not in markers or "END:VCALENDAR" not in markers:
        raise ICalendarError("Input is not a complete VCALENDAR feed")

    events: list[dict[str, Any]] = []
    current: dict[str, list[tuple[dict[str, str], str]]] | None = None
    for line in lines:
        if line.upper() == "BEGIN:VEVENT":
            if current is not None:
                raise ICalendarError("Nested VEVENT block")
            current = {}
            continue
        if line.upper() == "END:VEVENT":
            if current is None:
                raise ICalendarError("END:VEVENT without BEGIN:VEVENT")
            event = _event_from_properties(current)
            if event is not None:
                events.append(event)
            current = None
            continue
        if current is None:
            continue
        name, params, value = _split_content_line(line)
        current.setdefault(name, []).append((params, value))

    if current is not None:
        raise ICalendarError("Unclosed VEVENT block")

    uids = [event["uid"] for event in events]
    if len(uids) != len(set(uids)):
        raise ICalendarError("Feed contains duplicate event UIDs")
    return events


def import_calendar(
    conn: sqlite3.Connection,
    slug: str,
    name: str,
    text: str,
) -> dict[str, int]:
    """Atomically replace one calendar's membership from a parsed feed.

    A parse failure leaves both event records and memberships untouched.
    """
    if not slug.strip():
        raise ValueError("calendar slug must not be blank")
    events = parse_ical(text)
    ensure_schema(conn)
    counts = {"seen": len(events), "inserted": 0, "updated": 0, "memberships_added": 0, "memberships_removed": 0}

    conn.execute("SAVEPOINT wm_calendar_import")
    try:
        active_uids: set[str] = set()
        for event in events:
            uid = event["uid"]
            active_uids.add(uid)
            existing = conn.execute("SELECT 1 FROM wm_events WHERE uid = ?", (uid,)).fetchone()
            values = (
                event["title"], event["summary"], event["description"], event["start_at"],
                event["end_at"], event["timezone"], event["location"],
                event["source_url"], json.dumps(event["categories"], ensure_ascii=False),
                int(event["is_all_day"]), uid,
            )
            if existing:
                conn.execute(
                    """UPDATE wm_events SET title=?, summary=?, description=?, start_at=?, end_at=?,
                       timezone=?, location=?, source_url=?, categories=?, is_all_day=? WHERE uid=?""",
                    values,
                )
                counts["updated"] += 1
            else:
                conn.execute(
                    """INSERT INTO wm_events
                       (title, summary, description, start_at, end_at, timezone,
                        location, source_url, categories, is_all_day, uid)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values[:-1] + (uid,),
                )
                counts["inserted"] += 1

            membership = conn.execute(
                "SELECT 1 FROM wm_event_calendars WHERE uid = ? AND calendar_slug = ?",
                (uid, slug),
            ).fetchone()
            conn.execute(
                """INSERT INTO wm_event_calendars (uid, calendar_slug, calendar_name)
                   VALUES (?, ?, ?)
                   ON CONFLICT(uid, calendar_slug) DO UPDATE SET calendar_name=excluded.calendar_name""",
                (uid, slug, name.strip() or slug),
            )
            if not membership:
                counts["memberships_added"] += 1

        old_rows = conn.execute(
            "SELECT uid FROM wm_event_calendars WHERE calendar_slug = ?", (slug,)
        ).fetchall()
        stale_uids = [row[0] for row in old_rows if row[0] not in active_uids]
        if stale_uids:
            conn.executemany(
                "DELETE FROM wm_event_calendars WHERE uid = ? AND calendar_slug = ?",
                [(uid, slug) for uid in stale_uids],
            )
            counts["memberships_removed"] = len(stale_uids)

        conn.execute(
            "DELETE FROM wm_events WHERE NOT EXISTS "
            "(SELECT 1 FROM wm_event_calendars WHERE wm_event_calendars.uid = wm_events.uid)"
        )
        conn.execute("RELEASE SAVEPOINT wm_calendar_import")
        return counts
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT wm_calendar_import")
        conn.execute("RELEASE SAVEPOINT wm_calendar_import")
        raise

