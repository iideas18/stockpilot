"""Contract tests for single-resource API routes wired to the gateway."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stockpilot.api import main as api_main

from reliability_fakes import (
    gateway_with_compare_results,
    gateway_with_empty_required_symbol,
    gateway_with_empty_result,
    gateway_with_invalid_request,
    gateway_with_invalid_required_symbol,
    gateway_with_partial_quotes_batch,
    gateway_with_partial_required_symbol,
    gateway_with_realtime_quotes_batch,
    gateway_with_stale_single_result,
    gateway_with_unavailable_quotes_batch,
    gateway_with_unavailable_required_symbol,
    gateway_with_unavailable_single_result,
)


def test_price_route_includes_data_status(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_stale_single_result(
            domain="price_history", source="cache:yfinance"
        ),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/price?market=us")

    assert response.status_code == 200
    body = response.json()
    ds = body["data_status"]
    assert ds["status"] == "stale"
    assert ds["result_kind"] == "data"
    assert ds["served_from_cache"] is True
    assert ds["source"] == "cache:yfinance"
    assert ds["fetched_at"] == "2026-04-17T09:25:00Z"
    assert ds["age_seconds"] == 600
    assert ds["degraded_reason"] == "live sources unavailable; serving cached payload"
    assert ds["missing_symbols"] == []
    assert ds["attempted_sources"][0]["adapter"] == "yfinance"
    assert ds["attempted_sources"][0]["outcome"] == "error"


def test_chart_data_includes_data_status(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_stale_single_result(
            domain="price_history", source="cache:yfinance"
        ),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/chart-data?days=30&market=us")

    assert response.status_code == 200
    ds = response.json()["data_status"]
    assert ds["status"] == "stale"
    assert ds["source"] == "cache:yfinance"


def test_fundamentals_route_includes_data_status_on_success(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_stale_single_result(
            domain="fundamental_data", source="cache:yfinance"
        ),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/fundamentals?market=us")
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_fundamentals_route_maps_empty_to_404(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_empty_result(domain="fundamental_data"),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/UNKNOWN/fundamentals?market=us")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["status"] == "not_found"
    assert detail["code"] == "DATA_NOT_FOUND"
    assert detail["domain"] == "fundamental_data"
    assert detail["market"] == "us"


def test_fundamentals_route_preserves_invalid_request(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_invalid_request(domain="fundamental_data"),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/fundamentals?market=us")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["status"] == "invalid_request"
    assert detail["code"] == "DATA_REQUEST_INVALID"
    assert detail["domain"] == "fundamental_data"


def test_technical_analysis_route_includes_data_status(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_stale_single_result(
            domain="price_history", source="cache:yfinance"
        ),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/analysis/technical", json={"symbol": "AAPL", "market": "us"}
    )
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_patterns_route_includes_data_status(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_stale_single_result(
            domain="price_history", source="cache:yfinance"
        ),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/analysis/patterns", json={"symbol": "AAPL", "market": "us"}
    )
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_patterns_route_maps_data_not_found_to_404(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_empty_result(domain="price_history"),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/analysis/patterns", json={"symbol": "UNKNOWN", "market": "us"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATA_NOT_FOUND"


def test_chart_data_maps_unavailable_to_503(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_build_data_gateway",
        lambda: gateway_with_unavailable_single_result(domain="price_history"),
        raising=False,
    )
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/chart-data?days=30&market=us")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert detail["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert detail["domain"] == "price_history"
    assert detail["symbol"] == "AAPL"
    assert detail["market"] == "us"
    assert detail["retry_after_seconds"] == 120


def test_compare_route_aggregates_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_compare_results(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})

    assert response.status_code == 200
    ds = response.json()["data_status"]
    assert ds["status"] == "stale"
    assert ds["source"] == "mixed"
    assert ds["result_kind"] == "data"
    assert ds["served_from_cache"] is True
    assert ds["fetched_at"] == "2026-04-17T09:25:00Z"
    assert ds["age_seconds"] == 600
    assert ds["degraded_reason"] == "live sources unavailable; serving cached payload"
    assert ds["missing_symbols"] == []
    assert ds["attempted_sources"] == [
        {"symbol": "AAA", "adapter": "yfinance", "outcome": "success"},
        {"symbol": "BBB", "adapter": "akshare", "outcome": "error", "reason": "ConnectionError"},
    ]


def test_portfolio_route_returns_503_when_required_symbol_is_unavailable(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/portfolio/optimize", json={"symbols": ["AAA", "BBB"], "market": "us"})
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unavailable"
    assert response.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert response.json()["detail"]["symbol"] == "BBB"
    assert response.json()["detail"]["retry_after_seconds"] == 120


def test_compare_route_returns_404_when_required_symbol_is_empty(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_empty_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})
    assert response.status_code == 404
    assert response.json()["detail"]["status"] == "not_found"
    assert response.json()["detail"]["code"] == "DATA_NOT_FOUND"
    assert response.json()["detail"]["symbol"] == "BBB"


def test_compare_route_preserves_invalid_request(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_invalid_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})
    assert response.status_code == 400
    assert response.json()["detail"]["status"] == "invalid_request"
    assert response.json()["detail"]["code"] == "DATA_REQUEST_INVALID"


def test_compare_route_returns_503_when_required_result_is_partial(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_partial_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "dataset_incomplete"
    assert response.json()["detail"]["code"] == "DATASET_INCOMPLETE"
    assert response.json()["detail"]["missing_symbols"] == ["BBB"]


def test_backtest_compare_returns_503_when_required_symbol_is_unavailable(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/backtest/compare",
        json={
            "runs": [
                {"symbol": "AAA", "strategy": "ma_crossover", "market": "us"},
                {"symbol": "BBB", "strategy": "ma_crossover", "market": "us"},
            ],
            "days": 120,
            "initial_capital": 100000,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unavailable"
    assert response.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert response.json()["detail"]["symbol"] == "BBB"
    assert response.json()["detail"]["retry_after_seconds"] == 120


def test_portfolio_route_success_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_compare_results(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/portfolio/optimize", json={"symbols": ["AAA", "BBB"], "market": "us"})
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_backtest_compare_success_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_compare_results(), raising=False)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/backtest/compare",
        json={
            "runs": [
                {"symbol": "AAA", "strategy": "ma_crossover", "market": "us"},
                {"symbol": "BBB", "strategy": "ma_crossover", "market": "us"},
            ],
            "days": 120,
            "initial_capital": 100000,
        },
    )
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_quotes_route_returns_batch_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_realtime_quotes_batch(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/quotes", json={"symbols": ["AAA", "BBB"], "market": "us"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"]["status"] == "fresh"
    assert payload["data_status"]["result_kind"] == "data"
    assert payload["data_status"]["source"] == "yfinance"
    assert payload["data_status"]["missing_symbols"] == []
    assert payload["quotes"] == [
        {"symbol": "AAA", "price": 101.5, "change_pct": 0.42},
        {"symbol": "BBB", "price": 57.0, "change_pct": -0.11},
    ]


def test_quotes_route_returns_partial_batch(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_partial_quotes_batch(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/quotes", json={"symbols": ["AAA", "BBB"], "market": "us"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"]["status"] == "stale"
    assert payload["data_status"]["result_kind"] == "partial"
    assert payload["data_status"]["missing_symbols"] == ["BBB"]
    assert payload["data_status"]["degraded_reason"] == "quote provider returned partial batch"
    assert [q["symbol"] for q in payload["quotes"]] == ["AAA"]


def test_quotes_route_maps_unavailable_to_503(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_quotes_batch(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/quotes", json={"symbols": ["AAA", "BBB"], "market": "us"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert detail["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert detail["domain"] == "realtime_quotes"
    assert detail["market"] == "us"
    assert detail["retry_after_seconds"] == 120
