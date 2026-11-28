
"""
File: indicators.py
System: Binance Spot V3 Smart Signal Scanner
Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Test Status: LOCAL BASIC TEST PASS; REPOSITORY INTEGRATION NOT RUN

Pure indicator and market-structure calculations.
Input DataFrames require open, high, low, close, volume.
Caller must provide closed candles only.
"""

from __future__ import annotations

from typing import Any
import copy
import math

import numpy as np
import pandas as pd

from config import INDICATOR_CONFIG, MARKET_STRUCTURE_CONFIG


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def validate_dataframe(df: pd.DataFrame, min_rows: int = 2) -> bool:
    if not isinstance(df, pd.DataFrame) or len(df) < min_rows:
        return False
    if not set(REQUIRED_COLUMNS).issubset(df.columns):
        return False

    values = df.loc[:, REQUIRED_COLUMNS].apply(
        pd.to_numeric, errors="coerce"
    )

    if values.isna().any().any():
        return False

    if not np.isfinite(values.to_numpy(dtype=float)).all():
        return False

    if (values["close"] <= 0).any() or (values["volume"] < 0).any():
        return False

    if (
        values["high"]
        < values[["open", "close", "low"]].max(axis=1)
    ).any():
        return False

    if (
        values["low"]
        > values[["open", "close", "high"]].min(axis=1)
    ).any():
        return False

    return True


def _series(data: Any, name: str = "close") -> pd.Series:
    if isinstance(data, pd.DataFrame):
        if name not in data.columns:
            raise ValueError(f"DataFrame missing column: {name}")
        result = pd.to_numeric(data[name], errors="coerce")
    else:
        result = pd.to_numeric(pd.Series(data), errors="coerce")
    return result.astype(float)


