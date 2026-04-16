"""Interactive Plotly-based chart generation for stock analysis.

Generates K-line (candlestick) charts with technical indicator overlays
and backtest equity curve charts. Outputs standalone HTML files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def create_kline_chart(
    df: pd.DataFrame,
    symbol: str = "",
    title: str | None = None,
    indicators: list[str] | None = None,
    output_path: str | None = None,
    show: bool = False,
) -> str | None:
    """Create an interactive candlestick chart with indicator overlays.

    Args:
        df: DataFrame with columns: date/open/high/low/close/volume + indicator columns
        symbol: Stock symbol for the title
        title: Chart title (defaults to "K-Line: {symbol}")
        indicators: List of indicator columns to overlay (e.g., ["ma_5", "ma_20", "boll_upper"])
        output_path: Path to save HTML file. If None, returns HTML string.
        show: Whether to open in browser (requires display)

    Returns:
        HTML string if output_path is None, else the output file path.
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.error("plotly not installed. Run: pip install plotly")
        return None

    if indicators is None:
        indicators = ["ma_5", "ma_20", "ma_60"]

    title = title or f"K-Line: {symbol}"
    dates = df["date"] if "date" in df.columns else df.index

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[title, "Volume", "MACD"],
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K-Line",
            increasing_line_color="#ef5350",  # Red up (Chinese market convention)
            decreasing_line_color="#26a69a",  # Green down
        ),
        row=1, col=1,
    )

    # Indicator overlays
    colors = ["#FF9800", "#2196F3", "#9C27B0", "#4CAF50", "#F44336", "#00BCD4"]
    for i, ind in enumerate(indicators):
        if ind in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=dates, y=df[ind],
                    mode="lines",
                    name=ind.upper(),
                    line=dict(width=1, color=colors[i % len(colors)]),
                ),
                row=1, col=1,
            )

    # Bollinger Bands as filled area
    if "boll_upper" in df.columns and "boll_lower" in df.columns:
        if "boll_upper" not in indicators:
            fig.add_trace(
                go.Scatter(
                    x=dates, y=df["boll_upper"],
                    mode="lines", name="BOLL Upper",
                    line=dict(width=0.5, color="rgba(156,39,176,0.3)"),
                ),
                row=1, col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=dates, y=df["boll_lower"],
                    mode="lines", name="BOLL Lower",
                    fill="tonexty",
                    fillcolor="rgba(156,39,176,0.05)",
                    line=dict(width=0.5, color="rgba(156,39,176,0.3)"),
                ),
                row=1, col=1,
            )

    # Volume
    if "volume" in df.columns:
        colors_vol = [
            "#ef5350" if c >= o else "#26a69a"
            for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(
            go.Bar(x=dates, y=df["volume"], name="Volume", marker_color=colors_vol),
            row=2, col=1,
        )

    # MACD
    if "macd" in df.columns:
        fig.add_trace(
            go.Scatter(x=dates, y=df["macd"], mode="lines", name="MACD",
                        line=dict(color="#2196F3", width=1)),
            row=3, col=1,
        )
    if "macd_signal" in df.columns:
        fig.add_trace(
            go.Scatter(x=dates, y=df["macd_signal"], mode="lines", name="Signal",
                        line=dict(color="#FF9800", width=1)),
            row=3, col=1,
        )
    if "macd_hist" in df.columns:
        hist_colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df["macd_hist"]]
        fig.add_trace(
            go.Bar(x=dates, y=df["macd_hist"], name="Histogram", marker_color=hist_colors),
            row=3, col=1,
        )

    fig.update_layout(
        template="plotly_dark",
        height=800,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    if output_path:
        fig.write_html(output_path)
        logger.info("Chart saved to %s", output_path)
        if show:
            fig.show()
        return output_path
    else:
        return fig.to_html(full_html=True, include_plotlyjs="cdn")


def create_equity_chart(
    dates: list[str],
    equity_curve: list[float],
    initial_capital: float = 1_000_000,
    title: str = "Backtest Equity Curve",
    output_path: str | None = None,
    trades: list[dict] | None = None,
) -> str | None:
    """Create a backtest equity curve chart.

    Args:
        dates: List of date strings
        equity_curve: List of equity values over time
        initial_capital: Starting capital (for reference line)
        title: Chart title
        output_path: Path to save HTML file
        trades: Optional list of trade dicts for annotation

    Returns:
        HTML string or file path.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        logger.error("plotly not installed")
        return None

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates, y=equity_curve,
        mode="lines", name="Portfolio Equity",
        fill="tozeroy",
        fillcolor="rgba(33,150,243,0.1)",
        line=dict(color="#2196F3", width=2),
    ))

    fig.add_hline(
        y=initial_capital,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"Initial: ¥{initial_capital:,.0f}",
    )

    # Annotate buy/sell trades
    if trades:
        buys = [t for t in trades if t.get("action") == "buy"]
        sells = [t for t in trades if t.get("action") == "sell"]

        if buys:
            fig.add_trace(go.Scatter(
                x=[t["date"] for t in buys],
                y=[t.get("equity", initial_capital) for t in buys],
                mode="markers", name="Buy",
                marker=dict(symbol="triangle-up", size=10, color="#ef5350"),
            ))
        if sells:
            fig.add_trace(go.Scatter(
                x=[t["date"] for t in sells],
                y=[t.get("equity", initial_capital) for t in sells],
                mode="markers", name="Sell",
                marker=dict(symbol="triangle-down", size=10, color="#26a69a"),
            ))

    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=400,
        yaxis_title="Equity (¥)",
        xaxis_title="Date",
    )

    if output_path:
        fig.write_html(output_path)
        return output_path
    else:
        return fig.to_html(full_html=True, include_plotlyjs="cdn")
