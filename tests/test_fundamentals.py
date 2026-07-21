import fundamentals


def test_fetch_fundamentals_never_raises_on_network_failure(monkeypatch):
    class FailingTicker:
        def __init__(self, symbol):
            raise ConnectionError("simulated network failure")

    monkeypatch.setattr(fundamentals.yf, "Ticker", FailingTicker)
    result = fundamentals.fetch_fundamentals("ANY.NS")
    assert result is None


def test_fetch_fundamentals_never_raises_on_malformed_response(monkeypatch):
    class BadTicker:
        def __init__(self, symbol):
            self.info = None  # malformed / empty response

    monkeypatch.setattr(fundamentals.yf, "Ticker", BadTicker)
    result = fundamentals.fetch_fundamentals("ANY.NS")
    assert result is None


def test_fetch_fundamentals_returns_none_when_all_fields_empty(monkeypatch):
    class EmptyTicker:
        def __init__(self, symbol):
            self.info = {"symbol": symbol}  # present but none of the fields we want

    monkeypatch.setattr(fundamentals.yf, "Ticker", EmptyTicker)
    result = fundamentals.fetch_fundamentals("ANY.NS")
    assert result is None


def test_fetch_fundamentals_extracts_available_fields(monkeypatch):
    class GoodTicker:
        def __init__(self, symbol):
            self.info = {
                "sector": "Financial Services",
                "industry": "Banks",
                "trailingPE": 18.5,
                "marketCap": 500_000_000_000,
                "debtToEquity": 45.2,
            }

    monkeypatch.setattr(fundamentals.yf, "Ticker", GoodTicker)
    result = fundamentals.fetch_fundamentals("HDFCBANK.NS")
    assert result["sector"] == "Financial Services"
    assert result["pe_ratio"] == 18.5


def test_format_fundamentals_handles_none():
    assert fundamentals.format_fundamentals(None) == ""
    assert fundamentals.format_fundamentals({}) == ""


def test_format_fundamentals_renders_available_fields():
    text = fundamentals.format_fundamentals({
        "sector": "IT", "industry": "Software", "pe_ratio": 25.3,
        "market_cap": 1_000_000_000, "debt_to_equity": 5.0,
    })
    assert "IT" in text
    assert "25.3" in text
