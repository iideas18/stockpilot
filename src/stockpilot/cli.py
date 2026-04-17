"""StockPilot CLI — Typer-based command line interface."""

from __future__ import annotations

import json
from datetime import date, timedelta

import typer
from rich.console import Console
from rich.table import Table

from stockpilot.data.runtime import build_default_data_gateway

app = typer.Typer(name="stockpilot", help="AI-powered quantitative investment platform")
console = Console()


def _warn_if_stale(result) -> None:
    """Print a yellow warning if the DataResult is stale."""
    if getattr(result, "status", None) == "stale":
        console.print(
            f"[yellow]Using stale cached data from {result.source}[/yellow]"
        )


def _handle_error(result, symbol: str) -> None:
    """Surface a reliability error and exit with code 1."""
    err = getattr(result, "error", None)
    if err is None:
        return
    msg = getattr(err, "message", str(err))
    code = getattr(err, "code", "?")
    retry = getattr(err, "retry_after_seconds", None)
    console.print(
        f"[red]Data unavailable for {symbol}: {code} — {msg}[/red]"
    )
    if retry:
        console.print(
            f"[yellow]Retry after {retry} seconds.[/yellow]"
        )
    raise typer.Exit(1)


@app.command()
def analyze(
    symbol: str = typer.Argument(..., help="Stock symbol (e.g., 000001, AAPL)"),
    market: str = typer.Option("a_share", help="Market: a_share, us, hk"),
    days: int = typer.Option(120, help="Days of historical data"),
):
    """Run technical analysis on a stock."""
    from stockpilot.data.adapters import Market
    from stockpilot.analysis.signals import generate_signals

    console.print(f"\n📊 Analyzing [bold]{symbol}[/bold]...\n")

    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=days)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )
    _handle_error(result, symbol)
    _warn_if_stale(result)
    df = result.data

    if df is None or df.empty:
        console.print(f"[red]No data found for {symbol}[/red]")
        raise typer.Exit(1)

    sig = generate_signals(df)

    signal_colors = {
        "strong_buy": "green bold",
        "buy": "green",
        "hold": "yellow",
        "sell": "red",
        "strong_sell": "red bold",
    }
    signal = sig["signal"].value
    color = signal_colors.get(signal, "white")

    table = Table(title=f"Analysis: {symbol}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Signal", f"[{color}]{signal.upper()}[/{color}]")
    table.add_row("Combined Score", f"{sig['combined_score']:.4f}")
    table.add_row("Indicator Score", f"{sig['indicator_analysis']['composite_score']:.4f}")
    table.add_row("Pattern Score", f"{sig['pattern_analysis']['bullish_score']:.2f}")
    table.add_row("Bullish Patterns", str(sig['pattern_analysis']['bullish_count']))
    table.add_row("Bearish Patterns", str(sig['pattern_analysis']['bearish_count']))

    console.print(table)

    # Indicator details
    details = sig["indicator_analysis"].get("details", {})
    if details:
        detail_table = Table(title="Indicator Scores")
        detail_table.add_column("Indicator", style="cyan")
        detail_table.add_column("Score", style="white")
        for name, score in details.items():
            detail_table.add_row(name.upper(), f"{score:.2f}")
        console.print(detail_table)


@app.command()
def search(
    keyword: str = typer.Argument(..., help="Search keyword"),
    market: str = typer.Option("a_share", help="Market: a_share, us, hk"),
):
    """Search for stocks by name or symbol."""
    from stockpilot.data.adapters import Market

    gateway = build_default_data_gateway()
    result = gateway.search(keyword, market=Market(market))
    _handle_error(result, keyword)
    _warn_if_stale(result)
    results = result.data or []

    if not results:
        console.print(f"[yellow]No results for '{keyword}'[/yellow]")
        return

    table = Table(title=f"Search: {keyword}")
    table.add_column("Symbol", style="cyan")
    table.add_column("Name", style="white")

    for r in results[:20]:
        table.add_row(r.symbol, r.name)
    console.print(table)


