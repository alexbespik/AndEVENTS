"""Import public William & Mary calendar feeds into the local SQLite database.

The app's ``club_events`` table models weekly recurring events. W&M calendar
items are dated instances, so this module stores them separately.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/New_York"
MAX_ICAL_BYTES = 15 * 1024 * 1024
MAX_ICAL_LINES = 100_000

ALLOWED_HOSTS = frozenset({"events.wm.edu", "tribelink.wm.edu"})

WINDOWS_TZ_MAP = {
    "eastern standard time": "America/New_York",
    "eastern daylight time": "America/New_York",
    "us/eastern": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "utc": "UTC",
    "gmt": "UTC",
}

WM_BUILDING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:Integrated Science Center(?:\s+(?:1|2|3|Phase\s+[123]))?|Integrated Science Ctr|ISC(?:\s+[123])?)\b", re.IGNORECASE), "ISC"),
    (re.compile(r"\b(?:Sadler Center|Sadler Ctr|Sadler)\b", re.IGNORECASE), "Sadler"),
    (re.compile(r"\b(?:Blow Memorial Hall|Blow Hall|Blow)\b", re.IGNORECASE), "Blow"),
    (re.compile(r"\b(?:Jones Hall|Jones)\b", re.IGNORECASE), "Jones"),
    (re.compile(r"\b(?:Blair Hall|Blair)\b", re.IGNORECASE), "Blair"),
    (re.compile(r"\b(?:Chancellors Hall|Chancellors|Tyler Hall)\b", re.IGNORECASE), "Chancellors"),
    (re.compile(r"\b(?:McGlothlin-Street Hall|McGlothlin-Street|McGlothlin Street Hall|McGlothlin Street|MSH)\b", re.IGNORECASE), "McGlothlin-Street"),
    (re.compile(r"\b(?:Boswell Hall|Boswell|Morton Hall)\b", re.IGNORECASE), "Boswell"),
    (re.compile(r"\b(?:Tucker Hall|Tucker)\b", re.IGNORECASE), "Tucker"),
    (re.compile(r"\b(?:Earl Gregg Swem Library|Swem Library|Swem)\b", re.IGNORECASE), "Swem"),
    (re.compile(r"\b(?:Wren Building|Wren)\b", re.IGNORECASE), "Wren"),
    (re.compile(r"\b(?:Miller Hall|Miller)\b", re.IGNORECASE), "Miller"),
    (re.compile(r"\b(?:Small Hall|Small)\b", re.IGNORECASE), "Small"),
    (re.compile(r"\b(?:Washington Hall|Washington)\b", re.IGNORECASE), "Washington"),
    (re.compile(r"\b(?:Student Recreation Center|Student Rec Center|Rec Center)\b", re.IGNORECASE), "Rec Center"),
]


def is_allowed_feed_url(url: str) -> bool:
    """Validate that a URL is an allowed W&M calendar feed over HTTPS on port 443 with no credentials."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme != "https":
            return False
        if parsed.port not in (None, 443):
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        hostname = (parsed.hostname or "").lower()
        return hostname in ALLOWED_HOSTS
    except (ValueError, TypeError):
        return False


def resolve_tzid(tz_name: str) -> str:
    """Resolve Windows, legacy, and case-insensitive time zone identifiers to standard IANA names."""
    if not isinstance(tz_name, str):
        return DEFAULT_TIMEZONE
    cleaned = tz_name.strip().strip('"\'').strip()
    if not cleaned:
        return DEFAULT_TIMEZONE
    return WINDOWS_TZ_MAP.get(cleaned.lower(), cleaned)


def normalize_wm_location(raw_loc: str) -> str:
    """Canonicalize campus building names and room numbers to standard format."""
    if not raw_loc or not isinstance(raw_loc, str):
        return ""
    loc = raw_loc.strip()
    if not loc:
        return ""

    for pattern, canonical_name in WM_BUILDING_PATTERNS:
        m = pattern.search(loc)
        if m:
            prefix = loc[:m.start()].strip(" ,-–;:|")
            suffix = loc[m.end():].strip(" ,-–;:|")
            suffix = re.sub(r"^(?:room|rm\.?|suite|ste\.?)\s*", "", suffix, flags=re.IGNORECASE).strip(" ,-–;:|")
            parts = []
            if prefix:
                parts.append(prefix)
            parts.append(canonical_name)
            if suffix:
                parts.append(suffix)
            return " ".join(parts)
    return loc


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
    parts = _split_unquoted(left, ";")
    name = parts[0].split(".")[-1].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, equals, raw = part.partition("=")
        if equals:
            raw = raw.strip()
            if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                raw = raw[1:-1]
            params[key.strip().upper()] = raw
    return name, params, value


