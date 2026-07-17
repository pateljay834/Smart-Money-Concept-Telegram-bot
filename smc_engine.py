"""
Core Smart Money Concept analysis.

Design choice (read this before changing the scoring):
This does NOT claim to run a machine-learning "prediction". Instead it:
  1. Detects SMC structure (BOS/CHoCH, Order Blocks, FVGs, swing range) via
     the `smartmoneyconcepts` library.
  2. Scores how many bullish/bearish confluences are currently active.
  3. Backtests that same simplified rule set against the symbol's own
     history to report an actual historical win-rate ("probability of
     profit" = frequency this setup was followed by a favorable move in
     the past, not a guarantee).
This keeps every number traceable to real data rather than a black box.
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
    entry: float = None
    stop_loss: float = None
    target: float = None
    risk_reward: float = None
    win_rate: float = None
    sample_size: int = 0


def compute_indicators(ohlc: pd.DataFrame):
    swings = smc.swing_highs_lows(ohlc, swing_length=config.SWING_LENGTH)
    structure = smc.bos_choch(ohlc, swings, close_break=True)
    order_blocks = smc.ob(ohlc, swings, close_mitigation=False)
    fvg = smc.fvg(ohlc, join_consecutive=True)
    liquidity = smc.liquidity(ohlc, swings, range_percent=config.LIQUIDITY_RANGE_PCT)
    return swings, structure, order_blocks, fvg, liquidity


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


def score_signal(symbol: str, ohlc: pd.DataFrame) -> Signal:
    swings, structure, order_blocks, fvg, liquidity = compute_indicators(ohlc)
    price = ohlc["close"].iloc[-1]

    bull_score, bear_score = 0, 0
    reasons = []

    # 1) Latest confirmed structure break direction
    last_struct = structure.dropna(subset=["BOS", "CHOCH"], how="all").tail(1)
    struct_dir = None
    if not last_struct.empty:
        row = last_struct.iloc[0]
        if row.get("BOS") == 1 or row.get("CHOCH") == 1:
            struct_dir = "bull"
            bull_score += 1
            reasons.append("Latest structure break is bullish (BOS/CHoCH up)")
        elif row.get("BOS") == -1 or row.get("CHOCH") == -1:
            struct_dir = "bear"
            bear_score += 1
            reasons.append("Latest structure break is bearish (BOS/CHoCH down)")

    # 2) Nearby unmitigated order block in that direction
    unmitigated_ob = order_blocks[order_blocks["MitigatedIndex"].isna() | (order_blocks["MitigatedIndex"] == 0)]
    for _, ob_row in unmitigated_ob.tail(5).iterrows():
        if ob_row.get("OB") == 1 and ob_row["Bottom"] <= price <= ob_row["Top"] * 1.02:
            bull_score += 1
            reasons.append("Price near an unmitigated bullish order block")
        elif ob_row.get("OB") == -1 and ob_row["Bottom"] * 0.98 <= price <= ob_row["Top"]:
            bear_score += 1
            reasons.append("Price near an unmitigated bearish order block")

    # 3) Nearby unmitigated FVG in that direction
    unmitigated_fvg = fvg[fvg["MitigatedIndex"].isna() | (fvg["MitigatedIndex"] == 0)]
    for _, gap in unmitigated_fvg.tail(5).iterrows():
        if gap.get("FVG") == 1 and gap["Bottom"] <= price <= gap["Top"] * 1.02:
            bull_score += 1
            reasons.append("Price near an unfilled bullish fair value gap")
        elif gap.get("FVG") == -1 and gap["Bottom"] * 0.98 <= price <= gap["Top"]:
            bear_score += 1
            reasons.append("Price near an unfilled bearish fair value gap")

    # 4) Premium/discount positioning
    zone, swing_hi, swing_lo = _current_zone(ohlc, swings)
    if zone == "discount":
        bull_score += 1
        reasons.append("Price is in the discount zone of recent range")
    elif zone == "premium":
        bear_score += 1
        reasons.append("Price is in the premium zone of recent range")

    if bull_score == bear_score or max(bull_score, bear_score) < config.MIN_SCORE_TO_ALERT:
        return Signal(symbol=symbol, direction="NO TRADE", score=max(bull_score, bear_score), reasons=reasons)

    direction = "LONG" if bull_score > bear_score else "SHORT"
    score = max(bull_score, bear_score)

    # Risk levels: stop beyond the most recent opposite swing, target at the far side of range
    recent_swings = swings.dropna(subset=["Level"]).tail(10)
    if direction == "LONG":
        lows = recent_swings[recent_swings["HighLow"] == -1]["Level"]
        stop = float(lows.min()) * 0.995 if not lows.empty else price * 0.97
        target = float(swing_hi) if swing_hi else price * 1.05
    else:
        highs = recent_swings[recent_swings["HighLow"] == 1]["Level"]
        stop = float(highs.max()) * 1.005 if not highs.empty else price * 1.03
        target = float(swing_lo) if swing_lo else price * 0.95

    risk = abs(price - stop)
    reward = abs(target - price)
    rr = round(reward / risk, 2) if risk > 0 else None

    win_rate, samples = backtest_setup(ohlc, direction)

    return Signal(
        symbol=symbol,
        direction=direction,
        score=score,
        reasons=reasons,
        entry=round(float(price), 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_reward=rr,
        win_rate=win_rate,
        sample_size=samples,
    )


def backtest_setup(ohlc: pd.DataFrame, direction: str):
    """
    Simplified historical proxy: for every past bar where the same structure
    direction (BOS/CHoCH) plus zone condition matched today's setup, check
    whether price moved favorably over the next N bars. Returns None if too
    few historical occurrences exist -- an honest "not enough data" instead
    of a made-up number.
    """
    swings = smc.swing_highs_lows(ohlc, swing_length=config.SWING_LENGTH)
    structure = smc.bos_choch(ohlc, swings, close_break=True)

    target_val = 1 if direction == "LONG" else -1
    hits = structure[(structure["BOS"] == target_val) | (structure["CHOCH"] == target_val)]

    wins, total = 0, 0
    closes = ohlc["close"].values
    for pos in hits.index:
        # smartmoneyconcepts returns a positional (0..n-1) index aligned to
        # row order in `ohlc`, not a date label — so `pos` IS the row
        # position already; no lookup needed (and ohlc.index.get_loc(pos)
        # was wrong here since ohlc.index holds dates, not integers).
        if pos + config.BACKTEST_FORWARD_BARS >= len(closes):
            continue
        entry_price = closes[pos]
        future_price = closes[pos + config.BACKTEST_FORWARD_BARS]
        favorable = (future_price > entry_price) if direction == "LONG" else (future_price < entry_price)
        total += 1
        wins += int(favorable)

    if total < config.BACKTEST_MIN_SAMPLES:
        return None, total
    return round(100 * wins / total, 1), total