@app.command()
def news(
    platform: str = typer.Option("hackernews", help="Platform: hackernews, reddit_finance, weibo"),
    limit: int = typer.Option(15, help="Number of items"),
):
    """Get trending news."""
    from stockpilot.news.aggregator import NewsAggregator

    agg = NewsAggregator(platforms=[platform])
    items = agg.fetch_all()[:limit]

    if not items:
        console.print("[yellow]No news items found[/yellow]")
        return

    table = Table(title=f"Trending News — {platform}")
    table.add_column("#", style="dim")
    table.add_column("Title", style="white")
    table.add_column("Score", style="cyan")

    for i, item in enumerate(items, 1):
        table.add_row(str(i), item.title, str(item.hot_score))
    console.print(table)


@app.command()
def agent(
    symbol: str = typer.Argument(..., help="Stock symbol (e.g., 000001, AAPL)"),
    market: str = typer.Option("a_share", help="Market: a_share, us, hk"),
    personas: str = typer.Option(
        "warren_buffett,nassim_taleb,cathie_wood",
        help="Comma-separated persona keys",
    ),
    debate: bool = typer.Option(True, help="Run risk management debate"),
    rounds: int = typer.Option(2, help="Debate rounds"),
):
    """Run full LLM agent analysis with personas and risk debate."""
    from rich.panel import Panel

    from stockpilot.data.adapters import Market
    from stockpilot.analysis.signals import generate_signals
    from stockpilot.agents.personas.investors import PERSONAS, create_persona_agent
    from stockpilot.agents.memory import get_memory
    from stockpilot.agents.stats import get_global_stats

    console.print(f"\n🤖 Running AI agent analysis on [bold]{symbol}[/bold]...\n")

    stats = get_global_stats()
    stats.reset()

    # 1. Fetch data
    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=120)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )
    _handle_error(result, symbol)
    _warn_if_stale(result)
    df = result.data

    if df is None or df.empty:
        console.print(f"[red]No data found for {symbol}[/red]")
        raise typer.Exit(1)

    # 2. Technical analysis
    signals = generate_signals(df)
    signal_summary = (
        f"Signal: {signals['signal'].value.upper()}, "
        f"Score: {signals['combined_score']:.2f}"
    )
    console.print(f"📊 Technical: [cyan]{signal_summary}[/cyan]\n")

    # 3. Recall relevant memories
    memory = get_memory("agent_analysis")
    past = memory.recall_for_ticker(symbol, n_matches=3)
    if past:
        console.print(f"🧠 Found {len(past)} past analyses in memory\n")
        memory_context = "\n".join(
            f"- [{m['metadata'].get('date', '?')}] {m['recommendation']}"
            for m in past
        )
    else:
        memory_context = "No prior analyses found."

    # 4. Run persona analyses
    persona_keys = [p.strip() for p in personas.split(",") if p.strip() in PERSONAS]
    if not persona_keys:
        persona_keys = ["warren_buffett", "nassim_taleb", "cathie_wood"]

    state = {
        "ticker": symbol,
        "market": market,
        "fundamental_data": "See technical signals below",
        "technical_signals": signal_summary,
        "news_summary": "N/A",
        "persona_analyses": {},
        "memory_context": memory_context,
    }

    panels = []
    for key in persona_keys:
        persona = PERSONAS[key]
        console.print(f"  💭 {persona['name']} analyzing...", end="")
        agent_fn = create_persona_agent(key)
        try:
            persona_result = agent_fn(state)
            state.update(persona_result)
            analysis_text = state["persona_analyses"].get(persona["name"], "N/A")
            display_text = analysis_text[:500] + "..." if len(analysis_text) > 500 else analysis_text
            panels.append(Panel(
                display_text,
                title=f"[bold]{persona['name']}[/bold] ({persona['style']})",
                border_style="cyan",
                width=80,
            ))
            console.print(" ✅")
        except Exception as e:
            console.print(f" [red]❌ {e}[/red]")

    for panel in panels:
        console.print(panel)

    # 5. Risk debate
    if debate:
        console.print("\n⚔️  Running risk management debate...\n")
        try:
            from stockpilot.agents.risk_mgmt.debaters import run_risk_debate
            debate_result = run_risk_debate(
                trader_decision=f"Analyzing {symbol}: {signal_summary}",
                analysis_data={
                    "technical": signal_summary,
                    "fundamental": "See persona analyses above",
                    "sentiment": "N/A",
                    "news": "N/A",
                },
                rounds=rounds,
            )
            console.print(Panel(
                debate_result["final_assessment"],
                title="[bold]⚖️  Risk Assessment[/bold]",
                border_style="yellow",
            ))
        except Exception as e:
            console.print(f"[red]Debate failed: {e}[/red]")

    # 6. Save to memory
    all_analyses = "\n".join(
        f"{name}: {text[:200]}" for name, text in state.get("persona_analyses", {}).items()
    )
    memory.add_analysis(
        ticker=symbol,
        market=market,
        analysis_summary=f"{signal_summary}. Personas: {', '.join(persona_keys)}",
        recommendation=all_analyses[:500] if all_analyses else signal_summary,
        signal=signals["signal"].value,
        score=signals["combined_score"],
    )
    console.print(f"\n💾 Analysis saved to memory ({memory.count()} total memories)")

    # 7. Stats
    s = stats.get_stats()
    if s["llm_calls"] > 0:
        stats_table = Table(title="📈 LLM Usage Stats")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="white")
        stats_table.add_row("LLM Calls", str(s["llm_calls"]))
        stats_table.add_row("Tool Calls", str(s["tool_calls"]))
        stats_table.add_row("Tokens In", f"{s['tokens_in']:,}")
        stats_table.add_row("Tokens Out", f"{s['tokens_out']:,}")
        stats_table.add_row("Total Tokens", f"{s['total_tokens']:,}")
        console.print(stats_table)