def _split_unquoted(value: str, delimiter: str) -> list[str]:
    """Split on an RFC content-line delimiter outside quoted parameters."""
    parts: list[str] = []
    quoted = False
    escaped = False
    start = 0
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == delimiter and not quoted:
            parts.append(value[start:index])
            start = index + 1
    if quoted:
        raise ICalendarError("Unterminated quoted parameter value")
    parts.append(value[start:])
    return parts


def _unescape_text(value: str) -> str:
    value = re.sub(r"\\[nN]", "\n", value)
    return re.sub(r"\\([\\,;:])", r"\1", value)


def _parse_duration(value: str, is_all_day: bool) -> tuple[timedelta, timedelta]:
    """Parse a positive RFC 5545 duration into nominal and exact parts.

    Weeks and days are calendar-relative; hours/minutes/seconds are elapsed
    time. Keeping those parts separate preserves local wall time across DST.
    """
    match = re.fullmatch(
        r"(?P<sign>[+-])?P(?:(?P<weeks>\d+)W|(?:(?P<days>\d+)D)?"
        r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?)",
        value,
    )
    if not match:
        raise ICalendarError(f"Invalid iCalendar duration: {value!r}")

    try:
        values = {key: int(match.group(key) or 0) for key in ("weeks", "days", "hours", "minutes", "seconds")}
    except (OverflowError, ValueError) as exc:
        raise ICalendarError("iCalendar duration is out of range") from exc
    if "T" in value and not any(values[key] for key in ("hours", "minutes", "seconds")):
        raise ICalendarError(f"Invalid iCalendar duration: {value!r}")
    if not any(values.values()) or match.group("sign") == "-":
        raise ICalendarError(f"VEVENT duration must be positive: {value!r}")
    if is_all_day and any(values[key] for key in ("hours", "minutes", "seconds")):
        raise ICalendarError("All-day VEVENT duration must use whole days or weeks")

    try:
        nominal = timedelta(weeks=values["weeks"], days=values["days"])
        exact = timedelta(hours=values["hours"], minutes=values["minutes"], seconds=values["seconds"])
    except (OverflowError, ValueError) as exc:
        raise ICalendarError("iCalendar duration is out of range") from exc
    return nominal, exact


def _split_escaped_commas(value: str) -> list[str]:
    """Split a TEXT-list property without splitting escaped commas."""
    parts: list[str] = []
    escaped = False
    start = 0
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ",":
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return parts


def _parse_datetime(value: str, params: dict[str, str]) -> tuple[str, str, bool]:
    """Return (ISO value, timezone name, is_all_day) for DTSTART/DTEND."""
    resolved_tz = resolve_tzid(params.get("TZID", DEFAULT_TIMEZONE))
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        try:
            parsed_date = datetime.strptime(value, "%Y%m%d").date()
        except ValueError as exc:
            raise ICalendarError(f"Invalid iCalendar date: {value!r}") from exc
        return parsed_date.isoformat(), resolved_tz, True

    if not re.fullmatch(r"\d{8}T\d{4}(?:\d{2})?Z?", value):
        raise ICalendarError(f"Unsupported iCalendar date-time: {value!r}")

    is_utc = value.endswith("Z")
    raw = value[:-1] if is_utc else value
    fmt = "%Y%m%dT%H%M%S" if len(raw) == 15 else "%Y%m%dT%H%M"
    try:
        parsed = datetime.strptime(raw, fmt)
    except ValueError as exc:
        raise ICalendarError(f"Invalid iCalendar date-time: {value!r}") from exc

    tz_name = "UTC" if is_utc else resolved_tz
    try:
        timezone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ICalendarError(f"Unknown time zone {tz_name!r}") from exc
    return parsed.replace(tzinfo=timezone).isoformat(), tz_name, False


