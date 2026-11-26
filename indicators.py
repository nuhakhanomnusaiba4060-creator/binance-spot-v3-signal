"""
Binance Spot V3 Smart Signal Scanner
Technical Indicators Engine

Volume policy:
- Base volume: VWAP, OBV, CMF
- Quote volume: RVOL, volume momentum
- Original OHLCV data is preserved.
- Missing RVOL data remains NaN; it is never replaced with 1.0.
"""

import logging

import numpy as np
import pandas as pd

from config import INDICATOR_CONFIG

logger = logging.getLogger(__name__)


def _normalise_key(value):
    return "".join(c for c in str(value).upper() if c.isalnum())


def _find_config_value(target):
    target = _normalise_key(target)

    def search(mapping):
        if not isinstance(mapping, dict):
            return None

        for key, value in mapping.items():
            if _normalise_key(key) == target:
                return value

        for value in mapping.values():
            if isinstance(value, dict):
                result = search(value)
                if result is not None:
                    return result

        return None

    return search(INDICATOR_CONFIG)


def _get_setting(name, default, paths=()):
    for path in paths:
        current = INDICATOR_CONFIG
        found = True
        try:
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    found = False
                    break
                current = current[key]
            if found and current is not None:
                return current
        except (KeyError, TypeError):
            continue

    value = _find_config_value(name)
    return default if value is None else value


def _get_rvol_period():
    for key_name in ("RVOL_BASELINE_PERIOD", "RVOL_PERIOD", "BASELINE_CANDLES"):
        value = _find_config_value(key_name)
        if value is not None:
            period = int(value)
            if period < 2:
                raise ValueError("RVOL period must be at least 2.")
            return period

    return 20


EMA_FAST = int(_get_setting("EMA_FAST", 9, paths=(("EMA", "FAST"),)))
EMA_SLOW = int(_get_setting("EMA_SLOW", 20, paths=(("EMA", "SLOW"),)))

SMA_PERIODS = tuple(
    int(v) for v in _get_setting("SMA_PERIODS", (20, 50, 200))
)

RSI_PERIOD = int(_get_setting("RSI_PERIOD", 14))

MACD_FAST = int(_get_setting("MACD_FAST", 12, paths=(("MACD", "FAST"),)))
MACD_SLOW = int(_get_setting("MACD_SLOW", 26, paths=(("MACD", "SLOW"),)))
MACD_SIGNAL = int(_get_setting("MACD_SIGNAL", 9, paths=(("MACD", "SIGNAL"),)))

ADX_PERIOD = int(_get_setting("ADX_PERIOD", 14))
ATR_PERIOD = int(_get_setting("ATR_PERIOD", 14))

BOLLINGER_PERIOD = int(
    _get_setting("BOLLINGER_PERIOD", 20, paths=(("BB_PERIOD",),))
)
BOLLINGER_STD = float(
    _get_setting("BOLLINGER_STD", 2.0, paths=(("BB_STD_DEV",),))
)

RVOL_PERIOD = _get_rvol_period()

CMF_PERIOD = int(_get_setting("CMF_PERIOD", 20, paths=(("OBV_CMF_PERIOD",),)))

SUPPORT_RESISTANCE_LOOKBACK = int(
    _get_setting("SUPPORT_RESISTANCE_LOOKBACK", 100)
)

PIVOT_LEFT = int(_get_setting("PIVOT_LEFT", 3))
PIVOT_RIGHT = int(_get_setting("PIVOT_RIGHT", 3))

MIN_CANDLES_FOR_MA200 = int(
    _get_setting(
        "MIN_CANDLES_FOR_MA200",
        220,
        paths=(("MIN_CANDLE_HISTORY",),),
    )
)

ROC_PERIOD = int(_get_setting("ROC_PERIOD", 5))

