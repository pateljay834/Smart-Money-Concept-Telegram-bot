"""
Shared logic for both entry points (bot.py and run.py). Keeping this in one
place means the interactive bot and the GitHub Actions workflow always
produce identical analysis and formatting — no drift between the two.
"""
import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import config
from data_fetch import get_ohlc
from smc_engine import score_signal, htf_bias, index_bias, Signal
from chart_utils import plot_chart

log = logging.getLogger("smc_core")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class AnalysisResult:
    symbol: str
    signal: Signal = None
    chart_path: str = None
    error: str = None


def parse_tickers(raw: str) -> list:
    """Space-separated ticker string -> clean, deduped, capped list."""
    if not raw or not raw.strip():
        return []
    seen = []
    for tok in raw.replace(",", " ").split():
        t = tok.strip().upper()
        if t and t not in seen:
            seen.append(t)
    if len(seen) > config.MAX_TICKERS_PER_RUN:
        log.warning(f"{len(seen)} tickers requested, capping to {config.MAX_TICKERS_PER_RUN}")
        seen = seen[: config.MAX_TICKERS_PER_RUN]
    return seen


def get_market_regime() -> str:
    """
    Fetch the broader index (Nifty 50) structural bias ONCE and share it
    across every symbol in a batch — fetching it per-symbol would multiply
    API calls for no benefit, since it's the same data every time.
    Returns "bull", "bear", "neutral", or None if the fetch/filter is off.
    """
    if not config.USE_INDEX_FILTER:
        return None
    try:
        ohlc_index = get_ohlc(config.INDEX_SYMBOL, config.INTERVAL, config.INDEX_LOOKBACK)
        return index_bias(ohlc_index)
    except Exception:
        log.warning("Index regime fetch failed, continuing without market-regime check")
        return None


def analyze_one(symbol: str, index_direction: str = None) -> AnalysisResult:
    """
    Full pipeline for a single symbol, with every failure caught and
    attached to the result instead of raising — so one bad ticker never
    aborts a batch run of many.
    """
    try:
        ohlc = get_ohlc(symbol, config.INTERVAL, config.LOOKBACK_PERIOD)

        htf_direction = None
        if config.USE_HTF_FILTER:
            try:
                ohlc_htf = get_ohlc(symbol, config.HTF_INTERVAL, config.HTF_LOOKBACK)
                htf_direction = htf_bias(ohlc_htf)
            except Exception:
                log.warning(f"{symbol}: HTF fetch failed, continuing without HTF bias")

        signal = score_signal(symbol, ohlc, htf_direction=htf_direction, index_direction=index_direction)
        chart_path = plot_chart(symbol, ohlc, signal)
        return AnalysisResult(symbol=symbol, signal=signal, chart_path=chart_path)
    except Exception as e:
        log.exception(f"Analysis failed for {symbol}")
        return AnalysisResult(symbol=symbol, error=str(e))


def cleanup(result: AnalysisResult):
    """Delete a result's chart file. Always call this after the file is sent."""
    if result.chart_path and os.path.exists(result.chart_path):
        try:
            os.remove(result.chart_path)
        except OSError:
            pass


def build_analysis_message(signal: Signal) -> str:
    ts = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    trend_bits = []
    if signal.htf_bias:
        trend_bits.append(f"Weekly: {signal.htf_bias}")
    if signal.index_bias:
        trend_bits.append(f"Nifty: {signal.index_bias}")
    trend_str = f"   <b>Regime:</b> {', '.join(trend_bits)}" if trend_bits else ""

    lines = [
        f"<b>SMC Analysis — {signal.symbol}</b>",
        f"<i>{ts}</i>",
        "",
        f"<b>Bias:</b> {signal.direction}   <b>Score:</b> {signal.score}/{config.MAX_POSSIBLE_SCORE}{trend_str}",
        "",
        "<b>Confluences</b>",
    ]
    lines += [f"• {r}" for r in signal.reasons] if signal.reasons else ["• None detected"]

    if signal.warnings:
        lines.append("")
        lines.append("<b>⚠ Warnings</b>")
        lines += [f"• {w}" for w in signal.warnings]

    if signal.entry:
        lines.append("")
        lines.append("<b>Trade Plan</b>")
        lines.append(
            "<pre>"
            f"Entry   {signal.entry}\n"
            f"Stop    {signal.stop_loss}\n"
            f"Target  {signal.target}\n"
            f"R:R     1:{signal.risk_reward}"
            "</pre>"
        )
        if config.ACCOUNT_SIZE:
            risk_per_share = abs(signal.entry - signal.stop_loss)
            risk_amount = config.ACCOUNT_SIZE * config.RISK_PER_TRADE_PCT / 100
            qty = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
            lines.append(f"Suggested size: <b>{qty} shares</b> (risking {config.RISK_PER_TRADE_PCT}% of a {config.ACCOUNT_SIZE:,.0f} account)")
        if signal.win_rate is not None:
            lines.append(
                f"Historical win-rate of this exact setup (target-vs-stop simulated): "
                f"<b>{signal.win_rate}%</b> (n={signal.sample_size} resolved past trades, confidence: {signal.confidence})"
            )
        elif signal.sample_size > 0:
            lines.append(
                f"Only {signal.sample_size} resolved past occurrence(s) found — below the "
                f"{config.BACKTEST_MIN_SAMPLES} needed for a statistically meaningful win-rate. "
                f"Treat this setup as unvalidated."
            )
        else:
            lines.append("No resolved historical occurrences of this exact setup found on this symbol yet.")

    lines.append("")
    lines.append(f"<i>{config.REGULATORY_DISCLAIMER}</i>")
    return "\n".join(lines)


