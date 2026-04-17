import sqlite3
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from stockpilot.data.adapters import BaseDataAdapter, Market, TimeFrame
from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter
from stockpilot.data.errors import (
    CallerDataError,
    CoverageEmptyData,
    DisabledDataSourceError,
    SourceResponseError,
)
from stockpilot.data.manager import DataManager
from stockpilot.data.reliability.gateway import DataGateway
from stockpilot.data.reliability.registry import SourceRegistry
from stockpilot.data.reliability.shield import ReliabilityShield, make_cache_key
from stockpilot.data.reliability.store import ReliabilityStore, _utc_now_iso, _add_seconds
from stockpilot.data.reliability.types import (
    CacheClass,
    DomainId,
    DomainRequest,
    ResultKind,
    SourceHealthState,
)
from stockpilot.data.runtime import build_default_data_gateway


# ---------------------------------------------------------------- legacy tests


def test_yfinance_fundamentals_raise_coverage_empty(monkeypatch):
    class FakeTicker:
        info = {}

    adapter = YFinanceAdapter()
    monkeypatch.setattr(
        "stockpilot.data.adapters.yfinance_adapter.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    with pytest.raises(CoverageEmptyData):
        adapter.get_fundamental_data("AAPL")


def test_unsupported_market_maps_to_disabled_source():
    adapter = AKShareAdapter()
    with pytest.raises(DisabledDataSourceError):
        adapter.get_stock_list(Market.US)


# --------------------------------------------------------- test helpers


class _PriceSuccessAdapter(BaseDataAdapter):
    name = "akshare"
    supported_markets = [Market.A_SHARE]

    def __init__(self, name: str = "akshare", market: Market = Market.A_SHARE) -> None:
        self.name = name
        self.supported_markets = [market]

    def get_stock_list(self, market: Market = Market.A_SHARE) -> pd.DataFrame:
        return pd.DataFrame([{"symbol": "000001", "name": "x"}])

    def get_price_history(
        self,
        symbol,
        start_date=None,
        end_date=None,
        timeframe=TimeFrame.DAILY,
        adjust="qfq",
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": "2026-04-17",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 100,
                }
            ]
        )

    def get_realtime_quote(self, symbol):
        return {"symbol": symbol, "price": 10.5}

    def get_realtime_quotes(self, symbols):
        return pd.DataFrame([{"symbol": s, "price": 10.5} for s in symbols])

    def get_fundamental_data(self, symbol):
        return {"symbol": symbol, "pe_ratio": 10}

    def search(self, keyword):
        return [{"symbol": "000001", "name": "x"}]


class _FailingAdapter(_PriceSuccessAdapter):
    def get_price_history(self, *args, **kwargs):
        raise SourceResponseError("boom")

    def get_realtime_quote(self, symbol):
        raise SourceResponseError("boom")

    def get_stock_list(self, market=Market.A_SHARE):
        raise SourceResponseError("boom")


class _EmptyPriceAdapter(_PriceSuccessAdapter):
    def get_price_history(self, *args, **kwargs):
        return pd.DataFrame()


class _EmptyQuoteAdapter(_PriceSuccessAdapter):
    def get_realtime_quote(self, symbol):
        return {}


class _EmptySearchAdapter(_PriceSuccessAdapter):
    def search(self, keyword):
        return []


class _EmptyStockListAdapter(_PriceSuccessAdapter):
    def get_stock_list(self, market=Market.A_SHARE):
        return pd.DataFrame()


class _FundamentalsEmptyAdapter(_PriceSuccessAdapter):
    def get_fundamental_data(self, symbol):
        raise CoverageEmptyData("no fundamentals")


class _PartialQuotesAdapter(_PriceSuccessAdapter):
    def get_realtime_quotes(self, symbols):
        # Only return the first symbol
        if not symbols:
            return pd.DataFrame()
        return pd.DataFrame([{"symbol": symbols[0], "price": 10.5}])


def _build_gateway(tmp_path, adapters, source_order=None):
    if source_order is None:
        # Default: first adapter claims all domains for a_share
        names = [a.name for a in adapters]
        source_order = {
            "price_history": {"a_share": names, "us": ["yfinance"]},
            "realtime_quote": {"a_share": names, "us": ["yfinance"]},
            "realtime_quotes": {"a_share": names, "us": ["yfinance"]},
            "fundamental_data": {"a_share": names, "us": ["yfinance"]},
            "stock_list": {"a_share": names, "us": ["yfinance"]},
            "search": {"a_share": names, "us": ["yfinance"]},
        }
    store = ReliabilityStore(tmp_path / "rel.sqlite3")
    registry = SourceRegistry(source_order)
    manager = DataManager()
    for a in adapters:
        manager.register_adapter(a, priority=True)
    shield = ReliabilityShield(data_manager=manager, registry=registry, store=store)
    return DataGateway(shield=shield)


def gateway_with_successful_price_adapter(tmp_path):
    return _build_gateway(tmp_path, [_PriceSuccessAdapter()])


