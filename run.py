"""
Entry point for the GitHub Actions workflow (and usable locally the same way).

Reads two env vars:
  MODE     - "analyze" | "screen" | "both"   (default: "screen")
  TICKERS  - space-separated tickers, e.g. "RELIANCE.NS TCS.NS INFY.NS"
             if empty, falls back to config.WATCHLIST

  analyze  -> full report (chart + confluences + trade plan) for every ticker given
  screen   -> only sends full reports for tickers that meet MIN_SCORE_TO_ALERT,
              plus a summary of what qualified
  both     -> full report for every ticker AND a screening summary at the end
"""
import logging
import os
import time

import config
import core
from telegram_send import send_message, send_photo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run")


def main():
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (check repo Secrets or .env).")

    mode = os.environ.get("MODE", "screen").strip().lower()
    if mode not in ("analyze", "screen", "both"):
        raise SystemExit(f"Invalid MODE '{mode}' — must be analyze, screen, or both.")

    tickers = core.parse_tickers(os.environ.get("TICKERS", ""))
    if not tickers:
        tickers = config.WATCHLIST
        log.info(f"No tickers provided — using default watchlist ({len(tickers)} symbols).")

    log.info(f"Mode={mode}  Tickers={tickers}")
    start = time.time()

    def progress(done, total):
        log.info(f"Analyzed {done}/{total}")

    results = core.run_batch(tickers, mode, progress_cb=progress)
    elapsed = time.time() - start

    sent_any = False
    for r in results:
        if r.error is not None:
            continue  # reported in the summary instead of spamming per-symbol errors
        qualifies = r.signal.direction != "NO TRADE" and r.signal.score >= config.MIN_SCORE_TO_ALERT
        should_send_full_report = (mode in ("analyze", "both")) or (mode == "screen" and qualifies)
        if should_send_full_report:
            try:
                send_photo(r.chart_path, caption=core.build_analysis_message(r.signal))
                sent_any = True
            except Exception:
                log.exception(f"Failed to send Telegram message for {r.symbol}")
            finally:
                core.cleanup(r)
        else:
            core.cleanup(r)

    # Summary message: always for screen/both, and for analyze only if something failed
    if mode in ("screen", "both") or any(r.error for r in results):
        send_message(core.build_run_summary(mode, results, elapsed))
    elif not sent_any:
        send_message(f"Run finished ({mode}) — no messages generated. Check the Actions log.")

    log.info(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
