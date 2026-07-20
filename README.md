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
- **Realistic backtesting.** The win-rate is no longer "did price move the
  right direction after N bars" — it now simulates the SAME stop/target
  distances as the live signal on every past occurrence and checks whether
  the target was actually hit before the stop. A directional win that
  would've been stopped out first no longer counts as a win.
- **ATR-floored stops.** Stops can no longer be unrealistically tight (which
  used to inflate R:R on paper); they're floored at a minimum ATR distance.
- **Liquidity filter.** Thinly traded symbols (avg volume below 100k/day,
  configurable) get an explicit warning since fills/slippage are unreliable there.
- **Confidence tiering.** Every setup is labeled Low/Medium/High confidence
  based on how many resolved historical trades back it up — a setup with 3
  past occurrences is flagged as unvalidated rather than shown with a
  confident-looking percentage.

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
- `.github/workflows/tests.yml` — CI: runs `tests/` on every push/PR
- `tests/` — pytest suite covering the engine's highest-risk logic

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

## Expert audit — what changed and what's still worth knowing

An audit pass from a trading-methodology angle and a software-engineering
angle turned up one critical bug and several reliability gaps. Fixed:

- **Lookahead bias in structure detection (critical).** The `smartmoneyconcepts`
  library flags a BOS/CHoCH at the position of the *swing point* that defines
  it, but the break is only actually confirmed later, at that row's
  `BrokenIndex`. Earlier versions of this bot used the swing-point position
  as "when the signal fired" — both for the live read and, worse, for the
  backtest. That back-dates a signal to before it could have been known, and
  inflates backtest win-rates with information the strategy never had in
  real time. Now everything (live signal recency, backtest entry position)
  uses `BrokenIndex` via `confirmed_structure_events()`. This is covered by
  a regression test (`tests/test_smc_engine.py`) so it can't silently
  reappear on a library update.
- **Liquidity sweeps now used.** The library computed a liquidity-pool sweep
  indicator that was fetched but never read — a real SMC/ICT stop-hunt
  reversal trigger was being thrown away. It's now confluence #5.
- **Higher-timeframe (weekly) bias.** Top-down bias confirmation is standard
  SMC practice — a daily setup against the weekly trend is lower conviction
  even if the daily structure looks clean. The bot now fetches weekly data
  and flags counter-trend setups explicitly rather than presenting every
  qualifying setup with equal weight.
- **Tighter, volatility-scaled OB/FVG proximity.** "Near a zone" used to
  mean a flat 2% price buffer — too loose on expensive stocks, too tight on
  cheap ones. Now scaled to ATR.
- **Optional position sizing** based on a configurable account size and
  risk-per-trade percentage (opt-in, `.env` only — nothing hardcoded).
- **Dependencies pinned to exact tested versions.** A `smartmoneyconcepts`
  point release previously changed internal index semantics and silently
  broke the bot (the KeyError crashes from an earlier round). Ranges
  (`>=`) don't protect against that; exact pins plus a test suite do.
- **A real test suite** (`tests/`, run via `pytest`) covering the lookahead
  fix, backtest bounds, ATR stop floor, liquidity filtering, and HTF
  conflict warnings — plus a CI workflow (`.github/workflows/tests.yml`)
  that runs it on every push, so a future change that breaks this logic
  fails loudly in Actions instead of silently in your Telegram feed.

### Second audit round — trader panel + portfolio/investor review

- **Weighted, de-duplicated scoring (was a real bug).** Every confluence
  used to count as +1 regardless of importance, AND the OB/FVG loops summed
  +1 per matching row — so three overlapping order blocks near the same
  zone counted as three independent confirmations instead of one. Now each
  category (`config.WEIGHT_*`) contributes its weight at most once per
  direction, with structure breaks and HTF alignment weighted higher (2)
  than a loose FVG touch (1). `MIN_SCORE_TO_ALERT` moved from 2 to 4 out of
  a new max of 9 to keep the bar meaningfully strict under the new scale.
