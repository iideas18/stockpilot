"""K-line candlestick pattern recognition.

Supports 61 candlestick patterns using TA-Lib's pattern recognition functions.
Ported from Stock2's core/pattern.py.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _to_python_scalar(value: Any) -> Any:
    """Convert NumPy scalar values to native Python scalars."""
    if isinstance(value, np.generic):
        return value.item()
    return value

# All 61 TA-Lib candlestick pattern functions
CANDLESTICK_PATTERNS = {
    "CDL2CROWS": "Two Crows",
    "CDL3BLACKCROWS": "Three Black Crows",
    "CDL3INSIDE": "Three Inside Up/Down",
    "CDL3LINESTRIKE": "Three-Line Strike",
    "CDL3OUTSIDE": "Three Outside Up/Down",
    "CDL3STARSINSOUTH": "Three Stars In The South",
    "CDL3WHITESOLDIERS": "Three Advancing White Soldiers",
    "CDLABANDONEDBABY": "Abandoned Baby",
    "CDLADVANCEBLOCK": "Advance Block",
    "CDLBELTHOLD": "Belt-hold",
    "CDLBREAKAWAY": "Breakaway",
    "CDLCLOSINGMARUBOZU": "Closing Marubozu",
    "CDLCONCEALBABYSWALL": "Concealing Baby Swallow",
    "CDLCOUNTERATTACK": "Counterattack",
    "CDLDARKCLOUDCOVER": "Dark Cloud Cover",
    "CDLDOJI": "Doji",
    "CDLDOJISTAR": "Doji Star",
    "CDLDRAGONFLYDOJI": "Dragonfly Doji",
    "CDLENGULFING": "Engulfing Pattern",
    "CDLEVENINGDOJISTAR": "Evening Doji Star",
    "CDLEVENINGSTAR": "Evening Star",
    "CDLGAPSIDESIDEWHITE": "Up/Down-gap side-by-side white lines",
    "CDLGRAVESTONEDOJI": "Gravestone Doji",
    "CDLHAMMER": "Hammer",
    "CDLHANGINGMAN": "Hanging Man",
    "CDLHARAMI": "Harami Pattern",
    "CDLHARAMICROSS": "Harami Cross Pattern",
    "CDLHIGHWAVE": "High-Wave Candle",
    "CDLHIKKAKE": "Hikkake Pattern",
    "CDLHIKKAKEMOD": "Modified Hikkake Pattern",
    "CDLHOMINGPIGEON": "Homing Pigeon",
    "CDLIDENTICAL3CROWS": "Identical Three Crows",
    "CDLINNECK": "In-Neck Pattern",
    "CDLINVERTEDHAMMER": "Inverted Hammer",
    "CDLKICKING": "Kicking",
    "CDLKICKINGBYLENGTH": "Kicking (by length)",
    "CDLLADDERBOTTOM": "Ladder Bottom",
    "CDLLONGLEGGEDDOJI": "Long Legged Doji",
    "CDLLONGLINE": "Long Line Candle",
    "CDLMARUBOZU": "Marubozu",
    "CDLMATCHINGLOW": "Matching Low",
    "CDLMATHOLD": "Mat Hold",
    "CDLMORNINGDOJISTAR": "Morning Doji Star",
    "CDLMORNINGSTAR": "Morning Star",
    "CDLONNECK": "On-Neck Pattern",
    "CDLPIERCING": "Piercing Pattern",
    "CDLRICKSHAWMAN": "Rickshaw Man",
    "CDLRISEFALL3METHODS": "Rising/Falling Three Methods",
    "CDLSEPARATINGLINES": "Separating Lines",
    "CDLSHOOTINGSTAR": "Shooting Star",
    "CDLSHORTLINE": "Short Line Candle",
    "CDLSPINNINGTOP": "Spinning Top",
    "CDLSTALLEDPATTERN": "Stalled Pattern",
    "CDLSTICKSANDWICH": "Stick Sandwich",
    "CDLTAKURI": "Takuri (Dragonfly Doji with very long lower shadow)",
    "CDLTASUKIGAP": "Tasuki Gap",
    "CDLTHRUSTING": "Thrusting Pattern",
    "CDLTRISTAR": "Tristar Pattern",
    "CDLUNIQUE3RIVER": "Unique 3 River",
    "CDLUPSIDEGAP2CROWS": "Upside Gap Two Crows",
    "CDLXSIDEGAP3METHODS": "Upside/Downside Gap Three Methods",
}


def detect_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Detect all 61 candlestick patterns in OHLC data.

    Args:
        df: DataFrame with columns: open, high, low, close

    Returns:
        DataFrame with pattern columns added. Values:
        - Positive (100/200): Bullish signal
        - Negative (-100/-200): Bearish signal
        - 0: No pattern detected
    """
    df = df.copy()

    try:
        import talib
    except ImportError:
        logger.warning("TA-Lib not installed; K-line pattern detection unavailable")
        return df

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    for func_name, pattern_name in CANDLESTICK_PATTERNS.items():
        try:
            func = getattr(talib, func_name)
            result = func(o, h, l, c)
            df[func_name] = result
        except Exception as e:
            logger.debug("Pattern %s failed: %s", func_name, e)
            df[func_name] = 0

    return df


def get_pattern_signals(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Extract detected pattern signals from the last row of data.

    Returns list of dicts: [{"pattern": "Morning Star", "signal": "bullish", "strength": 100}, ...]
    """
    df = detect_patterns(df)
    if df.empty:
        return []

    last_row = df.iloc[-1]
    signals = []

    for func_name, pattern_name in CANDLESTICK_PATTERNS.items():
        if func_name not in df.columns:
            continue
        value = _to_python_scalar(last_row.get(func_name, 0))
        if value != 0:
            signals.append({
                "pattern": pattern_name,
                "code": func_name,
                "signal": "bullish" if value > 0 else "bearish",
                "strength": abs(int(value)),
            })

    return signals


def get_pattern_summary(df: pd.DataFrame, lookback: int = 5) -> dict[str, Any]:
    """Get a summary of patterns detected in the last N days.

    Returns:
        {
            "total_patterns": int,
            "bullish_count": int,
            "bearish_count": int,
            "bullish_score": float,  # normalized 0-1
            "patterns": [...]
        }
    """
    df_recent = df.tail(lookback)
    df_patterns = detect_patterns(df_recent)

    all_signals = []
    for i in range(len(df_patterns)):
        row = df_patterns.iloc[i]
        row_date = row.get("date", i)
        for func_name, pattern_name in CANDLESTICK_PATTERNS.items():
            if func_name in df_patterns.columns:
                value = _to_python_scalar(row.get(func_name, 0))
                if value != 0:
                    all_signals.append({
                        "date": str(row_date),
                        "pattern": pattern_name,
                        "signal": "bullish" if value > 0 else "bearish",
                        "strength": abs(int(value)),
                    })

    bullish = [s for s in all_signals if s["signal"] == "bullish"]
    bearish = [s for s in all_signals if s["signal"] == "bearish"]
    total = len(all_signals)

    return {
        "total_patterns": total,
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "bullish_score": float(len(bullish) / total) if total > 0 else 0.5,
        "patterns": all_signals,
    }
