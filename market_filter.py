
"""
Binance Spot V3 Smart Signal Scanner
BTC Market Filter

Python: 3.11
Market: Binance Spot only

Purpose:
    Analyse BTC market conditions across 15m, 1h and 4h.
    Classify the market as:
        BULLISH
        NEUTRAL
        BEARISH
        HIGH_RISK
        UNKNOWN

This module does not generate coin BUY/SELL signals.

Input format:
    btc_data = {
        "15m": pandas.DataFrame,
        "1h": pandas.DataFrame,
        "4h": pandas.DataFrame,
    }

    external_data = {
        "btc_dominance": float,
        "total_market_cap_change_24h_pct": float,
        "fear_greed_index": float,
    }

Missing external data remains UNKNOWN.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

from config import MARKET_CONFIG
from indicators import calculate_all_indicators


logger = logging.getLogger(__name__)


# ==================================================
# 1. CONFIGURATION
# ==================================================

REQUIRED_TIMEFRAMES = ("15m", "1h", "4h")

VALID_MARKET_STATUSES = (
    "BULLISH",
    "NEUTRAL",
    "BEARISH",
    "HIGH_RISK",
    "UNKNOWN",
)

DEFAULT_CONFIG = {
    "RSI_PERIOD": 14,
    "ADX_PERIOD": 14,
    "MIN_CANDLES_FOR_MA200": 220,
    "BULLISH_RSI_MIN": 50.0,
    "BEARISH_RSI_MAX": 45.0,
    "HIGH_RISK_RSI_MAX": 40.0,
    "STRONG_ADX_MIN": 25.0,
    "HIGH_VOLUME_RVOL": 1.5,
}


def _normalise_key(value):
    return "".join(
        character
        for character in str(value).upper()
        if character.isalnum()
    )


def _find_config_value(target):
    """
    Find an exact key recursively in MARKET_CONFIG.
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

    return search(MARKET_CONFIG)


def _get_setting(name, default):
    value = _find_config_value(name)

    if value is None:
        return default

    return value


RSI_PERIOD = int(
    _get_setting(
        "RSI_PERIOD",
        DEFAULT_CONFIG["RSI_PERIOD"],
    )
)

ADX_PERIOD = int(
    _get_setting(
        "ADX_PERIOD",
        DEFAULT_CONFIG["ADX_PERIOD"],
    )
)

MIN_CANDLES_FOR_MA200 = int(
    _get_setting(
        "MIN_CANDLES_FOR_MA200",
        DEFAULT_CONFIG["MIN_CANDLES_FOR_MA200"],
    )
)

BULLISH_RSI_MIN = float(
    _get_setting(
        "BULLISH_RSI_MIN",
        DEFAULT_CONFIG["BULLISH_RSI_MIN"],
    )
)

BEARISH_RSI_MAX = float(
    _get_setting(
        "BEARISH_RSI_MAX",
        DEFAULT_CONFIG["BEARISH_RSI_MAX"],
    )
)

HIGH_RISK_RSI_MAX = float(
    _get_setting(
        "HIGH_RISK_RSI_MAX",
        DEFAULT_CONFIG["HIGH_RISK_RSI_MAX"],
    )
)

STRONG_ADX_MIN = float(
    _get_setting(
        "STRONG_ADX_MIN",
        DEFAULT_CONFIG["STRONG_ADX_MIN"],
    )
)

HIGH_VOLUME_RVOL = float(
    _get_setting(
        "HIGH_VOLUME_RVOL",
        DEFAULT_CONFIG["HIGH_VOLUME_RVOL"],
    )
)


# ==================================================
# 2. SAFE VALUE HELPERS
# ==================================================

def _safe_float(value):
    """
    Convert a value to float safely.
    Invalid or missing values return None.
    """

    if value is None:
        return None

    try:
        result = float(value)

        if not np.isfinite(result):
            return None

        return result

    except (TypeError, ValueError):
        return None


def _get_latest_value(row, column):
    return _safe_float(
        row.get(column)
    )


def _is_valid_dataframe(df):
    return (
        isinstance(df, pd.DataFrame)
        and not df.empty
    )


# ==================================================
# 3. BTC TIMEFRAME ANALYSIS
# ==================================================

