"""
Interactive bot — run continuously (python bot.py / run.bat). Needs an
always-on process; not suited to GitHub Actions (see README).

Commands:
    /analyze RELIANCE.NS TCS.NS   - full report for one or more tickers
    /screen                       - screen the default watchlist (config.py)
    /screen RELIANCE.NS TCS.NS    - screen a custom list instead

Fix notes (why an earlier version could "work once then stop"):
  - All blocking work (yfinance download, pandas/backtest, chart render)
    now runs in a worker thread via asyncio.to_thread, instead of directly
    inside the async handler. Running that blocking code straight in the
    handler could stall the event loop long enough for Telegram's polling
    connection to time out on the next update.
  - A global error handler is registered so unhandled exceptions are logged
    and reported back to you instead of the bot going quiet.
  - Chart PNGs are written to temp files and deleted right after sending,
    so nothing accumulates on disk.
"""
import asyncio
import logging
import time

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import config
import core

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


async def _send_result(update: Update, result: core.AnalysisResult, force_send: bool):
    if result.error is not None:
        await update.message.reply_text(f"{result.symbol}: {result.error}")
        return
    qualifies = result.signal.direction != "NO TRADE" and result.signal.score >= config.MIN_SCORE_TO_ALERT
    if force_send or qualifies:
        try:
            with open(result.chart_path, "rb") as f:
                await update.message.reply_photo(photo=f, caption=core.build_analysis_message(result.signal), parse_mode="HTML")
        finally:
            core.cleanup(result)
    else:
        core.cleanup(result)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = core.parse_tickers(" ".join(context.args))
    if not tickers:
        await update.message.reply_text("Usage: /analyze RELIANCE.NS TCS.NS ...")
        return
    await update.message.reply_text(f"Analyzing {len(tickers)} ticker(s): {', '.join(tickers)} ...")
    results = await asyncio.to_thread(core.run_batch, tickers, "analyze")
    for r in results:
        await _send_result(update, r, force_send=True)


async def screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = core.parse_tickers(" ".join(context.args)) or config.WATCHLIST
    await update.message.reply_text(f"Screening {len(tickers)} ticker(s) ...")
    start = time.time()
    results = await asyncio.to_thread(core.run_batch, tickers, "screen")
    for r in results:
        await _send_result(update, r, force_send=False)
    await update.message.reply_text(core.build_run_summary("screen", results, time.time() - start), parse_mode="HTML")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "SMC bot ready.\n"
        "/analyze SYMBOL1 SYMBOL2 ... — full report on given tickers\n"
        "/screen [SYMBOL1 SYMBOL2 ...] — screen the list (or your default watchlist if none given)"
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(f"Something went wrong: {context.error}")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (in .env or your environment) first.")
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).read_timeout(60).connect_timeout(30).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("screen", screen))
    app.add_error_handler(on_error)
    log.info("Bot polling started...")
    app.run_polling()


if __name__ == "__main__":
    main()
