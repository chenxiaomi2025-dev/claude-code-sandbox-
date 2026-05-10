from datetime import date, datetime, timedelta

from intel.analysis.alerts import detect_alerts
from intel.collectors.earnings import _coerce_dates
from intel.storage.repo import (
    upcoming_earnings,
    upsert_company,
    upsert_earnings_event,
)


def test_coerce_dates_dict_form():
    out = _coerce_dates({"Earnings Date": [date(2026, 5, 22), date(2026, 8, 27)]})
    assert len(out) == 2
    assert out[0] == datetime(2026, 5, 22)


def test_coerce_dates_legacy_camel_case_key():
    out = _coerce_dates({"earningsDate": [datetime(2026, 5, 22, 13, 30)]})
    assert out == [datetime(2026, 5, 22, 13, 30)]


def test_coerce_dates_iso_string():
    out = _coerce_dates({"Earnings Date": ["2026-05-22"]})
    assert out == [datetime(2026, 5, 22)]


def test_coerce_dates_handles_none_and_empty():
    assert _coerce_dates(None) == []
    assert _coerce_dates({}) == []
    assert _coerce_dates({"Earnings Date": []}) == []


def test_coerce_dates_skips_garbage():
    out = _coerce_dates({"Earnings Date": [None, "not-a-date", date(2026, 5, 22)]})
    assert out == [datetime(2026, 5, 22)]


def test_upsert_earnings_event_idempotent(session):
    company = upsert_company(session, ticker="NVDA", name="NVIDIA", exchange="NASDAQ", private=False, tags=None)
    when = datetime(2026, 5, 22)
    a = upsert_earnings_event(session, company_id=company.id, expected_date=when)
    b = upsert_earnings_event(session, company_id=company.id, expected_date=when)
    assert a.id == b.id


def test_upcoming_earnings_filters_window(session):
    c = upsert_company(session, ticker="AMD", name="AMD", exchange="NASDAQ", private=False, tags=None)
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=3))
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=30))
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() - timedelta(days=2))
    rows = upcoming_earnings(session, within_days=14)
    assert len(rows) == 1
    assert (rows[0][0].expected_date - datetime.utcnow()).days <= 4


def test_alerts_emit_upcoming_earnings(session):
    c = upsert_company(session, ticker="NVDA", name="NVIDIA", exchange="NASDAQ", private=False, tags=None)
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=1))
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=5))
    alerts = detect_alerts(session, hours=24, earnings_lookahead_days=7)
    upcoming = [a for a in alerts if a.kind == "earnings_upcoming"]
    assert len(upcoming) == 2
    # T-1d → high, T-5d → medium
    by_days = sorted(upcoming, key=lambda a: a.when)
    assert by_days[0].severity == "high"
    assert by_days[1].severity == "medium"


def test_alerts_sort_puts_soonest_earnings_first(session):
    c = upsert_company(session, ticker="MSFT", name="Microsoft", exchange="NASDAQ", private=False, tags=None)
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(days=2))
    upsert_earnings_event(session, company_id=c.id, expected_date=datetime.utcnow() + timedelta(hours=12))
    alerts = detect_alerts(session, hours=24, earnings_lookahead_days=14)
    upcoming = [a for a in alerts if a.kind == "earnings_upcoming"]
    # Soonest first within high severity bucket
    assert upcoming[0].when < upcoming[1].when
