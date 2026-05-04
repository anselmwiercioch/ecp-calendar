#!/usr/bin/env python3
"""
ECP Calendar Scraper
Fetches events from https://pittecp.org/calendar and outputs a .ics file.
"""

import re
import sys
import uuid
import datetime
import urllib.request
import urllib.error
from html.parser import HTMLParser


CALENDAR_URL = "https://pittecp.org/Calendar"
# Fetch several months ahead by scraping multiple month pages
MONTHS_AHEAD = 6


class EventLinkParser(HTMLParser):
    """Extracts event links and basic info from the calendar page."""

    def __init__(self):
        super().__init__()
        self.events = {}  # keyed by event URL to deduplicate
        self._in_link = False
        self._current_href = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attr_dict = dict(attrs)
            href = attr_dict.get("href", "")
            title_attr = attr_dict.get("title", "")
            # Event links look like /event-XXXXXXX
            if re.match(r"https?://pittecp\.org/event-\d+", href) or re.match(r"/event-\d+", href):
                full_url = href if href.startswith("http") else f"https://pittecp.org{href}"
                # Strip query params from URL key
                base_url = full_url.split("?")[0]
                if base_url not in self.events:
                    self.events[base_url] = {
                        "url": base_url,
                        "title_attr": title_attr,
                    }

    def handle_endtag(self, tag):
        pass

    def handle_data(self, data):
        pass


class EventDetailParser(HTMLParser):
    """Parses an individual event page for full details."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.start_dt = None
        self.end_dt = None
        self.location = ""
        self.description = ""
        self._capture = None
        self._depth = 0
        self._capture_depth = 0
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "")

        if "eventTitle" in classes or "event-title" in classes:
            self._capture = "title"
            self._buffer = []
            self._capture_depth = self._depth

        if "eventLocation" in classes or "event-location" in classes:
            self._capture = "location"
            self._buffer = []
            self._capture_depth = self._depth

        if "eventDescription" in classes or "event-description" in classes:
            self._capture = "description"
            self._buffer = []
            self._capture_depth = self._depth

        self._depth += 1

    def handle_endtag(self, tag):
        self._depth -= 1
        if self._capture and self._depth <= self._capture_depth:
            text = " ".join(self._buffer).strip()
            if self._capture == "title":
                self.title = text
            elif self._capture == "location":
                self.location = text
            elif self._capture == "description":
                self.description = text[:500]  # truncate long descriptions
            self._capture = None
            self._buffer = []

    def handle_data(self, data):
        if self._capture:
            stripped = data.strip()
            if stripped:
                self._buffer.append(stripped)


def fetch_url(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ECP-Calendar-Sync/1.0 (+https://github.com)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_title_attr(title_attr):
    """
    Parse the title attribute on calendar event links.
    Format: "n[HH:MM AM]MM/DD/YYYY, HH:MM AM Location"
    or multi-day: "n[]MM/DD/YYYY  MM/DD/YYYY Location"
    """
    result = {"start": None, "end": None, "location": ""}

    # Extract date/time info from title attribute
    # Pattern: n[time]date info
    m = re.match(r"n\[([^\]]*)\](.*)", title_attr, re.DOTALL)
    if not m:
        return result

    time_str = m.group(1).strip()
    rest = m.group(2).strip()

    # Try to find dates in the rest
    date_pattern = r"(\d{1,2}/\d{1,2}/\d{4})"
    dates = re.findall(date_pattern, rest)

    if not dates:
        return result

    start_date_str = dates[0]
    end_date_str = dates[1] if len(dates) > 1 else dates[0]

    # Try to parse time
    time_obj = None
    if time_str:
        for fmt in ["%I:%M %p", "%H:%M"]:
            try:
                time_obj = datetime.datetime.strptime(time_str, fmt).time()
                break
            except ValueError:
                continue

    # Parse dates
    try:
        start_date = datetime.datetime.strptime(start_date_str, "%m/%d/%Y").date()
        end_date = datetime.datetime.strptime(end_date_str, "%m/%d/%Y").date()
    except ValueError:
        return result

    if time_obj:
        result["start"] = datetime.datetime.combine(start_date, time_obj)
        # Default 2 hour duration if no end time
        result["end"] = result["start"] + datetime.timedelta(hours=2)
        result["all_day"] = False
    else:
        result["start"] = start_date
        result["end"] = end_date + datetime.timedelta(days=1)  # iCal end is exclusive
        result["all_day"] = True

    # Extract location (text after the last date)
    last_date = dates[-1]
    loc_match = re.search(re.escape(last_date) + r"\s*(.*)", rest)
    if loc_match:
        result["location"] = loc_match.group(1).strip()

    return result


def extract_event_title(html, url):
    """Extract the event title from the event page HTML."""
    # Try og:title meta tag first
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Try <title> tag
    m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        t = m.group(1).strip()
        # Remove site name suffix
        t = re.sub(r"\s*[-|].*Explorers Club.*", "", t, flags=re.IGNORECASE).strip()
        if t:
            return t

    # Fallback: derive from URL
    m = re.search(r"/event-(\d+)", url)
    return f"ECP Event {m.group(1)}" if m else "ECP Event"


def extract_description(html):
    """Extract event description text from HTML."""
    # Look for common description containers
    for pattern in [
        r'class="[^"]*eventDescription[^"]*"[^>]*>(.*?)</div>',
        r'class="[^"]*event-description[^"]*"[^>]*>(.*?)</div>',
        r'class="[^"]*description[^"]*"[^>]*>(.*?)</div>',
    ]:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            text = re.sub(r"<[^>]+>", " ", m.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 20:
                return text[:1000]
    return ""


def scrape_month(year, month):
    """Scrape a single month's calendar page and return event stubs."""
    url = f"{CALENDAR_URL}?EventViewMode=1&EventListViewMode=2&SelectedDate={month}/1/{year}&CalendarViewType=1"
    try:
        html = fetch_url(url)
    except Exception as e:
        print(f"  Warning: could not fetch {url}: {e}", file=sys.stderr)
        return {}

    parser = EventLinkParser()
    parser.feed(html)
    return parser.events


