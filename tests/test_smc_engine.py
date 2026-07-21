"""
Tests focused on the parts of the engine where a bug would silently corrupt
trading decisions rather than crash loudly: the lookahead-bias fix in
structure confirmation, the realistic backtest, ATR-floored stops, the
liquidity filter, weighted/de-duplicated scoring, and conflict warnings.
A regression here is worse than a crash — it produces a wrong but
confident-looking number.
"""
import numpy as np
import pandas as pd

import config
import smc_engine
from conftest import make_ohlc


def test_confirmed_structure_events_uses_broken_index_not_swing_position():
    """
    The library flags BOS/CHoCH at the swing-point position but the break is
    only confirmed later at BrokenIndex. confirm_pos must reflect the LATER
    position — this is the core lookahead-bias fix. If this regresses, the
    backtest silently becomes optimistic again.
    """
    ohlc = make_ohlc(750, seed=0)
    swings = smc_engine.smc.swing_highs_lows(ohlc, swing_length=config.SWING_LENGTH)
    structure = smc_engine.smc.bos_choch(ohlc, swings, close_break=True)

    events = smc_engine.confirmed_structure_events(structure)
    assert not events.empty, "expected at least one confirmed structure event in 750 bars of synthetic data"

    for idx, row in events.iterrows():
        assert row["confirm_pos"] >= idx, (
            f"confirm_pos ({row['confirm_pos']}) is before the swing-point index ({idx}) — "
            "this would mean using information before it existed"
        )


def test_backtest_never_uses_future_bars_beyond_the_window():
    ohlc = make_ohlc(750, seed=3)
    win_rate, resolved, checked, avg_win_bars = smc_engine.backtest_setup(ohlc, "LONG", risk_dist=2.0, reward_dist=6.0)
    assert resolved <= checked
    assert win_rate is None or 0 <= win_rate <= 100
    assert avg_win_bars is None or 0 < avg_win_bars <= config.BACKTEST_FORWARD_BARS


def test_win_rate_hidden_below_min_samples():
    ohlc = make_ohlc(200, seed=1)
    win_rate, resolved, checked, avg_win_bars = smc_engine.backtest_setup(ohlc, "LONG", risk_dist=1.0, reward_dist=2.0)
    if resolved < config.BACKTEST_MIN_SAMPLES:
        assert win_rate is None


def test_stop_is_never_tighter_than_atr_floor():
    # Seed 16 + a matching HTF push reliably clears the (deliberately strict)
    # MIN_SCORE_TO_ALERT threshold — see test_htf_alignment_pushes_marginal_setup_over_threshold.
    ohlc = make_ohlc(750, seed=16)
    sig = smc_engine.score_signal("TEST.NS", ohlc, htf_direction="bear")
    assert sig.direction == "SHORT"
    atr = smc_engine.compute_atr(ohlc).iloc[-1]
    stop_dist = abs(sig.entry - sig.stop_loss)
    assert stop_dist >= atr * config.MIN_STOP_ATR_MULT * 0.99  # small float tolerance


def test_illiquid_symbol_gets_warning():
    ohlc = make_ohlc(750, seed=16, volume_range=(100, 5000))
    sig = smc_engine.score_signal("ILLIQUID.NS", ohlc)
    assert any("liquidity floor" in w for w in sig.warnings)


def test_liquid_symbol_gets_no_liquidity_warning():
    ohlc = make_ohlc(750, seed=16, volume_range=(500_000, 1_000_000))
    sig = smc_engine.score_signal("LIQUID.NS", ohlc)
    assert not any("liquidity floor" in w for w in sig.warnings)


def test_no_trade_when_scores_tied_or_below_threshold():
    dates = pd.date_range("2021-01-01", periods=300, freq="D")
    flat = pd.DataFrame({
        "open": [100.0] * 300, "high": [100.5] * 300, "low": [99.5] * 300,
        "close": [100.0] * 300, "volume": [500_000] * 300,
    }, index=dates)
    sig = smc_engine.score_signal("FLAT.NS", flat)
    assert sig.direction == "NO TRADE"


def test_score_signal_handles_many_seeds_without_crashing():
    """Broad robustness sweep — no synthetic scenario should raise, regardless of direction outcome."""
    for seed in range(40):
        ohlc = make_ohlc(750, seed=seed)
        sig = smc_engine.score_signal(f"S{seed}.NS", ohlc)
        assert sig.direction in ("LONG", "SHORT", "NO TRADE")
        assert sig.score <= config.MAX_POSSIBLE_SCORE


