"""CLI reliability integration tests (Task 8)."""

from __future__ import annotations

from typer.testing import CliRunner

from stockpilot.cli import app
from reliability_fakes import gateway_returning_stale_analysis_data


def test_analyze_prints_stale_warning(monkeypatch):
    monkeypatch.setattr(
        "stockpilot.cli.build_default_data_gateway",
        lambda: gateway_returning_stale_analysis_data(),
    )
    result = CliRunner().invoke(app, ["analyze", "AAPL", "--market", "us"])
    assert result.exit_code == 0, result.stdout
    assert "Using stale cached data" in result.stdout
