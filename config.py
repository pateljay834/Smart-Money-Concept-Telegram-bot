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
LOOKBACK_PERIOD = "3y" # longer history = more backtest occurrences = a less noisy win-rate estimate

# SMC engine tuning
SWING_LENGTH = 10        # smaller = more sensitive swing detection, larger = major structure only
LIQUIDITY_RANGE_PCT = 0.01
STRUCTURE_RECENCY_BARS = 10   # a confirmed structure break older than this many bars no longer
                               # counts as the "current" signal — stale structure isn't a live setup

# Confluence weights. NOT all equal — a discretionary trader weights a
# confirmed structure break or HTF alignment far higher than a loose FVG
# touch. Each category can contribute its weight AT MOST ONCE (multiple
# overlapping order blocks near the same zone are one confluence, not
# several — see score_signal for the dedup logic this backs).
WEIGHT_STRUCTURE = 2
WEIGHT_HTF = 2
WEIGHT_ORDER_BLOCK = 1
WEIGHT_FVG = 1
WEIGHT_ZONE = 1
WEIGHT_LIQUIDITY_SWEEP = 1
WEIGHT_OB_FVG_OVERLAP = 1   # bonus: OB and FVG both present in the same zone ("consequent encroachment")
WEIGHT_VOLUME_CONFIRMATION = 1   # the structure break happened on above-average volume — real
                                   # participation, not a low-volume drift that shakes out easily
MAX_POSSIBLE_SCORE = (WEIGHT_STRUCTURE + WEIGHT_HTF + WEIGHT_ORDER_BLOCK + WEIGHT_FVG
                       + WEIGHT_ZONE + WEIGHT_LIQUIDITY_SWEEP + WEIGHT_OB_FVG_OVERLAP
                       + WEIGHT_VOLUME_CONFIRMATION)  # 10

# Higher-timeframe bias (weekly) — standard SMC/ICT top-down practice:
# trade in the direction of the dominant trend, treat counter-trend setups
# as lower conviction rather than ignoring them outright.
USE_HTF_FILTER = True
HTF_INTERVAL = "1wk"
HTF_LOOKBACK = "3y"
HTF_SWING_LENGTH = 6
HTF_RECENCY_BARS = 8     # weeks

# Broader market regime filter (Nifty 50) — fetched ONCE per run and shared
# across all symbols, not once per symbol, to avoid multiplying API calls.
USE_INDEX_FILTER = True
INDEX_SYMBOL = "^NSEI"
INDEX_LOOKBACK = "3y"
INDEX_SWING_LENGTH = 8
INDEX_RECENCY_BARS = 15

# Trend-strength regime (ADX/DMI) — beyond pure SMC. SMC/ICT structural
# signals are historically less reliable in a choppy, non-trending market;
# this doesn't block a setup (a real reversal has to start somewhere) but
# flags the regime so you can weight the setup accordingly.
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 20   # below this, the market is considered range-bound/choppy

# Momentum context (RSI) — used as a caution flag (chasing an overbought
# move / selling into an oversold one), not a scored confluence. SMC gives
# the structural "where"; RSI gives a sanity check on "how stretched".
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# Volatility / risk realism
ATR_PERIOD = 14
MIN_STOP_ATR_MULT = 1.0   # stop must be at least 1x ATR away from entry — rejects noise-tight stops
                           # that look like a great R:R on paper but get stopped out by normal chop

# Overnight gap risk — a stop-loss is only as good as the market's ability
# to fill it. If the open has historically gapped past today's stop
# distance often enough, warn that the stop may not be honored.
GAP_RISK_LOOKBACK_DAYS = 252
GAP_RISK_WARNING_THRESHOLD = 0.03   # warn if >3% of sessions gapped beyond the stop distance

# Liquidity filter — thinly traded stocks have unreliable fills and wider slippage
MIN_AVG_VOLUME = 100_000   # average daily volume over the last 20 sessions

# Backtest settings used to turn "setup type" into an honest historical win-rate.
# The backtest simulates the SAME stop/target distances as the live signal (not
# just "did price move in the right direction") — a directional win where the
# stop would have been hit first is NOT counted as a win.
BACKTEST_FORWARD_BARS = 20      # max bars to wait for target/stop to be hit
BACKTEST_MIN_SAMPLES = 15       # need at least this many resolved past trades before showing a win-rate
CONFIDENCE_HIGH_SAMPLES = 30    # samples at/above this get labeled High confidence, else Medium

# Screener filter: only alert when a setup scores at or above this. Requires
# roughly "one major confluence (structure or HTF) plus one more", not just
# any two minor ones stacked together.
MIN_SCORE_TO_ALERT = 5  # out of MAX_POSSIBLE_SCORE (10)

# Safety cap so a mistyped list of 200 tickers doesn't blow past API rate limits / run time
MAX_TICKERS_PER_RUN = 25

# Position sizing — opt-in. Set ACCOUNT_SIZE to a real number (e.g. via .env /
# a secret, not hardcoded here) to get a suggested share quantity per trade
# risking RISK_PER_TRADE_PCT of that account. Left as None by default so no
# assumption is made about your capital.
ACCOUNT_SIZE = os.environ.get("ACCOUNT_SIZE")
ACCOUNT_SIZE = float(ACCOUNT_SIZE) if ACCOUNT_SIZE else None
RISK_PER_TRADE_PCT = float(os.environ.get("RISK_PER_TRADE_PCT", "1.0"))

# Lightweight fundamentals (P/E, sector, market cap) via yfinance's .info
# endpoint. Purely best-effort: this endpoint has been unreliable in
# testing (slow, occasionally 404s on valid symbols), so a failure here
# NEVER blocks or warns — it just silently omits the fundamentals section.
# Only fetched for symbols that already qualify, to limit extra API load.
USE_FUNDAMENTALS = True

REGULATORY_DISCLAIMER = (
    "This is a rule-based structural analysis and backtest, not investment "
    "advice under SEBI regulations, and this bot does not place or execute "
    "any orders. It cannot see ASM/GSM surveillance status or Trade-to-Trade "
    "segment restrictions — verify those on the exchange before trading any "
    "symbol. Consult a SEBI-registered advisor for personalized advice."
)