def test_htf_alignment_pushes_marginal_setup_over_threshold():
    """
    Documents and locks in the intended behavior of the stricter, weighted
    threshold: a marginal LTF lean alone may not qualify, but a genuine HTF
    weight-2 confluence in the same direction can legitimately push it over
    MIN_SCORE_TO_ALERT. This is the mechanism, not a workaround.
    """
    ohlc = make_ohlc(750, seed=16)
    baseline = smc_engine.score_signal("T.NS", ohlc)
    boosted = smc_engine.score_signal("T.NS", ohlc, htf_direction="bear")
    assert boosted.score > baseline.score
    assert boosted.direction == "SHORT"
    assert boosted.score >= config.MIN_SCORE_TO_ALERT


def test_ob_and_fvg_each_count_once_regardless_of_how_many_rows_match():
    """
    Regression guard for the double-counting bug: even if several
    overlapping order blocks (or FVGs) sit near price, that category may
    only contribute its configured weight ONCE, not once per matching row.
    """
    ohlc = make_ohlc(750, seed=16)
    sig = smc_engine.score_signal("T.NS", ohlc, htf_direction="bear")
    ob_mentions = sum(1 for r in sig.reasons if "order block" in r)
    fvg_mentions = sum(1 for r in sig.reasons if "fair value gap" in r and "overlap" not in r)
    assert ob_mentions <= 1
    assert fvg_mentions <= 1


def test_score_never_exceeds_max_possible():
    for seed in range(30):
        ohlc = make_ohlc(750, seed=seed)
        for htf in (None, "bull", "bear"):
            sig = smc_engine.score_signal(f"S{seed}.NS", ohlc, htf_direction=htf)
            assert sig.score <= config.MAX_POSSIBLE_SCORE


# --- Conflict-warning helpers, tested directly (isolated from whether
# synthetic data happens to organically clear the stricter threshold) ---

def test_htf_conflict_warning_fires_only_when_opposed():
    assert smc_engine._htf_conflict_warning("LONG", "bear") is not None
    assert smc_engine._htf_conflict_warning("SHORT", "bull") is not None
    assert smc_engine._htf_conflict_warning("LONG", "bull") is None
    assert smc_engine._htf_conflict_warning("SHORT", "bear") is None
    assert smc_engine._htf_conflict_warning("LONG", "neutral") is None
    assert smc_engine._htf_conflict_warning("LONG", None) is None


def test_index_conflict_warning_fires_only_when_opposed():
    assert smc_engine._index_conflict_warning("LONG", "bear") is not None
    assert smc_engine._index_conflict_warning("SHORT", "bull") is not None
    assert smc_engine._index_conflict_warning("LONG", "bull") is None
    assert smc_engine._index_conflict_warning("SHORT", "bear") is None
    assert smc_engine._index_conflict_warning("LONG", None) is None


def test_counter_trend_warning_present_in_real_signal():
    ohlc = make_ohlc(750, seed=16)
    conflicted = smc_engine.score_signal("T.NS", ohlc, htf_direction="bear", index_direction="bull")
    assert conflicted.direction == "SHORT"
    assert any("Nifty" in w for w in conflicted.warnings)


def test_aligned_index_bias_does_not_warn():
    ohlc = make_ohlc(750, seed=16)
    aligned = smc_engine.score_signal("T.NS", ohlc, htf_direction="bear", index_direction="bear")
    assert aligned.direction == "SHORT"
    assert not any("Nifty" in w for w in aligned.warnings)


# --- Gap risk ---

def test_gap_risk_zero_for_zero_stop_distance():
    ohlc = make_ohlc(750, seed=16)
    assert smc_engine._gap_risk(ohlc, 0) == 0.0


def test_gap_risk_detects_frequent_large_gaps():
    dates = pd.date_range("2021-01-01", periods=300, freq="D")
    np.random.seed(0)
    close = 100 + np.cumsum(np.random.randn(300) * 0.1)
    # Force every open to gap 5 points from the prior close — a stop 1 point
    # away should show ~100% gap-breach rate.
    open_ = np.roll(close, 1) + 5
    open_[0] = close[0]
    df = pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) + 0.5,
        "low": np.minimum(open_, close) - 0.5, "close": close,
        "volume": [500_000] * 300,
    }, index=dates)
    rate = smc_engine._gap_risk(df, stop_dist=1.0)
    assert rate > 0.9


# --- HTF / index bias ---

