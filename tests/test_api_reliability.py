"""Contract tests for single-resource API routes wired to the gateway."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stockpilot.api import main as api_main

from reliability_fakes import (
    gateway_with_empty_result,
    gateway_with_invalid_request,
    gateway_with_stale_single_result,
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