@app.command()
def backtest(
    symbol: str = typer.Argument(..., help="Stock symbol"),
    strategy: str = typer.Option("ma_crossover", help="Strategy: ma_crossover, turtle, breakout"),
    days: int = typer.Option(365, help="Backtest period in days"),
    capital: float = typer.Option(1_000_000, help="Initial capital"),
    market: str = typer.Option("a_share", help="Market: a_share, us, hk"),
):
    """Run a strategy backtest."""
    from stockpilot.data.adapters import Market
    from stockpilot.analysis.indicators import calculate_all_indicators
    from stockpilot.backtesting.engine import BacktestConfig, BacktestEngine
    from stockpilot.trading.strategies.library import get_strategy, list_strategies

    # Show available strategies if requested
    if strategy == "list":
        strats = list_strategies()
        strat_table = Table(title="Available Strategies")
        strat_table.add_column("Key", style="cyan")
        strat_table.add_column("Name", style="white")
        strat_table.add_column("Type", style="yellow")
        strat_table.add_column("Description")
        for s in strats:
            strat_table.add_row(s["key"], s["name"], s["type"], s["description"])
        console.print(strat_table)
        return

    console.print(f"\n📈 Backtesting [bold]{symbol}[/bold] with {strategy} strategy...\n")

    strat_fn = get_strategy(strategy)
    if strat_fn is None:
        console.print(f"[red]Unknown strategy '{strategy}'. Use --strategy list to see options.[/red]")
        raise typer.Exit(1)

    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=days)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )
    _handle_error(result, symbol)
    _warn_if_stale(result)
    df = result.data

    if df is None or df.empty:
        console.print(f"[red]No data found for {symbol}[/red]")
        raise typer.Exit(1)

    df = calculate_all_indicators(df)

    config = BacktestConfig(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        initial_capital=capital,
    )
    engine = BacktestEngine(config)
    engine.add_data(symbol, df)

    bt_result = engine.run(strat_fn)

    metrics_table = Table(title=f"Backtest Results: {symbol} ({strategy})")
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Value", style="white")
    m = bt_result.metrics
    metrics_table.add_row("Total Return", f"[{'green' if m.total_return_pct > 0 else 'red'}]{m.total_return_pct:.2f}%[/]")
    metrics_table.add_row("Annual Return", f"{m.annual_return_pct:.2f}%")
    metrics_table.add_row("Sharpe Ratio", f"{m.sharpe_ratio:.2f}")
    metrics_table.add_row("Max Drawdown", f"[red]{m.max_drawdown_pct:.2f}%[/red]")
    metrics_table.add_row("Win Rate", f"{m.win_rate * 100:.1f}%")
    metrics_table.add_row("Total Trades", str(m.total_trades))
    metrics_table.add_row("Final Capital", f"¥{m.final_capital:,.0f}")
    console.print(metrics_table)