def analyze_btc_timeframe(df, timeframe):
    """
    Analyse BTC indicators for one timeframe.

    Returns:
        {
            "timeframe": str,
            "trend": str,
            "close": float or None,
            "ema_9": float or None,
            "ema_20": float or None,
            "sma_20": float or None,
            "sma_50": float or None,
            "sma_200": float or None,
            "rsi": float or None,
            "macd": float or None,
            "macd_signal": float or None,
            "macd_histogram": float or None,
            "adx": float or None,
            "atr": float or None,
            "relative_volume": float or None,
            "volume_status": str,
            "data_quality": str,
            "warnings": list,
        }
    """

    result = {
        "timeframe": timeframe,
        "trend": "UNKNOWN",
        "close": None,
        "ema_9": None,
        "ema_20": None,
        "sma_20": None,
        "sma_50": None,
        "sma_200": None,
        "rsi": None,
        "macd": None,
        "macd_signal": None,
        "macd_histogram": None,
        "adx": None,
        "atr": None,
        "relative_volume": None,
        "volume_status": "UNKNOWN",
        "data_quality": "UNKNOWN",
        "warnings": [],
    }

    if not _is_valid_dataframe(df):

        result["warnings"].append(
            f"{timeframe}: BTC candle data missing."
        )

        return result

    try:

        enriched = calculate_all_indicators(df)

    except Exception as exc:

        logger.exception(
            "BTC indicator calculation failed for %s",
            timeframe,
        )

        result["warnings"].append(
            f"{timeframe}: Indicator calculation failed: "
            f"{type(exc).__name__}"
        )

        return result

    if enriched.empty:

        result["warnings"].append(
            f"{timeframe}: No valid indicator data."
        )

        return result

    latest = enriched.iloc[-1]

    for column in (
        "close",
        "ema_9",
        "ema_20",
        "sma_20",
        "sma_50",
        "sma_200",
        "rsi",
        "macd",
        "macd_signal",
        "macd_histogram",
        "adx",
        "atr",
        "relative_volume",
    ):

        result[column] = _get_latest_value(
            latest,
            column,
        )

    candle_count = len(enriched)

    if candle_count < MIN_CANDLES_FOR_MA200:

        result["warnings"].append(
            f"{timeframe}: Insufficient candles for reliable MA200."
        )

    required_values = (
        result["close"],
        result["sma_20"],
        result["sma_50"],
        result["sma_200"],
        result["rsi"],
        result["macd_histogram"],
    )

    if any(
        value is None
        for value in required_values
    ):

        result["data_quality"] = "INCOMPLETE"

        result["warnings"].append(
            f"{timeframe}: Required BTC indicators unavailable."
        )

        return result

    result["data_quality"] = "VALID"

    close = result["close"]
    sma20 = result["sma_20"]
    sma50 = result["sma_50"]
    sma200 = result["sma_200"]
    rsi = result["rsi"]
    macd_histogram = result["macd_histogram"]

    bullish_structure = (
        close > sma20 > sma50 > sma200
    )

    bearish_structure = (
        close < sma20 < sma50 < sma200
    )

    bullish_momentum = (
        rsi >= BULLISH_RSI_MIN
        and macd_histogram > 0
    )

    bearish_momentum = (
        rsi <= BEARISH_RSI_MAX
        and macd_histogram < 0
    )

    if (
        bullish_structure
        and bullish_momentum
    ):

        result["trend"] = "BULLISH"

    elif (
        bearish_structure
        and bearish_momentum
    ):

        result["trend"] = "BEARISH"

    else:

        result["trend"] = "NEUTRAL"

    # Volume classification.

    rvol = result["relative_volume"]

    if rvol is None:

        result["volume_status"] = "UNKNOWN"

    elif rvol >= HIGH_VOLUME_RVOL:

        result["volume_status"] = "HIGH"

    elif rvol >= 1.0:

        result["volume_status"] = "NORMAL"

    else:

        result["volume_status"] = "LOW"

    return result


# ==================================================
# 4. BTC VOLUME ANALYSIS
# ==================================================

