from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from icalendar import Calendar
from calendar_feed import (
    FREE_PREFIX, SOURCE, TZ, apply_tags, assemble, crawl, event_tags, export_link,
    listing, normalize,
)

FIX = Path(__file__).parent / "fixtures"
STAMP = datetime(2026, 10, 9, tzinfo=timezone.utc)
URL = "https://www.mcgill.ca/channels/channels/event/musical-evenings-mgss-374725"

def event():
    return normalize((FIX / "event.ics").read_bytes(), URL, STAMP)[0]

def test_actual_html_and_export():
    links, nxt = listing((FIX / "listing.html").read_bytes(), SOURCE)
    assert len(links) == 15 and nxt == SOURCE + "?page=1"
    assert export_link((FIX / "event.html").read_bytes(), URL).endswith('/node/220485/ical')
    e = event()
    assert e.decoded('DTSTART') == datetime(2026,10,15,19,30,tzinfo=TZ)
    assert e.decoded('DTEND') == datetime(2026,10,15,21,tzinfo=TZ)
    assert 'Clara Lichtenstein Hall' in str(e['LOCATION'])
    assert 'graduate students' in str(e['DESCRIPTION'])
    assert str(e['URL']) == URL

def test_exact_free_tag_decorates_summary_and_categories_without_changing_uid():
    tags = event_tags((FIX / 'event.html').read_bytes())
    assert tags == ['Free events', 'Concerts']
    plain = event()
    free = normalize((FIX / 'event.ics').read_bytes(), URL, STAMP, tags)[0]
    assert str(free['SUMMARY']) == FREE_PREFIX + str(plain['SUMMARY'])
    assert [str(category) for category in free['CATEGORIES'].cats] == ['Free events']
    assert free['UID'] == plain['UID']

def test_untagged_and_similarly_named_tags_are_not_marked_free():
    for tags in ([], ['Free Events'], ['Free events online'], ['Concerts']):
        candidate = normalize((FIX / 'event.ics').read_bytes(), URL, STAMP, tags)[0]
        assert str(candidate['SUMMARY']) == 'Musical Evenings with MGSS'
        assert 'CATEGORIES' not in candidate

def test_free_tag_application_is_idempotent_and_deduplicates():
    free = normalize((FIX / 'event.ics').read_bytes(), URL, STAMP, ['Free events'])[0]
    original_uid = str(free['UID'])
    apply_tags(free, ['Free events'])
    assert str(free['SUMMARY']).count(FREE_PREFIX) == 1
    assert [str(category) for category in free['CATEGORIES'].cats] == ['Free events']
    assert str(free['UID']) == original_uid
    calendar = assemble([free, free], None, STAMP)
    assert len(calendar.walk('VEVENT')) == 1

def test_free_tag_preserves_existing_categories_without_duplicates():
    candidate = event()
    candidate.add('CATEGORIES', ['Concerts'])
    apply_tags(candidate, ['Free events'])
    apply_tags(candidate, ['Free events'])
    assert [str(category) for category in candidate['CATEGORIES'].cats] == [
        'Concerts', 'Free events',
    ]

def test_stable_uid_slug_time_and_source_uid_changes():
    a = event()
    b = normalize((FIX/'event.ics').read_bytes().replace(b'20261015T233000Z',b'20261016T233000Z').replace(b'20261016T010000Z',b'20261017T010000Z'), URL.replace('musical-evenings-mgss', 'new-title'), STAMP)[0]
    assert a['UID'] == b['UID']

def test_dedupe_roundtrip_and_unchanged_metadata():
    cal = assemble([event(), event()], None, STAMP)
    assert len(cal.walk('VEVENT')) == 1
    assert cal.walk('VTIMEZONE')
    parsed = Calendar.from_ical(cal.to_ical())
    later = assemble([event()], parsed, STAMP + timedelta(days=1))
    assert later.to_ical() == cal.to_ical()
    changed = event()
    changed['SUMMARY'] = 'Changed title'
    updated = assemble([changed], parsed, STAMP + timedelta(days=1)).walk('VEVENT')[0]
    assert int(updated['SEQUENCE']) == 1

def test_fail_closed():
    with pytest.raises(ValueError): listing('<html>maintenance</html>', SOURCE)
    with pytest.raises(ValueError): export_link('<html></html>', URL)
    with pytest.raises(ValueError): normalize(b'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n',URL,STAMP)
    with pytest.raises(ValueError): assemble([],None,STAMP)
    a,b=event(),event(); b['SUMMARY']='conflicting'
    with pytest.raises(ValueError): assemble([a,b],None,STAMP)

def test_pagination_loop_and_limit():
    class Fetch:
        def get(self,url): return (FIX/'listing.html').read_bytes()
    with pytest.raises(ValueError,match='Pagination'): crawl(Fetch())
    with pytest.raises(ValueError,match='Pagination'): crawl(Fetch(),1)

def test_all_day_and_cancelled():
    raw=b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:CANCELLED | Example\r\nDTSTART;VALUE=DATE:20261101\r\nDTEND;VALUE=DATE:20261103\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'
    e=normalize(raw,URL,STAMP)[0]
    assert str(e['STATUS'])=='CANCELLED'
    assert not isinstance(e.decoded('DTSTART'),datetime)

    free = normalize(raw, URL, STAMP, ['Free events'])[0]
    assert str(free['STATUS']) == 'CANCELLED'
    assert str(free['SUMMARY']) == FREE_PREFIX + 'CANCELLED | Example'

def test_dst_and_utf8_folding():
    e=event()
    e['SUMMARY']='Été, concert; '+ 'é'*100
    cal=assemble([e],None,STAMP)
    assert Calendar.from_ical(cal.to_ical()).walk('VEVENT')[0]['SUMMARY']==e['SUMMARY']
    assert datetime(2026,1,1,tzinfo=TZ).utcoffset()==timedelta(hours=-5)
    assert e.decoded('DTSTART').utcoffset()==timedelta(hours=-4)

def test_failed_refresh_preserves_existing_file(tmp_path, monkeypatch):
    import calendar_feed
    target = tmp_path / 'calendar.ics'
    target.write_bytes(b'previous successful calendar')
    def fail(*args, **kwargs):
        raise ValueError('broken source')
    monkeypatch.setattr(calendar_feed, 'crawl', fail)
    monkeypatch.setattr('sys.argv', ['calendar_feed.py', '--output', str(target)])
    with pytest.raises(ValueError, match='broken source'):
        calendar_feed.main()
    assert target.read_bytes() == b'previous successful calendar'