VOLUME_MOMENTUM_PERIOD = int(
    _get_setting("VOLUME_MOMENTUM_PERIOD", 3)
)


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def validate_dataframe(df):
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    result = df.copy()

    for column in REQUIRED_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.replace([np.inf, -np.inf], np.nan)
    result = result.dropna(subset=REQUIRED_COLUMNS)

    if result.empty:
        raise ValueError("No valid OHLCV data available.")

    invalid_values = (
        (result["open"] <= 0)
        | (result["high"] <= 0)
        | (result["low"] <= 0)
        | (result["close"] <= 0)
        | (result["volume"] < 0)
    )
    if invalid_values.any():
        raise ValueError("OHLCV contains invalid prices or volume.")

    invalid_ranges = (
        (result["high"] < result["low"])
        | (result["high"] < result["open"])
        | (result["high"] < result["close"])
        | (result["low"] > result["open"])
        | (result["low"] > result["close"])
    )
    if invalid_ranges.any():
        raise ValueError("OHLCV candle contains an invalid price range.")

    result["base_volume"] = result["volume"].astype("float64")

    if "quote_volume" in result.columns:
        quote = pd.to_numeric(result["quote_volume"], errors="coerce")
        quote = quote.replace([np.inf, -np.inf], np.nan)
        quote = quote.where(quote >= 0)

        estimated_quote = result["base_volume"] * result["close"]
        result["quote_volume"] = quote.where(quote.notna(), estimated_quote)
    else:
        result["quote_volume"] = result["base_volume"] * result["close"]

    if "open_time" in result.columns:
        numeric_time = pd.to_numeric(result["open_time"], errors="coerce")

        if numeric_time.notna().all():
            result["open_time"] = numeric_time
            result = result.sort_values("open_time", kind="stable")
        else:
            datetime_time = pd.to_datetime(
                result["open_time"],
                utc=True,
                errors="coerce",
            )
            if datetime_time.isna().any():
                raise ValueError("Invalid open_time values.")

            result["open_time"] = datetime_time
            result = result.sort_values("open_time", kind="stable")

        result = result.drop_duplicates(subset=["open_time"], keep="last")

    result = result.reset_index(drop=True)

    if result.empty:
        raise ValueError("No valid candles remain after validation.")

    return result


def calculate_ema(data, period):
    if period < 1:
        raise ValueError("EMA period must be positive.")

    series = pd.Series(data, dtype="float64")
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def calculate_sma(data, period):
    if period < 1:
        raise ValueError("SMA period must be positive.")

    series = pd.Series(data, dtype="float64")
    return series.rolling(window=period, min_periods=period).mean()


def calculate_rsi(data, period=RSI_PERIOD):
    if period < 1:
        raise ValueError("RSI period must be positive.")

    close = pd.Series(data, dtype="float64")
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)

    return rsi.clip(0.0, 100.0)


def calculate_macd(
    data,
    fast=MACD_FAST,
    slow=MACD_SLOW,
    signal=MACD_SIGNAL,
):
    if fast >= slow:
        raise ValueError("MACD fast must be smaller than slow.")

    close = pd.Series(data, dtype="float64")
    ema_fast = calculate_ema(close, fast)
    ema_slow = calculate_ema(close, slow)

    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
    })


def calculate_true_range(df):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    previous_close = close.shift(1)

    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def calculate_atr(df, period=ATR_PERIOD):
    if period < 1:
        raise ValueError("ATR period must be positive.")

    tr = calculate_true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def calculate_adx(df, period=ADX_PERIOD):
    if period < 1:
        raise ValueError("ADX period must be positive.")

    high = df["high"]
    low = df["low"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )

    atr = calculate_atr(df, period)

    smoothed_plus = plus_dm.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    smoothed_minus = minus_dm.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()

    plus_di = 100.0 * smoothed_plus / atr.replace(0, np.nan)
    minus_di = 100.0 * smoothed_minus / atr.replace(0, np.nan)

    denominator = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denominator

    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    return pd.DataFrame({
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    })


