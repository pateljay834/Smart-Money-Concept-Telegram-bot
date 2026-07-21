"""
Lightweight fundamentals (P/E, sector, market cap) via yfinance's `.info`
endpoint. This is deliberately separated from the core SMC engine — it's
enrichment, not signal. `.info` has been unreliable in testing on this
project (slow, occasional 404s on perfectly valid symbols), so every
function here is designed to NEVER raise and NEVER block the pipeline: a
failure just means the fundamentals section is omitted from the message,
not that the analysis fails.
"""
import logging

import yfinance as yf

log = logging.getLogger("fundamentals")


def fetch_fundamentals(symbol: str) -> dict | None:
    """
    Best-effort fetch. Returns a dict with whichever of these fields yfinance
    actually provided (often incomplete — that's normal, not an error), or
    None if the fetch failed outright. Never raises.
    """
    try:
        info = yf.Ticker(symbol).info
        if not info or not isinstance(info, dict):
            return None
        result = {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "pe_ratio": info.get("trailingPE"),
            "market_cap": info.get("marketCap"),
            "debt_to_equity": info.get("debtToEquity"),
        }
        if not any(result.values()):
            return None
        return result
    except Exception:
        log.warning(f"{symbol}: fundamentals fetch failed (non-fatal, continuing without it)")
        return None


def format_fundamentals(fundamentals: dict) -> str:
    """Render whichever fields are present into a short one-line-per-field block."""
    if not fundamentals:
        return ""
    lines = []
    if fundamentals.get("sector"):
        industry = f" / {fundamentals['industry']}" if fundamentals.get("industry") else ""
        lines.append(f"Sector: {fundamentals['sector']}{industry}")
    if fundamentals.get("market_cap"):
        cap = fundamentals["market_cap"]
        cap_str = f"₹{cap / 1e7:,.0f} Cr" if cap else None
        if cap_str:
            lines.append(f"Market cap: {cap_str}")
    if fundamentals.get("pe_ratio"):
        lines.append(f"P/E (trailing): {fundamentals['pe_ratio']:.1f}")
    if fundamentals.get("debt_to_equity") is not None:
        lines.append(f"Debt/Equity: {fundamentals['debt_to_equity']:.1f}")
    return "\n".join(lines)
