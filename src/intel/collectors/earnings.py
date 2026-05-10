"""Earnings calendar collector.

Pulls the next expected earnings date for a ticker via yfinance.
yfinance.Ticker.calendar may return a dict (newer versions) or a DataFrame
(older). We tolerate both shapes and yield a list of datetime objects.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

log = logging.getLogger("intel.earnings")


def _coerce_dates(raw) -> list[datetime]:
    """Accept dict / DataFrame / list / None — return list of naive datetimes."""
    if raw is None:
        return []
    out: list[datetime] = []

    # newer yfinance: dict {"Earnings Date": [date, date], ...}
    if isinstance(raw, dict):
        candidates = raw.get("Earnings Date") or raw.get("earningsDate") or []
    else:
        # pandas DataFrame style — try columns first
        try:
            if "Earnings Date" in getattr(raw, "columns", []):
                candidates = list(raw["Earnings Date"].dropna())
            elif "Earnings Date" in getattr(raw, "index", []):
                candidates = list(raw.loc["Earnings Date"])
            else:
                candidates = []
        except Exception:
            candidates = []

    if not isinstance(candidates, (list, tuple)):
        candidates = [candidates]

    for d in candidates:
        if d is None:
            continue
        if isinstance(d, datetime):
            out.append(d.replace(tzinfo=None))
        elif isinstance(d, date):
            out.append(datetime(d.year, d.month, d.day))
        else:
            try:
                out.append(datetime.fromisoformat(str(d).replace("Z", "")).replace(tzinfo=None))
            except (TypeError, ValueError):
                continue
    return out


def fetch_earnings(ticker: str) -> list[datetime]:
    """Return upcoming earnings dates for a single ticker via yfinance.

    Returns an empty list if yfinance isn't available, the call fails, or no
    dates are listed. Never raises.
    """
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        cal = yf.Ticker(ticker).calendar
    except Exception as e:
        log.warning("yfinance calendar(%s) failed: %s", ticker, e)
        return []
    return _coerce_dates(cal)
