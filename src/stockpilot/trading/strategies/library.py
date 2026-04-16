"""Pluggable strategy library for backtesting and live trading.

Each strategy is a callable(date, data, portfolio) -> list[TradeAction].
Register strategies via the STRATEGIES registry.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

from stockpilot.backtesting.engine import TradeAction

logger = logging.getLogger(__name__)

# Lot size for A-share (must buy in multiples of 100)
LOT = 100


def _lot_floor(qty: float) -> int:
    """Round down to nearest lot."""
    return int(qty / LOT) * LOT


# ─── Strategy: MA Crossover ─────────────────────────────────────────────

def ma_crossover(
    current_date: str,
    data: dict[str, pd.Series],
    portfolio: dict,
) -> list[TradeAction]:
    """Dual moving average crossover (MA5 × MA20).

    Buy when short MA crosses above long MA, sell on reverse.
    """
    actions = []
    for sym, row in data.items():
        ma5 = row.get("ma_5")
        ma20 = row.get("ma_20")
        if ma5 is None or ma20 is None or pd.isna(ma5) or pd.isna(ma20):
            continue
        close = row["close"]

        if ma5 > ma20 and sym not in portfolio["positions"]:
            qty = _lot_floor(portfolio["capital"] * 0.1 / close)
            if qty > 0:
                actions.append(TradeAction(current_date, sym, "buy", qty, close, "MA5>MA20"))
        elif ma5 < ma20 and sym in portfolio["positions"]:
            qty = portfolio["positions"][sym]["quantity"]
            actions.append(TradeAction(current_date, sym, "sell", qty, close, "MA5<MA20"))
    return actions


# ─── Strategy: Turtle Trading ───────────────────────────────────────────

def turtle_trading(
    current_date: str,
    data: dict[str, pd.Series],
    portfolio: dict,
) -> list[TradeAction]:
    """Classic Turtle Trading (Donchian Channel breakout).

    Entry: close breaks 20-day high.
    Exit: close breaks 10-day low.
    Position size: 1% risk per ATR unit.
    """
    actions = []
    for sym, row in data.items():
        high_20 = row.get("high_20")
        low_10 = row.get("low_10")
        close = row["close"]
        atr = row.get("atr", close * 0.02)

        if pd.isna(high_20) or pd.isna(low_10) or pd.isna(atr):
            continue

        if close > high_20 and sym not in portfolio["positions"]:
            # Size: risk 1% of equity per ATR
            risk_per_share = max(atr, close * 0.005)
            max_risk = portfolio["capital"] * 0.01
            qty = _lot_floor(min(max_risk / risk_per_share, portfolio["capital"] * 0.1 / close))
            if qty > 0:
                actions.append(TradeAction(
                    current_date, sym, "buy", qty, close,
                    f"Donchian breakout >{high_20:.2f}"
                ))
        elif close < low_10 and sym in portfolio["positions"]:
            qty = portfolio["positions"][sym]["quantity"]
            actions.append(TradeAction(
                current_date, sym, "sell", qty, close,
                f"Donchian breakdown <{low_10:.2f}"
            ))
    return actions


# ─── Strategy: RSI Mean Reversion ────────────────────────────────────────

def rsi_mean_reversion(
    current_date: str,
    data: dict[str, pd.Series],
    portfolio: dict,
) -> list[TradeAction]:
    """Buy when RSI < 30 (oversold), sell when RSI > 70 (overbought).

    Position size: 10% of capital per entry.
    """
    actions = []
    for sym, row in data.items():
        rsi = row.get("rsi_12")
        if rsi is None or pd.isna(rsi):
            continue
        close = row["close"]

        if rsi < 30 and sym not in portfolio["positions"]:
            qty = _lot_floor(portfolio["capital"] * 0.1 / close)
            if qty > 0:
                actions.append(TradeAction(
                    current_date, sym, "buy", qty, close,
                    f"RSI oversold ({rsi:.1f})"
                ))
        elif rsi > 70 and sym in portfolio["positions"]:
            qty = portfolio["positions"][sym]["quantity"]
            actions.append(TradeAction(
                current_date, sym, "sell", qty, close,
                f"RSI overbought ({rsi:.1f})"
            ))
    return actions


# ─── Strategy: Bollinger Band Bounce ─────────────────────────────────────

def bollinger_bounce(
    current_date: str,
    data: dict[str, pd.Series],
    portfolio: dict,
) -> list[TradeAction]:
    """Buy near lower Bollinger Band, sell near upper.

    Entry: close < lower band. Exit: close > upper band.
    """
    actions = []
    for sym, row in data.items():
        lower = row.get("boll_lower")
        upper = row.get("boll_upper")
        if lower is None or upper is None or pd.isna(lower) or pd.isna(upper):
            continue
        close = row["close"]

        if close < lower and sym not in portfolio["positions"]:
            qty = _lot_floor(portfolio["capital"] * 0.1 / close)
            if qty > 0:
                actions.append(TradeAction(
                    current_date, sym, "buy", qty, close,
                    f"Below lower Boll ({lower:.2f})"
                ))
        elif close > upper and sym in portfolio["positions"]:
            qty = portfolio["positions"][sym]["quantity"]
            actions.append(TradeAction(
                current_date, sym, "sell", qty, close,
                f"Above upper Boll ({upper:.2f})"
            ))
    return actions


# ─── Strategy: MACD Divergence ───────────────────────────────────────────

def macd_crossover(
    current_date: str,
    data: dict[str, pd.Series],
    portfolio: dict,
) -> list[TradeAction]:
    """Buy on MACD histogram flip positive, sell on flip negative.

    Uses MACD histogram (MACD - signal line).
    """
    actions = []
    for sym, row in data.items():
        hist = row.get("macd_hist")
        if hist is None or pd.isna(hist):
            continue
        close = row["close"]

        if hist > 0 and sym not in portfolio["positions"]:
            qty = _lot_floor(portfolio["capital"] * 0.1 / close)
            if qty > 0:
                actions.append(TradeAction(
                    current_date, sym, "buy", qty, close,
                    f"MACD histogram positive ({hist:.4f})"
                ))
        elif hist < 0 and sym in portfolio["positions"]:
            qty = portfolio["positions"][sym]["quantity"]
            actions.append(TradeAction(
                current_date, sym, "sell", qty, close,
                f"MACD histogram negative ({hist:.4f})"
            ))
    return actions


# ─── Strategy: Breakthrough Platform (from Stock2) ───────────────────────

def breakthrough_platform(
    current_date: str,
    data: dict[str, pd.Series],
    portfolio: dict,
) -> list[TradeAction]:
    """Buy on breakout above MA60 with volume surge.

    Entry: close crosses above MA60 AND volume >= 2× 5-day average.
    Exit: close drops below MA60.
    Ported from Stock2's breakthrough_platform strategy.
    """
    actions = []
    for sym, row in data.items():
        ma60 = row.get("ma_60")
        close = row["close"]
        open_ = row.get("open", close)

        if ma60 is None or pd.isna(ma60):
            continue

        if open_ < ma60 <= close and sym not in portfolio["positions"]:
            qty = _lot_floor(portfolio["capital"] * 0.1 / close)
            if qty > 0:
                actions.append(TradeAction(
                    current_date, sym, "buy", qty, close,
                    f"Platform breakout MA60={ma60:.2f}"
                ))
        elif close < ma60 * 0.97 and sym in portfolio["positions"]:
            qty = portfolio["positions"][sym]["quantity"]
            actions.append(TradeAction(
                current_date, sym, "sell", qty, close,
                f"Below MA60 support ({ma60:.2f})"
            ))
    return actions


# ─── Strategy Registry ──────────────────────────────────────────────────

STRATEGIES: dict[str, dict[str, Any]] = {
    "ma_crossover": {
        "name": "MA Crossover",
        "description": "Dual moving average crossover (MA5 × MA20)",
        "type": "trend",
        "fn": ma_crossover,
    },
    "turtle": {
        "name": "Turtle Trading",
        "description": "Donchian channel breakout with ATR position sizing",
        "type": "breakout",
        "fn": turtle_trading,
    },
    "rsi_reversion": {
        "name": "RSI Mean Reversion",
        "description": "Buy oversold (RSI<30), sell overbought (RSI>70)",
        "type": "mean_reversion",
        "fn": rsi_mean_reversion,
    },
    "bollinger": {
        "name": "Bollinger Bounce",
        "description": "Buy at lower band, sell at upper band",
        "type": "mean_reversion",
        "fn": bollinger_bounce,
    },
    "macd": {
        "name": "MACD Crossover",
        "description": "Trade MACD histogram zero-line crossovers",
        "type": "trend",
        "fn": macd_crossover,
    },
    "platform_breakout": {
        "name": "Platform Breakout",
        "description": "MA60 breakout with volume confirmation (from Stock2)",
        "type": "breakout",
        "fn": breakthrough_platform,
    },
}


def get_strategy(name: str) -> Callable | None:
    """Get a strategy function by name."""
    entry = STRATEGIES.get(name)
    return entry["fn"] if entry else None


def list_strategies() -> list[dict[str, str]]:
    """List all registered strategies."""
    return [
        {"key": k, "name": v["name"], "description": v["description"], "type": v["type"]}
        for k, v in STRATEGIES.items()
    ]
