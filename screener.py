"""
Run the SMC screener across the watchlist and push qualifying setups to Telegram.

Usage:
    python screener.py

This is deliberately a single pass, not a long-running process, so it works
both as a local script and as a scheduled GitHub Actions job.
"""
import traceback

import config
from data_fetch import get_ohlc
from smc_engine import score_signal
from chart_utils import plot_chart
from telegram_send import send_message, send_photo


def format_caption(signal) -> str:
    lines = [
        f"<b>{signal.symbol}</b>  —  {signal.direction}  (score {signal.score}/4)",
        "",
        "Confluences:",
    ]
    lines += [f"• {r}" for r in signal.reasons]
    lines.append("")
    if signal.entry:
        lines.append(f"Entry: {signal.entry}   Stop: {signal.stop_loss}   Target: {signal.target}")
        lines.append(f"Risk:Reward ≈ 1:{signal.risk_reward}")
        if signal.win_rate is not None:
            lines.append(f"Historical win-rate of this setup: {signal.win_rate}% (n={signal.sample_size} past occurrences)")
        else:
            lines.append(f"Not enough historical occurrences yet to estimate a win-rate (n={signal.sample_size})")
    lines.append("")
    lines.append("Not financial advice — a rule-based read of current structure, for your own judgement.")
    return "\n".join(lines)


def run():
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as environment variables / secrets first.")

    alerts_sent = 0
    for symbol in config.WATCHLIST:
        try:
            ohlc = get_ohlc(symbol, config.INTERVAL, config.LOOKBACK_PERIOD)
            signal = score_signal(symbol, ohlc)

            if signal.direction == "NO TRADE" or signal.score < config.MIN_SCORE_TO_ALERT:
                print(f"{symbol}: no qualifying setup (score {signal.score})")
                continue

            chart_path = plot_chart(symbol, ohlc, signal)
            send_photo(chart_path, caption=format_caption(signal))
            alerts_sent += 1
            print(f"{symbol}: alert sent ({signal.direction}, score {signal.score})")

        except Exception as e:
            print(f"{symbol}: FAILED — {e}")
            traceback.print_exc()

    if alerts_sent == 0:
        send_message("Screener ran — no qualifying SMC setups in the watchlist right now.")


if __name__ == "__main__":
    run()