def calculate_vwap(df):
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["base_volume"] if "base_volume" in df.columns else df["volume"]
    price_volume = typical_price * volume

    if "open_time" in df.columns:
        if pd.api.types.is_numeric_dtype(df["open_time"]):
            timestamps = pd.to_datetime(
                df["open_time"], unit="ms", utc=True, errors="coerce"
            )
        else:
            timestamps = pd.to_datetime(
                df["open_time"], utc=True, errors="coerce"
            )

        if timestamps.isna().any():
            raise ValueError("Invalid open_time values for VWAP.")

        utc_dates = timestamps.dt.strftime("%Y-%m-%d")
        cumulative_pv = price_volume.groupby(utc_dates, sort=False).cumsum()
        cumulative_volume = volume.groupby(utc_dates, sort=False).cumsum()
    else:
        cumulative_pv = price_volume.cumsum()
        cumulative_volume = volume.cumsum()

    return cumulative_pv / cumulative_volume.replace(0, np.nan)


def calculate_relative_volume(volume, period=RVOL_PERIOD):
    if period < 2:
        raise ValueError("RVOL period must be at least 2.")

    series = pd.Series(volume, dtype="float64")
    average_volume = (
        series.shift(1).rolling(window=period, min_periods=period).mean()
    )

    result = series / average_volume.replace(0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def calculate_volume_momentum(
    volume,
    period=VOLUME_MOMENTUM_PERIOD,
):
    if period < 1:
        raise ValueError("Volume momentum period must be positive.")

    series = pd.Series(volume, dtype="float64")
    previous_avg = (
        series.shift(1).rolling(window=period, min_periods=period).mean()
    )

    result = series / previous_avg.replace(0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def calculate_roc(data, period=ROC_PERIOD):
    if period < 1:
        raise ValueError("ROC period must be positive.")

    close = pd.Series(data, dtype="float64")
    return ((close - close.shift(period)) / close.shift(period).replace(0, np.nan)) * 100.0


def calculate_obv(df):
    direction = np.sign(df["close"].diff()).fillna(0.0)
    volume = df["base_volume"] if "base_volume" in df.columns else df["volume"]
    return (direction * volume).cumsum()


def calculate_cmf(df, period=CMF_PERIOD):
    if period < 1:
        raise ValueError("CMF period must be positive.")

    price_range = (df["high"] - df["low"]).replace(0, np.nan)
    multiplier = (
        ((df["close"] - df["low"]) - (df["high"] - df["close"])) / price_range
    ).fillna(0.0)

    volume = df["base_volume"] if "base_volume" in df.columns else df["volume"]
    money_flow_volume = multiplier * volume

    volume_sum = volume.rolling(window=period, min_periods=period).sum()
    money_flow_sum = money_flow_volume.rolling(window=period, min_periods=period).sum()

    return money_flow_sum / volume_sum.replace(0, np.nan)


def calculate_bollinger_bands(
    data,
    period=BOLLINGER_PERIOD,
    std_dev=BOLLINGER_STD,
):
    if period < 1 or std_dev <= 0:
        raise ValueError("Invalid Bollinger Band parameters.")

    close = pd.Series(data, dtype="float64")
    middle = close.rolling(window=period, min_periods=period).mean()
    standard_deviation = close.rolling(window=period, min_periods=period).std(ddof=0)

    upper = middle + std_dev * standard_deviation
    lower = middle - std_dev * standard_deviation
    bb_width = (upper - lower) / middle.replace(0, np.nan)

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
        "bb_width": bb_width,
    })


