"""Signal generation — combines indicators and patterns into actionable signals."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import pandas as pd

from stockpilot.analysis.indicators import calculate_all_indicators
from stockpilot.analysis.patterns import get_pattern_summary

logger = logging.getLogger(__name__)


class Signal(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


def score_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Score the latest indicator values to produce a composite signal.

    Returns dict with individual indicator scores and overall composite.
    """
    if df.empty:
        return {"composite_score": 0.5, "signal": Signal.HOLD, "details": {}}

    last = df.iloc[-1]
    scores: dict[str, float] = {}

    # MACD signal: positive histogram = bullish
    if "macd_hist" in df.columns and pd.notna(last.get("macd_hist")):
        macd_hist = last["macd_hist"]
        prev_hist = df["macd_hist"].iloc[-2] if len(df) > 1 else 0
        if macd_hist > 0 and macd_hist > prev_hist:
            scores["macd"] = 0.8
        elif macd_hist > 0:
            scores["macd"] = 0.6
        elif macd_hist < 0 and macd_hist < prev_hist:
            scores["macd"] = 0.2
        else:
            scores["macd"] = 0.4

    # RSI signal
    if "rsi_12" in df.columns and pd.notna(last.get("rsi_12")):
        rsi = last["rsi_12"]
        if rsi < 20:
            scores["rsi"] = 0.9  # oversold = buy
        elif rsi < 30:
            scores["rsi"] = 0.7
        elif rsi > 80:
            scores["rsi"] = 0.1  # overbought = sell
        elif rsi > 70:
            scores["rsi"] = 0.3
        else:
            scores["rsi"] = 0.5

    # KDJ signal
    if "kdj_j" in df.columns and pd.notna(last.get("kdj_j")):
        j = last["kdj_j"]
        if j < 0:
            scores["kdj"] = 0.85
        elif j < 20:
            scores["kdj"] = 0.7
        elif j > 100:
            scores["kdj"] = 0.15
        elif j > 80:
            scores["kdj"] = 0.3
        else:
            scores["kdj"] = 0.5

    # Bollinger Bands: price near lower = buy, near upper = sell
    if all(c in df.columns for c in ("boll_upper", "boll_lower")):
        if pd.notna(last.get("boll_upper")) and pd.notna(last.get("boll_lower")):
            close = last["close"]
            upper = last["boll_upper"]
            lower = last["boll_lower"]
            band_width = upper - lower
            if band_width > 0:
                position = (close - lower) / band_width
                scores["bollinger"] = 1 - position  # lower position = more bullish

    # CCI signal
    if "cci" in df.columns and pd.notna(last.get("cci")):
        cci = last["cci"]
        if cci < -200:
            scores["cci"] = 0.9
        elif cci < -100:
            scores["cci"] = 0.7
        elif cci > 200:
            scores["cci"] = 0.1
        elif cci > 100:
            scores["cci"] = 0.3
        else:
            scores["cci"] = 0.5

    # ADX trend strength
    if "adx" in df.columns and pd.notna(last.get("adx")):
        adx = last["adx"]
        if adx > 25:  # strong trend
            plus_di = last.get("plus_di", 0)
            minus_di = last.get("minus_di", 0)
            if pd.notna(plus_di) and pd.notna(minus_di):
                scores["adx"] = 0.7 if plus_di > minus_di else 0.3
        else:
            scores["adx"] = 0.5

    # Composite score
    if scores:
        composite = sum(scores.values()) / len(scores)
    else:
        composite = 0.5

    # Map to signal
    if composite >= 0.75:
        signal = Signal.STRONG_BUY
    elif composite >= 0.6:
        signal = Signal.BUY
    elif composite <= 0.25:
        signal = Signal.STRONG_SELL
    elif composite <= 0.4:
        signal = Signal.SELL
    else:
        signal = Signal.HOLD

    return {
        "composite_score": round(composite, 4),
        "signal": signal,
        "details": scores,
    }


def generate_signals(df: pd.DataFrame) -> dict[str, Any]:
    """Full signal generation: indicators + patterns combined.

    Args:
        df: DataFrame with OHLCV columns (open, high, low, close, volume)

    Returns:
        Comprehensive signal analysis dict
    """
    # Calculate indicators
    df_with_indicators = calculate_all_indicators(df)

    # Score indicators
    indicator_result = score_indicators(df_with_indicators)

    # Pattern analysis
    pattern_result = get_pattern_summary(df)

    # Combine: 70% indicators, 30% patterns
    indicator_score = indicator_result["composite_score"]
    pattern_score = pattern_result["bullish_score"]
    combined_score = 0.7 * indicator_score + 0.3 * pattern_score

    if combined_score >= 0.75:
        final_signal = Signal.STRONG_BUY
    elif combined_score >= 0.6:
        final_signal = Signal.BUY
    elif combined_score <= 0.25:
        final_signal = Signal.STRONG_SELL
    elif combined_score <= 0.4:
        final_signal = Signal.SELL
    else:
        final_signal = Signal.HOLD

    return {
        "signal": final_signal,
        "combined_score": round(combined_score, 4),
        "indicator_scores": indicator_result.get("details", {}),
        "indicator_analysis": indicator_result,
        "pattern_analysis": pattern_result,
    }