def gateway_with_partial_quote_adapter(tmp_path):
    return _build_gateway(tmp_path, [_PartialQuotesAdapter()])


def gateway_with_empty_price_history_and_stale_cache(tmp_path):
    # Seed the store with a stale cache entry, then use an empty-returning adapter.
    gateway = _build_gateway(tmp_path, [_EmptyPriceAdapter()])
    store = gateway.shield.store
    req = gateway.build_price_history_request(
        "000001",
        Market.A_SHARE,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    cache_key = make_cache_key(req)
    now_iso = _utc_now_iso()
    # stale window: fetched far in the past but stale_until still in the future
    store.put_cache_entry(
        cache_key=cache_key,
        domain=req.domain.value,
        market=req.market,
        adapter="akshare",
        request_params_json=cache_key,
        subject_key="subj",
        payload_format="records",
        payload=[{"date": "2026-01-01", "close": 9.9}],
        result_kind="data",
        meta={},
        fetched_at=_add_seconds(now_iso, -7200),
        fresh_until=_add_seconds(now_iso, -3600),
        stale_until=_add_seconds(now_iso, 3600),
    )
    return gateway


def gateway_with_empty_quote(tmp_path):
    return _build_gateway(tmp_path, [_EmptyQuoteAdapter()])


def gateway_with_empty_search(tmp_path):
    return _build_gateway(tmp_path, [_EmptySearchAdapter()])


def gateway_with_empty_stock_list(tmp_path):
    return _build_gateway(tmp_path, [_EmptyStockListAdapter()])


def gateway_with_cooling_down_source(tmp_path):
    gateway = _build_gateway(tmp_path, [_FailingAdapter()])
    store = gateway.shield.store
    now_iso = _utc_now_iso()
    # Push errors past the cool_down threshold to force cooling_down state.
    for _ in range(4):
        store.record_source_failure(
            "akshare", DomainId.PRICE_HISTORY.value, "a_share", "transient", now_iso
        )
    return gateway


# -------------------------------------------------------------------- tests


def test_gateway_returns_stale_when_live_fetch_fails_but_cache_is_valid(tmp_path):
    # Successful adapter writes a fresh entry, then swap adapter to one that fails.
    success = _PriceSuccessAdapter()
    gateway = _build_gateway(tmp_path, [success])
    result = gateway.get_price_history(
        "000001",
        Market.A_SHARE,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    assert result.status == "fresh"

    # Now rewrite the cache to be stale (not fresh) by shifting fresh_until back.
    store = gateway.shield.store
    cache_key = result.cache_key
    stored = store.get_cache_entry(cache_key)
    assert stored is not None
    now_iso = _utc_now_iso()
    store.put_cache_entry(
        cache_key=cache_key,
        domain=stored.domain,
        market=stored.market,
        adapter=stored.adapter,
        request_params_json=stored.request_params_json,
        subject_key=stored.subject_key,
        payload_format=stored.payload_format,
        payload=stored.payload,
        result_kind=stored.result_kind,
        meta={},
        fetched_at=_add_seconds(now_iso, -7200),
        fresh_until=_add_seconds(now_iso, -3600),
        stale_until=_add_seconds(now_iso, 3600),
    )

    # Replace adapter with a failing one.
    gateway.shield.data_manager._adapters["akshare"] = _FailingAdapter()
    result2 = gateway.get_price_history(
        "000001",
        Market.A_SHARE,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    assert result2.status == "stale"
    assert result2.served_from_cache is True
    assert result2.source.startswith("cache:")


def test_gateway_rejects_non_configured_adapter_override(tmp_path):
    gateway = _build_gateway(
        tmp_path,
        [_PriceSuccessAdapter()],
        source_order={
            "price_history": {"a_share": ["akshare"]},
        },
    )
    result = gateway.get_price_history(
        "000001",
        Market.A_SHARE,
        adapter_name="yfinance",
    )
    assert result.error is not None
    assert result.error.code == "DATA_REQUEST_INVALID"
    assert result.error.http_status == 400


def test_gateway_builds_normalized_unavailable_error(tmp_path):
    gateway = _build_gateway(tmp_path, [_FailingAdapter()])
    result = gateway.get_price_history("000001", Market.A_SHARE)
    assert result.error is not None
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"
    assert result.error.domain == "price_history"
    assert result.error.http_status == 503


def test_gateway_marks_batch_as_dataset_incomplete_when_require_complete_is_true(tmp_path):
    gateway = gateway_with_partial_quote_adapter(tmp_path)
    result = gateway.get_realtime_quotes(
        ["000001", "000002"],
        Market.A_SHARE,
        require_complete=True,
    )
    assert result.error is not None
    assert result.error.code == "DATASET_INCOMPLETE"
    assert "000002" in result.error.missing_symbols


def test_gateway_uses_adapter_name_in_cache_key(tmp_path):
    gateway = _build_gateway(tmp_path, [_PriceSuccessAdapter()])
    req_auto = gateway.build_price_history_request("000001", Market.A_SHARE)
    req_explicit = gateway.build_price_history_request(
        "000001", Market.A_SHARE, adapter_name="akshare"
    )
    assert make_cache_key(req_auto) != make_cache_key(req_explicit)


def test_gateway_respects_registry_market_policy_before_adapter_capability(tmp_path):
    a = _PriceSuccessAdapter(name="akshare")
    b = _PriceSuccessAdapter(name="yfinance")
    gateway = _build_gateway(
        tmp_path,
        [a, b],
        source_order={
            "price_history": {"a_share": ["akshare"]},
        },
    )
    result = gateway.get_price_history("000001", Market.A_SHARE)
    assert result.source == "akshare"


def test_gateway_classifies_today_request_as_session_series(tmp_path):
    gateway = _build_gateway(tmp_path, [_PriceSuccessAdapter()])
    today = date.today().isoformat()
    # Pretend now is 10:30 Beijing time on a weekday
    # Use a known weekday
    now_override = "2026-04-17T10:30:00"  # Friday 2026-04-17 is a weekday
    req = gateway.build_price_history_request(
        "000001",
        Market.A_SHARE,
        start_date="2026-04-17",
        end_date="2026-04-17",
        now_override=now_override,
    )
    assert req.cache_class == CacheClass.SESSION_SERIES


def test_gateway_classifies_after_hours_and_weekend_requests_as_historical_series(tmp_path):
    gateway = _build_gateway(tmp_path, [_PriceSuccessAdapter()])
    # After hours on a weekday
    req_after = gateway.build_price_history_request(
        "000001",
        Market.A_SHARE,
        start_date="2026-04-17",
        end_date="2026-04-17",
        now_override="2026-04-17T20:00:00",
    )
    assert req_after.cache_class == CacheClass.HISTORICAL_SERIES

    # Weekend (2026-04-18 is a Saturday)
    req_weekend = gateway.build_price_history_request(
        "000001",
        Market.A_SHARE,
        start_date="2026-04-18",
        end_date="2026-04-18",
        now_override="2026-04-18T10:30:00",
    )
    assert req_weekend.cache_class == CacheClass.HISTORICAL_SERIES


def test_gateway_time_zone_failure_falls_back_to_historical_series(tmp_path, monkeypatch):
    gateway = _build_gateway(tmp_path, [_PriceSuccessAdapter()])

    def raiser(*args, **kwargs):
        raise RuntimeError("no tz")

    monkeypatch.setattr(gateway.shield, "_market_now", raiser)
    req = gateway.build_price_history_request(
        "000001",
        Market.A_SHARE,
        start_date="2026-04-17",
        end_date="2026-04-17",
    )
    assert req.cache_class == CacheClass.HISTORICAL_SERIES


def test_price_history_all_empty_does_not_substitute_stale_cache(tmp_path):
    gateway = gateway_with_empty_price_history_and_stale_cache(tmp_path)
    result = gateway.get_price_history(
        "000001",
        Market.A_SHARE,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    assert result.status == "fresh"
    assert result.result_kind == ResultKind.EMPTY


def test_realtime_quote_empty_is_invalid(tmp_path):
    gateway = gateway_with_empty_quote(tmp_path)
    result = gateway.get_realtime_quote("000001", Market.A_SHARE)
    assert result.error is not None
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"


def test_search_empty_is_valid(tmp_path):
    gateway = gateway_with_empty_search(tmp_path)
    result = gateway.search("no-match", Market.A_SHARE)
    assert result.status == "fresh"
    assert result.result_kind == ResultKind.EMPTY


def test_fundamentals_coverage_empty_maps_to_fresh_empty(tmp_path):
    gateway = _build_gateway(tmp_path, [_FundamentalsEmptyAdapter()])
    result = gateway.get_fundamental_data("AAPL", Market.A_SHARE)
    assert result.status == "fresh"
    assert result.result_kind == ResultKind.EMPTY


def test_stock_list_empty_is_invalid(tmp_path):
    gateway = gateway_with_empty_stock_list(tmp_path)
    result = gateway.get_stock_list(Market.A_SHARE)
    assert result.error is not None
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"


def test_gateway_stays_unavailable_while_source_is_cooling_down(tmp_path):
    gateway = gateway_with_cooling_down_source(tmp_path)
    # First request: probe begins, adapter still fails, so unavailable.
    first = gateway.get_price_history("000001", Market.A_SHARE)
    assert first.error is not None
    assert first.error.code == "DATA_SOURCE_UNAVAILABLE"

    # Second request should be skipped due to cooling_down / recent probe.
    second = gateway.get_price_history("000001", Market.A_SHARE)
    assert second.error is not None
    assert second.error.code == "DATA_SOURCE_UNAVAILABLE"


def test_build_default_data_gateway_falls_back_to_stateless_store(monkeypatch):
    def _explode(*args, **kwargs):
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(
        "stockpilot.data.runtime.ReliabilityStore",
        _explode,
    )
    gateway = build_default_data_gateway()
    assert gateway.shield.store.stateless is True