def analyze_btc_volume(timeframe_results):
    """
    Combine BTC volume conditions.

    Missing values are not treated as normal volume.
    """

    available = [
        result["volume_status"]
        for result in timeframe_results.values()
        if result["volume_status"] != "UNKNOWN"
    ]

    if not available:
        return "UNKNOWN"

    high_count = available.count("HIGH")
    low_count = available.count("LOW")

    if high_count >= 2:
        return "HIGH"

    if low_count >= 2:
        return "LOW"

    if "NORMAL" in available:
        return "NORMAL"

    return "MIXED"


# ==================================================
# 5. OVERALL BTC TREND
# ==================================================

def determine_btc_trend(timeframe_results):
    """
    Determine overall BTC trend using 1h and 4h.

    15m is used as a short-term confirmation only.
    """

    one_hour = timeframe_results.get("1h", {})
    four_hour = timeframe_results.get("4h", {})
    fifteen_min = timeframe_results.get("15m", {})

    trend_1h = one_hour.get(
        "trend",
        "UNKNOWN",
    )

    trend_4h = four_hour.get(
        "trend",
        "UNKNOWN",
    )

    trend_15m = fifteen_min.get(
        "trend",
        "UNKNOWN",
    )

    if "UNKNOWN" in (trend_1h, trend_4h):
        return "UNKNOWN"

    if (
        trend_1h == "BULLISH"
        and trend_4h == "BULLISH"
    ):
        return "BULLISH"

    if (
        trend_1h == "BEARISH"
        and trend_4h == "BEARISH"
    ):
        return "BEARISH"

    if (
        trend_1h == "BULLISH"
        and trend_4h == "NEUTRAL"
    ):
        return "NEUTRAL"

    if (
        trend_1h == "NEUTRAL"
        and trend_4h == "BULLISH"
    ):
        return "NEUTRAL"

    if (
        trend_1h == "BEARISH"
        and trend_4h == "NEUTRAL"
    ):
        return "NEUTRAL"

    if (
        trend_1h == "NEUTRAL"
        and trend_4h == "BEARISH"
    ):
        return "NEUTRAL"

    if (
        trend_1h == "BULLISH"
        and trend_4h == "BEARISH"
    ):
        return "NEUTRAL"

    if (
        trend_1h == "BEARISH"
        and trend_4h == "BULLISH"
    ):
        return "NEUTRAL"

    return "NEUTRAL"


# ==================================================
# 6. HIGH RISK DETECTION
# ==================================================

def detect_high_risk(timeframe_results):
    """
    Detect severe BTC downside conditions.

    HIGH_RISK requires multiple bearish confirmations.
    A single weak timeframe is not enough.
    """

    one_hour = timeframe_results.get("1h", {})
    four_hour = timeframe_results.get("4h", {})

    if (
        one_hour.get("data_quality") != "VALID"
        or four_hour.get("data_quality") != "VALID"
    ):
        return False, []

    warnings = []

    one_hour_bearish = (
        one_hour.get("trend") == "BEARISH"
    )

    four_hour_bearish = (
        four_hour.get("trend") == "BEARISH"
    )

    one_hour_rsi = one_hour.get("rsi")
    four_hour_rsi = four_hour.get("rsi")

    one_hour_adx = one_hour.get("adx")
    four_hour_adx = four_hour.get("adx")

    strong_downtrend = (
        one_hour_bearish
        and four_hour_bearish
    )

    oversold_confirmation = (
        one_hour_rsi is not None
        and four_hour_rsi is not None
        and one_hour_rsi <= HIGH_RISK_RSI_MAX
        and four_hour_rsi <= HIGH_RISK_RSI_MAX
    )

    adx_confirmation = (
        (
            one_hour_adx is not None
            and one_hour_adx >= STRONG_ADX_MIN
        )
        or (
            four_hour_adx is not None
            and four_hour_adx >= STRONG_ADX_MIN
        )
    )

    if (
        strong_downtrend
        and (
            oversold_confirmation
            or adx_confirmation
        )
    ):

        warnings.append(
            "BTC shows confirmed bearish conditions "
            "on both 1h and 4h."
        )

        return True, warnings

    return False, warnings


# ==================================================
# 7. EXTERNAL MARKET DATA
# ==================================================

