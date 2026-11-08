
"""
Binance Spot V3 Smart Signal Scanner
Technical Indicators Engine

Input:
    Closed-candle pandas DataFrame from data_provider.py

Output:
    Individual indicator Series/DataFrames
    Enriched DataFrame from calculate_all_indicators()

No trading signals are generated in this module.
"""

import logging

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

EMA_FAST = 9
EMA_SLOW = 20

SMA_PERIODS = (20, 50, 200)

RSI_PERIOD = 14

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ADX_PERIOD = 14
ATR_PERIOD = 14

BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0

RVOL_PERIOD = 20
CMF_PERIOD = 20

SUPPORT_RESISTANCE_LOOKBACK = 100
PIVOT_LEFT = 3
PIVOT_RIGHT = 3

MIN_CANDLES_FOR_MA200 = 220


# --------------------------------------------------
# DATA VALIDATION
# --------------------------------------------------

REQUIRED_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def validate_dataframe(df):
    """
    Validate OHLCV input data.
    Returns a safe copy with numeric columns.
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")

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

    result = result.reset_index(drop=True)

    if result.empty:
        raise ValueError("No valid OHLCV data available.")

    invalid_prices = (
        (result["open"] <= 0)
        | (result["high"] <= 0)
        | (result["low"] <= 0)
        | (result["close"] <= 0)
        | (result["volume"] < 0)
    )

    if invalid_prices.any():
        raise ValueError(
            "OHLCV data contains invalid prices or volume."
        )

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

    return result


# --------------------------------------------------
# 1. EMA
# --------------------------------------------------

def calculate_ema(data, period):
    """
    Calculate Exponential Moving Average.
    """

    if period < 1:
        raise ValueError("EMA period must be positive.")

    series = pd.Series(data, dtype="float64")

    return series.ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).mean()


# --------------------------------------------------
# 2. SMA
# --------------------------------------------------

def calculate_sma(data, period):
    """
    Calculate Simple Moving Average.
    """

    if period < 1:
        raise ValueError("SMA period must be positive.")

    series = pd.Series(data, dtype="float64")

    return series.rolling(
        window=period,
        min_periods=period,
    ).mean()


# --------------------------------------------------
# 3. RSI
# --------------------------------------------------

def calculate_rsi(data, period=RSI_PERIOD):
    """
    Calculate RSI using Wilder-style smoothing.
    """

    if period < 1:
        raise ValueError("RSI period must be positive.")

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

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

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


# --------------------------------------------------
# 4. MACD
# --------------------------------------------------

def calculate_macd(
    data,
    fast=MACD_FAST,
    slow=MACD_SLOW,
    signal=MACD_SIGNAL,
):
    """
    Return MACD, signal line and histogram.
    """

    if fast >= slow:
        raise ValueError(
            "MACD fast period must be smaller than slow period."
        )

    close = pd.Series(
        data,
        dtype="float64",
    )

    ema_fast = calculate_ema(close, fast)
    ema_slow = calculate_ema(close, slow)

    macd_line = ema_fast - ema_slow

    signal_line = calculate_ema(
        macd_line,
        signal,
    )

    histogram = macd_line - signal_line

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
    })


# --------------------------------------------------
# 5. TRUE RANGE
# --------------------------------------------------

def calculate_true_range(df):
    """
    Calculate True Range.
    """

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


# --------------------------------------------------
# 6. ATR
# --------------------------------------------------

def calculate_atr(df, period=ATR_PERIOD):
    """
    Calculate Average True Range using Wilder smoothing.
    """

    if period < 1:
        raise ValueError("ATR period must be positive.")

    true_range = calculate_true_range(df)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


# --------------------------------------------------
# 7. ADX
# --------------------------------------------------

def calculate_adx(df, period=ADX_PERIOD):
    """
    Calculate ADX, positive DI and negative DI.

    Returns a DataFrame:
        adx
        plus_di
        minus_di
    """

    if period < 1:
        raise ValueError("ADX period must be positive.")

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

    atr = calculate_atr(df, period)

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
        100 * smoothed_plus / atr.replace(0, np.nan)
    )

    minus_di = (
        100 * smoothed_minus / atr.replace(0, np.nan)
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


# --------------------------------------------------
# 8. VWAP
# --------------------------------------------------

def calculate_vwap(df):
    """
    Calculate UTC-day anchored VWAP.

    If open_time exists, candles are grouped by UTC date.
    Otherwise, cumulative VWAP is calculated over the
    supplied DataFrame.
    """

    typical_price = (
        df["high"] + df["low"] + df["close"]
    ) / 3

    volume = df["volume"]

    price_volume = typical_price * volume

    if "open_time" in df.columns:

        timestamps = pd.to_datetime(
            df["open_time"],
            unit="ms",
            utc=True,
            errors="coerce",
        )

        if timestamps.isna().any():
            raise ValueError(
                "Invalid open_time values for VWAP."
            )

        utc_dates = timestamps.dt.date

        cumulative_pv = price_volume.groupby(
            utc_dates
        ).cumsum()

        cumulative_volume = volume.groupby(
            utc_dates
        ).cumsum()

    else:
        cumulative_pv = price_volume.cumsum()
        cumulative_volume = volume.cumsum()

    return (
        cumulative_pv
        / cumulative_volume.replace(0, np.nan)
    )


# --------------------------------------------------
# 9. RELATIVE VOLUME
# --------------------------------------------------

def calculate_relative_volume(
    volume,
    period=RVOL_PERIOD,
):
    """
    Current candle volume divided by the average
    volume of the previous N candles.

    Current candle is excluded from the baseline.
    """

    if period < 1:
        raise ValueError("RVOL period must be positive.")

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


# --------------------------------------------------
# 10. OBV
# --------------------------------------------------

def calculate_obv(df):
    """
    Calculate On-Balance Volume.
    """

    direction = np.sign(
        df["close"].diff()
    ).fillna(0)

    return (
        direction * df["volume"]
    ).cumsum()


# --------------------------------------------------
# 11. CMF
# --------------------------------------------------

def calculate_cmf(df, period=CMF_PERIOD):
    """
    Calculate Chaikin Money Flow.
    """

    if period < 1:
        raise ValueError("CMF period must be positive.")

    price_range = (
        df["high"] - df["low"]
    ).replace(0, np.nan)

    money_flow_multiplier = (
        (
            (df["close"] - df["low"])
            - (df["high"] - df["close"])
        )
        / price_range
    )

    money_flow_multiplier = (
        money_flow_multiplier.fillna(0)
    )

    money_flow_volume = (
        money_flow_multiplier * df["volume"]
    )

    volume_sum = df["volume"].rolling(
        window=period,
        min_periods=period,
    ).sum()

    money_flow_sum = money_flow_volume.rolling(
        window=period,
        min_periods=period,
    ).sum()

    return (
        money_flow_sum
        / volume_sum.replace(0, np.nan)
    )


# --------------------------------------------------
# 12. BOLLINGER BANDS
# --------------------------------------------------

def calculate_bollinger_bands(
    data,
    period=BOLLINGER_PERIOD,
    std_dev=BOLLINGER_STD,
):
    """
    Return upper, middle and lower Bollinger Bands.
    """

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

    std = close.rolling(
        window=period,
        min_periods=period,
    ).std(ddof=0)

    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
    })


# --------------------------------------------------
# 13. SUPPORT AND RESISTANCE
# --------------------------------------------------

def support_resistance(
    df,
    lookback=SUPPORT_RESISTANCE_LOOKBACK,
    left=PIVOT_LEFT,
    right=PIVOT_RIGHT,
):
    """
    Find nearest confirmed pivot support and resistance.

    A pivot is confirmed only after the required number
    of candles to its right have closed.

    Returns:
        {
            "support": float or None,
            "resistance": float or None
        }
    """

    if lookback < 10:
        raise ValueError(
            "Support/resistance lookback is too small."
        )

    if left < 1 or right < 1:
        raise ValueError(
            "Pivot left/right must be positive."
        )

    recent = df.tail(lookback).reset_index(drop=True)

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

    # Exclude unconfirmed pivots near the end.
    last_confirmed = len(recent) - right

    for index in range(
        left,
        last_confirmed,
    ):

        low_value = recent["low"].iloc[index]
        high_value = recent["high"].iloc[index]

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
            pivot_lows.append(float(low_value))

        if (
            high_value > left_highs.max()
            and high_value > right_highs.max()
        ):
            pivot_highs.append(float(high_value))

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

    nearest_support = (
        max(supports)
        if supports
        else None
    )

    nearest_resistance = (
        min(resistances)
        if resistances
        else None
    )

    return {
        "support": nearest_support,
        "resistance": nearest_resistance,
    }


# --------------------------------------------------
# 14. CANDLE ANALYSIS
# --------------------------------------------------

def analyze_candles(df):
    """
    Analyze the latest closed candle.

    This is descriptive candle analysis only.
    It does not generate a BUY signal.
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
        body = abs(close - open_price)

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


