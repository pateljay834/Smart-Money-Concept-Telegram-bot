"""
Central configuration.
Telegram credentials are read from environment variables so that:
  - locally, you set them in a .env or run.bat (set TELEGRAM_BOT_TOKEN=...)
  - on GitHub Actions, you set them as repo Secrets (Settings -> Secrets -> Actions)
Never hardcode the token/chat id in this file.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env if present (local runs); no-op on GitHub Actions, which uses real Secrets instead
except ImportError:
    pass  # python-dotenv not installed yet -- fine, env vars can still be set directly

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # your personal or group chat id

# Yahoo Finance tickers. NSE stocks need a ".NS" suffix, BSE needs ".BO".
WATCHLIST = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
]

# Candle timeframe + lookback for analysis
INTERVAL = "1d"        # "1d", "1h", "15m" etc (intraday intervals limit lookback on yfinance)
LOOKBACK_PERIOD = "1y" # how much history to pull

# SMC engine tuning
SWING_LENGTH = 10        # smaller = more sensitive swing detection, larger = major structure only
LIQUIDITY_RANGE_PCT = 0.01

# Backtest settings used to turn "setup type" into an honest historical win-rate
BACKTEST_FORWARD_BARS = 10   # how many bars forward we check for a win after a signal
BACKTEST_MIN_SAMPLES = 8     # don't report a probability unless we found at least this many past occurrences

# Screener filter: only alert when a setup scores at or above this
MIN_SCORE_TO_ALERT = 2  # see smc_engine.score_signal for how score is built

# Safety cap so a mistyped list of 200 tickers doesn't blow past API rate limits / run time
MAX_TICKERS_PER_RUN = 100
