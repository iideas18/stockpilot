"""Backtesting engine — run historical strategy simulations.

Ported from AI Hedge Fund's backtesting/engine.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 1_000_000
    commission_rate: float = 0.0003
    slippage_rate: float = 0.001
    max_position_pct: float = 0.1


@dataclass
class TradeAction:
    date: str
    symbol: str
    action: str  # buy | sell
    quantity: int
    price: float
    reason: str = ""


@dataclass
class BacktestMetrics:
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    calmar_ratio: float = 0.0
    final_capital: float = 0.0


class BacktestEngine:
    """Historical strategy backtesting engine.

    Usage:
        engine = BacktestEngine(config)
        engine.add_data("000001", price_df)

        def my_strategy(date, data, portfolio):
            if data["rsi_12"] < 30:
                return [TradeAction(date, "000001", "buy", 100, data["close"])]
            return []

        result = engine.run(my_strategy)
        print(result.metrics)
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self._data: dict[str, pd.DataFrame] = {}
        self._capital = self.config.initial_capital
        self._positions: dict[str, dict] = {}
        self._trades: list[TradeAction] = []
        self._closed_trade_pnls: list[float] = []
        self._closed_trade_returns: list[float] = []
        self._equity_curve: list[float] = []
        self._dates: list[str] = []

    def add_data(self, symbol: str, df: pd.DataFrame) -> None:
        """Add price data for a symbol. Expects columns: date, open, high, low, close, volume."""
        df = df.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.set_index("date")
        self._data[symbol] = df.sort_index()

    def run(
        self,
        strategy: Callable[[str, dict[str, pd.Series], dict], list[TradeAction]],
    ) -> BacktestResult:
        """Run the backtest with the given strategy function.

        Args:
            strategy: Function(date, data_dict, portfolio) -> list[TradeAction]
                      data_dict maps symbol -> row Series for that date
                      portfolio has: capital, positions, equity
        """
        # Collect all unique dates
        all_dates = sorted(set(
            d for df in self._data.values() for d in df.index
            if self.config.start_date <= d <= self.config.end_date
        ))

        self._capital = self.config.initial_capital
        self._positions = {}
        self._trades = []
        self._closed_trade_pnls = []
        self._closed_trade_returns = []
        self._equity_curve = []
        self._dates = []

        for current_date in all_dates:
            data_for_date = {}
            for symbol, df in self._data.items():
                if current_date in df.index:
                    data_for_date[symbol] = df.loc[current_date]

            if not data_for_date:
                continue

            portfolio = {
                "capital": self._capital,
                "positions": dict(self._positions),
                "equity": self._calculate_equity(data_for_date),
            }

            try:
                actions = strategy(current_date, data_for_date, portfolio)
                for action in actions:
                    self._execute_trade(action)
            except Exception as e:
                logger.warning("Strategy error on %s: %s", current_date, e)

            equity = self._calculate_equity(data_for_date)
            self._equity_curve.append(equity)
            self._dates.append(current_date)

        metrics = self._calculate_metrics()
        return BacktestResult(
            config=self.config,
            metrics=metrics,
            trades=list(self._trades),
            equity_curve=list(self._equity_curve),
            dates=list(self._dates),
        )

    def _execute_trade(self, action: TradeAction) -> None:
        """Execute a simulated trade."""
        slippage = action.price * self.config.slippage_rate
        commission = action.price * action.quantity * self.config.commission_rate

        if action.action == "buy":
            exec_price = action.price + slippage
            cost = exec_price * action.quantity + commission
            if cost > self._capital:
                return

            self._capital -= cost
            pos = self._positions.get(action.symbol, {"quantity": 0, "avg_cost": 0, "total_cost": 0})
            new_qty = pos["quantity"] + action.quantity
            pos["total_cost"] = pos.get("total_cost", 0) + cost
            pos["avg_cost"] = pos["total_cost"] / new_qty if new_qty > 0 else 0
            pos["quantity"] = new_qty
            self._positions[action.symbol] = pos

        elif action.action == "sell":
            pos = self._positions.get(action.symbol)
            if not pos or pos["quantity"] < action.quantity:
                return

            exec_price = action.price - slippage
            proceeds = exec_price * action.quantity - commission
            avg_cost = pos["avg_cost"]
            if avg_cost > 0 and action.quantity > 0:
                net_exit_price = proceeds / action.quantity
                realized_pnl = (net_exit_price - avg_cost) * action.quantity
                realized_return = (net_exit_price - avg_cost) / avg_cost
                self._closed_trade_pnls.append(realized_pnl)
                self._closed_trade_returns.append(realized_return)
            self._capital += proceeds

            pos["quantity"] -= action.quantity
            if pos["quantity"] <= 0:
                del self._positions[action.symbol]
            else:
                pos["total_cost"] = pos["avg_cost"] * pos["quantity"]
                self._positions[action.symbol] = pos

        self._trades.append(action)

    def _calculate_equity(self, current_data: dict[str, pd.Series]) -> float:
        equity = self._capital
        for symbol, pos in self._positions.items():
            if symbol in current_data:
                price = current_data[symbol].get("close", pos["avg_cost"])
                equity += price * pos["quantity"]
            else:
                equity += pos["avg_cost"] * pos["quantity"]
        return equity

    def _calculate_metrics(self) -> BacktestMetrics:
        if not self._equity_curve:
            return BacktestMetrics(final_capital=self._capital)

        equity = np.array(self._equity_curve)
        initial = self.config.initial_capital
        final = equity[-1]

        # Returns
        total_return = (final - initial) / initial
        n_days = len(equity)
        annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1 if n_days > 0 else 0

        # Sharpe ratio
        daily_returns = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0])
        sharpe = np.sqrt(252) * np.mean(daily_returns) / np.std(daily_returns) if np.std(daily_returns) > 0 else 0

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0

        closed_trade_pnls = np.array(self._closed_trade_pnls, dtype=float)
        closed_trade_returns = np.array(self._closed_trade_returns, dtype=float)
        winning = int(np.sum(closed_trade_pnls > 0))
        losing = int(np.sum(closed_trade_pnls < 0))
        closed_total = len(closed_trade_pnls)
        win_rate = winning / closed_total if closed_total > 0 else 0
        avg_win_pct = (
            float(np.mean(closed_trade_returns[closed_trade_pnls > 0]) * 100)
            if winning
            else 0.0
        )
        avg_loss_pct = (
            float(np.mean(closed_trade_returns[closed_trade_pnls < 0]) * 100)
            if losing
            else 0.0
        )
        gross_profit = float(np.sum(closed_trade_pnls[closed_trade_pnls > 0])) if winning else 0.0
        gross_loss = float(-np.sum(closed_trade_pnls[closed_trade_pnls < 0])) if losing else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        total = len(self._trades)

        # Calmar ratio
        calmar = annual_return / max_drawdown if max_drawdown > 0 else 0

        return BacktestMetrics(
            total_return_pct=round(total_return * 100, 2),
            annual_return_pct=round(annual_return * 100, 2),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown_pct=round(max_drawdown * 100, 2),
            win_rate=round(win_rate, 4),
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            avg_win_pct=round(avg_win_pct, 2),
            avg_loss_pct=round(avg_loss_pct, 2),
            profit_factor=round(profit_factor, 3),
            calmar_ratio=round(calmar, 3),
            final_capital=round(final, 2),
        )


@dataclass
class BacktestResult:
    config: BacktestConfig
    metrics: BacktestMetrics
    trades: list[TradeAction] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)

    def summary(self) -> str:
        m = self.metrics
        return f"""Backtest Results:
  Period: {self.config.start_date} to {self.config.end_date}
  Initial Capital: ¥{self.config.initial_capital:,.0f}
  Final Capital:   ¥{m.final_capital:,.0f}
  Total Return:    {m.total_return_pct:+.2f}%
  Annual Return:   {m.annual_return_pct:+.2f}%
  Sharpe Ratio:    {m.sharpe_ratio:.3f}
  Max Drawdown:    {m.max_drawdown_pct:.2f}%
  Calmar Ratio:    {m.calmar_ratio:.3f}
  Total Trades:    {m.total_trades}"""