def support_resistance(
    df,
    lookback=SUPPORT_RESISTANCE_LOOKBACK,
    left=PIVOT_LEFT,
    right=PIVOT_RIGHT,
):
    if lookback < 10 or left < 1 or right < 1:
        raise ValueError("Invalid support/resistance parameters.")

    if df.empty:
        return {"support": None, "resistance": None}

    recent = df.tail(lookback).reset_index(drop=True)
    if len(recent) < left + right + 1:
        return {"support": None, "resistance": None}

    current_price = float(recent["close"].iloc[-1])
    pivot_lows = []
    pivot_highs = []
    last_confirmed = len(recent) - right

    for index in range(left, last_confirmed):
        low_value = float(recent["low"].iloc[index])
        high_value = float(recent["high"].iloc[index])

        left_lows = recent["low"].iloc[index - left : index]
        right_lows = recent["low"].iloc[index + 1 : index + right + 1]

        left_highs = recent["high"].iloc[index - left : index]
        right_highs = recent["high"].iloc[index + 1 : index + right + 1]

        if low_value < left_lows.min() and low_value < right_lows.min():
            pivot_lows.append(low_value)

        if high_value > left_highs.max() and high_value > right_highs.max():
            pivot_highs.append(high_value)

    supports = [value for value in pivot_lows if value < current_price]
    resistances = [value for value in pivot_highs if value > current_price]

    return {
        "support": max(supports) if supports else None,
        "resistance": min(resistances) if resistances else None,
    }


def analyze_candles(df):
    if len(df) < 2:
        return {
            "candle_direction": "UNKNOWN",
            "body_percent": None,
            "upper_wick_percent": None,
            "lower_wick_percent": None,
            "bullish_engulfing": False,
            "bearish_engulfing": False,
            "strong_bullish_candle": False,
            "strong_bearish_candle": False,
        }

    current = df.iloc[-1]
    previous = df.iloc[-2]

    open_price = float(current["open"])
    high = float(current["high"])
    low = float(current["low"])
    close = float(current["close"])

    candle_range = high - low

    if candle_range <= 0:
        body_percent = 0.0
        upper_wick_percent = 0.0
        lower_wick_percent = 0.0
    else:
        body = abs(close - open_price)
        upper_wick = high - max(open_price, close)
        lower_wick = min(open_price, close) - low

        body_percent = body / candle_range * 100.0
        upper_wick_percent = upper_wick / candle_range * 100.0
        lower_wick_percent = lower_wick / candle_range * 100.0

    bullish = close > open_price
    bearish = close < open_price

    previous_bullish = previous["close"] > previous["open"]
    previous_bearish = previous["close"] < previous["open"]

    bullish_engulfing = (
        bullish
        and previous_bearish
        and open_price <= previous["close"]
        and close >= previous["open"]
    )

    bearish_engulfing = (
        bearish
        and previous_bullish
        and open_price >= previous["close"]
        and close <= previous["open"]
    )

    return {
        "candle_direction": (
            "BULLISH" if bullish else "BEARISH" if bearish else "NEUTRAL"
        ),
        "body_percent": round(float(body_percent), 2),
        "upper_wick_percent": round(float(upper_wick_percent), 2),
        "lower_wick_percent": round(float(lower_wick_percent), 2),
        "bullish_engulfing": bool(bullish_engulfing),
        "bearish_engulfing": bool(bearish_engulfing),
        "strong_bullish_candle": bool(bullish and body_percent >= 65.0),
        "strong_bearish_candle": bool(bearish and body_percent >= 65.0),
    }