def _rank_key(r):
    s = r.signal
    confidence_rank = {"High": 3, "Medium": 2, "Low": 1, None: 0}[s.confidence]
    win_rate = s.win_rate if s.win_rate is not None else -1
    return (confidence_rank, win_rate, s.score)


def build_run_summary(mode: str, results: list, elapsed_sec: float) -> str:
    ok = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    qualifying = [r for r in ok if r.signal.direction != "NO TRADE" and r.signal.score >= config.MIN_SCORE_TO_ALERT]
    qualifying.sort(key=_rank_key, reverse=True)

    ts = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    lines = [
        "<b>Run Summary</b>",
        f"<i>{ts}</i>",
        "",
        f"Mode: {mode}   Scanned: {len(results)}   Failed: {len(failed)}   Elapsed: {elapsed_sec:.1f}s",
    ]

    if qualifying:
        lines.append("")
        lines.append(f"<b>Qualifying setups</b> (ranked by backtest confidence, then win-rate) — score out of {config.MAX_POSSIBLE_SCORE}")
        for r in qualifying:
            s = r.signal
            wr = f"{s.win_rate}%" if s.win_rate is not None else "insufficient data"
            flag = " ⚠" if s.warnings else ""
            lines.append(f"• {s.symbol} — {s.direction}, score {s.score}/{config.MAX_POSSIBLE_SCORE}, R:R 1:{s.risk_reward}, win-rate {wr} ({s.confidence or 'n/a'}){flag}")

        # Portfolio-level view — a list of "independent" opportunities can
        # really be one concentrated directional bet if they're correlated.
        # No sector data is fetched here (adds fragile, rate-limited API
        # calls) — this is a cheap, robust proxy: pure directional skew.
        longs = [r for r in qualifying if r.signal.direction == "LONG"]
        shorts = [r for r in qualifying if r.signal.direction == "SHORT"]
        lines.append("")
        lines.append("<b>Portfolio view</b>")
        lines.append(f"{len(longs)} LONG / {len(shorts)} SHORT among qualifying setups.")
        if len(qualifying) >= 3 and (not longs or not shorts):
            lines.append("⚠ All qualifying setups point the same direction — before sizing all of them, check "
                          "whether they're actually independent bets or one concentrated sector/market-direction bet.")
        if config.ACCOUNT_SIZE:
            total_risk_pct = len(qualifying) * config.RISK_PER_TRADE_PCT
            lines.append(f"Taking every qualifying setup at the configured sizing would risk "
                         f"~{total_risk_pct:.1f}% of your account simultaneously ({len(qualifying)} × {config.RISK_PER_TRADE_PCT}%).")
    else:
        lines.append("")
        lines.append("No qualifying setups this run.")

    if failed:
        lines.append("")
        lines.append("<b>Failed</b>")
        for r in failed:
            lines.append(f"• {r.symbol}: {r.error}")

    lines.append("")
    lines.append(f"<i>{config.REGULATORY_DISCLAIMER}</i>")
    return "\n".join(lines)


def run_batch(tickers: list, mode: str, progress_cb=None) -> list:
    """
    mode: "analyze" (send full report for every ticker) or
          "screen" (only send full report for tickers that qualify).
    progress_cb(done, total) is called after each ticker, if provided.
    Returns the list of AnalysisResult so the caller can decide what to send.
    """
    index_direction = get_market_regime()  # fetched once, shared across all tickers
    results = []
    for i, symbol in enumerate(tickers, 1):
        results.append(analyze_one(symbol, index_direction=index_direction))
        if progress_cb:
            progress_cb(i, len(tickers))
    return results
