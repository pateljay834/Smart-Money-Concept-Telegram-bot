# SMC Telegram Bot

Smart Money Concept (BOS/CHoCH, Order Blocks, FVGs, premium/discount) analysis,
screener, charting, and Telegram delivery — usable both as a manual GitHub
Actions workflow and as an always-on interactive bot.

## What changed in this version

- **No files left behind.** Charts are written to a temp file and deleted
  immediately after being sent to Telegram — nothing accumulates on your
  laptop or in the repo.
- **One bad ticker can't kill a run.** Every symbol is analyzed inside its
  own try/except; failures are collected and reported in the summary instead
  of stopping the batch.
- **The bot staying responsive.** The interactive bot now runs analysis in a
  worker thread instead of blocking Telegram's event loop directly — this
  was the likely cause of it "working once, then going quiet."
- **One workflow, both jobs.** `run.py` (used by both the GitHub Action and
  locally) takes a `MODE` (`analyze` / `screen` / `both`) and a `TICKERS`
  list instead of only ever scanning a fixed watchlist.
- **Shared core.** `core.py` is the single source of truth for analysis and
  message formatting, used identically by `bot.py` and `run.py` — no drift
  between the two interfaces.

## Two ways to run it

### 1. GitHub Actions — manual, on demand, no server
Go to the repo's **Actions tab → SMC Bot → Run workflow**. You'll get two
fields:
- **mode**: `analyze` (full report on every ticker given), `screen` (only
  tickers meeting the score threshold), or `both` (full report on everything
  plus a screening summary at the end)
- **tickers**: space-separated, e.g. `RELIANCE.NS TCS.NS INFY.NS` — leave
  blank to fall back to `WATCHLIST` in `config.py`

Nothing runs on a schedule. It only runs when you click the button.

### 2. Interactive bot — for live chat commands
Needs an always-running process (GitHub Actions can't do this — runners
aren't persistent). Run locally via `run.bat`, or on an always-on free host.

```
/analyze RELIANCE.NS TCS.NS     - full report on the tickers you list
/screen                         - screen your default watchlist
/screen RELIANCE.NS TCS.NS      - screen a custom list instead
```

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather), get the token.
2. Message your bot once, then get your chat ID (e.g. via `@userinfobot`).
3. Push this folder to a GitHub repo. `.env` is gitignored — only
   `.env.example` (no real values) gets committed.
4. **For GitHub Actions**: Settings → Secrets and variables → Actions → New
   repository secret — required, since Actions runners never see your local
   filesystem or `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. **For the local bot**: copy `.env.example` to `.env` and fill in the same
   two values — `config.py` loads it automatically.
6. Optionally edit `WATCHLIST` in `config.py` (used only when you don't pass
   tickers explicitly).
7. Run it: Actions tab for on-demand workflow runs, or `run.bat` for the live bot.

## Files

- `config.py` — defaults, thresholds, reads secrets from environment/`.env`
- `data_fetch.py` — OHLCV via yfinance, with retry on transient failures
- `smc_engine.py` — SMC structure detection, scoring, risk levels, backtest-based win-rate
- `chart_utils.py` — candlestick chart with OB/FVG/entry-stop-target overlays, written to a temp file
- `core.py` — shared batch-analysis + message-formatting logic (used by both entry points)
- `run.py` — GitHub Actions / manual entry point (`MODE`, `TICKERS` env vars)
- `bot.py` — interactive polling bot (run locally / always-on host)
- `.github/workflows/screener.yml` — the manual-trigger workflow

## Honesty note on "probability of profit"

There's no black-box ML prediction here. `smc_engine.backtest_setup()` looks
at every past time this exact rule-based setup occurred on that same stock's
own history, and reports the real win-rate from that. If there aren't enough
past occurrences yet, it says so instead of inventing a number.

## Limits worth knowing

- `MAX_TICKERS_PER_RUN` (default 25) caps a single run so a mistyped huge
  list doesn't blow past API rate limits or run time — raise it in `config.py`
  if you need more.
- yfinance intraday intervals (e.g. `15m`) only return ~60 days of history;
  daily (`1d`, the default) goes back much further.
