"""Pure-Python technical indicators.

We keep this dependency-free (no numpy/pandas) so it runs anywhere and is
trivially testable. Inputs are lists of floats ordered oldest → newest.

Indicators implemented:
  - sma(values, window)       — simple moving average
  - momentum(values, window)  — pct change vs. `window` ago
  - drawdown(values)          — drop from rolling max in pct
  - rsi(values, period=14)    — Wilder's RSI
  - cross(short, long)        — golden/death cross signal from two SMA series
"""
from __future__ import annotations


def sma(values: list[float], window: int) -> list[float | None]:
    """Simple moving average. Returns a list of len(values) with None where
    not enough data."""
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float | None] = []
    running = 0.0
    queue: list[float] = []
    for v in values:
        queue.append(v)
        running += v
        if len(queue) > window:
            running -= queue.pop(0)
        out.append(running / window if len(queue) == window else None)
    return out


def momentum(values: list[float], window: int) -> float | None:
    """Percentage change between values[-1] and values[-(window+1)]."""
    if len(values) < window + 1:
        return None
    base = values[-(window + 1)]
    if not base:
        return None
    return (values[-1] / base - 1.0) * 100.0


def drawdown(values: list[float]) -> float | None:
    """Current drawdown (negative pct) from the running max."""
    if not values:
        return None
    peak = max(values)
    if not peak:
        return None
    return (values[-1] / peak - 1.0) * 100.0


def rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder's RSI. Returns None if data shorter than period+1."""
    if len(values) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(values)):
        diff = values[i] - values[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def cross_signal(short: list[float | None], long: list[float | None]) -> str:
    """Detect golden/death cross from the last two valid points of two SMA
    series. Returns 'golden' / 'death' / 'none'."""
    pairs = [(s, lo) for s, lo in zip(short, long, strict=False) if s is not None and lo is not None]
    if len(pairs) < 2:
        return "none"
    s_prev, lo_prev = pairs[-2]
    s_curr, lo_curr = pairs[-1]
    if s_prev <= lo_prev and s_curr > lo_curr:
        return "golden"
    if s_prev >= lo_prev and s_curr < lo_curr:
        return "death"
    return "none"


def summarize(closes: list[float]) -> dict:
    """Compute the full bundle used by TechAgent."""
    if not closes:
        return {
            "n": 0, "last": None, "ma5": None, "ma20": None, "ma60": None,
            "mom_5d": None, "mom_20d": None, "mom_60d": None,
            "drawdown_pct": None, "rsi14": None, "ma_cross": "none",
        }
    ma5_series = sma(closes, 5)
    ma20_series = sma(closes, 20)
    ma60_series = sma(closes, 60)
    return {
        "n": len(closes),
        "last": closes[-1],
        "ma5": ma5_series[-1],
        "ma20": ma20_series[-1],
        "ma60": ma60_series[-1],
        "mom_5d": momentum(closes, 5),
        "mom_20d": momentum(closes, 20),
        "mom_60d": momentum(closes, 60),
        "drawdown_pct": drawdown(closes),
        "rsi14": rsi(closes, 14),
        "ma_cross": cross_signal(ma5_series, ma20_series),
    }
