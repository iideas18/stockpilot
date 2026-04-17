"""CLI reliability integration tests (Task 8)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from stockpilot.agents.tools.agent_tools import get_stock_price_history
from stockpilot.cli import app
from reliability_fakes import (
    gateway_returning_stale_analysis_data,
    gateway_returning_stale_history,
)


def test_analyze_prints_stale_warning(monkeypatch):
    monkeypatch.setattr(
        "stockpilot.cli.build_default_data_gateway",
        lambda: gateway_returning_stale_analysis_data(),
    )
    result = CliRunner().invoke(app, ["analyze", "AAPL", "--market", "us"])
    assert result.exit_code == 0, result.stdout
    assert "Using stale cached data" in result.stdout


def test_get_stock_price_history_includes_data_status(monkeypatch):
    monkeypatch.setattr(
        "stockpilot.agents.tools.agent_tools.build_default_data_gateway",
        lambda: gateway_returning_stale_history(),
    )
    payload = json.loads(
        get_stock_price_history.invoke(
            {"symbol": "AAPL", "days": 30, "market": "us"}
        )
    )
    assert payload["data_status"]["status"] == "stale"
    assert "data" in payload
