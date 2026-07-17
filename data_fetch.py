import time

import pandas as pd
import yfinance as yf


def get_ohlc(symbol: str, interval: str, period: str, retries: int = 2) -> pd.DataFrame:
    """
    Fetch OHLCV data and format it exactly how the smartmoneyconcepts
    library expects: lowercase columns open/high/low/close/volume.

    Retries on transient failures (Yahoo occasionally rate-limits or blips) -
    this is likely why a symbol that worked once failed on a later call.
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            df = yf.download(symbol, interval=interval, period=period, progress=False, auto_adjust=True)

            if df.empty:
                raise ValueError(f"No data returned for '{symbol}'. Check the ticker/suffix (.NS / .BO).")

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.rename(columns=str.lower)
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df.index.name = "date"

            if len(df) < 30:
                raise ValueError(f"Only {len(df)} candles returned for '{symbol}' — not enough history to analyze.")

            return df
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError(f"Failed to fetch data for '{symbol}' after {retries + 1} attempts: {last_err}")
