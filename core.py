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
from smc_engine import score_signal, Signal
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


def analyze_one(symbol: str) -> AnalysisResult:
    """
    Full pipeline for a single symbol, with every failure caught and
    attached to the result instead of raising — so one bad ticker never
    aborts a batch run of many.
    """
    try:
        ohlc = get_ohlc(symbol, config.INTERVAL, config.LOOKBACK_PERIOD)
        signal = score_signal(symbol, ohlc)
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
    lines = [
        f"<b>SMC Analysis — {signal.symbol}</b>",
        f"<i>{ts}</i>",
        "",
        f"<b>Bias:</b> {signal.direction}   <b>Score:</b> {signal.score}/4",
        "",
        "<b>Confluences</b>",
    ]
    lines += [f"• {r}" for r in signal.reasons] if signal.reasons else ["• None detected"]

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
        if signal.win_rate is not None:
            lines.append(f"Historical win-rate of this setup: <b>{signal.win_rate}%</b> (n={signal.sample_size} past occurrences)")
        else:
            lines.append(f"Not enough historical occurrences to estimate a win-rate yet (n={signal.sample_size})")

    lines.append("")
    lines.append("<i>Rule-based structural read, not financial advice.</i>")
    return "\n".join(lines)


def build_run_summary(mode: str, results: list, elapsed_sec: float) -> str:
    ok = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    qualifying = [r for r in ok if r.signal.direction != "NO TRADE" and r.signal.score >= config.MIN_SCORE_TO_ALERT]
    qualifying.sort(key=lambda r: r.signal.score, reverse=True)

    ts = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    lines = [
        "<b>Run Summary</b>",
        f"<i>{ts}</i>",
        "",
        f"Mode: {mode}   Scanned: {len(results)}   Failed: {len(failed)}   Elapsed: {elapsed_sec:.1f}s",
    ]

    if qualifying:
        lines.append("")
        lines.append("<b>Qualifying setups</b>")
        for r in qualifying:
            s = r.signal
            lines.append(f"• {s.symbol} — {s.direction}, score {s.score}/4, R:R 1:{s.risk_reward}")
    else:
        lines.append("")
        lines.append("No qualifying setups this run.")

    if failed:
        lines.append("")
        lines.append("<b>Failed</b>")
        for r in failed:
            lines.append(f"• {r.symbol}: {r.error}")

    return "\n".join(lines)


def run_batch(tickers: list, mode: str, progress_cb=None) -> list:
    """
    mode: "analyze" (send full report for every ticker) or
          "screen" (only send full report for tickers that qualify).
    progress_cb(done, total) is called after each ticker, if provided.
    Returns the list of AnalysisResult so the caller can decide what to send.
    """
    results = []
    for i, symbol in enumerate(tickers, 1):
        results.append(analyze_one(symbol))
        if progress_cb:
            progress_cb(i, len(tickers))
    return results