def calculate_all_indicators(df):
    result = validate_dataframe(df)
    close = result["close"]

    result[f"ema_{EMA_FAST}"] = calculate_ema(close, EMA_FAST)
    result[f"ema_{EMA_SLOW}"] = calculate_ema(close, EMA_SLOW)

    for period in SMA_PERIODS:
        column = f"sma_{period}"
        if period == 200 and len(result) < MIN_CANDLES_FOR_MA200:
            result[column] = np.nan
        else:
            result[column] = calculate_sma(close, period)

    result["rsi"] = calculate_rsi(close, RSI_PERIOD)

    macd = calculate_macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    result["macd"] = macd["macd"]
    result["macd_signal"] = macd["macd_signal"]
    result["macd_histogram"] = macd["macd_histogram"]

    adx = calculate_adx(result, ADX_PERIOD)
    result["adx"] = adx["adx"]
    result["plus_di"] = adx["plus_di"]
    result["minus_di"] = adx["minus_di"]

    result["atr"] = calculate_atr(result, ATR_PERIOD)
    result["vwap"] = calculate_vwap(result)

    result["relative_volume"] = calculate_relative_volume(
        result["quote_volume"],
        RVOL_PERIOD,
    )

    result["volume_momentum"] = calculate_volume_momentum(
        result["quote_volume"],
        VOLUME_MOMENTUM_PERIOD,
    )

    result["roc"] = calculate_roc(close, ROC_PERIOD)
    result["obv"] = calculate_obv(result)
    result["cmf"] = calculate_cmf(result, CMF_PERIOD)

    bands = calculate_bollinger_bands(close, BOLLINGER_PERIOD, BOLLINGER_STD)
    result["bb_upper"] = bands["bb_upper"]
    result["bb_middle"] = bands["bb_middle"]
    result["bb_lower"] = bands["bb_lower"]
    result["bb_width"] = bands["bb_width"]

    return result


def get_latest_indicator_snapshot(df):
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")

    if df.empty:
        raise ValueError("Cannot create snapshot from empty data.")

    enriched = calculate_all_indicators(df)
    latest = enriched.iloc[-1]

    def safe_value(column):
        value = latest.get(column)
        if value is None or pd.isna(value):
            return None
        return float(value)

    levels = support_resistance(enriched)
    candle_info = analyze_candles(enriched)

    return {
        "close": safe_value("close"),
        "ema_9": safe_value(f"ema_{EMA_FAST}"),
        "ema_20": safe_value(f"ema_{EMA_SLOW}"),
        "sma_20": safe_value("sma_20"),
        "sma_50": safe_value("sma_50"),
        "sma_200": safe_value("sma_200"),
        "rsi": safe_value("rsi"),
        "macd": safe_value("macd"),
        "macd_signal": safe_value("macd_signal"),
        "macd_histogram": safe_value("macd_histogram"),
        "adx": safe_value("adx"),
        "plus_di": safe_value("plus_di"),
        "minus_di": safe_value("minus_di"),
        "atr": safe_value("atr"),
        "vwap": safe_value("vwap"),
        "relative_volume": safe_value("relative_volume"),
        "volume_momentum": safe_value("volume_momentum"),
        "roc": safe_value("roc"),
        "obv": safe_value("obv"),
        "cmf": safe_value("cmf"),
        "bb_upper": safe_value("bb_upper"),
        "bb_middle": safe_value("bb_middle"),
        "bb_lower": safe_value("bb_lower"),
        "bb_width": safe_value("bb_width"),
        "support": levels["support"],
        "resistance": levels["resistance"],
        "candle_analysis": candle_info,
        "candle_count": len(enriched),
        "ma200_available": safe_value("sma_200") is not None,
    }


def get_indicator_config():
    return {
        "ema_fast": EMA_FAST,
        "ema_slow": EMA_SLOW,
        "sma_periods": SMA_PERIODS,
        "rsi_period": RSI_PERIOD,
        "macd_fast": MACD_FAST,
        "macd_slow": MACD_SLOW,
        "macd_signal": MACD_SIGNAL,
        "adx_period": ADX_PERIOD,
        "atr_period": ATR_PERIOD,
        "bollinger_period": BOLLINGER_PERIOD,
        "bollinger_std": BOLLINGER_STD,
        "rvol_period": RVOL_PERIOD,
        "cmf_period": CMF_PERIOD,
        "support_resistance_lookback": SUPPORT_RESISTANCE_LOOKBACK,
        "pivot_left": PIVOT_LEFT,
        "pivot_right": PIVOT_RIGHT,
        "min_candles_for_ma200": MIN_CANDLES_FOR_MA200,
        "roc_period": ROC_PERIOD,
        "volume_momentum_period": VOLUME_MOMENTUM_PERIOD,
    }
