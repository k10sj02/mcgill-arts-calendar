# Validation report

Validated October 9, 2026, Toronto time against the live McGill site.

- Crawled all 11 listing pages and retrieved 153 event detail pages and 153 official ICS exports.
- Generated 153 events with unique stable UIDs, source URLs, and valid start dates.
- Verified the output parses successfully and an unchanged rebuild preserves the exact calendar bytes.
- Confirmed Musical Evenings with MGSS: October 15, 2026, 19:30–21:00 America/Toronto, Clara Lichtenstein Hall, with its full official description.
- Eight offline tests pass, including pagination failure, preservation of the previous feed on failure, UID stability, deduplication, revision metadata, timezone offsets, cancellation, all-day events, and UTF-8 round-trip serialization.

GitHub-hosted deployment has not been run; upload the repository and follow README.md to enable Pages and Actions.