def calculate_ema(data: Any, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    return _series(data).ewm(
        span=period, adjust=False, min_periods=period
    ).mean()


def calculate_sma(data: Any, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("SMA period must be positive")
    return _series(data).rolling(
        period, min_periods=period
    ).mean()


def calculate_rsi(data: Any, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("RSI period must be positive")

    close = _series(data)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)

    return rsi.clip(0, 100)


def calculate_macd(
    data: Any,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    if min(fast, slow, signal) <= 0 or fast >= slow:
        raise ValueError("MACD requires 0 < fast < slow")

    close = _series(data)

    fast_ema = close.ewm(
        span=fast, adjust=False, min_periods=slow
    ).mean()

    slow_ema = close.ewm(
        span=slow, adjust=False, min_periods=slow
    ).mean()

    macd_line = fast_ema - slow_ema

    signal_line = macd_line.ewm(
        span=signal, adjust=False, min_periods=signal
    ).mean()

    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        },
        index=close.index,
    )


def calculate_true_range(df: pd.DataFrame) -> pd.Series:
    if not {"high", "low", "close"}.issubset(df.columns):
        raise ValueError("Requires high, low and close")

    high = _series(df, "high")
    low = _series(df, "low")
    previous_close = _series(df, "close").shift(1)

    return pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("ATR period must be positive")

    return calculate_true_range(df).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("ADX period must be positive")

    high = _series(df, "high")
    low = _series(df, "low")

    tr = calculate_true_range(df)
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where(
        (up_move > down_move) & (up_move > 0), 0.0
    )

    minus_dm = down_move.where(
        (down_move > up_move) & (down_move > 0), 0.0
    )

    atr = tr.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()

    plus_di = (
        100
        * plus_dm.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()
        / atr.replace(0, np.nan)
    )

    minus_di = (
        100
        * minus_dm.ewm(
            alpha=1 / period, adjust=False, min_periods=period
        ).mean()
        / atr.replace(0, np.nan)
    )

    denominator = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denominator

    return dx.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean().clip(0, 100)


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    if not {"high", "low", "close", "volume"}.issubset(df.columns):
        raise ValueError("VWAP requires OHLCV")

    typical = (
        _series(df, "high")
        + _series(df, "low")
        + _series(df, "close")
    ) / 3

    volume = _series(df, "volume")
    cumulative_volume = volume.cumsum().replace(0, np.nan)

    return (typical * volume).cumsum() / cumulative_volume


def calculate_relative_volume(
    volume: Any, period: int = 20
) -> pd.Series:
    if period <= 0:
        raise ValueError("RVOL period must be positive")

    series = (
        _series(volume, "volume")
        if isinstance(volume, pd.DataFrame)
        else _series(volume)
    )

    # Baseline excludes the current candle to avoid self-inflation.
    baseline = series.shift(1).rolling(
        period, min_periods=period
    ).mean()

    return series / baseline.replace(0, np.nan)


def calculate_volume_momentum(
    volume: Any, period: int = 20
) -> pd.Series:
    if period <= 0:
        raise ValueError("Volume momentum period must be positive")

    series = (
        _series(volume, "volume")
        if isinstance(volume, pd.DataFrame)
        else _series(volume)
    )

    average = series.rolling(
        period, min_periods=period
    ).mean()

    return series / average.replace(0, np.nan) - 1.0


def calculate_roc(data: Any, period: int = 12) -> pd.Series:
    if period <= 0:
        raise ValueError("ROC period must be positive")
    return _series(data).pct_change(periods=period) * 100.0


def calculate_obv(df: pd.DataFrame) -> pd.Series:
    close = _series(df, "close")
    volume = _series(df, "volume")
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def calculate_cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    if period <= 0:
        raise ValueError("CMF period must be positive")

    high = _series(df, "high")
    low = _series(df, "low")
    close = _series(df, "close")
    volume = _series(df, "volume")

    spread = (high - low).replace(0, np.nan)

    multiplier = (
        (close - low) - (high - close)
    ) / spread

    money_flow_volume = multiplier.fillna(0) * volume

    numerator = money_flow_volume.rolling(
        period, min_periods=period
    ).sum()

    denominator = volume.rolling(
        period, min_periods=period
    ).sum().replace(0, np.nan)

    return numerator / denominator


def calculate_bollinger_bands(
    data: Any,
    period: int = 20,
    standard_deviation: float = 2.0,
) -> pd.DataFrame:
    if period <= 0 or standard_deviation <= 0:
        raise ValueError("Invalid Bollinger Band parameters")

    close = _series(data)

    middle = close.rolling(
        period, min_periods=period
    ).mean()

    std = close.rolling(
        period, min_periods=period
    ).std(ddof=0)

    upper = middle + standard_deviation * std
    lower = middle - standard_deviation * std

    width = (upper - lower) / middle.replace(0, np.nan)

    percent_b = (
        (close - lower) / (upper - lower).replace(0, np.nan)
    )

    return pd.DataFrame(
        {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "width": width,
            "percent_b": percent_b,
        },
        index=close.index,
    )


def support_resistance(
    df: pd.DataFrame,
    lookback: int = 50,
    pivot_left: int = 3,
    pivot_right: int = 3,
) -> dict[str, list[float]]:
    if lookback <= 0 or pivot_left < 1 or pivot_right < 1:
        raise ValueError("Invalid support/resistance parameters")

    if not {"high", "low"}.issubset(df.columns):
        raise ValueError("Requires high and low")

    data = df.tail(lookback)
    highs = _series(data, "high").to_numpy()
    lows = _series(data, "low").to_numpy()

    resistance: list[float] = []
    support: list[float] = []

    for i in range(pivot_left, len(data) - pivot_right):
        high_window = highs[i-pivot_left:i+pivot_right+1]
        low_window = lows[i-pivot_left:i+pivot_right+1]

        if highs[i] >= np.max(high_window):
            resistance.append(float(highs[i]))

        if lows[i] <= np.min(low_window):
            support.append(float(lows[i]))

    return {
        "support": sorted(set(support)),
        "resistance": sorted(set(resistance)),
    }


def analyze_candles(df: pd.DataFrame) -> dict[str, Any]:
    if not validate_dataframe(df, min_rows=2):
        raise ValueError("Invalid OHLCV DataFrame")

    last = df.iloc[-1]
    previous = df.iloc[-2]

    open_price = float(last["open"])
    close_price = float(last["close"])
    high_price = float(last["high"])
    low_price = float(last["low"])

    candle_range = high_price - low_price
    body = abs(close_price - open_price)

    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price

    return {
        "bullish": close_price > open_price,
        "bearish": close_price < open_price,

        "bullish_engulfing": bool(
            previous["close"] < previous["open"]
            and close_price > open_price
            and open_price <= previous["close"]
            and close_price >= previous["open"]
        ),

        "bearish_engulfing": bool(
            previous["close"] > previous["open"]
            and close_price < open_price
            and open_price >= previous["close"]
            and close_price <= previous["open"]
        ),

        "body_to_range": (
            body / candle_range if candle_range > 0 else 0.0
        ),

        "upper_wick_ratio": (
            upper_wick / candle_range if candle_range > 0 else 0.0
        ),

        "lower_wick_ratio": (
            lower_wick / candle_range if candle_range > 0 else 0.0
        ),
    }


def detect_market_structure(
    df: pd.DataFrame,
    lookback: int | None = None,
    pivot_left: int = 3,
    pivot_right: int = 3,
) -> dict[str, Any]:
    if not validate_dataframe(
        df, min_rows=pivot_left + pivot_right + 3
    ):
        raise ValueError("Insufficient or invalid structure data")

    window = int(
        lookback or MARKET_STRUCTURE_CONFIG.get(
            "structure_lookback", 50
        )
    )

    pivots = support_resistance(
        df, window, pivot_left, pivot_right
    )

    highs = pivots["resistance"]
    lows = pivots["support"]

    close = float(df["close"].iloc[-1])
    previous_close = float(df["close"].iloc[-2])

    latest_high = highs[-1] if highs else None
    latest_low = lows[-1] if lows else None

    prior_high = highs[-2] if len(highs) >= 2 else None
    prior_low = lows[-2] if len(lows) >= 2 else None

    bullish_bos = bool(
        latest_high is not None
        and previous_close <= latest_high < close
    )

    bearish_bos = bool(
        latest_low is not None
        and previous_close >= latest_low > close
    )

    higher_high = bool(
        latest_high is not None
        and prior_high is not None
        and latest_high > prior_high
    )

    higher_low = bool(
        latest_low is not None
        and prior_low is not None
        and latest_low > prior_low
    )

    lower_high = bool(
        latest_high is not None
        and prior_high is not None
        and latest_high < prior_high
    )

    lower_low = bool(
        latest_low is not None
        and prior_low is not None
        and latest_low < prior_low
    )

    return {
        "higher_high": higher_high,
        "higher_low": higher_low,
        "lower_high": lower_high,
        "lower_low": lower_low,
        "bullish_bos": bullish_bos,
        "bearish_bos": bearish_bos,
        "choch_bullish": bool(bullish_bos and (lower_high or lower_low)),
        "choch_bearish": bool(bearish_bos and (higher_high or higher_low)),
        "latest_swing_high": latest_high,
        "latest_swing_low": latest_low,
        "support": lows,
        "resistance": highs,
    }


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if not validate_dataframe(df, min_rows=2):
        raise ValueError("Invalid OHLCV DataFrame")

    out = df.copy()
    cfg = INDICATOR_CONFIG

    for period in cfg.get("ema_periods", [20, 50, 200]):
        out[f"ema_{period}"] = calculate_ema(
            out["close"], int(period)
        )

    rsi_cfg = cfg.get("rsi", {})
    out["rsi"] = calculate_rsi(
        out["close"], int(rsi_cfg.get("period", 14))
    )

    macd_cfg = cfg.get("macd", {})
    macd = calculate_macd(
        out["close"],
        int(macd_cfg.get("fast", 12)),
        int(macd_cfg.get("slow", 26)),
        int(macd_cfg.get("signal", 9)),
    )

    out["macd"] = macd["macd"]
    out["macd_signal"] = macd["signal"]
    out["macd_histogram"] = macd["histogram"]

    out["atr"] = calculate_atr(
        out, int(cfg.get("atr", {}).get("period", 14))
    )

    out["adx"] = calculate_adx(
        out, int(cfg.get("adx", {}).get("period", 14))
    )

    out["vwap"] = calculate_vwap(out)

    out["rvol"] = calculate_relative_volume(
        out["volume"],
        int(cfg.get("rvol", {}).get("period", 20)),
    )

    out["volume_momentum"] = calculate_volume_momentum(
        out["volume"],
        int(cfg.get("rvol", {}).get("period", 20)),
    )

    out["roc"] = calculate_roc(
        out["close"],
        int(cfg.get("roc", {}).get("period", 12)),
    )

    out["obv"] = calculate_obv(out)
    out["cmf"] = calculate_cmf(out, 20)

    bb_cfg = cfg.get("bollinger", {})

    bands = calculate_bollinger_bands(
        out["close"],
        int(bb_cfg.get("period", 20)),
        float(bb_cfg.get("standard_deviation", 2.0)),
    )

    for column in bands.columns:
        out[f"bb_{column}"] = bands[column]

    return out


def get_latest_indicator_snapshot(
    df: pd.DataFrame,
) -> dict[str, Any]:
    enriched = calculate_all_indicators(df)
    row = enriched.iloc[-1]

    result: dict[str, Any] = {}

    for key, value in row.items():
        if isinstance(value, (np.integer, int)):
            result[key] = int(value)
        elif isinstance(value, (np.floating, float)):
            number = float(value)
            result[key] = number if math.isfinite(number) else None
        else:
            result[key] = value

    result["market_structure"] = detect_market_structure(df)
    result["candle_analysis"] = analyze_candles(df)

    return result


def get_indicator_config() -> dict[str, Any]:
    return copy.deepcopy(INDICATOR_CONFIG)


# Compatibility aliases for the new codebase.
calculate_rvol = calculate_relative_volume
calculate_bollinger = calculate_bollinger_bands
