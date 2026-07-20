import os

import core
from conftest import make_ohlc


def test_parse_tickers_dedupes_and_uppercases():
    assert core.parse_tickers("reliance.ns TCS.ns reliance.ns") == ["RELIANCE.NS", "TCS.NS"]


def test_parse_tickers_handles_commas_and_whitespace():
    assert core.parse_tickers(" a.ns, b.ns   c.ns ") == ["A.NS", "B.NS", "C.NS"]


def test_parse_tickers_empty_input():
    assert core.parse_tickers("") == []
    assert core.parse_tickers("   ") == []


def test_parse_tickers_caps_at_max(monkeypatch):
    monkeypatch.setattr(core.config, "MAX_TICKERS_PER_RUN", 3)
    result = core.parse_tickers("a.ns b.ns c.ns d.ns e.ns")
    assert len(result) == 3


def test_analyze_one_isolates_failures(monkeypatch):
    def failing_get_ohlc(symbol, interval, period):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(core, "get_ohlc", failing_get_ohlc)
    result = core.analyze_one("BAD.NS")
    assert result.error is not None
    assert result.signal is None


def test_run_batch_continues_after_one_failure(monkeypatch):
    good_df = make_ohlc(750, seed=16)

    def mixed_get_ohlc(symbol, interval, period):
        if symbol == "BAD.NS":
            raise RuntimeError("simulated failure")
        return good_df

    monkeypatch.setattr(core, "get_ohlc", mixed_get_ohlc)
    monkeypatch.setattr(core.config, "USE_HTF_FILTER", False)
    monkeypatch.setattr(core.config, "USE_INDEX_FILTER", False)

    results = core.run_batch(["GOOD.NS", "BAD.NS", "GOOD2.NS"], "analyze")
    by_symbol = {r.symbol: r for r in results}
    assert by_symbol["BAD.NS"].error is not None
    assert by_symbol["GOOD.NS"].error is None
    assert by_symbol["GOOD2.NS"].error is None
    for r in results:
        core.cleanup(r)


def test_cleanup_removes_chart_file(monkeypatch):
    monkeypatch.setattr(core.config, "USE_HTF_FILTER", False)
    monkeypatch.setattr(core.config, "USE_INDEX_FILTER", False)
    df = make_ohlc(750, seed=16)
    monkeypatch.setattr(core, "get_ohlc", lambda symbol, interval, period: df)

    result = core.analyze_one("X.NS")
    assert result.chart_path is not None
    assert os.path.exists(result.chart_path)
    core.cleanup(result)
    assert not os.path.exists(result.chart_path)


def test_get_market_regime_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(core.config, "USE_INDEX_FILTER", False)
    assert core.get_market_regime() is None


def test_get_market_regime_returns_none_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(core.config, "USE_INDEX_FILTER", True)

    def failing(symbol, interval, period):
        raise RuntimeError("network down")

    monkeypatch.setattr(core, "get_ohlc", failing)
    assert core.get_market_regime() is None


def test_get_market_regime_fetches_once_and_returns_valid_label(monkeypatch):
    calls = []
    df = make_ohlc(750, seed=16)

    def counting_get_ohlc(symbol, interval, period):
        calls.append(symbol)
        return df

    monkeypatch.setattr(core.config, "USE_INDEX_FILTER", True)
    monkeypatch.setattr(core, "get_ohlc", counting_get_ohlc)
    result = core.get_market_regime()
    assert result in ("bull", "bear", "neutral")
    assert calls == [core.config.INDEX_SYMBOL]


def test_run_batch_fetches_index_regime_once_for_whole_batch(monkeypatch):
    df = make_ohlc(750, seed=16)
    index_fetch_count = [0]

    def counting_get_ohlc(symbol, interval, period):
        if symbol == core.config.INDEX_SYMBOL:
            index_fetch_count[0] += 1
        return df

    monkeypatch.setattr(core.config, "USE_INDEX_FILTER", True)
    monkeypatch.setattr(core.config, "USE_HTF_FILTER", False)
    monkeypatch.setattr(core, "get_ohlc", counting_get_ohlc)

    results = core.run_batch(["A.NS", "B.NS", "C.NS"], "analyze")
    assert index_fetch_count[0] == 1, "index regime should be fetched once per batch, not once per ticker"
    for r in results:
        core.cleanup(r)


def test_build_run_summary_ranks_by_confidence_then_winrate():
    from smc_engine import Signal
    from core import AnalysisResult, build_run_summary

    high_conf = AnalysisResult(symbol="HIGH.NS", signal=Signal(
        symbol="HIGH.NS", direction="LONG", score=5, risk_reward=2.0,
        win_rate=70.0, sample_size=40, confidence="High"))
    low_conf = AnalysisResult(symbol="LOW.NS", signal=Signal(
        symbol="LOW.NS", direction="LONG", score=5, risk_reward=2.0,
        win_rate=None, sample_size=2, confidence="Low"))

    summary = build_run_summary("screen", [low_conf, high_conf], elapsed_sec=1.0)
    assert summary.index("HIGH.NS") < summary.index("LOW.NS")


def test_build_run_summary_flags_directional_concentration():
    from smc_engine import Signal
    from core import AnalysisResult, build_run_summary

    all_long = [
        AnalysisResult(symbol=f"S{i}.NS", signal=Signal(
            symbol=f"S{i}.NS", direction="LONG", score=5, risk_reward=2.0,
            win_rate=None, sample_size=1, confidence="Low"))
        for i in range(3)
    ]
    summary = build_run_summary("screen", all_long, elapsed_sec=1.0)
    assert "concentrated" in summary or "3 LONG / 0 SHORT" in summary


def test_build_run_summary_shows_aggregate_risk_when_account_size_set(monkeypatch):
    from smc_engine import Signal
    from core import AnalysisResult, build_run_summary

    monkeypatch.setattr(core.config, "ACCOUNT_SIZE", 100000.0)
    monkeypatch.setattr(core.config, "RISK_PER_TRADE_PCT", 1.0)

    results = [
        AnalysisResult(symbol=f"S{i}.NS", signal=Signal(
            symbol=f"S{i}.NS", direction="LONG", score=5, risk_reward=2.0,
            win_rate=None, sample_size=1, confidence="Low"))
        for i in range(2)
    ]
    summary = build_run_summary("screen", results, elapsed_sec=1.0)
    assert "2.0%" in summary or "2%" in summary