def test_htf_bias_returns_valid_label(weekly_ohlc):
    result = smc_engine.htf_bias(weekly_ohlc)
    assert result in ("bull", "bear", "neutral")


def test_htf_bias_neutral_on_insufficient_history():
    tiny = make_ohlc(5, seed=0, freq="W")
    assert smc_engine.htf_bias(tiny) == "neutral"


def test_index_bias_returns_valid_label(daily_ohlc):
    result = smc_engine.index_bias(daily_ohlc)
    assert result in ("bull", "bear", "neutral")


# --- Beyond-SMC additions: ADX, RSI, volume confirmation, time horizon ---

def test_rsi_in_valid_range():
    for seed in range(10):
        ohlc = make_ohlc(750, seed=seed)
        rsi = smc_engine.compute_rsi(ohlc)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_high_for_strong_uptrend():
    dates = pd.date_range("2021-01-01", periods=60, freq="D")
    close = pd.Series(range(100, 160), index=dates, dtype=float)  # strictly rising, no down days
    ohlc = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                          "close": close, "volume": [500_000] * 60}, index=dates)
    rsi = smc_engine.compute_rsi(ohlc)
    assert rsi.iloc[-1] > 90  # a pure uptrend with zero down-days should be near 100


def test_adx_in_valid_range():
    for seed in range(10):
        ohlc = make_ohlc(750, seed=seed)
        adx = smc_engine.compute_adx(ohlc)
        valid = adx.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


def test_adx_higher_for_trending_than_choppy_data():
    dates = pd.date_range("2021-01-01", periods=200, freq="D")
    trending_close = pd.Series(100 + np.arange(200) * 0.5, index=dates)
    trending = pd.DataFrame({
        "open": trending_close, "high": trending_close + 0.3, "low": trending_close - 0.3,
        "close": trending_close, "volume": [500_000] * 200,
    }, index=dates)

    np.random.seed(0)
    choppy_close = pd.Series(100 + np.sin(np.arange(200) / 3) * 2, index=dates)
    choppy = pd.DataFrame({
        "open": choppy_close, "high": choppy_close + 0.3, "low": choppy_close - 0.3,
        "close": choppy_close, "volume": [500_000] * 200,
    }, index=dates)

    trend_adx = smc_engine.compute_adx(trending).iloc[-1]
    choppy_adx = smc_engine.compute_adx(choppy).iloc[-1]
    assert trend_adx > choppy_adx


def test_volume_confirmed_true_on_spike():
    dates = pd.date_range("2021-01-01", periods=50, freq="D")
    vol = [100_000] * 50
    vol[40] = 500_000  # a clear spike at position 40
    df = pd.DataFrame({"open": [10] * 50, "high": [10] * 50, "low": [10] * 50,
                        "close": [10] * 50, "volume": vol}, index=dates)
    assert smc_engine._volume_confirmed(df, 40) is True


def test_volume_confirmed_false_without_spike():
    dates = pd.date_range("2021-01-01", periods=50, freq="D")
    df = pd.DataFrame({"open": [10] * 50, "high": [10] * 50, "low": [10] * 50,
                        "close": [10] * 50, "volume": [100_000] * 50}, index=dates)
    assert smc_engine._volume_confirmed(df, 40) is False


def test_time_horizon_none_without_data():
    assert smc_engine._time_horizon(None) == (None, None)


def test_time_horizon_labels_scale_with_bars():
    short_days, short_label = smc_engine._time_horizon(2)
    swing_days, swing_label = smc_engine._time_horizon(7)
    positional_days, positional_label = smc_engine._time_horizon(15)
    extended_days, extended_label = smc_engine._time_horizon(25)
    assert "Short-term" in short_label
    assert "Swing" in swing_label
    assert "Positional" in positional_label
    assert "Extended" in extended_label


def test_adx_and_rsi_populated_on_signal():
    ohlc = make_ohlc(750, seed=16)
    sig = smc_engine.score_signal("T.NS", ohlc)
    assert sig.adx is not None
    assert sig.rsi is not None
    assert 0 <= sig.rsi <= 100
    assert sig.adx >= 0


def test_low_adx_produces_choppy_regime_warning():
    ohlc = make_ohlc(750, seed=16)
    sig = smc_engine.score_signal("T.NS", ohlc, htf_direction="bear")
    assert sig.direction == "SHORT"
    if sig.adx is not None and sig.adx < config.ADX_TREND_THRESHOLD:
        assert any("choppy" in w or "range-bound" in w for w in sig.warnings)
