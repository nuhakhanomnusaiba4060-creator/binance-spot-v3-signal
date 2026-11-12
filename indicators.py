"""
Binance Spot V3 Smart Signal Scanner
Technical Indicators Engine

Python: 3.11
Market: Binance Spot only

Input:
    Closed-candle pandas DataFrame from data_provider.py

Output:
    Individual indicator Series/DataFrames
    Enriched DataFrame
    Latest indicator snapshot

This module calculates indicators only.
It does NOT generate BUY/SELL signals.
"""

import logging

import numpy as np
import pandas as pd

from config import INDICATOR_CONFIG


logger = logging.getLogger(__name__)


# ==================================================
# 1. CONFIGURATION
# ==================================================

def _normalise_key(value):
    """Normalise configuration keys for matching."""
    return "".join(
        character
        for character in str(value).upper()
        if character.isalnum()
    )


def _find_config_value(target):
    """
    Find an exact configuration key recursively.
    Does not guess values from unrelated keys.
    """

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
    """
    Read a setting from INDICATOR_CONFIG.

    Supports both flat keys and common nested structures.
    Defaults match the V3 configuration specification.
    """

    for path in paths:
        current = INDICATOR_CONFIG

        try:
            for key in path:
                current = current[key]

            if current is not None:
                return current

        except (KeyError, TypeError):
            continue

    value = _find_config_value(name)

    if value is not None:
        return value

    return default


EMA_FAST = int(
    _get_setting(
        "EMA_FAST",
        9,
        paths=(
            ("EMA", "FAST"),
            ("EMA_PERIODS", "FAST"),
        ),
    )
)

EMA_SLOW = int(
    _get_setting(
        "EMA_SLOW",
        20,
        paths=(
            ("EMA", "SLOW"),
            ("EMA_PERIODS", "SLOW"),
        ),
    )
)

SMA_PERIODS = tuple(
    int(value)
    for value in _get_setting(
        "SMA_PERIODS",
        (20, 50, 200),
    )
)

RSI_PERIOD = int(
    _get_setting("RSI_PERIOD", 14)
)

MACD_FAST = int(
    _get_setting(
        "MACD_FAST",
        12,
        paths=(("MACD", "FAST"),),
    )
)

MACD_SLOW = int(
    _get_setting(
        "MACD_SLOW",
        26,
        paths=(("MACD", "SLOW"),),
    )
)

MACD_SIGNAL = int(
    _get_setting(
        "MACD_SIGNAL",
        9,
        paths=(("MACD", "SIGNAL"),),
    )
)

ADX_PERIOD = int(
    _get_setting("ADX_PERIOD", 14)
)

ATR_PERIOD = int(
    _get_setting("ATR_PERIOD", 14)
)

BOLLINGER_PERIOD = int(
    _get_setting(
        "BOLLINGER_PERIOD",
        20,
        paths=(("BOLLINGER", "PERIOD"),),
    )
)

BOLLINGER_STD = float(
    _get_setting(
        "BOLLINGER_STD",
        2.0,
        paths=(
            ("BOLLINGER", "STD"),
            ("BOLLINGER", "STD_DEV"),
        ),
    )
)

RVOL_PERIOD = int(
    _get_setting(
        "RVOL_PERIOD",
        20,
        paths=(
            ("RVOL", "PERIOD"),
            ("RELATIVE_VOLUME", "PERIOD"),
        ),
    )
)

CMF_PERIOD = int(
    _get_setting("CMF_PERIOD", 20)
)

SUPPORT_RESISTANCE_LOOKBACK = int(
    _get_setting(
        "SUPPORT_RESISTANCE_LOOKBACK",
        100,
    )
)

PIVOT_LEFT = int(
    _get_setting("PIVOT_LEFT", 3)
)

PIVOT_RIGHT = int(
    _get_setting("PIVOT_RIGHT", 3)
)

MIN_CANDLES_FOR_MA200 = int(
    _get_setting(
        "MIN_CANDLES_FOR_MA200",
        220,
    )
)

# 🔥 NEW INDICATOR SETTINGS
ROC_PERIOD = int(_get_setting("ROC_PERIOD", 5))  # 5-candle momentum
VOLUME_MOMENTUM_PERIOD = int(_get_setting("VOLUME_MOMENTUM_PERIOD", 3))


