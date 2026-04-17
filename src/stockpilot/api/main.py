"""FastAPI web application — unified REST API for StockPilot."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from pydantic import BaseModel, Field

from stockpilot.config import get_settings
from stockpilot.data.adapters import Market

logger = logging.getLogger(__name__)

# Paths for web assets
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("StockPilot API starting up...")
    yield
    logger.info("StockPilot API shutting down...")


app = FastAPI(
    title="StockPilot API",
    description="AI-powered quantitative investment platform",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if TEMPLATES_DIR.exists() else None


# ── Request/Response Models ──

class StockQuery(BaseModel):
    symbol: str = Field(min_length=1)
    market: Market = Market.A_SHARE


class AnalysisRequest(BaseModel):
    symbol: str = Field(min_length=1)
    market: Market = Market.A_SHARE
    days: int = Field(default=120, ge=1, le=3650)


class AgentAnalysisRequest(BaseModel):
    ticker: str = Field(min_length=1)
    market: Market = Market.A_SHARE
    enable_personas: bool = True
    enable_debate: bool = True
    persona_keys: list[str] | None = None


class BacktestRequest(BaseModel):
    symbol: str = Field(min_length=1)
    market: Market = Market.A_SHARE
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = Field(default=1_000_000, gt=0)
    strategy: str = Field(default="ma_crossover", min_length=1)


class CompareSymbolsRequest(BaseModel):
    symbols: list[str] = Field(min_length=2)
    market: Market = Market.A_SHARE
    days: int = Field(default=120, ge=1, le=3650)


class BacktestCompareRunRequest(BaseModel):
    symbol: str = Field(min_length=1)
    strategy: str = Field(default="ma_crossover", min_length=1)
    market: Market = Market.A_SHARE
    label: str | None = None


class BacktestCompareRequest(BaseModel):
    runs: list[BacktestCompareRunRequest] = Field(min_length=1)
    days: int = Field(default=365, ge=1, le=3650)
    initial_capital: float = Field(default=1_000_000, gt=0)


# ── Data Routes ──

@app.get("/", include_in_schema=False)
async def root(request: Request):
    if templates and (TEMPLATES_DIR / "index.html").exists():
        return templates.TemplateResponse(request, "index.html")
    return RedirectResponse(url="/docs")


@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/v1/stocks/search")
async def search_stocks(keyword: str = Query(..., min_length=1)):
    """Search for stocks by name or symbol."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter

    try:
        dm = DataManager()
        dm.register_adapter(AKShareAdapter(), priority=True)
        results = dm.search(keyword)
        return {"results": [r.model_dump() for r in results[:20]]}
    except Exception as e:
        logger.error("Search failed: %s", e)
        raise HTTPException(status_code=503, detail=f"Data source unavailable: {e}")


@app.get("/api/v1/stocks/{symbol}/price")
async def get_price_history(
    symbol: str,
    days: int = Query(default=90, ge=1, le=3650),
    market: Market = Query(default=Market.A_SHARE),
):
    """Get historical OHLCV price data."""
    end = date.today()
    start = end - timedelta(days=days)
    result = _load_price_history_result(
        gateway=_build_data_gateway(),
        symbol=symbol,
        market=market,
        start_date=start,
        end_date=end,
    )
    df = result.data
    return {
        "symbol": symbol,
        "data": df.to_dict(orient="records"),
        "data_status": _status_dict(result),
    }


@app.get("/api/v1/stocks/{symbol}/fundamentals")
async def get_fundamentals(symbol: str, market: Market = Query(default=Market.A_SHARE)):
    """Get fundamental data for a stock."""
    result = _load_fundamental_result(
        gateway=_build_data_gateway(),
        symbol=symbol,
        market=market,
    )
    payload = result.data if isinstance(result.data, dict) else {"data": result.data}
    payload = dict(payload)
    payload["data_status"] = _status_dict(result)
    return payload


# ── Analysis Routes ──

@app.post("/api/v1/analysis/technical")
async def run_technical_analysis(req: AnalysisRequest):
    """Run full technical analysis with signal generation."""
    from stockpilot.analysis.signals import generate_signals

    end = date.today()
    start = end - timedelta(days=req.days)
    result = _load_price_history_result(
        gateway=_build_data_gateway(),
        symbol=req.symbol,
        market=req.market,
        start_date=start,
        end_date=end,
    )
    df = result.data

    analysis = generate_signals(df)
    analysis["signal"] = analysis["signal"].value
    return {
        "symbol": req.symbol,
        "analysis": analysis,
        "data_status": _status_dict(result),
    }


