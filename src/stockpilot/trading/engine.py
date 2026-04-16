"""Event-driven trading engine.

Provides an event bus and strategy execution framework.
Ported from Stock2's trade/robot/engine/.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Queue
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    MARKET_DATA = "market_data"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    POSITION = "position"
    TIMER = "timer"
    CUSTOM = "custom"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    """Central event bus for publishing and subscribing to events."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Callable]] = defaultdict(list)
        self._queue: Queue[Event] = Queue()
        self._running = False
        self._thread: threading.Thread | None = None

    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        self._queue.put(event)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        logger.info("EventBus started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("EventBus stopped")

    def _process_loop(self) -> None:
        while self._running:
            try:
                event = self._queue.get(timeout=1)
                for handler in self._handlers.get(event.type, []):
                    try:
                        handler(event)
                    except Exception as e:
                        logger.error("Handler error for %s: %s", event.type, e)
            except Exception:
                continue


class BaseStrategy(ABC):
    """Abstract trading strategy template."""

    name: str = "base_strategy"

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._bus.subscribe(EventType.MARKET_DATA, self.on_market_data)
        self._bus.subscribe(EventType.SIGNAL, self.on_signal)
        self._bus.subscribe(EventType.FILL, self.on_fill)

    @abstractmethod
    def on_market_data(self, event: Event) -> None:
        """Called when new market data arrives."""
        ...

    def on_signal(self, event: Event) -> None:
        """Called when a trading signal is generated."""
        pass

    def on_fill(self, event: Event) -> None:
        """Called when an order is filled."""
        pass

    def submit_order(
        self,
        symbol: str,
        action: str,  # buy | sell
        quantity: int,
        price: float | None = None,
        order_type: str = "market",
    ) -> None:
        """Submit a trade order through the event bus."""
        self._bus.publish(Event(
            type=EventType.ORDER,
            data={
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
                "strategy": self.name,
            },
        ))


class PaperTradingExecutor:
    """Simulated trade execution for paper trading."""

    def __init__(self, event_bus: EventBus, initial_capital: float = 1_000_000) -> None:
        self._bus = event_bus
        self.capital = initial_capital
        self.positions: dict[str, dict] = {}
        self.trades: list[dict] = []
        self._bus.subscribe(EventType.ORDER, self._handle_order)

    def _handle_order(self, event: Event) -> None:
        data = event.data
        symbol = data["symbol"]
        action = data["action"]
        quantity = data["quantity"]
        price = data.get("price", 0)

        if action == "buy":
            cost = price * quantity
            if cost > self.capital:
                logger.warning("Insufficient capital for %s buy: need %.2f, have %.2f", symbol, cost, self.capital)
                return
            self.capital -= cost
            pos = self.positions.get(symbol, {"quantity": 0, "avg_cost": 0})
            total_qty = pos["quantity"] + quantity
            pos["avg_cost"] = (pos["avg_cost"] * pos["quantity"] + price * quantity) / total_qty if total_qty > 0 else 0
            pos["quantity"] = total_qty
            self.positions[symbol] = pos

        elif action == "sell":
            pos = self.positions.get(symbol, {"quantity": 0, "avg_cost": 0})
            if pos["quantity"] < quantity:
                logger.warning("Insufficient shares for %s sell: have %d, want %d", symbol, pos["quantity"], quantity)
                return
            self.capital += price * quantity
            pos["quantity"] -= quantity
            if pos["quantity"] == 0:
                del self.positions[symbol]
            else:
                self.positions[symbol] = pos

        trade = {
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "timestamp": datetime.now().isoformat(),
            "strategy": data.get("strategy", ""),
        }
        self.trades.append(trade)
        logger.info("Paper trade: %s %d %s @ %.2f", action, quantity, symbol, price)

        self._bus.publish(Event(
            type=EventType.FILL,
            data=trade,
        ))

    @property
    def portfolio_value(self) -> float:
        return self.capital + sum(
            p["quantity"] * p.get("current_price", p["avg_cost"])
            for p in self.positions.values()
        )


class TradingEngine:
    """Main trading engine — coordinates event bus, strategies, and execution."""

    def __init__(
        self,
        initial_capital: float = 1_000_000,
        mode: str = "paper",
    ) -> None:
        self.event_bus = EventBus()
        self.strategies: list[BaseStrategy] = []

        if mode == "paper":
            self.executor = PaperTradingExecutor(self.event_bus, initial_capital)
        else:
            self.executor = PaperTradingExecutor(self.event_bus, initial_capital)
            logger.warning("Live trading not enabled; using paper trading")

    def add_strategy(self, strategy_cls: type[BaseStrategy]) -> BaseStrategy:
        strategy = strategy_cls(self.event_bus)
        self.strategies.append(strategy)
        return strategy

    def start(self) -> None:
        self.event_bus.start()
        logger.info("Trading engine started with %d strategies", len(self.strategies))

    def stop(self) -> None:
        self.event_bus.stop()
        logger.info("Trading engine stopped")

    def feed_market_data(self, symbol: str, data: dict) -> None:
        self.event_bus.publish(Event(
            type=EventType.MARKET_DATA,
            data={"symbol": symbol, **data},
        ))

    def get_portfolio_summary(self) -> dict:
        return {
            "capital": self.executor.capital,
            "positions": dict(self.executor.positions),
            "portfolio_value": self.executor.portfolio_value,
            "total_trades": len(self.executor.trades),
        }