# --------------------------------------------------
# 15. CALCULATE ALL INDICATORS
# --------------------------------------------------

def calculate_all_indicators(df):
    """
    Calculate all indicators and return an enriched DataFrame.

    Original OHLCV columns are preserved.

    Additional columns:
        ema_9, ema_20
        sma_20, sma_50, sma_200
        rsi
        macd, macd_signal, macd_histogram
        adx, plus_di, minus_di
        atr
        vwap
        relative_volume
        obv
        cmf
        bb_upper, bb_middle, bb_lower

    Support/resistance and candle analysis are available
    separately through their dedicated functions.
    """

    result = validate_dataframe(df)

    close = result["close"]

    # EMA
    result["ema_9"] = calculate_ema(
        close,
        EMA_FAST,
    )

    result["ema_20"] = calculate_ema(
        close,
        EMA_SLOW,
    )

    # SMA
    result["sma_20"] = calculate_sma(
        close,
        20,
    )

    result["sma_50"] = calculate_sma(
        close,
        50,
    )

    # MA200 is not considered reliable before 220 candles.
    if len(result) >= MIN_CANDLES_FOR_MA200:
        result["sma_200"] = calculate_sma(
            close,
            200,
        )
    else:
        result["sma_200"] = np.nan

    # RSI
    result["rsi"] = calculate_rsi(
        close,
        RSI_PERIOD,
    )

    # MACD
    macd = calculate_macd(close)

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

    # Relative volume
    result["relative_volume"] = (
        calculate_relative_volume(
            result["volume"],
            RVOL_PERIOD,
        )
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

    return result


# --------------------------------------------------
# 16. LATEST INDICATOR SNAPSHOT
# --------------------------------------------------

def get_latest_indicator_snapshot(df):
    """
    Return latest available indicator values.

    Missing values remain None.
    No missing indicator is replaced with a guessed value.
    """

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

    levels = support_resistance(enriched)

    candle_info = analyze_candles(enriched)

    return {
        "close": safe_value("close"),
        "ema_9": safe_value("ema_9"),
        "ema_20": safe_value("ema_20"),
        "sma_20": safe_value("sma_20"),
        "sma_50": safe_value("sma_50"),
        "sma_200": safe_value("sma_200"),
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
        "obv": safe_value("obv"),
        "cmf": safe_value("cmf"),
        "bb_upper": safe_value("bb_upper"),
        "bb_middle": safe_value("bb_middle"),
        "bb_lower": safe_value("bb_lower"),
        "support": levels["support"],
        "resistance": levels["resistance"],
        "candle_analysis": candle_info,
        "candle_count": len(enriched),
        "ma200_available": (
            safe_value("sma_200") is not None
        ),
    }