def analyze_external_data(external_data=None):
    """
    Read optional external market information.

    Supported keys:
        btc_dominance
        total_market_cap_change_24h_pct
        fear_greed_index

    No external API requests are made here.
    """

    result = {
        "btc_dominance": None,
        "btc_dominance_status": "UNKNOWN",
        "total_market_cap_change_24h_pct": None,
        "total_market_status": "UNKNOWN",
        "fear_greed_index": None,
        "sentiment_status": "UNKNOWN",
    }

    if not isinstance(external_data, dict):
        return result

    dominance = _safe_float(
        external_data.get("btc_dominance")
    )

    market_change = _safe_float(
        external_data.get(
            "total_market_cap_change_24h_pct"
        )
    )

    fear_greed = _safe_float(
        external_data.get("fear_greed_index")
    )

    # BTC dominance.

    if dominance is not None and 0 <= dominance <= 100:

        result["btc_dominance"] = dominance

        result["btc_dominance_status"] = (
            "RISING"
            if external_data.get(
                "btc_dominance_trend"
            ) == "RISING"
            else "FALLING"
            if external_data.get(
                "btc_dominance_trend"
            ) == "FALLING"
            else "AVAILABLE"
        )

    # Total crypto market cap change.

    if market_change is not None:

        result["total_market_cap_change_24h_pct"] = (
            market_change
        )

        if market_change > 2:
            result["total_market_status"] = "BULLISH"

        elif market_change < -2:
            result["total_market_status"] = "BEARISH"

        else:
            result["total_market_status"] = "NEUTRAL"

    # Fear and Greed Index.

    if fear_greed is not None and 0 <= fear_greed <= 100:

        result["fear_greed_index"] = fear_greed

        if fear_greed <= 24:
            result["sentiment_status"] = "EXTREME_FEAR"

        elif fear_greed <= 44:
            result["sentiment_status"] = "FEAR"

        elif fear_greed <= 55:
            result["sentiment_status"] = "NEUTRAL"

        elif fear_greed <= 74:
            result["sentiment_status"] = "GREED"

        else:
            result["sentiment_status"] = "EXTREME_GREED"

    return result


# ==================================================
# 8. MARKET CLASSIFICATION
# ==================================================

def classify_market(
    btc_trend,
    timeframe_results,
    external_result,
):
    """
    Classify overall market condition.

    Missing BTC 1h/4h data produces UNKNOWN.
    HIGH_RISK overrides all other classifications.
    """

    high_risk, risk_warnings = detect_high_risk(
        timeframe_results
    )

    if high_risk:
        return "HIGH_RISK", risk_warnings

    if btc_trend == "UNKNOWN":
        return "UNKNOWN", [
            "Insufficient BTC trend data."
        ]

    one_hour = timeframe_results.get("1h", {})
    four_hour = timeframe_results.get("4h", {})

    if (
        one_hour.get("data_quality") != "VALID"
        or four_hour.get("data_quality") != "VALID"
    ):
        return "UNKNOWN", [
            "Required BTC timeframe data is incomplete."
        ]

    # External market conditions can add caution,
    # but missing external data does not fabricate a trend.

    total_market_status = external_result.get(
        "total_market_status",
        "UNKNOWN",
    )

    if btc_trend == "BULLISH":

        if total_market_status == "BEARISH":
            return "NEUTRAL", [
                "BTC is bullish but total market cap is falling."
            ]

        return "BULLISH", []

    if btc_trend == "BEARISH":

        return "BEARISH", [
            "BTC trend is bearish. New entries require extra caution."
        ]

    return "NEUTRAL", [
        "BTC higher-timeframe trend is mixed or neutral."
    ]


# ==================================================
# 9. RISK LEVEL
# ==================================================

def determine_risk_level(market_status):
    """
    Return a simple market risk label.
    """

    mapping = {
        "BULLISH": "LOW_TO_MODERATE",
        "NEUTRAL": "MODERATE",
        "BEARISH": "HIGH",
        "HIGH_RISK": "VERY_HIGH",
        "UNKNOWN": "UNKNOWN",
    }

    return mapping.get(
        market_status,
        "UNKNOWN",
    )


# ==================================================
# 10. MAIN MARKET ANALYSIS
# ==================================================

