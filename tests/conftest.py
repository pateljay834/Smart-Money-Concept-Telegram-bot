import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import pytest


def make_ohlc(n=750, seed=0, freq="D", drift=0.02, volume_range=(200_000, 800_000)):
    """Deterministic synthetic OHLCV data for tests."""
    np.random.seed(seed)
    dates = pd.date_range("2021-01-01", periods=n, freq=freq)
    price = 100 + np.cumsum(np.random.randn(n) * 0.3 + drift)
    high = price + np.random.rand(n) * 1.5
    low = price - np.random.rand(n) * 1.5
    open_ = price + np.random.randn(n) * 0.4
    close = price + np.random.randn(n) * 0.4
    vol = np.random.randint(volume_range[0], volume_range[1], n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=dates)
    df.index.name = "date"
    return df


@pytest.fixture
def daily_ohlc():
    return make_ohlc(750, seed=16)


@pytest.fixture
def weekly_ohlc():
    return make_ohlc(156, seed=16, freq="W")
