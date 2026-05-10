"""Price history collector via yfinance."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import yfinance as yf


def fetch_prices(ticker: str, *, period: str = "1mo", interval: str = "1d") -> Iterable[dict]:
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return
    for ts, row in df.iterrows():
        yield {
            "date": datetime(ts.year, ts.month, ts.day),
            "open": float(row.get("Open")) if row.get("Open") is not None else None,
            "high": float(row.get("High")) if row.get("High") is not None else None,
            "low": float(row.get("Low")) if row.get("Low") is not None else None,
            "close": float(row.get("Close")) if row.get("Close") is not None else None,
            "volume": float(row.get("Volume")) if row.get("Volume") is not None else None,
        }