def build_ics_event(uid, summary, start, end, location, description, url, all_day=False):
    """Build a VEVENT string."""
    now = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    def ics_escape(s):
        s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        s = s.replace("\n", "\\n").replace("\r", "")
        return s

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"SUMMARY:{ics_escape(summary)}",
    ]

    if all_day:
        if isinstance(start, datetime.datetime):
            start = start.date()
        if isinstance(end, datetime.datetime):
            end = end.date()
        lines.append(f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}")
    else:
        # Treat as America/New_York local time
        lines.append(f"DTSTART;TZID=America/New_York:{start.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"DTEND;TZID=America/New_York:{end.strftime('%Y%m%dT%H%M%S')}")

    if location:
        lines.append(f"LOCATION:{ics_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{ics_escape(description)}")
    if url:
        lines.append(f"URL:{url}")

    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def fold_line(line):
    """Fold long lines per RFC 5545 (max 75 octets)."""
    result = []
    while len(line.encode("utf-8")) > 75:
        # Find safe split point
        for i in range(75, 0, -1):
            if len(line[:i].encode("utf-8")) <= 75:
                result.append(line[:i])
                line = " " + line[i:]
                break
        else:
            result.append(line[:75])
            line = " " + line[75:]
    result.append(line)
    return "\r\n".join(result)


def main():
    print("ECP Calendar Scraper", file=sys.stderr)
    print("=" * 40, file=sys.stderr)

    # Collect events across multiple months
    all_event_stubs = {}
    now = datetime.date.today()

    for i in range(MONTHS_AHEAD):
        month = (now.month - 1 + i) % 12 + 1
        year = now.year + (now.month - 1 + i) // 12
        print(f"Fetching {year}-{month:02d}...", file=sys.stderr)
        stubs = scrape_month(year, month)
        all_event_stubs.update(stubs)
        print(f"  Found {len(stubs)} event links", file=sys.stderr)

    print(f"\nTotal unique events found: {len(all_event_stubs)}", file=sys.stderr)

    # Build ICS events
    vevents = []
    for event_url, stub in all_event_stubs.items():
        title_attr = stub.get("title_attr", "")
        parsed = parse_title_attr(title_attr)

        if parsed["start"] is None:
            # Try fetching the event page for more info
            try:
                print(f"  Fetching detail page: {event_url}", file=sys.stderr)
                detail_html = fetch_url(event_url)
                summary = extract_event_title(detail_html, event_url)
                description = extract_description(detail_html)
                location = parsed.get("location", "")
                # Skip if we still can't get dates
                print(f"  Warning: no date parsed for {event_url}, skipping", file=sys.stderr)
                continue
            except Exception as e:
                print(f"  Error fetching {event_url}: {e}", file=sys.stderr)
                continue
        else:
            summary = extract_event_title("", event_url)  # placeholder
            description = ""
            location = parsed.get("location", "")

        # Try to get better title from event page
        try:
            detail_html = fetch_url(event_url)
            summary = extract_event_title(detail_html, event_url)
            description = extract_description(detail_html)
        except Exception:
            pass  # use whatever we have

        # Generate stable UID from URL
        event_id = re.search(r"event-(\d+)", event_url)
        uid = f"{event_id.group(1) if event_id else uuid.uuid4()}@pittecp.org"

        all_day = parsed.get("all_day", False)
        vevent = build_ics_event(
            uid=uid,
            summary=summary,
            start=parsed["start"],
            end=parsed["end"],
            location=location,
            description=description,
            url=event_url,
            all_day=all_day,
        )
        vevents.append(vevent)
        print(f"  ✓ {summary}", file=sys.stderr)

    # Assemble full ICS
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ECP Calendar Sync//pittecp.org//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Explorers Club of Pittsburgh",
        "X-WR-CALDESC:Events from the Explorers Club of Pittsburgh",
        "X-WR-TIMEZONE:America/New_York",
        # Inline timezone definition for America/New_York
        "BEGIN:VTIMEZONE",
        "TZID:America/New_York",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:-0500",
        "TZOFFSETTO:-0400",
        "TZNAME:EDT",
        "DTSTART:19700308T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:-0400",
        "TZOFFSETTO:-0500",
        "TZNAME:EST",
        "DTSTART:19701101T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    for vevent in vevents:
        ics_lines.extend(vevent.split("\r\n"))

    ics_lines.append("END:VCALENDAR")

    # Fold and join
    folded = "\r\n".join(fold_line(line) for line in ics_lines)

    print(folded)
    print(f"\nDone! Generated {len(vevents)} events.", file=sys.stderr)


if __name__ == "__main__":
    main()
