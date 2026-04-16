"""Technical analysis indicators module.

Provides 30+ technical indicators using TA-Lib and pandas.
Ported from Stock2's core/indicator.py.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_talib(func_name: str, *args, **kwargs) -> Any:
    """Safely call a TA-Lib function, returning None if unavailable."""
    try:
        import talib
        func = getattr(talib, func_name)
        return func(*args, **kwargs)
    except ImportError:
        logger.warning("TA-Lib not installed, using pandas fallback for %s", func_name)
        return None
    except Exception as e:
        logger.error("TA-Lib %s failed: %s", func_name, e)
        return None


def calculate_ma(close: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    return close.rolling(window=period).mean()


def calculate_ema(close: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return close.ewm(span=period, adjust=False).mean()


def calculate_macd(
    close: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD (Moving Average Convergence Divergence).

    Returns: (macd_line, signal_line, histogram)
    """
    result = _safe_talib("MACD", close.values, fastperiod=fast_period,
                         slowperiod=slow_period, signalperiod=signal_period)
    if result is not None:
        return pd.Series(result[0], index=close.index), \
               pd.Series(result[1], index=close.index), \
               pd.Series(result[2], index=close.index)

    # Pandas fallback
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    fastk_period: int = 9,
    slowk_period: int = 3,
    slowd_period: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """KDJ indicator.

    Returns: (K, D, J)
    """
    result = _safe_talib("STOCH", high.values, low.values, close.values,
                         fastk_period=fastk_period, slowk_period=slowk_period,
                         slowd_period=slowd_period)
    if result is not None:
        k = pd.Series(result[0], index=close.index)
        d = pd.Series(result[1], index=close.index)
        j = 3 * k - 2 * d
        return k, d, j

    # Pandas fallback
    lowest_low = low.rolling(window=fastk_period).min()
    highest_high = high.rolling(window=fastk_period).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    k = rsv.ewm(com=slowk_period - 1, adjust=False).mean()
    d = k.ewm(com=slowd_period - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    result = _safe_talib("RSI", close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_bollinger(
    close: pd.Series,
    period: int = 20,
    nbdev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Returns: (upper, middle, lower)
    """
    result = _safe_talib("BBANDS", close.values, timeperiod=period,
                         nbdevup=nbdev, nbdevdn=nbdev)
    if result is not None:
        return pd.Series(result[0], index=close.index), \
               pd.Series(result[1], index=close.index), \
               pd.Series(result[2], index=close.index)

    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + nbdev * std
    lower = middle - nbdev * std
    return upper, middle, lower


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range."""
    result = _safe_talib("ATR", high.values, low.values, close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Commodity Channel Index."""
    result = _safe_talib("CCI", high.values, low.values, close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)

    tp = (high + low + close) / 3
    ma = tp.rolling(window=period).mean()
    md = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
    return (tp - ma) / (0.015 * md)


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    result = _safe_talib("OBV", close.values, volume.values.astype(float))
    if result is not None:
        return pd.Series(result, index=close.index)

    direction = np.sign(close.diff())
    return (volume * direction).cumsum()


def calculate_sar(
    high: pd.Series,
    low: pd.Series,
    acceleration: float = 0.02,
    maximum: float = 0.2,
) -> pd.Series:
    """Parabolic SAR."""
    result = _safe_talib("SAR", high.values, low.values,
                         acceleration=acceleration, maximum=maximum)
    if result is not None:
        return pd.Series(result, index=high.index)
    return pd.Series(np.nan, index=high.index)


def calculate_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average Directional Index."""
    result = _safe_talib("ADX", high.values, low.values, close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)
    return pd.Series(np.nan, index=close.index)


def calculate_dmi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Directional Movement Index.

    Returns: (plus_di, minus_di, adx)
    """
    plus_di_res = _safe_talib("PLUS_DI", high.values, low.values, close.values, timeperiod=period)
    minus_di_res = _safe_talib("MINUS_DI", high.values, low.values, close.values, timeperiod=period)
    adx_res = _safe_talib("ADX", high.values, low.values, close.values, timeperiod=period)

    plus_di = pd.Series(plus_di_res, index=close.index) if plus_di_res is not None else pd.Series(np.nan, index=close.index)
    minus_di = pd.Series(minus_di_res, index=close.index) if minus_di_res is not None else pd.Series(np.nan, index=close.index)
    adx = pd.Series(adx_res, index=close.index) if adx_res is not None else pd.Series(np.nan, index=close.index)
    return plus_di, minus_di, adx


def calculate_williams_r(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Williams %R."""
    result = _safe_talib("WILLR", high.values, low.values, close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)

    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    return -100 * (highest_high - close) / (highest_high - lowest_low)


def calculate_roc(close: pd.Series, period: int = 12) -> pd.Series:
    """Rate of Change."""
    result = _safe_talib("ROC", close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)
    return ((close - close.shift(period)) / close.shift(period)) * 100


def calculate_mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Money Flow Index."""
    result = _safe_talib("MFI", high.values, low.values, close.values,
                         volume.values.astype(float), timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)

    tp = (high + low + close) / 3
    raw_mf = tp * volume
    positive_mf = raw_mf.where(tp > tp.shift(1), 0)
    negative_mf = raw_mf.where(tp < tp.shift(1), 0)
    pos_sum = positive_mf.rolling(window=period).sum()
    neg_sum = negative_mf.rolling(window=period).sum()
    mfi = 100 - (100 / (1 + pos_sum / neg_sum))
    return mfi


def calculate_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Volume Weighted Average Price."""
    tp = (high + low + close) / 3
    return (tp * volume).cumsum() / volume.cumsum()


def calculate_trix(close: pd.Series, period: int = 15) -> pd.Series:
    """Triple EMA (TRIX)."""
    result = _safe_talib("TRIX", close.values, timeperiod=period)
    if result is not None:
        return pd.Series(result, index=close.index)

    ema1 = close.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return ema3.pct_change() * 100


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all indicators and add them as columns to the DataFrame.

    Expects columns: open, high, low, close, volume
    """
    df = df.copy()

    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]

    # Moving Averages
    for p in (5, 10, 20, 60):
        df[f"ma_{p}"] = calculate_ma(c, p)
        df[f"ema_{p}"] = calculate_ema(c, p)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = calculate_macd(c)

    # KDJ
    df["kdj_k"], df["kdj_d"], df["kdj_j"] = calculate_kdj(h, l, c)

    # RSI
    for p in (6, 12, 24):
        df[f"rsi_{p}"] = calculate_rsi(c, p)

    # Bollinger Bands
    df["boll_upper"], df["boll_mid"], df["boll_lower"] = calculate_bollinger(c)

    # ATR
    df["atr"] = calculate_atr(h, l, c)

    # Donchian Channels (for Turtle strategy)
    df["high_20"] = h.rolling(20).max()
    df["low_10"] = l.rolling(10).min()
    df["high_55"] = h.rolling(55).max()
    df["low_20"] = l.rolling(20).min()

    # CCI
    df["cci"] = calculate_cci(h, l, c)

    # OBV
    df["obv"] = calculate_obv(c, v)

    # SAR
    df["sar"] = calculate_sar(h, l)

    # ADX + DMI
    df["plus_di"], df["minus_di"], df["adx"] = calculate_dmi(h, l, c)

    # Williams %R
    df["willr"] = calculate_williams_r(h, l, c)

    # ROC
    df["roc"] = calculate_roc(c)

    # MFI
    df["mfi"] = calculate_mfi(h, l, c, v)

    # VWAP
    df["vwap"] = calculate_vwap(h, l, c, v)

    # TRIX
    df["trix"] = calculate_trix(c)

    return df