@app.command()
def chart(
    symbol: str = typer.Argument(..., help="Stock symbol"),
    days: int = typer.Option(120, help="Number of days"),
    market: str = typer.Option("a_share", help="Market: a_share, us, hk"),
    output: str = typer.Option("", help="Output HTML file path (default: {symbol}_chart.html)"),
    indicators: str = typer.Option("ma_5,ma_20,ma_60", help="Comma-separated indicator columns"),
):
    """Generate interactive K-line chart with indicators."""
    from stockpilot.data.adapters import Market
    from stockpilot.analysis.indicators import calculate_all_indicators
    from stockpilot.analysis.charts import create_kline_chart

    console.print(f"📊 Generating chart for [bold]{symbol}[/bold]...")

    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=days)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )
    _handle_error(result, symbol)
    _warn_if_stale(result)
    df = result.data

    if df is None or df.empty:
        console.print(f"[red]No data found for {symbol}[/red]")
        raise typer.Exit(1)

    df = calculate_all_indicators(df)

    out_path = output or f"{symbol}_chart.html"
    ind_list = [i.strip() for i in indicators.split(",") if i.strip()]

    chart_result = create_kline_chart(
        df, symbol=symbol, indicators=ind_list, output_path=out_path,
    )
    if chart_result:
        console.print(f"✅ Chart saved to [bold]{chart_result}[/bold]")
    else:
        console.print("[red]Chart generation failed (plotly not installed?)[/red]")


@app.command()
def portfolio(
    symbols: str = typer.Argument(..., help="Comma-separated stock symbols"),
    method: str = typer.Option("max_sharpe", help="Method: equal_weight, min_variance, max_sharpe, risk_parity"),
    days: int = typer.Option(365, help="Lookback period in days"),
    capital: float = typer.Option(1_000_000, help="Total capital to allocate"),
    market: str = typer.Option("a_share", help="Market"),
):
    """Optimize portfolio allocation across multiple stocks."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.data.adapters import Market
    from stockpilot.analysis.portfolio import PortfolioOptimizer

    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(sym_list) < 2:
        console.print("[red]Provide at least 2 symbols (comma-separated)[/red]")
        raise typer.Exit(1)

    console.print(f"\n📊 Optimizing portfolio for [bold]{', '.join(sym_list)}[/bold]...\n")

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)

    end = date.today()
    start = end - timedelta(days=days)

    optimizer = PortfolioOptimizer()
    for sym in sym_list:
        df = dm.get_price_history(sym, market=Market(market), start_date=start, end_date=end)
        if df.empty:
            console.print(f"[yellow]⚠ No data for {sym}, skipping[/yellow]")
            continue
        optimizer.add_prices_df(sym, df)

    if len(optimizer.symbols) < 2:
        console.print("[red]Need data for at least 2 symbols[/red]")
        raise typer.Exit(1)

    methods = {
        "equal_weight": optimizer.equal_weight,
        "min_variance": optimizer.min_variance,
        "max_sharpe": optimizer.max_sharpe,
        "risk_parity": optimizer.risk_parity,
    }

    fn = methods.get(method)
    if not fn:
        console.print(f"[red]Unknown method '{method}'. Options: {', '.join(methods.keys())}[/red]")
        raise typer.Exit(1)

    result = fn()

    # Display results
    alloc_table = Table(title=f"Portfolio Allocation ({result.method})")
    alloc_table.add_column("Symbol", style="cyan")
    alloc_table.add_column("Weight", style="white", justify="right")
    alloc_table.add_column("Amount (¥)", style="green", justify="right")
    for sym, w in sorted(result.weights.items(), key=lambda x: -x[1]):
        alloc_table.add_row(sym, f"{w:.1%}", f"{capital * w:,.0f}")
    console.print(alloc_table)

    metrics_table = Table(title="Portfolio Metrics")
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Value", style="white")
    metrics_table.add_row("Expected Return", f"{result.expected_return:+.2%}")
    metrics_table.add_row("Expected Volatility", f"{result.expected_volatility:.2%}")
    metrics_table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.3f}")
    console.print(metrics_table)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host"),
    port: int = typer.Option(8000, help="Port"),
):
    """Start the API server."""
    import uvicorn
    console.print(f"🚀 Starting StockPilot API on {host}:{port}")
    uvicorn.run("stockpilot.api.main:app", host=host, port=port, reload=True)


@app.command()
def version():
    """Show version information."""
    from stockpilot import __version__
    console.print(f"StockPilot v{__version__}")


if __name__ == "__main__":
    app()