@app.post("/api/v1/analysis/patterns")
async def get_patterns(req: StockQuery):
    """Detect K-line candlestick patterns."""
    from stockpilot.analysis.patterns import get_pattern_summary

    end = date.today()
    start = end - timedelta(days=60)
    result = _load_price_history_result(
        gateway=_build_data_gateway(),
        symbol=req.symbol,
        market=req.market,
        start_date=start,
        end_date=end,
    )
    df = result.data

    return {
        "symbol": req.symbol,
        "patterns": get_pattern_summary(df),
        "data_status": _status_dict(result),
    }


# ── Agent Routes ──

@app.post("/api/v1/agents/analyze")
async def run_agent_analysis(req: AgentAnalysisRequest):
    """Run full LLM agent analysis pipeline."""
    from stockpilot.agents.graph.orchestrator import StockPilotGraph

    graph = StockPilotGraph(
        enable_personas=req.enable_personas,
        enable_debate=req.enable_debate,
        persona_keys=req.persona_keys,
    )
    result = graph.analyze(req.ticker, market=req.market)

    return {
        "ticker": req.ticker,
        "final_decision": result.get("final_decision"),
        "risk_assessment": result.get("risk_assessment"),
        "fundamental_analysis": result.get("fundamental_analysis"),
        "technical_analysis": result.get("technical_analysis"),
        "persona_analyses": result.get("persona_analyses", {}),
        "debate_history": result.get("debate_history", []),
    }


# ── News Routes ──

