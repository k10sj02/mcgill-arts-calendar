# McGill Music / Arts / Culture calendar

An independent public ICS subscription, refreshed daily from [McGill Channels](https://www.mcgill.ca/channels/section/group_arts_culture/channel_event). No API keys, server, or paid services required. Python 3.10+ (Actions uses 3.12).

## Deploy on GitHub

1. Create a **public** repository and upload all files in this folder, including `.github/`, to its `main` branch. Alternatively initialize Git here, commit, and push to your new repository.
2. In **Settings → Pages → Build and deployment → Source**, select **GitHub Actions**.
3. Enable Actions if prompted. Under **Actions → Refresh and publish calendar → Run workflow**, run the workflow on `main`.
4. Once successful, visit `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/`. Your subscription URL is `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/calendar.ics`.

Apple Calendar: File → New Calendar Subscription, paste the HTTPS URL and choose your refresh interval. Google Calendar on desktop: Other calendars → + → From URL, paste the HTTPS URL. Outlook: Add calendar → Subscribe from web. Subscribe by URL to receive changes; importing the downloaded file makes a one-time copy.

The refresh runs daily at **10:17 UTC** (06:17 Toronto during daylight time, 05:17 in winter), on pushes to main, and manually. GitHub can delay scheduled jobs; public repositories can have schedules disabled after 60 days of inactivity. Check Actions for failures and re-enable disabled schedules. Calendar clients have their own refresh delays. Pages and the feed are public.

## Local use

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python calendar_feed.py
python -m http.server --directory public 8000
```

`--output PATH` changes the feed destination; `--max-pages N` sets a safety limit (default 100). The default writes `public/calendar.ics` and `public/status.json`. The checked-in feed is a validated initial snapshot; run the workflow for fresh data.

## Source investigation and extraction

Observed October 9, 2026 (Toronto): the source is server-rendered Drupal HTML. Listing rows use `.channel_event.views-row`, titles use `.views-field-title a`, and `.pager-next a` advances zero-based `?page=1` pagination. The first listing exposed 15 events and a last-page link to `?page=10` (11 pages). The detail page for Musical Evenings with MGSS links to `/channels/node/220485/ical` through `a.service-links-ical`. That export supplies a full description, location, URL, and UTC dates matching October 15, 19:30–21:00 Toronto.

No aggregate RSS/Atom/ICS subscription was advertised in the inspected listing HTML. **Official per-event ICS exports do exist**, so this project aggregates them rather than guessing dates from display text. Their generated UIDs include export timestamps; the project replaces them with stable UIDs derived from the numeric event URL ID. A multi-VEVENT export uses its ordinal within that export; if McGill changes that ordering, review identity behavior. Unexpected recurrence definitions fail for review rather than silently lose instances.

Every listing page is followed until no next link remains. Event URLs are deduplicated, all details and exports are fetched sequentially, and all required properties are validated. Naive timed values are interpreted in America/Toronto, aware values are converted, and all-day dates retain their exclusive end dates. A generated VTIMEZONE includes the event date range. ICS serialization handles UTF-8 folding and text escaping. CANCELLED title prefixes set STATUS:CANCELLED; sold-out events retain their titles.

Changed entries retain UIDs and increment SEQUENCE. Unchanged entries keep timestamps. The workflow caches the last successful feed to retain revision metadata; cache eviction can reset revision counters, but UIDs stay stable. Only currently listed events are included. Events removed by McGill disappear from the next feed; calendar clients differ in removal handling. There is no inferred cancellation or permanent historical archive.

## Reliability and maintenance

HTTP requests have connection/read timeouts, retries for 429 and transient server errors, backoff, and a 0.3-second pacing delay. Unexpected HTML, missing exports, invalid ranges, pagination loops, and conflicting duplicates fail the run. No partial feed is published: the file is replaced only after a complete successful crawl, and GitHub Pages deploys only on success, leaving the previous deployment available. An empty source also fails for manual review.

Review Actions failures and the public status file. If McGill changes its markup, update the selectors and fixtures, then run tests and a live refresh. Tests use captured public HTML and an official export, with additional cases for identity, metadata, deduplication, DST, all-day dates, cancellation, malformed input, pagination, and UTF-8 serialization. Live network access is required only for refreshes.

This is an independent tool, unaffiliated with McGill. Event content belongs to its publishers; fixtures are included for parser validation. Confirm details at the original event URL before attending.