# Validate configuration at import time.

if EMA_FAST >= EMA_SLOW:
    raise ValueError("EMA_FAST must be smaller than EMA_SLOW.")

if MACD_FAST >= MACD_SLOW:
    raise ValueError("MACD_FAST must be smaller than MACD_SLOW.")

if min(
    RSI_PERIOD,
    ADX_PERIOD,
    ATR_PERIOD,
    BOLLINGER_PERIOD,
    RVOL_PERIOD,
    CMF_PERIOD,
) < 1:
    raise ValueError("Indicator periods must be positive.")

if BOLLINGER_STD <= 0:
    raise ValueError("BOLLINGER_STD must be positive.")

if not SMA_PERIODS or any(period < 1 for period in SMA_PERIODS):
    raise ValueError("SMA periods are invalid.")


# ==================================================
# 2. DATA VALIDATION
# ==================================================

REQUIRED_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def validate_dataframe(df):
    """
    Validate OHLCV data.

    - Requires OHLCV columns.
    - Converts numeric values.
    - Rejects invalid prices.
    - Sorts candles chronologically when open_time exists.
    - Removes duplicate open_time candles.
    - Returns a safe copy.
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            "Input must be a pandas DataFrame."
        )

    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing OHLCV columns: {missing}"
        )

    result = df.copy()

    for column in REQUIRED_COLUMNS:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result = result.replace(
        [np.inf, -np.inf],
        np.nan,
    )

    result = result.dropna(
        subset=REQUIRED_COLUMNS
    )

    if result.empty:
        raise ValueError(
            "No valid OHLCV data available."
        )

    # Validate OHLCV values.

    invalid_values = (
        (result["open"] <= 0)
        | (result["high"] <= 0)
        | (result["low"] <= 0)
        | (result["close"] <= 0)
        | (result["volume"] < 0)
    )

    if invalid_values.any():
        raise ValueError(
            "OHLCV contains invalid prices or volume."
        )

    # Validate candle price ranges.

    invalid_ranges = (
        (result["high"] < result["low"])
        | (result["high"] < result["open"])
        | (result["high"] < result["close"])
        | (result["low"] > result["open"])
        | (result["low"] > result["close"])
    )

    if invalid_ranges.any():
        raise ValueError(
            "OHLCV candle contains an invalid price range."
        )

    # Sort and deduplicate candles if open_time exists.

    if "open_time" in result.columns:

        numeric_time = pd.to_numeric(
            result["open_time"],
            errors="coerce",
        )

        if numeric_time.notna().all():

            result["open_time"] = numeric_time

            result = result.sort_values(
                "open_time",
                kind="stable",
            )

        else:

            datetime_time = pd.to_datetime(
                result["open_time"],
                utc=True,
                errors="coerce",
            )

            if datetime_time.isna().any():
                raise ValueError(
                    "Invalid open_time values."
                )

            result["open_time"] = datetime_time

            result = result.sort_values(
                "open_time",
                kind="stable",
            )

        result = result.drop_duplicates(
            subset=["open_time"],
            keep="last",
        )

    result = result.reset_index(drop=True)

    if result.empty:
        raise ValueError(
            "No valid candles remain after validation."
        )

    return result


# ==================================================
# 3. EMA
# ==================================================

def calculate_ema(data, period):
    """Calculate Exponential Moving Average."""

    if period < 1:
        raise ValueError(
            "EMA period must be positive."
        )

    series = pd.Series(
        data,
        dtype="float64",
    )

    return series.ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).mean()


# ==================================================
# 4. SMA
# ==================================================

def calculate_sma(data, period):
    """Calculate Simple Moving Average."""

    if period < 1:
        raise ValueError(
            "SMA period must be positive."
        )

    series = pd.Series(
        data,
        dtype="float64",
    )

    return series.rolling(
        window=period,
        min_periods=period,
    ).mean()


# ==================================================
# 5. RSI
# ==================================================

def calculate_rsi(data, period=RSI_PERIOD):
    """
    Calculate RSI using Wilder smoothing.
    Output range: 0 to 100.
    """

    if period < 1:
        raise ValueError(
            "RSI period must be positive."
        )

    close = pd.Series(
        data,
        dtype="float64",
    )

    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(0, np.nan)
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    rsi = rsi.mask(
        (avg_loss == 0) & (avg_gain > 0),
        100,
    )

    rsi = rsi.mask(
        (avg_gain == 0) & (avg_loss > 0),
        0,
    )

    rsi = rsi.mask(
        (avg_gain == 0) & (avg_loss == 0),
        50,
    )

    return rsi.clip(0, 100)


# ==================================================
# 6. MACD
# ==================================================

def calculate_macd(
    data,
    fast=MACD_FAST,
    slow=MACD_SLOW,
    signal=MACD_SIGNAL,
):
    """
    Return MACD line, signal line and histogram.
    """

    if fast >= slow:
        raise ValueError(
            "MACD fast period must be smaller than slow period."
        )

    if min(fast, slow, signal) < 1:
        raise ValueError(
            "MACD periods must be positive."
        )

    close = pd.Series(
        data,
        dtype="float64",
    )

    ema_fast = calculate_ema(
        close,
        fast,
    )

    ema_slow = calculate_ema(
        close,
        slow,
    )

    macd_line = ema_fast - ema_slow

    signal_line = calculate_ema(
        macd_line,
        signal,
    )

    histogram = (
        macd_line - signal_line
    )

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
    })


# ==================================================
# 7. TRUE RANGE
# ==================================================

def calculate_true_range(df):
    """Calculate True Range."""

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


# ==================================================
# 8. ATR
# ==================================================

def calculate_atr(df, period=ATR_PERIOD):
    """Calculate ATR using Wilder smoothing."""

    if period < 1:
        raise ValueError(
            "ATR period must be positive."
        )

    true_range = calculate_true_range(df)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


# ==================================================
# 9. ADX
# ==================================================

def calculate_adx(df, period=ADX_PERIOD):
    """
    Calculate ADX, +DI and -DI.

    Returns:
        adx
        plus_di
        minus_di
    """

    if period < 1:
        raise ValueError(
            "ADX period must be positive."
        )

    high = df["high"]
    low = df["low"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0.0,
        ),
        index=df.index,
    )

    minus_dm = pd.Series(
        np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0.0,
        ),
        index=df.index,
    )

    atr = calculate_atr(
        df,
        period,
    )

    smoothed_plus = plus_dm.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    smoothed_minus = minus_dm.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    plus_di = (
        100
        * smoothed_plus
        / atr.replace(0, np.nan)
    )

    minus_di = (
        100
        * smoothed_minus
        / atr.replace(0, np.nan)
    )

    denominator = (
        plus_di + minus_di
    ).replace(0, np.nan)

    dx = (
        100
        * (plus_di - minus_di).abs()
        / denominator
    )

    adx = dx.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    return pd.DataFrame({
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    })


# ==================================================
# 10. VWAP
# ==================================================

def calculate_vwap(df):
    """
    Calculate UTC-day anchored VWAP.

    If open_time exists:
        VWAP resets at each UTC day.

    Otherwise:
        Cumulative VWAP is calculated over the input.
    """

    typical_price = (
        df["high"]
        + df["low"]
        + df["close"]
    ) / 3

    volume = df["volume"]

    price_volume = (
        typical_price * volume
    )

    if "open_time" in df.columns:

        if pd.api.types.is_numeric_dtype(
            df["open_time"]
        ):

            timestamps = pd.to_datetime(
                df["open_time"],
                unit="ms",
                utc=True,
                errors="coerce",
            )

        else:

            timestamps = pd.to_datetime(
                df["open_time"],
                utc=True,
                errors="coerce",
            )

        if timestamps.isna().any():
            raise ValueError(
                "Invalid open_time values for VWAP."
            )

        utc_dates = timestamps.dt.strftime(
            "%Y-%m-%d"
        )

        cumulative_pv = (
            price_volume.groupby(
                utc_dates,
                sort=False,
            ).cumsum()
        )

        cumulative_volume = (
            volume.groupby(
                utc_dates,
                sort=False,
            ).cumsum()
        )

    else:

        cumulative_pv = (
            price_volume.cumsum()
        )

        cumulative_volume = (
            volume.cumsum()
        )

    return (
        cumulative_pv
        / cumulative_volume.replace(0, np.nan)
    )


# ==================================================
# 11. RELATIVE VOLUME
# ==================================================

def calculate_relative_volume(
    volume,
    period=RVOL_PERIOD,
):
    """
    Current volume divided by average volume
    of previous N candles.

    The current candle is excluded from baseline.
    """

    if period < 1:
        raise ValueError(
            "RVOL period must be positive."
        )

    series = pd.Series(
        volume,
        dtype="float64",
    )

    average_volume = (
        series.shift(1)
        .rolling(
            window=period,
            min_periods=period,
        )
        .mean()
    )

    return (
        series
        / average_volume.replace(0, np.nan)
    )


# ==================================================
# 11b. VOLUME MOMENTUM (NEW)
# ==================================================

def calculate_volume_momentum(
    volume,
    period=VOLUME_MOMENTUM_PERIOD,
):
    """
    Measures if volume is sequentially increasing.
    A value > 1 means current volume is higher than the average of the last N candles.
    A value > 1.5 means strong volume acceleration.
    """
    if period < 1:
        raise ValueError("Volume momentum period must be positive.")

    series = pd.Series(volume, dtype="float64")
    
    # Compare current candle volume to the average of previous N candles
    previous_avg = series.shift(1).rolling(window=period, min_periods=period).mean()
    
    return series / previous_avg.replace(0, np.nan)


# ==================================================
# 11c. RATE OF CHANGE (ROC) (NEW)
# ==================================================

def calculate_roc(data, period=ROC_PERIOD):
    """
    Rate of Change: percentage change in price over N periods.
    Useful for detecting sudden early price acceleration.
    """
    if period < 1:
        raise ValueError("ROC period must be positive.")

    close = pd.Series(data, dtype="float64")
    
    return ((close - close.shift(period)) / close.shift(period).replace(0, np.nan)) * 100


# ==================================================
# 12. OBV
# ==================================================

def calculate_obv(df):
    """Calculate On-Balance Volume."""

    direction = np.sign(
        df["close"].diff()
    ).fillna(0)

    return (
        direction * df["volume"]
    ).cumsum()


# ==================================================
# 13. CMF
# ==================================================

def calculate_cmf(
    df,
    period=CMF_PERIOD,
):
    """Calculate Chaikin Money Flow."""

    if period < 1:
        raise ValueError(
            "CMF period must be positive."
        )

    price_range = (
        df["high"] - df["low"]
    ).replace(0, np.nan)

    multiplier = (
        (
            (df["close"] - df["low"])
            - (df["high"] - df["close"])
        )
        / price_range
    ).fillna(0)

    money_flow_volume = (
        multiplier * df["volume"]
    )

    volume_sum = (
        df["volume"].rolling(
            window=period,
            min_periods=period,
        ).sum()
    )

    money_flow_sum = (
        money_flow_volume.rolling(
            window=period,
            min_periods=period,
        ).sum()
    )

    return (
        money_flow_sum
        / volume_sum.replace(0, np.nan)
    )


# ==================================================
# 14. BOLLINGER BANDS
# ==================================================

def calculate_bollinger_bands(
    data,
    period=BOLLINGER_PERIOD,
    std_dev=BOLLINGER_STD,
):
    """Calculate upper, middle and lower Bollinger Bands."""

    if period < 1 or std_dev <= 0:
        raise ValueError(
            "Invalid Bollinger Band parameters."
        )

    close = pd.Series(
        data,
        dtype="float64",
    )

    middle = close.rolling(
        window=period,
        min_periods=period,
    ).mean()

    standard_deviation = close.rolling(
        window=period,
        min_periods=period,
    ).std(ddof=0)

    upper = (
        middle + std_dev * standard_deviation
    )

    lower = (
        middle - std_dev * standard_deviation
    )

    # 🔥 NEW: Bollinger Band Width (BBW) - detects squeezes
    bb_width = (upper - lower) / middle.replace(0, np.nan)

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
        "bb_width": bb_width,
    })


# ==================================================
# 15. SUPPORT AND RESISTANCE
# ==================================================

def support_resistance(
    df,
    lookback=SUPPORT_RESISTANCE_LOOKBACK,
    left=PIVOT_LEFT,
    right=PIVOT_RIGHT,
):
    """
    Find nearest confirmed pivot support/resistance.

    A pivot is considered confirmed only after
    the required right-side candles have closed.
    """

    if lookback < 10:
        raise ValueError(
            "Support/resistance lookback is too small."
        )

    if left < 1 or right < 1:
        raise ValueError(
            "Pivot left/right must be positive."
        )

    if df.empty:
        return {
            "support": None,
            "resistance": None,
        }

    recent = (
        df.tail(lookback)
        .reset_index(drop=True)
    )

    if len(recent) < left + right + 1:
        return {
            "support": None,
            "resistance": None,
        }

    current_price = float(
        recent["close"].iloc[-1]
    )

    pivot_lows = []
    pivot_highs = []

    last_confirmed = (
        len(recent) - right
    )

    for index in range(
        left,
        last_confirmed,
    ):

        low_value = float(
            recent["low"].iloc[index]
        )

        high_value = float(
            recent["high"].iloc[index]
        )

        left_lows = recent["low"].iloc[
            index - left:index
        ]

        right_lows = recent["low"].iloc[
            index + 1:index + right + 1
        ]

        left_highs = recent["high"].iloc[
            index - left:index
        ]

        right_highs = recent["high"].iloc[
            index + 1:index + right + 1
        ]

        if (
            low_value < left_lows.min()
            and low_value < right_lows.min()
        ):
            pivot_lows.append(low_value)

        if (
            high_value > left_highs.max()
            and high_value > right_highs.max()
        ):
            pivot_highs.append(high_value)

    supports = [
        value
        for value in pivot_lows
        if value < current_price
    ]

    resistances = [
        value
        for value in pivot_highs
        if value > current_price
    ]

    return {
        "support": (
            max(supports)
            if supports
            else None
        ),
        "resistance": (
            min(resistances)
            if resistances
            else None
        ),
    }


# ==================================================
# 16. CANDLE ANALYSIS
# ==================================================

def analyze_candles(df):
    """
    Analyze the latest candle.

    This function does not generate trading signals.
    """

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

        body = abs(
            close - open_price
        )

        upper_wick = (
            high - max(open_price, close)
        )

        lower_wick = (
            min(open_price, close) - low
        )

        body_percent = (
            body / candle_range
        ) * 100

        upper_wick_percent = (
            upper_wick / candle_range
        ) * 100

        lower_wick_percent = (
            lower_wick / candle_range
        ) * 100

    bullish = close > open_price
    bearish = close < open_price

    previous_bullish = (
        previous["close"] > previous["open"]
    )

    previous_bearish = (
        previous["close"] < previous["open"]
    )

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
            "BULLISH"
            if bullish
            else "BEARISH"
            if bearish
            else "NEUTRAL"
        ),
        "body_percent": round(
            float(body_percent), 2
        ),
        "upper_wick_percent": round(
            float(upper_wick_percent), 2
        ),
        "lower_wick_percent": round(
            float(lower_wick_percent), 2
        ),
        "bullish_engulfing": bool(
            bullish_engulfing
        ),
        "bearish_engulfing": bool(
            bearish_engulfing
        ),
        "strong_bullish_candle": bool(
            bullish and body_percent >= 65
        ),
        "strong_bearish_candle": bool(
            bearish and body_percent >= 65
        ),
    }


# ==================================================
# 17. CALCULATE ALL INDICATORS
# ==================================================

def calculate_all_indicators(df):
    """
    Calculate all indicators.

    Original OHLCV columns are preserved.

    Added columns:
        ema_9
        ema_20
        sma_20
        sma_50
        sma_200
        rsi
        macd
        macd_signal
        macd_histogram
        adx
        plus_di
        minus_di
        atr
        vwap
        relative_volume
        volume_momentum  # NEW
        roc              # NEW
        obv
        cmf
        bb_upper
        bb_middle
        bb_lower
        bb_width         # NEW
    """

    result = validate_dataframe(df)

    close = result["close"]

    # EMA

    result[f"ema_{EMA_FAST}"] = (
        calculate_ema(
            close,
            EMA_FAST,
        )
    )

    result[f"ema_{EMA_SLOW}"] = (
        calculate_ema(
            close,
            EMA_SLOW,
        )
    )

    # SMA

    for period in SMA_PERIODS:

        column = f"sma_{period}"

        if (
            period == 200
            and len(result) < MIN_CANDLES_FOR_MA200
        ):
            result[column] = np.nan

        else:
            result[column] = calculate_sma(
                close,
                period,
            )

    # RSI

    result["rsi"] = calculate_rsi(
        close,
        RSI_PERIOD,
    )

    # MACD

    macd = calculate_macd(
        close,
        MACD_FAST,
        MACD_SLOW,
        MACD_SIGNAL,
    )

    result["macd"] = macd["macd"]
    result["macd_signal"] = macd["macd_signal"]

    result["macd_histogram"] = (
        macd["macd_histogram"]
    )

    # ADX

    adx = calculate_adx(
        result,
        ADX_PERIOD,
    )

    result["adx"] = adx["adx"]
    result["plus_di"] = adx["plus_di"]
    result["minus_di"] = adx["minus_di"]

    # ATR

    result["atr"] = calculate_atr(
        result,
        ATR_PERIOD,
    )

    # VWAP

    result["vwap"] = calculate_vwap(
        result
    )

    # Relative Volume

    result["relative_volume"] = (
        calculate_relative_volume(
            result["volume"],
            RVOL_PERIOD,
        )
    )

    # 🔥 NEW: Volume Momentum
    result["volume_momentum"] = (
        calculate_volume_momentum(
            result["volume"],
            VOLUME_MOMENTUM_PERIOD,
        )
    )

    # 🔥 NEW: Rate of Change (Price Momentum)
    result["roc"] = calculate_roc(
        close,
        ROC_PERIOD,
    )

    # OBV

    result["obv"] = calculate_obv(
        result
    )

    # CMF

    result["cmf"] = calculate_cmf(
        result,
        CMF_PERIOD,
    )

    # Bollinger Bands

    bands = calculate_bollinger_bands(
        close,
        BOLLINGER_PERIOD,
        BOLLINGER_STD,
    )

    result["bb_upper"] = bands["bb_upper"]
    result["bb_middle"] = bands["bb_middle"]
    result["bb_lower"] = bands["bb_lower"]
    
    # 🔥 NEW: Bollinger Band Width (Squeeze Detection)
    result["bb_width"] = bands["bb_width"]

    return result


# ==================================================
# 18. LATEST INDICATOR SNAPSHOT
# ==================================================

def get_latest_indicator_snapshot(df):
    """
    Return the latest available indicator values.

    Missing values remain None.
    No missing value is guessed or fabricated.
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            "Input must be a pandas DataFrame."
        )

    if df.empty:
        raise ValueError(
            "Cannot create snapshot from empty data."
        )

    enriched = calculate_all_indicators(df)

    latest = enriched.iloc[-1]

    def safe_value(column):
        value = latest.get(column)

        if value is None or pd.isna(value):
            return None

        return float(value)

    levels = support_resistance(
        enriched
    )

    candle_info = analyze_candles(
        enriched
    )

    sma200_column = "sma_200"

    return {
        "close": safe_value("close"),

        "ema_9": safe_value("ema_9"),
        "ema_20": safe_value("ema_20"),

        "sma_20": safe_value("sma_20"),
        "sma_50": safe_value("sma_50"),
        "sma_200": safe_value(sma200_column),

        "rsi": safe_value("rsi"),

        "macd": safe_value("macd"),
        "macd_signal": safe_value("macd_signal"),
        "macd_histogram": safe_value(
            "macd_histogram"
        ),

        "adx": safe_value("adx"),
        "plus_di": safe_value("plus_di"),
        "minus_di": safe_value("minus_di"),

        "atr": safe_value("atr"),
        "vwap": safe_value("vwap"),

        "relative_volume": safe_value(
            "relative_volume"
        ),
        
        # 🔥 NEW INDICATORS IN SNAPSHOT
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

        "ma200_available": (
            safe_value(sma200_column) is not None
        ),
    }


# ==================================================
# 19. MODULE STATUS
# ==================================================

def get_indicator_config():
    """
    Return the active indicator configuration.
    Useful for tests and diagnostics.
    """

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
        "support_resistance_lookback": (
            SUPPORT_RESISTANCE_LOOKBACK
        ),
        "pivot_left": PIVOT_LEFT,
        "pivot_right": PIVOT_RIGHT,
        "min_candles_for_ma200": (
            MIN_CANDLES_FOR_MA200
        ),
        "roc_period": ROC_PERIOD,
        "volume_momentum_period": VOLUME_MOMENTUM_PERIOD,
    }