@app.get("/api/v1/news/trending")
async def get_trending_news(
    platforms: str = Query(default="hackernews,reddit_finance"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get trending news from multiple platforms."""
    from stockpilot.news.aggregator import NewsAggregator

    platform_list = [p.strip() for p in platforms.split(",")]
    agg = NewsAggregator(platforms=platform_list)
    items = agg.fetch_all()[:limit]

    return {
        "count": len(items),
        "news": [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "rank": item.rank,
                "hot_score": item.hot_score,
            }
            for item in items
        ],
    }


# ── Backtest Routes ──

@app.post("/api/v1/backtest/run")
async def run_backtest(req: BacktestRequest):
    """Run a strategy backtest."""
    return _run_backtest_job(
        symbol=req.symbol,
        market=req.market,
        strategy=req.strategy,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
    )


# ── Strategy & Persona Routes ──

@app.get("/api/v1/strategies")
async def list_strategies():
    """List available trading strategies."""
    from stockpilot.trading.strategies.library import list_strategies as ls
    return {"strategies": ls()}


@app.get("/api/v1/personas")
async def list_personas():
    """List available AI analyst personas."""
    from stockpilot.agents.personas.investors import PERSONAS
    return {
        "personas": [
            {
                "key": k,
                "name": v["name"],
                "style": v["style"],
                "type": v.get("type", "investor"),
                "description": v.get("description", ""),
            }
            for k, v in PERSONAS.items()
        ]
    }


class PortfolioOptRequest(BaseModel):
    symbols: list[str] = Field(min_length=2)
    method: str = "max_sharpe"
    days: int = Field(default=365, ge=1, le=3650)
    capital: float = Field(default=1_000_000, gt=0)
    market: Market = Market.A_SHARE
    risk_free_rate: float = 0.03


def _build_data_manager():
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    dm.register_adapter(YFinanceAdapter())
    return dm


def _build_data_gateway():
    from stockpilot.data.runtime import build_default_data_gateway

    return build_default_data_gateway()


def _status_dict(result):
    return result.to_status_dict()


def _not_found_envelope(*, domain: str, market, symbol: str) -> dict[str, Any]:
    market_value = market.value if isinstance(market, Market) else str(market)
    return {
        "status": "not_found",
        "code": "DATA_NOT_FOUND",
        "message": f"No data found for {symbol}",
        "domain": domain,
        "market": market_value,
        "symbol": symbol,
        "missing_symbols": [],
        "attempted_sources": [],
        "cache_state": None,
        "retry_after_seconds": None,
        "http_status": 404,
    }


def _load_price_history_result(
    *,
    gateway,
    symbol: str,
    market: Market,
    start_date,
    end_date,
    domain: str = "price_history",
):
    result = gateway.get_price_history(
        symbol,
        market=market,
        start_date=start_date,
        end_date=end_date,
    )
    if result.error is not None:
        raise HTTPException(
            status_code=result.error.http_status,
            detail=result.error.to_dict(),
        )
    # Single-resource routes translate empty payloads into 404 not_found
    from stockpilot.data.reliability.types import ResultKind

    if result.result_kind == ResultKind.EMPTY:
        raise HTTPException(
            status_code=404,
            detail=_not_found_envelope(
                domain=domain, market=market, symbol=symbol
            ),
        )
    return result


def _load_fundamental_result(
    *,
    gateway,
    symbol: str,
    market: Market,
):
    result = gateway.get_fundamental_data(symbol, market=market)
    if result.error is not None:
        raise HTTPException(
            status_code=result.error.http_status,
            detail=result.error.to_dict(),
        )
    from stockpilot.data.reliability.types import ResultKind

    if result.result_kind == ResultKind.EMPTY:
        raise HTTPException(
            status_code=404,
            detail=_not_found_envelope(
                domain="fundamental_data", market=market, symbol=symbol
            ),
        )
    return result


def _load_price_history(
    *,
    data_manager,
    symbol: str,
    market: Market,
    start_date,
    end_date,
    empty_detail: str,
):
    try:
        df = data_manager.get_price_history(
            symbol,
            market=market,
            start_date=start_date,
            end_date=end_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to load price history for %s (%s): %s", symbol, market, e)
        raise HTTPException(status_code=503, detail=f"Data source unavailable for {symbol}: {e}") from e

    if df.empty:
        raise HTTPException(status_code=404, detail=empty_detail)

    return df


def _serialize_backtest_result(symbol: str, strategy: str, result) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "metrics": {
            "total_return_pct": result.metrics.total_return_pct,
            "annual_return_pct": result.metrics.annual_return_pct,
            "sharpe_ratio": result.metrics.sharpe_ratio,
            "max_drawdown_pct": result.metrics.max_drawdown_pct,
            "win_rate": result.metrics.win_rate,
            "total_trades": result.metrics.total_trades,
            "final_capital": result.metrics.final_capital,
        },
        "equity_curve": [round(float(value), 4) for value in result.equity_curve],
        "dates": [str(value) for value in result.dates],
        "trades": [
            {
                "date": str(t.date),
                "symbol": t.symbol,
                "action": t.action,
                "quantity": int(t.quantity),
                "price": round(float(t.price), 4),
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }


def _run_backtest_job(
    *,
    symbol: str,
    market: Market,
    strategy: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
):
    from stockpilot.analysis.indicators import calculate_all_indicators
    from stockpilot.backtesting.engine import BacktestConfig, BacktestEngine
    from stockpilot.trading.strategies.library import get_strategy

    dm = _build_data_manager()
    df = _load_price_history(
        data_manager=dm,
        symbol=symbol,
        market=market,
        start_date=start_date,
        end_date=end_date,
        empty_detail=f"No data for {symbol}",
    )

    df = calculate_all_indicators(df)

    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
    )
    engine = BacktestEngine(config)
    engine.add_data(symbol, df)

    strat_fn = get_strategy(strategy)
    if strat_fn is None:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {strategy}")
    result = engine.run(strat_fn)
    return _serialize_backtest_result(symbol, strategy, result)


@app.post("/api/v1/portfolio/optimize")
async def optimize_portfolio(req: PortfolioOptRequest):
    """Run portfolio optimization across multiple stocks."""
    from stockpilot.analysis.portfolio import PortfolioOptimizer

    end = date.today()
    start = end - timedelta(days=req.days)

    dm = _build_data_manager()
    optimizer = PortfolioOptimizer(risk_free_rate=req.risk_free_rate)
    for sym in req.symbols:
        try:
            df = _load_price_history(
                data_manager=dm,
                symbol=sym,
                market=req.market,
                start_date=start,
                end_date=end,
                empty_detail=f"No data found for {sym}",
            )
            if not df.empty:
                optimizer.add_prices_df(sym, df)
        except Exception as e:
            logger.warning("Failed to load %s: %s", sym, e)

    if len(optimizer.symbols) < 2:
        raise HTTPException(status_code=404, detail=f"Need data for ≥2 symbols, got {len(optimizer.symbols)}")

    methods = {
        "equal_weight": optimizer.equal_weight,
        "min_variance": optimizer.min_variance,
        "max_sharpe": optimizer.max_sharpe,
        "risk_parity": optimizer.risk_parity,
    }
    fn = methods.get(req.method, optimizer.max_sharpe)
    result = fn()

    return {
        "method": result.method,
        "weights": result.weights,
        "expected_return": result.expected_return,
        "expected_volatility": result.expected_volatility,
        "sharpe_ratio": result.sharpe_ratio,
        "capital": req.capital,
        "risk_free_rate": req.risk_free_rate,
        "loaded_symbols": optimizer.symbols,
        "allocations": {s: round(w * req.capital, 2) for s, w in result.weights.items()},
    }


@app.get("/api/v1/stocks/{symbol}/chart-data")
async def get_chart_data(
    symbol: str,
    days: int = Query(default=120, ge=1, le=3650),
    market: Market = Query(default=Market.A_SHARE),
):
    """Get OHLCV data with all technical indicators for charting."""
    from stockpilot.analysis.indicators import calculate_all_indicators
    from stockpilot.analysis.signals import generate_signals

    gateway = _build_data_gateway()

    end = date.today()
    start = end - timedelta(days=days)
    result = _load_price_history_result(
        gateway=gateway,
        symbol=symbol,
        market=market,
        start_date=start,
        end_date=end,
    )
    df = result.data

    df = calculate_all_indicators(df)
    signals = generate_signals(df)

    # Select key columns for the chart
    cols = ["date", "open", "high", "low", "close", "volume",
            "ma_5", "ma_10", "ma_20", "ma_60",
            "macd", "macd_signal", "macd_hist",
            "rsi_6", "rsi_12",
            "boll_upper", "boll_mid", "boll_lower",
            "kdj_k", "kdj_d", "kdj_j",
            "atr", "adx", "cci", "obv", "sar"]
    available_cols = [c for c in cols if c in df.columns]
    chart_df = df[available_cols].copy()
    chart_df = chart_df.fillna("")

    return {
        "symbol": symbol,
        "signal": signals["signal"].value,
        "combined_score": signals["combined_score"],
        "indicator_scores": signals.get("indicator_scores", {}),
        "data": chart_df.to_dict(orient="records"),
        "data_status": _status_dict(result),
    }


@app.post("/api/v1/compare/symbols")
async def compare_symbols(req: CompareSymbolsRequest):
    """Compare multiple symbols with normalized performance and signal summaries."""
    from stockpilot.analysis.indicators import calculate_all_indicators
    from stockpilot.analysis.signals import generate_signals

    if len(req.symbols) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 symbols")

    dm = _build_data_manager()
    end = date.today()
    start = end - timedelta(days=req.days)

    series = []
    summaries = []
    load_errors = []
    for symbol in req.symbols[:4]:
        try:
            df = _load_price_history(
                data_manager=dm,
                symbol=symbol,
                market=req.market,
                start_date=start,
                end_date=end,
                empty_detail=f"No data found for {symbol}",
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                logger.info("Skipping %s in compare symbols: %s", symbol, exc.detail)
            else:
                logger.warning("Skipping %s in compare symbols due to upstream issue: %s", symbol, exc.detail)
                load_errors.append(symbol)
            continue

        df = calculate_all_indicators(df)
        signals = generate_signals(df)
        first_close = float(df["close"].iloc[0])
        last_close = float(df["close"].iloc[-1])

        series.append({
            "symbol": symbol,
            "dates": [str(v) for v in df["date"].tolist()],
            "normalized": [round(float(v) / first_close * 100, 4) for v in df["close"].tolist()],
            "close": [round(float(v), 4) for v in df["close"].tolist()],
        })
        summaries.append({
            "symbol": symbol,
            "signal": signals["signal"].value,
            "combined_score": round(float(signals["combined_score"]), 4),
            "last_close": round(last_close, 4),
            "change_pct": round((last_close / first_close - 1) * 100, 2),
            "indicator_scores": signals.get("indicator_scores", {}),
        })

    if len(series) < 2:
        if load_errors:
            raise HTTPException(status_code=503, detail="Data source unavailable for one or more requested symbols")
        raise HTTPException(status_code=404, detail="Need valid data for at least 2 symbols")

    return {
        "market": req.market,
        "days": req.days,
        "series": series,
        "summaries": summaries,
    }


@app.post("/api/v1/backtest/compare")
async def compare_backtests(req: BacktestCompareRequest):
    """Run several backtests and return overlay-ready equity curves."""
    if not req.runs:
        raise HTTPException(status_code=400, detail="No runs provided")

    end = date.today()
    start = end - timedelta(days=req.days)
    runs = []
    for run in req.runs[:4]:
        result = _run_backtest_job(
            symbol=run.symbol,
            market=run.market,
            strategy=run.strategy,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            initial_capital=req.initial_capital,
        )
        result["label"] = run.label or f"{run.symbol} · {run.strategy}"
        runs.append(result)

    return {
        "days": req.days,
        "initial_capital": req.initial_capital,
        "runs": runs,
    }


def start():
    """Entry point for `stockpilot-api` command."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "stockpilot.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=(settings.app_env == "development"),
    )


if __name__ == "__main__":
    start()