def _event_from_properties(
    properties: dict[str, list[tuple[dict[str, str], str]]],
    strict: bool = True,
) -> dict[str, Any] | None:
    for name in ("UID", "SUMMARY", "DTSTART", "DTEND", "DURATION", "STATUS"):
        if len(properties.get(name, [])) > 1:
            raise ICalendarError(f"VEVENT contains multiple {name} properties")

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

    start_at, timezone_name, is_all_day = _parse_datetime(start_item[1], start_item[0])
    end_item = first("DTEND")
    duration_item = first("DURATION")
    if end_item and duration_item:
        raise ICalendarError(f"VEVENT {uid_item[1]!r} cannot contain both DTEND and DURATION")

    end_at = None
    if end_item:
        end_at, _, end_is_all_day = _parse_datetime(end_item[1], end_item[0])
        if end_is_all_day != is_all_day:
            if strict:
                raise ICalendarError(f"VEVENT {uid_item[1]!r} DTSTART and DTEND value types do not match")
            if not is_all_day and end_is_all_day:
                dt_end_date = date.fromisoformat(end_at)
                end_dt = datetime.combine(dt_end_date, time(23, 59, 59), tzinfo=ZoneInfo(timezone_name))
                end_at = end_dt.isoformat()
            elif is_all_day and not end_is_all_day:
                end_at = end_at[:10]
        if is_all_day:
            if date.fromisoformat(end_at) <= date.fromisoformat(start_at):
                end_at = (date.fromisoformat(start_at) + timedelta(days=1)).isoformat()
        else:
            start_utc = datetime.fromisoformat(start_at).astimezone(dt_timezone.utc)
            end_utc = datetime.fromisoformat(end_at).astimezone(dt_timezone.utc)
            if end_utc <= start_utc:
                raise ICalendarError(f"VEVENT {uid_item[1]!r} DTEND must be after DTSTART")
    elif duration_item:
        nominal, exact = _parse_duration(duration_item[1], is_all_day)
        try:
            if is_all_day:
                end_at = (date.fromisoformat(start_at) + nominal).isoformat()
            else:
                start_datetime = datetime.fromisoformat(start_at).astimezone(ZoneInfo(timezone_name))
                end_datetime = start_datetime + nominal
                if exact:
                    end_datetime = (end_datetime.astimezone(dt_timezone.utc) + exact).astimezone(ZoneInfo(timezone_name))
                if end_datetime.astimezone(dt_timezone.utc) <= start_datetime.astimezone(dt_timezone.utc):
                    raise ICalendarError(f"VEVENT {uid_item[1]!r} DURATION must end after DTSTART")
                end_at = end_datetime.isoformat()
        except (OverflowError, ValueError) as exc:
            raise ICalendarError(f"VEVENT {uid_item[1]!r} DURATION is out of range") from exc
    elif is_all_day:
        # RFC 5545 gives DATE events without an explicit end a one-day span.
        try:
            end_at = (date.fromisoformat(start_at) + timedelta(days=1)).isoformat()
        except (OverflowError, ValueError) as exc:
            raise ICalendarError(f"VEVENT {uid_item[1]!r} implicit end is out of range") from exc
    else:
        # A DATE-TIME event without DTEND or DURATION is instantaneous.
        end_at = start_at

    categories: list[str] = []
    for _, raw_categories in properties.get("CATEGORIES", []):
        categories.extend(item for raw in _split_escaped_commas(raw_categories) if (item := _unescape_text(raw).strip()))

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
        "timezone": timezone_name,
        "is_all_day": is_all_day,
        "location": normalize_wm_location(text_value("LOCATION")),
        "source_url": text_value("URL"),
        "categories": categories,
    }


DAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _expand_rrule(
    event: dict[str, Any],
    rrule_str: str,
    exdate_items: list[tuple[dict[str, str], str]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Expand RFC 5545 RRULE occurrences over [now - 2 days, now + 45 days] in America/New_York."""
    campus_tz = ZoneInfo(DEFAULT_TIMEZONE)
    if now is None:
        now = datetime.now(campus_tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=campus_tz)
    else:
        now = now.astimezone(campus_tz)

    win_start = now - timedelta(days=2)
    win_end = now + timedelta(days=45)

    is_all_day = bool(event["is_all_day"])
    exdates: set[Any] = set()
    for params, val_str in exdate_items:
        for token in val_str.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                ex_iso, _, ex_is_all_day = _parse_datetime(token, params)
                if is_all_day or ex_is_all_day:
                    exdates.add(date.fromisoformat(ex_iso[:10]))
                else:
                    exdates.add(datetime.fromisoformat(ex_iso).astimezone(dt_timezone.utc))
            except Exception:
                continue

    parts: dict[str, str] = {}
    for item in rrule_str.split(";"):
        k, sep, v = item.partition("=")
        if sep:
            parts[k.strip().upper()] = v.strip()

    freq = parts.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY"):
        return [event]

    try:
        interval = max(1, int(parts.get("INTERVAL", 1)))
    except ValueError:
        interval = 1

    count_limit = int(parts["COUNT"]) if "COUNT" in parts and parts["COUNT"].isdigit() else None

    until_dt: datetime | None = None
    until_d: date | None = None
    if "UNTIL" in parts:
        raw_until = parts["UNTIL"]
        try:
            until_iso, _, until_all_day = _parse_datetime(raw_until, {"VALUE": "DATE"} if re.fullmatch(r"\d{8}", raw_until) else {})
            if until_all_day:
                until_d = date.fromisoformat(until_iso[:10])
            else:
                until_dt = datetime.fromisoformat(until_iso)
        except Exception:
            pass

    occurrences: list[Any] = []
    total_count = 0
    base_uid = event["uid"]

    if is_all_day:
        start_d = date.fromisoformat(event["start_at"])
        end_d = date.fromisoformat(event["end_at"])
        duration_d = end_d - start_d
        win_start_d = win_start.astimezone(campus_tz).date()
        win_end_d = win_end.astimezone(campus_tz).date()

        if freq == "DAILY":
            cur_d = start_d
            while True:
                if until_d is not None and cur_d > until_d:
                    break
                if until_dt is not None and datetime.combine(cur_d, datetime.min.time(), tzinfo=campus_tz).astimezone(dt_timezone.utc) > until_dt.astimezone(dt_timezone.utc):
                    break
                total_count += 1
                if count_limit is not None and total_count > count_limit:
                    break
                if cur_d not in exdates:
                    if win_start_d <= cur_d <= win_end_d:
                        occurrences.append(cur_d)
                cur_d += timedelta(days=interval)
                if cur_d > win_end_d + timedelta(days=7) or total_count > 1000:
                    break

        elif freq == "WEEKLY":
            byday_str = parts.get("BYDAY")
            if byday_str:
                bydays = sorted(set(DAY_CODES[d[-2:].upper()] for d in byday_str.split(",") if d[-2:].upper() in DAY_CODES))
            else:
                bydays = [start_d.weekday()]

            cur_week_monday = start_d - timedelta(days=start_d.weekday())
            stopped = False
            while not stopped:
                for day_idx in bydays:
                    cand_d = cur_week_monday + timedelta(days=day_idx)
                    if cand_d < start_d:
                        continue
                    if until_d is not None and cand_d > until_d:
                        stopped = True
                        break
                    if until_dt is not None and datetime.combine(cand_d, datetime.min.time(), tzinfo=campus_tz).astimezone(dt_timezone.utc) > until_dt.astimezone(dt_timezone.utc):
                        stopped = True
                        break
                    total_count += 1
                    if count_limit is not None and total_count > count_limit:
                        stopped = True
                        break
                    if cand_d not in exdates:
                        if win_start_d <= cand_d <= win_end_d:
                            occurrences.append(cand_d)
                cur_week_monday += timedelta(weeks=interval)
                if cur_week_monday > win_end_d + timedelta(days=7) or total_count > 1000:
                    break

        if not occurrences:
            return []
        instances = []
        for occ_d in occurrences:
            inst = dict(event)
            inst["start_at"] = occ_d.isoformat()
            inst["end_at"] = (occ_d + duration_d).isoformat()
            inst["uid"] = f"{base_uid}::{occ_d.strftime('%Y%m%dT%H%M')}"
            instances.append(inst)
        return instances

    else:
        start_dt = datetime.fromisoformat(event["start_at"])
        end_dt = datetime.fromisoformat(event["end_at"])
        duration = end_dt - start_dt
        start_time = start_dt.timetz()

        if freq == "DAILY":
            cur_date = start_dt.date()
            while True:
                cur_dt = datetime.combine(cur_date, start_time)
                if until_dt is not None and cur_dt.astimezone(dt_timezone.utc) > until_dt.astimezone(dt_timezone.utc):
                    break
                if until_d is not None and cur_date > until_d:
                    break
                total_count += 1
                if count_limit is not None and total_count > count_limit:
                    break
                if cur_dt.astimezone(dt_timezone.utc) not in exdates:
                    cur_ny = cur_dt.astimezone(campus_tz)
                    if win_start <= cur_ny <= win_end:
                        occurrences.append(cur_dt)
                cur_date += timedelta(days=interval)
                if datetime.combine(cur_date, start_time).astimezone(campus_tz) > win_end + timedelta(days=7) or total_count > 1000:
                    break

        elif freq == "WEEKLY":
            byday_str = parts.get("BYDAY")
            if byday_str:
                bydays = sorted(set(DAY_CODES[d[-2:].upper()] for d in byday_str.split(",") if d[-2:].upper() in DAY_CODES))
            else:
                bydays = [start_dt.weekday()]

            cur_week_monday = start_dt.date() - timedelta(days=start_dt.weekday())
            stopped = False
            while not stopped:
                for day_idx in bydays:
                    cand_date = cur_week_monday + timedelta(days=day_idx)
                    if cand_date < start_dt.date():
                        continue
                    cand_dt = datetime.combine(cand_date, start_time)
                    if until_dt is not None and cand_dt.astimezone(dt_timezone.utc) > until_dt.astimezone(dt_timezone.utc):
                        stopped = True
                        break
                    if until_d is not None and cand_date > until_d:
                        stopped = True
                        break
                    total_count += 1
                    if count_limit is not None and total_count > count_limit:
                        stopped = True
                        break
                    if cand_dt.astimezone(dt_timezone.utc) not in exdates:
                        cand_ny = cand_dt.astimezone(campus_tz)
                        if win_start <= cand_ny <= win_end:
                            occurrences.append(cand_dt)
                cur_week_monday += timedelta(weeks=interval)
                if datetime.combine(cur_week_monday, start_time).astimezone(campus_tz) > win_end + timedelta(days=7) or total_count > 1000:
                    break

        if not occurrences:
            return []
        instances = []
        for occ_dt in occurrences:
            inst = dict(event)
            inst["start_at"] = occ_dt.isoformat()
            inst["end_at"] = (occ_dt + duration).isoformat()
            inst["uid"] = f"{base_uid}::{occ_dt.strftime('%Y%m%dT%H%M')}"
            instances.append(inst)
        return instances


def parse_ical(text: str, now: datetime | None = None, strict: bool = True) -> list[dict[str, Any]]:
    """Parse VEVENT records from a UTF-8 iCalendar feed.

    The parser supports folded lines, quoted parameters, escaped text, all-day
    dates, UTC values, TZID-local values, VEVENT DURATION, and RFC 5545 RRULE
    expansion (FREQ=DAILY|WEEKLY) with EXDATE over [now - 2 days, now + 45 days].
    Date-times without Z or TZID are interpreted in W&M's ``America/New_York`` timezone.
    """
    if not isinstance(text, str):
        raise ICalendarError("Feed must be text")
    if len(text) > MAX_ICAL_BYTES:
        raise ICalendarError(f"Feed exceeds {MAX_ICAL_BYTES} bytes")
    try:
        byte_count = 0
        for offset in range(0, len(text), 64 * 1024):
            byte_count += len(text[offset : offset + 64 * 1024].encode("utf-8"))
            if byte_count > MAX_ICAL_BYTES:
                raise ICalendarError(f"Feed exceeds {MAX_ICAL_BYTES} bytes")
    except UnicodeEncodeError as exc:
        raise ICalendarError("Feed contains invalid Unicode text") from exc
    physical_line_count = text.count("\n") + text.count("\r") - text.count("\r\n")
    if physical_line_count > MAX_ICAL_LINES:
        raise ICalendarError(f"Feed exceeds {MAX_ICAL_LINES} lines")
    lines = _unfold_lines(text)
    if not any(line.upper() == "BEGIN:VCALENDAR" for line in lines) or not any(
        line.upper() == "END:VCALENDAR" for line in lines
    ):
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
            try:
                event = _event_from_properties(current, strict=strict)
                if event is not None:
                    rrule_list = current.get("RRULE", [])
                    if rrule_list:
                        exdate_items = current.get("EXDATE", [])
                        expanded = _expand_rrule(event, rrule_list[0][1], exdate_items, now=now)
                        events.extend(expanded)
                    else:
                        events.append(event)
            except ICalendarError:
                if strict:
                    raise
            current = None
            continue
        if current is None:
            continue
        try:
            name, params, value = _split_content_line(line)
            current.setdefault(name, []).append((params, value))
        except ICalendarError:
            if strict:
                raise
            if current:
                last_key = list(current.keys())[-1]
                last_params, last_val = current[last_key][-1]
                current[last_key][-1] = (last_params, last_val + " " + line.strip())

    if current is not None:
        raise ICalendarError("Unclosed VEVENT block")

    uids = [event["uid"] for event in events]
    if len(uids) != len(set(uids)):
        if strict:
            raise ICalendarError("Feed contains duplicate event UIDs")
        seen_uids: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for ev in events:
            if ev["uid"] not in seen_uids:
                seen_uids.add(ev["uid"])
                deduped.append(ev)
        events = deduped
    return events


def import_calendar(
    conn: sqlite3.Connection,
    slug: str,
    name: str,
    text: str,
    strict: bool = False,
) -> dict[str, int]:
    """Atomically replace one calendar's membership from a parsed feed.

    A parse failure leaves both event records and memberships untouched.
    """
    if not slug.strip():
        raise ValueError("calendar slug must not be blank")
    events = parse_ical(text, strict=strict)
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

