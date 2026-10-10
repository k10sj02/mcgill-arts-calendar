"""Aggregate McGill's official per-event exports; fail closed on incomplete crawls."""
import argparse
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCE = "https://www.mcgill.ca/channels/section/group_arts_culture/channel_event"
TZ = ZoneInfo("America/Toronto")
FREE_TAG = "Free events"
FREE_PREFIX = "🆓 FREE | "


def safe_url(base, href):
    url = urljoin(base, href)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.mcgill.ca":
        raise ValueError(f"Unexpected source URL: {url}")
    return url


def listing(html, url):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(".channel_event.views-row")
    if not rows:
        raise ValueError(f"No event rows found: {url}")
    links = []
    for row in rows:
        a = row.select_one(".views-field-title a")
        if not a or not re.search(r"/event/[^/]+-\d+$", a.get("href", "")):
            raise ValueError("Event row missing recognizable URL")
        links.append(safe_url(url, a["href"]))
    nxt = soup.select_one(".pager-next a")
    next_url = safe_url(url, nxt["href"]) if nxt else None
    if next_url and urlsplit(next_url).path != urlsplit(SOURCE).path:
        raise ValueError("Unexpected pagination path")
    return links, next_url


def export_link(html, url):
    soup = BeautifulSoup(html, "html.parser")
    a = soup.select_one("a.service-links-ical")
    if not a or not re.fullmatch(r"/channels/node/\d+/ical", a.get("href", "")):
        raise ValueError(f"Missing official calendar export: {url}")
    return safe_url(url, a["href"])


def event_tags(html):
    soup = BeautifulSoup(html, "html.parser")
    return [meta["content"] for meta in soup.select('meta[name="mcgill_tag"][content]')]


def apply_tags(event, tags):
    if FREE_TAG not in tags:
        return
    summary = str(event["SUMMARY"])
    if not summary.startswith(FREE_PREFIX):
        event["SUMMARY"] = FREE_PREFIX + summary
    categories = event.get("CATEGORIES")
    properties = categories if isinstance(categories, list) else [categories] if categories else []
    existing = [str(value) for prop in properties for value in prop.cats]
    if FREE_TAG not in existing:
        if "CATEGORIES" in event:
            del event["CATEGORIES"]
        event.add("CATEGORIES", [*existing, FREE_TAG])


def normalize(data, url, stamp, tags=()):
    cal = Calendar.from_ical(data)
    events = cal.walk("VEVENT")
    if not events:
        raise ValueError(f"Empty event export: {url}")
    node_id = re.search(r"-(\d+)$", url).group(1)
    result = []
    for index, event in enumerate(events):
        if not event.get("SUMMARY") or not event.get("DTSTART"):
            raise ValueError(f"Incomplete event export: {url}")
        if event.get("RRULE") or event.get("RECURRENCE-ID"):
            raise ValueError("Unexpected recurrence; review source before publishing")
        for key in ("DTSTART", "DTEND"):
            if key in event:
                value = event.decoded(key)
                if isinstance(value, datetime):
                    if value.tzinfo is None:
                        value = value.replace(tzinfo=TZ)
                    else:
                        value = value.astimezone(TZ)
                    del event[key]
                    event.add(key, value)
        if "DTEND" in event and event.decoded("DTEND") <= event.decoded("DTSTART"):
            raise ValueError(f"Invalid date range: {url}")
        for key in ("UID", "DTSTAMP", "URL", "LAST-MODIFIED", "SEQUENCE"):
            if key in event:
                del event[key]
        # URL numeric ID survives title/slug changes; index supports multiple exports.
        event.add("UID", f"mcgill-arts-{node_id}-{index}@mcgill-calendar.invalid")
        event.add("URL", url)
        if re.match(r"^CANCELLED\b", str(event["SUMMARY"]), re.I):
            event["STATUS"] = "CANCELLED"
        apply_tags(event, tags)
        event.add("DTSTAMP", stamp)
        result.append(event)
    return result


def fingerprint(event):
    copy = type(event).from_ical(event.to_ical())
    for key in ("DTSTAMP", "LAST-MODIFIED", "SEQUENCE"):
        if key in copy:
            del copy[key]
    return hashlib.sha256(copy.to_ical()).hexdigest()


def assemble(events, previous, stamp):
    old = {str(e["UID"]): e for e in previous.walk("VEVENT")} if previous else {}
    unique = {}
    for event in events:
        uid = str(event["UID"])
        if uid in unique and fingerprint(unique[uid]) != fingerprint(event):
            raise ValueError(f"Conflicting duplicate: {uid}")
        unique[uid] = event
    if not unique:
        raise ValueError("Refusing to publish empty calendar")
    cal = Calendar()
    for key, value in {"VERSION": "2.0", "PRODID": "-//Independent McGill Arts Calendar//EN",
                       "CALSCALE": "GREGORIAN", "X-WR-CALNAME": "McGill Music / Arts / Culture",
                       "X-WR-TIMEZONE": "America/Toronto"}.items():
        cal.add(key, value)
    timed = [e.decoded(k) for e in unique.values() for k in ("DTSTART", "DTEND")
             if k in e and isinstance(e.decoded(k), datetime)]
    if timed:
        cal.add_component(Timezone.from_tzinfo(TZ, first_date=min(timed).date(), last_date=max(timed).date()))
    for uid, event in sorted(unique.items()):
        prior = old.get(uid)
        unchanged = prior is not None and fingerprint(prior) == fingerprint(event)
        if unchanged:
            event["DTSTAMP"] = prior["DTSTAMP"]
            event["LAST-MODIFIED"] = prior.get("LAST-MODIFIED", prior["DTSTAMP"])
        else:
            event.add("LAST-MODIFIED", stamp)
        event.add("SEQUENCE", int(prior.get("SEQUENCE", 0)) + (0 if unchanged else 1) if prior else 0)
        cal.add_component(event)
    return cal


class Fetcher:
    def __init__(self, delay=0.3):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "IndependentMcGillArtsCalendar/1.0 (public calendar aggregation)"
        retry = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET"], respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, url):
        time.sleep(self.delay)
        response = self.session.get(url, timeout=(10, 45))
        response.raise_for_status()
        if urlsplit(response.url).netloc != "www.mcgill.ca":
            raise ValueError("Unexpected redirect host")
        return response.content


def crawl(fetch, max_pages=100):
    url, pages, links = SOURCE, set(), set()
    while url:
        if url in pages or len(pages) >= max_pages:
            raise ValueError("Pagination loop or page limit reached")
        pages.add(url)
        found, url = listing(fetch.get(url), url)
        links.update(found)
    stamp = datetime.now(timezone.utc)
    events = []
    for i, url in enumerate(sorted(links), 1):
        logging.info("Event %s/%s: %s", i, len(links), url)
        page = fetch.get(url)
        events.extend(normalize(fetch.get(export_link(page, url)), url, stamp, event_tags(page)))
    return events, len(pages), stamp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("public/calendar.ics"))
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    events, pages, stamp = crawl(Fetcher(), args.max_pages)
    previous = Calendar.from_ical(args.output.read_bytes()) if args.output.exists() else None
    cal = assemble(events, previous, stamp)
    data = cal.to_ical()
    Calendar.from_ical(data)  # verify before replacing the last successful feed
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(args.output)
    report = {"updated_at": stamp.isoformat(), "pages": pages, "events": len(cal.walk("VEVENT")), "source": SOURCE}
    args.output.with_name("status.json").write_text(json.dumps(report, indent=2) + "\n")
    logging.info("Published %s", report)


if __name__ == "__main__":
    main()
