#!/usr/bin/env python3
"""Import public W&M iCalendar feeds into ``schedule.db``.

Live discovery starts at https://events.wm.edu/search/all_calendars, follows
calendar pages on that host, and imports only same-host ICS/export links. The
directory's live markup and feed availability must be verified at run time;
this tool reports every skipped source and never treats a failed fetch as an
empty successful calendar. Use ``--file SLUG=PATH`` to import saved feeds.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from wm_data import (
    ALLOWED_HOSTS,
    ICalendarError,
    MAX_ICAL_BYTES,
    ensure_schema,
    import_calendar,
    is_allowed_feed_url,
)

HOST = "events.wm.edu"
DIRECTORY = f"https://{HOST}/search/all_calendars"
MAX_BYTES = MAX_ICAL_BYTES
USER_AGENT = "WMEventsLocalImporter/1.0 (public calendar feed importer)"
DEFAULT_DISCOVERY_FEEDS = [
    ("tribelink", "TribeLink Campus Events", "https://tribelink.wm.edu/events.ics"),
    ("wm-main", "William & Mary Master Calendar", "https://events.wm.edu/calendar/upcoming_ical/wm"),
    ("studentengagement", "Student Engagement & Activities", "https://events.wm.edu/calendar/upcoming_ical/studentengagement"),
    ("libraries", "Swem Library Events & Workshops", "https://events.wm.edu/calendar/upcoming_ical/libraries"),
    ("swem", "Swem Library", "https://events.wm.edu/calendar/upcoming_ical/swem"),
    ("athletics", "W&M Tribe Athletics", "https://events.wm.edu/calendar/upcoming_ical/athletics"),
    ("tribeathletics", "W&M Tribe Athletics (Varsity)", "https://tribeathletics.com/calendar.ashx/calendar.ics"),
    ("recsports", "Campus Recreation & Fitness", "https://events.wm.edu/calendar/upcoming_ical/recsports"),
    ("career", "Cohen Career Center", "https://events.wm.edu/calendar/upcoming_ical/career"),
    ("wellness", "Health & Wellness", "https://events.wm.edu/calendar/upcoming_ical/wellness"),
    ("arts", "Arts & Entertainment", "https://events.wm.edu/calendar/upcoming_ical/arts"),
    ("theatre-performance", "Theatre & Performance", "https://events.wm.edu/calendar/upcoming_ical/theatre-performance"),
    ("music", "Music Department Events", "https://events.wm.edu/calendar/upcoming_ical/music"),
    ("student-affairs", "Student Affairs & Campus Life", "https://events.wm.edu/calendar/upcoming_ical/student-affairs"),
    ("cce", "Civic & Community Engagement", "https://events.wm.edu/calendar/upcoming_ical/cce"),
    ("computerscience", "Computer Science Colloquia & Events", "https://events.wm.edu/calendar/upcoming_ical/computerscience"),
    ("studenthappenings", "Sadler & Campus Happenings", "https://events.wm.edu/calendar/upcoming_ical/studenthappenings"),
    ("academiccalendarug", "Undergraduate Academic Calendar", "https://events.wm.edu/calendar/upcoming_ical/academiccalendarug"),
]


class SameHostRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_feed_url(newurl):
            raise URLError(f"refused redirect away from allowed W&M HTTPS feeds: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "a" and attrs.get("href"):
            self._current = {key: value or "" for key, value in attrs.items()}
            self._current["text"] = ""
            self.links.append(self._current)
        elif self._current is not None and tag.lower() == "img":
            self._current["text"] += " " + attrs.get("alt", "")

    def handle_data(self, data):
        if self._current is not None:
            self._current["text"] += data

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            self._current = None


def _same_host_https(url: str) -> bool:
    parsed = urlparse(url)
    try:
        allowed_port = parsed.port in (None, 443)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == HOST
        and parsed.username is None
        and allowed_port
    )


def _get(url: str, delay: float = 0.0, timeout: float = 20.0) -> tuple[bytes, str]:
    if not is_allowed_feed_url(url):
        raise ValueError(f"refused non-W&M HTTPS URL: {url}")
    if delay:
        time.sleep(delay)
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/calendar,*/*"})
    with build_opener(SameHostRedirects()).open(req, timeout=timeout) as response:
        final_url = response.geturl()
        if not is_allowed_feed_url(final_url):
            raise ValueError(f"refused final URL outside allowed W&M hosts: {final_url}")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"response exceeded {MAX_BYTES} bytes")
        return data, response.headers.get_content_type()


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="strict")


def _read_local_feed(path: Path, max_bytes: int = MAX_BYTES) -> str:
    """Read a saved feed without allowing it to exceed the live-feed cap."""
    with path.open("rb") as feed:
        data = feed.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"file exceeded {max_bytes} bytes")
    return _decode(data)


def _calendar_pages(html: str, base: str) -> list[tuple[str, str, str]]:
    parser = Links()
    parser.feed(html)
    pages: dict[str, tuple[str, str, str]] = {}
    for link in parser.links:
        url = urljoin(base, link["href"])
        if not _same_host_https(url):
            continue
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        # Directory links point to canonical homepages at
        # /calendar/upcoming/<slug>. This excludes month views, event detail
        # pages, search routes, and arbitrary URLs containing "calendar".
        if len(path_parts) != 3 or [part.lower() for part in path_parts[:2]] != ["calendar", "upcoming"]:
            continue
        slug = path_parts[2]
        title = (link.get("text", "") or link.get("title", "")).strip()
        if not title:
            title = slug.replace("_", " ").replace("-", " ").title()
        pages.setdefault(url, (slug, title, url))
    return list(pages.values())


def _feed_links(html: str, base: str) -> list[str]:
    parser = Links()
    parser.feed(html)
    found: list[str] = []
    for link in parser.links:
        raw_href = link.get("href", "").strip()
        if not raw_href:
            continue
        url = urljoin(base, raw_href)
        if not is_allowed_feed_url(url):
            continue
        parsed = urlparse(url)
        url_lower = url.lower()
        path_lower = parsed.path.lower()
        is_ics_ext = path_lower.endswith(".ics") or re.search(r"\.ics(?:$|[?#])", url_lower) is not None
        is_ical_route = (
            "/upcoming_ical/" in path_lower
            or "/view_ical/" in path_lower
            or "format=ics" in url_lower
        )
        if is_ics_ext or is_ical_route:
            if url not in found:
                found.append(url)
    return found


def discover_and_import(
    conn: sqlite3.Connection,
    delay: float = 0.5,
    timeout: float = 14.0,
    discover_directory: bool = False,
) -> tuple[int, int]:
    """Attempt public feed sync; crawl directory only if discover_directory is True."""
    successes = failures = 0
    # First, import default discovery feeds (master calendar & tribelink)
    for slug, name, feed_url in DEFAULT_DISCOVERY_FEEDS:
        try:
            feed_data, _ = _get(feed_url, delay=delay, timeout=timeout)
            result = import_calendar(conn, slug, name, _decode(feed_data))
            successes += 1
            print(f"IMPORTED {slug}: {result['seen']} events ({feed_url})")
        except Exception as exc:
            failures += 1
            print(f"INACCESSIBLE/UNRECOGNIZED: {slug} feed {feed_url}: {exc}", file=sys.stderr)

    if not discover_directory:
        return successes, failures

    try:
        directory_data, _ = _get(DIRECTORY, delay=delay, timeout=timeout)
        pages = _calendar_pages(_decode(directory_data), DIRECTORY)
        if not pages:
            print(f"UNRECOGNIZED: no same-host calendar page links found at {DIRECTORY}", file=sys.stderr)
            return successes, failures + 1
    except Exception as exc:
        print(f"INACCESSIBLE: directory {DIRECTORY}: {exc}", file=sys.stderr)
        return successes, failures + 1

    print(f"Discovered {len(pages)} candidate calendar pages from {DIRECTORY}.")
    for slug, name, page_url in pages:
        try:
            page_data, _ = _get(page_url, delay=delay, timeout=timeout)
            feeds = _feed_links(_decode(page_data), page_url)
            if not feeds:
                failures += 1
                print(f"UNRECOGNIZED: no same-host ICS/export link on {page_url}", file=sys.stderr)
                continue
            feed_url = feeds[0]
            if len(feeds) > 1:
                print(f"NOTE: {slug} exposes {len(feeds)} export links; using {feed_url}", file=sys.stderr)
            try:
                feed_data, _ = _get(feed_url, delay=delay, timeout=timeout)
                result = import_calendar(conn, slug, name, _decode(feed_data))
                successes += 1
                print(f"IMPORTED {slug}: {result['seen']} events ({feed_url})")
            except Exception as exc:
                failures += 1
                print(f"INACCESSIBLE/UNRECOGNIZED: {slug} feed {feed_url}: {exc}", file=sys.stderr)
        except Exception as exc:
            failures += 1
            print(f"INACCESSIBLE: calendar page {page_url}: {exc}", file=sys.stderr)
    return successes, failures


def _database_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    content_dir = os.environ.get("SCIEDU_CONTENT_DIR")
    return Path(content_dir).expanduser() / "schedule.db" if content_dir else Path(__file__).resolve().parent / "schedule.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import W&M calendar ICS feeds. Live mode only covers discovered, accessible same-host feeds; use --file for saved .ics files.",
        epilog="Examples: python import_wm_events.py --discover; python import_wm_events.py --file student-life=events.ics --db schedule.db",
    )
    parser.add_argument("--discover", action="store_true", help="crawl events.wm.edu/search/all_calendars and accessible same-host ICS/export links")
    parser.add_argument("--file", action="append", default=[], metavar="SLUG=PATH", help="import a previously downloaded local .ics file; repeatable")
    parser.add_argument("--db", help="SQLite path (default: SCIEDU_CONTENT_DIR/schedule.db or project schedule.db)")
    parser.add_argument("--delay", type=float, default=1.0, help="minimum seconds between live requests (default: 1.0)")
    args = parser.parse_args(argv)
    if not args.discover and not args.file:
        parser.error("choose --discover and/or at least one --file SLUG=PATH")
    if args.delay < 0:
        parser.error("--delay must be non-negative")

    db_path = _database_path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    successes = failures = 0
    for item in args.file:
        slug, separator, filename = item.partition("=")
        if not separator or not slug.strip() or not filename:
            print(f"INVALID --file value {item!r}; expected SLUG=PATH", file=sys.stderr)
            failures += 1
            continue
        path = Path(filename).expanduser()
        try:
            content = _read_local_feed(path)
            count = import_calendar(conn, slug.strip(), slug.strip(), content)
            successes += 1
            print(f"IMPORTED {slug.strip()}: {count['seen']} events from {path}")
        except (OSError, UnicodeError, ICalendarError, sqlite3.Error, ValueError) as exc:
            failures += 1
            print(f"INACCESSIBLE/UNRECOGNIZED: {path}: {exc}", file=sys.stderr)
    if args.discover:
        live_successes, live_failures = discover_and_import(conn, args.delay, discover_directory=True)
        successes += live_successes
        failures += live_failures
    conn.commit()
    conn.close()
    print(f"Completed with {successes} feed imports and {failures} source failures; this is not a claim of complete W&M calendar coverage.")
    return 0 if successes and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