- **OB+FVG overlap bonus ("consequent encroachment").** A recognized
  higher-probability ICT confluence — an order block and fair value gap
  sitting in the same zone — is now specifically detected and flagged,
  not just counted as two separate, unrelated points.
- **Broader market regime (Nifty 50) check.** Fetched once per run and
  shared across every symbol (not re-fetched per ticker). Setups that fight
  the index's own structural trend are flagged, the way a portfolio manager
  would push back on a trade that's fighting the tape.
- **Overnight gap risk.** A stop-loss is only as good as the market's
  ability to fill it. The bot now checks how often, historically, an
  overnight gap alone would have jumped past today's stop distance, and
  warns when that's happened often enough to matter — a real risk on
  Indian mid/small caps that no intraday-only backtest can see.
- **Portfolio-level view in the run summary.** A screen returning 10
  qualifying LONGs isn't 10 independent opportunities if they're all the
  same directional bet — the summary now shows the LONG/SHORT split, flags
  it when everything points the same way, and (if `ACCOUNT_SIZE` is set)
  shows the aggregate risk of taking every qualifying setup at once.
- **Explicit regulatory disclaimer.** Every message now states plainly that
  this isn't SEBI-registered advice, doesn't place or execute any orders,
  and can't see ASM/GSM surveillance or Trade-to-Trade segment status —
  check those manually before trading a flagged symbol.

**Known limitations that remain — read before sizing real capital:**

- The backtest still recomputes structure over the *entire* series and reads
  off `BrokenIndex`, rather than a true walk-forward simulation that
  recomputes indicators using only data available at each historical point.
  `BrokenIndex` removes the worst of the lookahead (the break-confirmation
  delay), but a fully rigorous backtest would re-run swing detection with an
  expanding window. That's meaningfully more compute (roughly O(n²) instead
  of O(n) per symbol) and was left out to keep runs fast enough for a manual
  GitHub Actions trigger — a reasonable trade-off for a screening tool, not
  for validating a strategy you're about to size seriously.
- Scoring confluences (structure, OB, FVG, zone, sweep, HTF) are weighted
  equally (1 point each). A real discretionary SMC trader would weight
  structure break and HTF alignment more heavily than a loose FVG touch —
  this is a simplification, not a calibrated model.
- No slippage, spread, or brokerage cost modeling in the backtest — real
  fills will be worse than the simulated target/stop levels, especially on
  the lower-liquidity end of what passes the liquidity filter.
- Same-bar target+stop touches are resolved conservatively as losses, but
  daily OHLC genuinely can't tell you which was touched first — on a
  volatile day the real outcome could go either way.
- **No lower-timeframe entry refinement.** Proper ICT/SMC top-down practice
  uses the HTF for bias and then drops to a lower timeframe (e.g. 15m/1h)
  to time the actual entry off an LTF structure shift. This bot enters
  directly off the daily close — there's no LTF refinement layer.
- **No breaker blocks, mitigation blocks, or Optimal Trade Entry (Fibonacci
  62–79% retracement) confluence** — all distinct, commonly-traded SMC/ICT
  concepts not implemented here.
- **No displacement/imbalance quality scoring.** An order block or FVG
  formed by an explosive move is a stronger signal than one formed by a
  shallow one — the bot detects presence, not strength.
- **The portfolio concentration check is directional only, not sector-aware.**
  It flags "all qualifying setups are LONG" but can't tell you 8 of them are
  all banking stocks — that would need per-symbol sector data, which isn't
  fetched (yfinance's `.info` endpoint is slow and unreliable enough to risk
  breaking runs for a nice-to-have).
- **No fundamental or event-risk screen.** A technically clean setup can be
  invalidated overnight by an earnings surprise or corporate action; none of
  that is checked.
- This is a single-strategy, single-timeframe-pair (daily + weekly) tool.
  It is not a substitute for your own risk management, and the "win-rate"
  is a backtest statistic on synthetic-free but limited historical data —
  not a forward-looking guarantee.
