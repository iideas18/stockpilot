"""SQLAlchemy database models for StockPilot.

Defines the schema for persisting stock data, analysis results,
trading records, and portfolio state.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class StockDaily(Base):
    """Daily OHLCV + indicators for a stock."""

    __tablename__ = "stock_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)
    change_pct = Column(Float)
    turnover_rate = Column(Float)
    # Technical indicators (filled by analysis engine)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_hist = Column(Float)
    rsi_6 = Column(Float)
    rsi_12 = Column(Float)
    rsi_24 = Column(Float)
    kdj_k = Column(Float)
    kdj_d = Column(Float)
    kdj_j = Column(Float)
    boll_upper = Column(Float)
    boll_mid = Column(Float)
    boll_lower = Column(Float)

    __table_args__ = (
        Index("ix_stock_daily_symbol_date", "symbol", "date", unique=True),
    )


class StockInfo(Base):
    """Stock basic information and metadata."""

    __tablename__ = "stock_info"

    symbol = Column(String(10), primary_key=True)
    name = Column(String(50))
    market = Column(String(10), default="a_share")
    industry = Column(String(50))
    sector = Column(String(50))
    list_date = Column(Date)
    total_shares = Column(BigInteger)
    circulating_shares = Column(BigInteger)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PatternSignal(Base):
    """Detected K-line patterns and signals."""

    __tablename__ = "pattern_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    pattern_name = Column(String(50), nullable=False)
    signal_type = Column(String(10))  # bullish, bearish, neutral
    strength = Column(Float)  # 0-1 confidence score
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentAnalysis(Base):
    """LLM agent analysis results."""

    __tablename__ = "agent_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    analysis_date = Column(Date, nullable=False)
    agent_type = Column(String(50))  # fundamentals, technicals, persona:warren_buffett, etc.
    recommendation = Column(String(20))  # strong_buy, buy, hold, sell, strong_sell
    confidence = Column(Float)
    reasoning = Column(Text)
    raw_output = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class TradeRecord(Base):
    """Executed or simulated trade records."""

    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    trade_date = Column(DateTime, nullable=False)
    action = Column(String(10))  # buy, sell
    quantity = Column(Integer)
    price = Column(Float)
    amount = Column(Float)
    commission = Column(Float)
    is_paper = Column(Boolean, default=True)
    strategy_name = Column(String(50))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class PortfolioPosition(Base):
    """Current portfolio holdings."""

    __tablename__ = "portfolio_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    name = Column(String(50))
    quantity = Column(Integer, default=0)
    avg_cost = Column(Float)
    current_price = Column(Float)
    market_value = Column(Float)
    unrealized_pnl = Column(Float)
    unrealized_pnl_pct = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BacktestResult(Base):
    """Backtesting run results."""

    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    initial_capital = Column(Float)
    final_capital = Column(Float)
    total_return_pct = Column(Float)
    annual_return_pct = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown_pct = Column(Float)
    win_rate = Column(Float)
    total_trades = Column(Integer)
    config_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_engine(database_url: str = "sqlite:///stockpilot.db"):
    """Create SQLAlchemy engine."""
    return create_engine(database_url, echo=False)


def init_db(database_url: str = "sqlite:///stockpilot.db") -> sessionmaker:
    """Initialize database and return session factory."""
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