def analyze_market(btc_data, external_data=None):
    """
    Main market analysis function.

    Parameters:
        btc_data:
            Dictionary containing:
                "15m": DataFrame
                "1h": DataFrame
                "4h": DataFrame

        external_data:
            Optional dictionary containing:
                btc_dominance
                btc_dominance_trend
                total_market_cap_change_24h_pct
                fear_greed_index

    Returns:
        Standard market context dictionary.

    Important:
        This function does not fetch market data.
        Data must be supplied by data_provider.py.
    """

    warnings = []

    if not isinstance(btc_data, dict):

        return {
            "market_status": "UNKNOWN",
            "btc_trend": "UNKNOWN",
            "btc_rsi": None,
            "btc_volume_status": "UNKNOWN",
            "btc_dominance_status": "UNKNOWN",
            "total_market_status": "UNKNOWN",
            "sentiment_status": "UNKNOWN",
            "risk_level": "UNKNOWN",
            "warnings": [
                "btc_data must be a timeframe dictionary."
            ],
            "data_quality": "INVALID",
            "timeframes": {},
        }

    timeframe_results = {}

    for timeframe in REQUIRED_TIMEFRAMES:

        timeframe_df = btc_data.get(
            timeframe
        )

        timeframe_results[timeframe] = (
            analyze_btc_timeframe(
                timeframe_df,
                timeframe,
            )
        )

        warnings.extend(
            timeframe_results[timeframe]["warnings"]
        )

    btc_trend = determine_btc_trend(
        timeframe_results
    )

    external_result = analyze_external_data(
        external_data
    )

    market_status, classification_warnings = (
        classify_market(
            btc_trend,
            timeframe_results,
            external_result,
        )
    )

    warnings.extend(
        classification_warnings
    )

    btc_volume_status = analyze_btc_volume(
        timeframe_results
    )

    one_hour_rsi = timeframe_results.get(
        "1h", {}
    ).get("rsi")

    if all(
        timeframe_results[tf]["data_quality"] == "VALID"
        for tf in REQUIRED_TIMEFRAMES
    ):
        data_quality = "VALID"

    elif any(
        timeframe_results[tf]["data_quality"] == "VALID"
        for tf in REQUIRED_TIMEFRAMES
    ):
        data_quality = "PARTIAL"

    else:
        data_quality = "INVALID"

    risk_level = determine_risk_level(
        market_status
    )

    if external_result["btc_dominance_status"] == "UNKNOWN":
        warnings.append(
            "BTC dominance data unavailable."
        )

    if external_result["total_market_status"] == "UNKNOWN":
        warnings.append(
            "Total crypto market cap data unavailable."
        )

    if external_result["sentiment_status"] == "UNKNOWN":
        warnings.append(
            "Fear and Greed data unavailable."
        )

    return {
        "market_status": market_status,
        "btc_trend": btc_trend,
        "btc_rsi": one_hour_rsi,
        "btc_volume_status": btc_volume_status,

        "btc_dominance": (
            external_result["btc_dominance"]
        ),

        "btc_dominance_status": (
            external_result["btc_dominance_status"]
        ),

        "total_market_cap_change_24h_pct": (
            external_result[
                "total_market_cap_change_24h_pct"
            ]
        ),

        "total_market_status": (
            external_result["total_market_status"]
        ),

        "fear_greed_index": (
            external_result["fear_greed_index"]
        ),

        "sentiment_status": (
            external_result["sentiment_status"]
        ),

        "risk_level": risk_level,

        "warnings": list(dict.fromkeys(warnings)),

        "data_quality": data_quality,

        "timeframes": timeframe_results,

        "signal_policy": {
            "allow_new_signals": (
                market_status not in (
                    "HIGH_RISK",
                    "UNKNOWN",
                )
            ),
            "market_caution": (
                market_status in (
                    "BEARISH",
                    "NEUTRAL",
                )
            ),
        },
    }


# ==================================================
# 11. MARKET FILTER VALIDATION
# ==================================================

def validate_market_context(market_context):
    """
    Validate market context before passing it
    to the entry engine.
    """

    if not isinstance(market_context, dict):
        return False

    status = market_context.get(
        "market_status"
    )

    if status not in VALID_MARKET_STATUSES:
        return False

    if status in ("HIGH_RISK", "UNKNOWN"):
        return False

    if market_context.get("data_quality") not in (
        "VALID",
        "PARTIAL",
    ):
        return False

    return True
