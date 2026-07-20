"""
Core Smart Money Concept analysis.

=== Critical fix: lookahead bias in structure detection ===
The `smartmoneyconcepts` library records a BOS/CHoCH flag at the position of
the SWING POINT that defines it, but the break is only actually confirmed
later, at that row's `BrokenIndex` — the candle where price closed beyond
the level. Using the swing-point position as "when the signal fired" would
back-date the signal to before it could have been known, both for the live
read and for the backtest. This uses BrokenIndex as the real signal
timestamp everywhere, via confirmed_structure_events().

=== Weighted, de-duplicated confluence scoring ===
Not every confluence is equally meaningful. A confirmed structure break or
HTF alignment gets more weight than a loose FVG touch (config.WEIGHT_*).
Each category can contribute its weight AT MOST ONCE per direction — three
overlapping order blocks near the same zone are one confluence, not three
(the old version summed +1 per matching row, which double-counted).

Design otherwise unchanged: no black-box ML prediction. Every number is
traceable to real data. The backtest simulates the SAME stop/target
distances as the live signal — a directional "win" where the stop would
have been hit first is NOT counted as a win.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from smartmoneyconcepts import smc

import config


@dataclass
class Signal:
    symbol: str
    direction: str          # "LONG", "SHORT", or "NO TRADE"
    score: int
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    entry: float = None
    stop_loss: float = None
    target: float = None
    risk_reward: float = None
    win_rate: float = None
    sample_size: int = 0
    confidence: str = None   # "Low", "Medium", "High", or None if no backtest ran
    htf_bias: str = None     # "bull", "bear", "neutral", or None if not checked
    index_bias: str = None   # same, for the broader market regime check


def compute_indicators(ohlc: pd.DataFrame):
    swings = smc.swing_highs_lows(ohlc, swing_length=config.SWING_LENGTH)
    structure = smc.bos_choch(ohlc, swings, close_break=True)
    order_blocks = smc.ob(ohlc, swings, close_mitigation=False)
    fvg = smc.fvg(ohlc, join_consecutive=True)
    liquidity = smc.liquidity(ohlc, swings, range_percent=config.LIQUIDITY_RANGE_PCT)
    return swings, structure, order_blocks, fvg, liquidity


def compute_atr(ohlc: pd.DataFrame, period: int = None) -> pd.Series:
    period = period or config.ATR_PERIOD
    high, low, close = ohlc["high"], ohlc["low"], ohlc["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def confirmed_structure_events(structure: pd.DataFrame) -> pd.DataFrame:
    """
    Reindex structure breaks by BrokenIndex (the position where the break
    was ACTUALLY confirmed) instead of the swing-point position the library
    stores them at. `confirm_pos` is the earliest position this signal
    could honestly have been acted on.
    """
    events = structure.dropna(subset=["BOS", "CHOCH"], how="all").copy()
    events = events[events["BrokenIndex"] > 0]
    if events.empty:
        return events
    events["confirm_pos"] = events["BrokenIndex"].astype(int)
    return events.sort_values("confirm_pos")


def _current_zone(ohlc, swings):
    """Premium (upper half of recent swing range) vs discount (lower half)."""
    recent = swings.dropna(subset=["Level"]).tail(20)
    if recent.empty:
        return "unknown", None, None
    hi = recent["Level"].max()
    lo = recent["Level"].min()
    if hi == lo:
        return "unknown", hi, lo
    price = ohlc["close"].iloc[-1]
    midpoint = (hi + lo) / 2
    zone = "discount" if price < midpoint else "premium"
    return zone, hi, lo


def _liquidity_check(ohlc: pd.DataFrame):
    avg_vol = ohlc["volume"].tail(20).mean()
    if avg_vol < config.MIN_AVG_VOLUME:
        return False, avg_vol
    return True, avg_vol


def _recent_liquidity_sweep(liquidity_df: pd.DataFrame, n_bars: int, recency: int):
    """
    A liquidity pool built from equal highs ("bullish liquidity" in the
    library's naming — it just means the pool sits above price) that gets
    swept is a classic bearish reversal trigger (stop-hunt above resistance,
    then dump). A pool built from equal lows getting swept is the bullish
    mirror. Returns "bull", "bear", or None.
    """
    swept = liquidity_df.dropna(subset=["Swept"])
    swept = swept[(swept["Swept"] > 0) & (swept["Swept"] >= n_bars - 1 - recency)]
    if swept.empty:
        return None
    last = swept.sort_values("Swept").iloc[-1]
    if last["Liquidity"] == 1:
        return "bear"
    if last["Liquidity"] == -1:
        return "bull"
    return None


def _gap_risk(ohlc: pd.DataFrame, stop_dist: float) -> float:
    """
    Fraction of recent sessions where the overnight gap (open vs prior
    close) alone exceeded today's stop distance. A high value means a
    gap could realistically skip straight past the stop before it can
    execute — a real risk on Indian mid/small caps, invisible to any
    backtest that only checks intraday high/low against the stop.
    """
    if stop_dist <= 0:
        return 0.0
    recent = ohlc.tail(config.GAP_RISK_LOOKBACK_DAYS)
    prior_close = recent["close"].shift(1)
    gap = (recent["open"] - prior_close).abs().dropna()
    if gap.empty:
        return 0.0
    return float((gap > stop_dist).mean())


def _structural_bias(ohlc_tf: pd.DataFrame, swing_length: int, recency_bars: int) -> str:
    """Shared logic behind htf_bias() and index_bias() — same method, different timeframe/instrument."""
    if len(ohlc_tf) < swing_length * 4:
        return "neutral"
    swings = smc.swing_highs_lows(ohlc_tf, swing_length=swing_length)
    structure = smc.bos_choch(ohlc_tf, swings, close_break=True)
    events = confirmed_structure_events(structure)
    if events.empty:
        return "neutral"
    recent = events[events["confirm_pos"] >= len(ohlc_tf) - 1 - recency_bars]
    if recent.empty:
        return "neutral"
    last = recent.iloc[-1]
    if last["BOS"] == 1 or last["CHOCH"] == 1:
        return "bull"
    if last["BOS"] == -1 or last["CHOCH"] == -1:
        return "bear"
    return "neutral"


def htf_bias(ohlc_htf: pd.DataFrame) -> str:
    """Higher-timeframe (weekly) structural bias — standard top-down SMC/ICT practice."""
    return _structural_bias(ohlc_htf, config.HTF_SWING_LENGTH, config.HTF_RECENCY_BARS)


def index_bias(ohlc_index: pd.DataFrame) -> str:
    """Broader market (Nifty 50) structural regime — fetch once per run, share across all symbols."""
    return _structural_bias(ohlc_index, config.INDEX_SWING_LENGTH, config.INDEX_RECENCY_BARS)


def _htf_conflict_warning(direction: str, htf_direction: str) -> str:
    if htf_direction and ((direction == "LONG" and htf_direction == "bear") or (direction == "SHORT" and htf_direction == "bull")):
        return f"This setup is counter-trend against the weekly HTF bias ({htf_direction}) — lower conviction"
    return None


def _index_conflict_warning(direction: str, index_direction: str) -> str:
    if index_direction and ((direction == "LONG" and index_direction == "bear") or (direction == "SHORT" and index_direction == "bull")):
        return f"This setup goes against the broader Nifty trend ({index_direction}) — trading against market regime carries extra risk"
    return None


def score_signal(symbol: str, ohlc: pd.DataFrame, htf_direction: str = None, index_direction: str = None) -> Signal:
    swings, structure, order_blocks, fvg, liquidity = compute_indicators(ohlc)
    price = ohlc["close"].iloc[-1]
    atr_series = compute_atr(ohlc)
    atr = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None
    proximity_buffer = (atr * 0.25) if atr else price * 0.005

    bull_score, bear_score = 0, 0
    reasons = []
    warnings = []
    bull_flags, bear_flags = set(), set()

    liquid, avg_vol = _liquidity_check(ohlc)
    if not liquid:
        warnings.append(f"Average volume ({avg_vol:,.0f}/day) is below the {config.MIN_AVG_VOLUME:,} liquidity floor — fills and slippage may be unreliable")

    # 1) Most recently CONFIRMED structure break (BrokenIndex-based)
    events = confirmed_structure_events(structure)
    recent_events = events[events["confirm_pos"] >= len(ohlc) - 1 - config.STRUCTURE_RECENCY_BARS] if not events.empty else events
    if not recent_events.empty:
        row = recent_events.iloc[-1]
        if row.get("BOS") == 1 or row.get("CHOCH") == 1:
            bull_score += config.WEIGHT_STRUCTURE
            bull_flags.add("structure")
            reasons.append("Most recently confirmed structure break is bullish (BOS/CHoCH up)")
        elif row.get("BOS") == -1 or row.get("CHOCH") == -1:
            bear_score += config.WEIGHT_STRUCTURE
            bear_flags.add("structure")
            reasons.append("Most recently confirmed structure break is bearish (BOS/CHoCH down)")

    # 2) Nearby unmitigated order block — counted ONCE per direction even if
    #    several rows match (they're the same zone, not independent confirmations)
    unmitigated_ob = order_blocks[order_blocks["MitigatedIndex"].isna() | (order_blocks["MitigatedIndex"] == 0)]
    ob_bull = ob_bear = False
    for _, ob_row in unmitigated_ob.tail(5).iterrows():
        if ob_row.get("OB") == 1 and ob_row["Bottom"] - proximity_buffer <= price <= ob_row["Top"] + proximity_buffer:
            ob_bull = True
        elif ob_row.get("OB") == -1 and ob_row["Bottom"] - proximity_buffer <= price <= ob_row["Top"] + proximity_buffer:
            ob_bear = True
    if ob_bull:
        bull_score += config.WEIGHT_ORDER_BLOCK
        bull_flags.add("ob")
        reasons.append("Price near an unmitigated bullish order block")
    if ob_bear:
        bear_score += config.WEIGHT_ORDER_BLOCK
        bear_flags.add("ob")
        reasons.append("Price near an unmitigated bearish order block")

    # 3) Nearby unmitigated FVG — same one-per-direction dedup
    unmitigated_fvg = fvg[fvg["MitigatedIndex"].isna() | (fvg["MitigatedIndex"] == 0)]
    fvg_bull = fvg_bear = False
    for _, gap in unmitigated_fvg.tail(5).iterrows():
        if gap.get("FVG") == 1 and gap["Bottom"] - proximity_buffer <= price <= gap["Top"] + proximity_buffer:
            fvg_bull = True
        elif gap.get("FVG") == -1 and gap["Bottom"] - proximity_buffer <= price <= gap["Top"] + proximity_buffer:
            fvg_bear = True
    if fvg_bull:
        bull_score += config.WEIGHT_FVG
        bull_flags.add("fvg")
        reasons.append("Price near an unfilled bullish fair value gap")
    if fvg_bear:
        bear_score += config.WEIGHT_FVG
        bear_flags.add("fvg")
        reasons.append("Price near an unfilled bearish fair value gap")

    # OB + FVG overlap bonus ("consequent encroachment") — a recognized
    # higher-probability ICT confluence, not just two separate points
    if "ob" in bull_flags and "fvg" in bull_flags:
        bull_score += config.WEIGHT_OB_FVG_OVERLAP
        reasons.append("Order block and fair value gap overlap in the same bullish zone — higher-probability confluence")
    if "ob" in bear_flags and "fvg" in bear_flags:
        bear_score += config.WEIGHT_OB_FVG_OVERLAP
        reasons.append("Order block and fair value gap overlap in the same bearish zone — higher-probability confluence")

    # 4) Premium/discount positioning
    zone, swing_hi, swing_lo = _current_zone(ohlc, swings)
    if zone == "discount":
        bull_score += config.WEIGHT_ZONE
        reasons.append("Price is in the discount zone of recent range")
    elif zone == "premium":
        bear_score += config.WEIGHT_ZONE
        reasons.append("Price is in the premium zone of recent range")

    # 5) Recent liquidity sweep (stop-hunt reversal trigger)
    sweep_dir = _recent_liquidity_sweep(liquidity, len(ohlc), config.STRUCTURE_RECENCY_BARS)
    if sweep_dir == "bull":
        bull_score += config.WEIGHT_LIQUIDITY_SWEEP
        reasons.append("Sell-side liquidity was recently swept (stop-hunt low) — bullish reversal trigger")
    elif sweep_dir == "bear":
        bear_score += config.WEIGHT_LIQUIDITY_SWEEP
        reasons.append("Buy-side liquidity was recently swept (stop-hunt high) — bearish reversal trigger")

    # 6) Higher-timeframe bias alignment
    if htf_direction == "bull":
        bull_score += config.WEIGHT_HTF
        reasons.append("Weekly higher-timeframe structure is bullish")
    elif htf_direction == "bear":
        bear_score += config.WEIGHT_HTF
        reasons.append("Weekly higher-timeframe structure is bearish")

    if bull_score == bear_score or max(bull_score, bear_score) < config.MIN_SCORE_TO_ALERT:
        return Signal(symbol=symbol, direction="NO TRADE", score=max(bull_score, bear_score), reasons=reasons,
                       warnings=warnings, htf_bias=htf_direction, index_bias=index_direction)

    direction = "LONG" if bull_score > bear_score else "SHORT"
    score = max(bull_score, bear_score)

    htf_warning = _htf_conflict_warning(direction, htf_direction)
    if htf_warning:
        warnings.append(htf_warning)

    # Market-regime check: trading against the broader index isn't scored
    # (going WITH the market isn't a bonus confluence, it's just not fighting
    # it) but going against it is flagged as extra risk, the way a portfolio
    # manager would.
    index_warning = _index_conflict_warning(direction, index_direction)
    if index_warning:
        warnings.append(index_warning)

    # Risk levels: stop beyond the most recent opposite swing, floored at a
    # minimum ATR distance so a lucky/noisy micro-swing can't produce an
    # unrealistically tight stop and an inflated, unexecutable R:R.
    recent_swings = swings.dropna(subset=["Level"]).tail(10)
    min_stop_dist = (atr * config.MIN_STOP_ATR_MULT) if atr else price * 0.01

    if direction == "LONG":
        lows = recent_swings[recent_swings["HighLow"] == -1]["Level"]
        swing_stop = float(lows.min()) * 0.995 if not lows.empty else price - min_stop_dist
        stop = min(swing_stop, price - min_stop_dist)
        target = float(swing_hi) if swing_hi else price + min_stop_dist * 2
    else:
        highs = recent_swings[recent_swings["HighLow"] == 1]["Level"]
        swing_stop = float(highs.max()) * 1.005 if not highs.empty else price + min_stop_dist
        stop = max(swing_stop, price + min_stop_dist)
        target = float(swing_lo) if swing_lo else price - min_stop_dist * 2

    risk = abs(price - stop)
    reward = abs(target - price)
    if risk <= 0:
        return Signal(symbol=symbol, direction="NO TRADE", score=score, reasons=reasons,
                       warnings=warnings + ["Could not compute a valid stop distance"],
                       htf_bias=htf_direction, index_bias=index_direction)
    rr = round(reward / risk, 2)

    if rr < 1.0:
        warnings.append(f"Reward:Risk is below 1:1 (1:{rr}) — target is closer than the stop, a weak trade even if the setup is directionally right")

    gap_breach_rate = _gap_risk(ohlc, risk)
    if gap_breach_rate > config.GAP_RISK_WARNING_THRESHOLD:
        warnings.append(
            f"Overnight gaps exceeded this stop distance on {gap_breach_rate * 100:.1f}% of the last "
            f"{config.GAP_RISK_LOOKBACK_DAYS} sessions — a gap could skip past your stop before it can execute"
        )

    win_rate, samples, resolved_total = backtest_setup(ohlc, direction, risk, reward)

    confidence = None
    if samples >= config.BACKTEST_MIN_SAMPLES:
        confidence = "High" if samples >= config.CONFIDENCE_HIGH_SAMPLES else "Medium"
    elif samples > 0:
        confidence = "Low"

    return Signal(
        symbol=symbol,
        direction=direction,
        score=score,
        reasons=reasons,
        warnings=warnings,
        entry=round(float(price), 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_reward=rr,
        win_rate=win_rate,
        sample_size=samples,
        confidence=confidence,
        htf_bias=htf_direction,
        index_bias=index_direction,
    )


def backtest_setup(ohlc: pd.DataFrame, direction: str, risk_dist: float, reward_dist: float):
    """
    Realistic backtest: for every PAST structure break CONFIRMED in the same
    direction (using BrokenIndex — the lookahead-bias fix), simulate a trade
    using the same risk:reward ratio as the live signal, scaled to that
    historical bar's own ATR. Walk forward and check whether price hits the
    target or the stop first.

    Outcomes:
      - target hit before stop  -> win
      - stop hit before target  -> loss
      - both hit same bar       -> counted as a loss (conservative — daily
        OHLC can't tell us which was touched first intrabar)
      - neither hit in the window -> excluded as inconclusive

    Returns (win_rate_pct or None, resolved_sample_count, total_occurrences_checked).
    None win_rate means fewer than BACKTEST_MIN_SAMPLES resolved trades —
    an honest "not enough data" instead of a number built on noise.
    """
    swings = smc.swing_highs_lows(ohlc, swing_length=config.SWING_LENGTH)
    structure = smc.bos_choch(ohlc, swings, close_break=True)
    atr_series = compute_atr(ohlc)

    rr_multiple = reward_dist / risk_dist if risk_dist > 0 else 1.0
    target_val = 1 if direction == "LONG" else -1

    events = confirmed_structure_events(structure)
    if events.empty:
        return None, 0, 0
    hits = events[(events["BOS"] == target_val) | (events["CHOCH"] == target_val)]

    highs = ohlc["high"].values
    lows = ohlc["low"].values
    closes = ohlc["close"].values
    atr_vals = atr_series.values

    wins, resolved, checked = 0, 0, 0
    for pos in hits["confirm_pos"]:
        pos = int(pos)
        if pos >= len(atr_vals) or np.isnan(atr_vals[pos]):
            continue
        entry_price = closes[pos]
        bar_atr = atr_vals[pos]
        stop_dist = max(bar_atr * config.MIN_STOP_ATR_MULT, bar_atr * 0.5)
        reward_dist_hist = stop_dist * rr_multiple

        if direction == "LONG":
            stop_level = entry_price - stop_dist
            target_level = entry_price + reward_dist_hist
        else:
            stop_level = entry_price + stop_dist
            target_level = entry_price - reward_dist_hist

        checked += 1
        outcome = None
        end = min(pos + 1 + config.BACKTEST_FORWARD_BARS, len(closes))
        for j in range(pos + 1, end):
            if direction == "LONG":
                hit_target = highs[j] >= target_level
                hit_stop = lows[j] <= stop_level
            else:
                hit_target = lows[j] <= target_level
                hit_stop = highs[j] >= stop_level
            if hit_target and hit_stop:
                outcome = False
                break
            if hit_target:
                outcome = True
                break
            if hit_stop:
                outcome = False
                break

        if outcome is not None:
            resolved += 1
            wins += int(outcome)

    if resolved < config.BACKTEST_MIN_SAMPLES:
        return None, resolved, checked
    return round(100 * wins / resolved, 1), resolved, checked
