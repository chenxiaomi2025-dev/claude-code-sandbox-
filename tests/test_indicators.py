import math

from intel.analysis.indicators import (
    cross_signal,
    drawdown,
    momentum,
    rsi,
    sma,
    summarize,
)


def test_sma_window_3():
    out = sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0
    assert out[3] == 3.0
    assert out[4] == 4.0


def test_sma_handles_window_larger_than_data():
    out = sma([1.0, 2.0], 5)
    assert out == [None, None]


def test_momentum_basic():
    assert math.isclose(momentum([100.0, 110.0], 1), 10.0, abs_tol=1e-9)
    assert math.isclose(momentum([100.0, 105.0, 120.0], 2), 20.0, abs_tol=1e-9)


def test_momentum_short_data():
    assert momentum([100.0], 5) is None


def test_drawdown_from_peak():
    assert drawdown([100, 110, 90]) == (90 / 110 - 1) * 100  # -18.1818...
    assert drawdown([]) is None


def test_rsi_returns_100_when_all_gains():
    val = rsi([float(i) for i in range(1, 30)], period=14)
    assert val == 100.0


def test_rsi_returns_sane_for_oscillating():
    vals = [100 + (i % 5) for i in range(40)]
    val = rsi(vals, period=14)
    assert val is not None
    assert 0 < val < 100


def test_rsi_short_data():
    assert rsi([1.0, 2.0, 3.0], period=14) is None


def test_cross_signal_golden_and_death():
    short = [9.0, 10.0, 11.0]
    long = [10.0, 10.0, 10.0]
    assert cross_signal(short, long) == "golden"

    short = [11.0, 10.0, 9.0]
    long = [10.0, 10.0, 10.0]
    assert cross_signal(short, long) == "death"

    short = [11.0, 12.0]
    long = [10.0, 10.0]
    assert cross_signal(short, long) == "none"


def test_summarize_full_bundle():
    closes = [100.0 + i * 0.5 for i in range(100)]
    out = summarize(closes)
    assert out["n"] == 100
    assert out["last"] == 100.0 + 99 * 0.5
    assert out["ma5"] is not None and out["ma20"] is not None and out["ma60"] is not None
    assert out["mom_20d"] is not None
    assert math.isclose(out["mom_20d"], (out["last"] / closes[-21] - 1) * 100, rel_tol=1e-6)
    assert out["rsi14"] == 100.0  # monotonic up


def test_summarize_empty():
    out = summarize([])
    assert out["n"] == 0
    assert out["last"] is None
    assert out["ma_cross"] == "none"
