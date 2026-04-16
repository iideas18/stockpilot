"""Portfolio optimization and multi-stock allocation.

Provides mean-variance optimization, equal-weight, and risk-parity
allocation strategies for building diversified portfolios.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PortfolioAllocation:
    """Result of portfolio optimization."""
    weights: dict[str, float]
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    method: str = "equal_weight"

    def summary(self) -> str:
        lines = [f"Portfolio Allocation ({self.method})"]
        lines.append(f"  Expected Return:     {self.expected_return:+.2%}")
        lines.append(f"  Expected Volatility: {self.expected_volatility:.2%}")
        lines.append(f"  Sharpe Ratio:        {self.sharpe_ratio:.3f}")
        lines.append("  Weights:")
        for sym, w in sorted(self.weights.items(), key=lambda x: -x[1]):
            lines.append(f"    {sym}: {w:.1%}")
        return "\n".join(lines)


class PortfolioOptimizer:
    """Multi-stock portfolio optimizer."""

    def __init__(self, risk_free_rate: float = 0.03):
        self.risk_free_rate = risk_free_rate
        self._returns: dict[str, pd.Series] = {}

    def add_returns(self, symbol: str, prices: pd.Series) -> None:
        """Add daily price data for a symbol. Computes daily returns."""
        returns = prices.pct_change().dropna()
        self._returns[symbol] = returns

    def add_prices_df(self, symbol: str, df: pd.DataFrame) -> None:
        """Add from a DataFrame with 'close' column."""
        if "close" in df.columns:
            self.add_returns(symbol, df["close"])

    @property
    def symbols(self) -> list[str]:
        return list(self._returns.keys())

    def _aligned_returns(self) -> pd.DataFrame:
        """Get aligned returns matrix."""
        if not self._returns:
            return pd.DataFrame()
        return pd.DataFrame(self._returns).dropna()

    def equal_weight(self) -> PortfolioAllocation:
        """Equal-weight allocation."""
        n = len(self.symbols)
        if n == 0:
            return PortfolioAllocation(weights={}, method="equal_weight")

        weights = {s: 1.0 / n for s in self.symbols}
        return self._compute_allocation(weights, "equal_weight")

    def min_variance(self) -> PortfolioAllocation:
        """Minimum variance portfolio (analytical solution)."""
        returns_df = self._aligned_returns()
        if returns_df.empty or len(self.symbols) < 2:
            return self.equal_weight()

        cov = returns_df.cov().values * 252
        n = len(self.symbols)

        try:
            cov_inv = np.linalg.inv(cov)
            ones = np.ones(n)
            w = cov_inv @ ones / (ones @ cov_inv @ ones)
            w = np.maximum(w, 0)  # No short selling
            w = w / w.sum()
        except np.linalg.LinAlgError:
            w = np.ones(n) / n

        weights = {s: float(w[i]) for i, s in enumerate(self.symbols)}
        return self._compute_allocation(weights, "min_variance")

    def max_sharpe(self, n_portfolios: int = 5000) -> PortfolioAllocation:
        """Maximum Sharpe ratio portfolio via Monte Carlo simulation.

        Generates random portfolios and picks the one with highest Sharpe.
        """
        returns_df = self._aligned_returns()
        if returns_df.empty or len(self.symbols) < 2:
            return self.equal_weight()

        n = len(self.symbols)
        mean_returns = returns_df.mean().values * 252
        cov = returns_df.cov().values * 252

        best_sharpe = -np.inf
        best_weights = np.ones(n) / n

        for _ in range(n_portfolios):
            w = np.random.random(n)
            w /= w.sum()

            ret = np.dot(w, mean_returns)
            vol = np.sqrt(w @ cov @ w)
            sharpe = (ret - self.risk_free_rate) / vol if vol > 0 else 0

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_weights = w

        weights = {s: float(best_weights[i]) for i, s in enumerate(self.symbols)}
        return self._compute_allocation(weights, "max_sharpe")

    def risk_parity(self) -> PortfolioAllocation:
        """Risk parity — each asset contributes equally to portfolio risk."""
        returns_df = self._aligned_returns()
        if returns_df.empty or len(self.symbols) < 2:
            return self.equal_weight()

        vols = returns_df.std().values * np.sqrt(252)
        inv_vol = 1.0 / np.maximum(vols, 1e-8)
        w = inv_vol / inv_vol.sum()

        weights = {s: float(w[i]) for i, s in enumerate(self.symbols)}
        return self._compute_allocation(weights, "risk_parity")

    def _compute_allocation(
        self, weights: dict[str, float], method: str
    ) -> PortfolioAllocation:
        """Compute portfolio metrics from weights."""
        returns_df = self._aligned_returns()
        if returns_df.empty:
            return PortfolioAllocation(weights=weights, method=method)

        w = np.array([weights[s] for s in self.symbols])
        mean_returns = returns_df.mean().values * 252
        cov = returns_df.cov().values * 252

        expected_return = float(np.dot(w, mean_returns))
        expected_vol = float(np.sqrt(w @ cov @ w))
        sharpe = (expected_return - self.risk_free_rate) / expected_vol if expected_vol > 0 else 0

        return PortfolioAllocation(
            weights=weights,
            expected_return=expected_return,
            expected_volatility=expected_vol,
            sharpe_ratio=round(sharpe, 4),
            method=method,
        )
