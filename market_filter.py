
"""
Binance Spot V3 Smart Signal Scanner
BTC Market Filter

Python: 3.11
Market: Binance Spot only

Analyses BTC on 15m, 1h and 4h.
Does not generate coin BUY/SELL signals.
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
    return default if value is None else value


RSI_PERIOD = int(
    _get_setting("RSI_PERIOD", DEFAULT_CONFIG["RSI_PERIOD"])
)

ADX_PERIOD = int(
    _get_setting("ADX_PERIOD", DEFAULT_CONFIG["ADX_PERIOD"])
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
    return _safe_float(row.get(column))


def _is_valid_dataframe(df):
    return (
        isinstance(df, pd.DataFrame)
        and not df.empty
    )


# ==================================================
# 3. BTC TIMEFRAME ANALYSIS
# ==================================================

def analyze_btc_timeframe(df, timeframe):
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
        "plus_di": None,
        "minus_di": None,
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

    columns = (
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
        "plus_di",
        "minus_di",
        "atr",
        "relative_volume",
    )

    for column in columns:
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

    if any(value is None for value in required_values):
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

    if bullish_structure and bullish_momentum:
        result["trend"] = "BULLISH"

    elif bearish_structure and bearish_momentum:
        result["trend"] = "BEARISH"

    else:
        result["trend"] = "NEUTRAL"

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
    one_hour = timeframe_results.get("1h", {})
    four_hour = timeframe_results.get("4h", {})

    trend_1h = one_hour.get("trend", "UNKNOWN")
    trend_4h = four_hour.get("trend", "UNKNOWN")

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

    return "NEUTRAL"


# ==================================================
# 6. HIGH RISK DETECTION + DIAGNOSTICS
# ==================================================

def detect_high_risk(timeframe_results):
    """
    Existing HIGH_RISK conditions are preserved.
    Additional diagnostic logs explain the decision.
    """

    one_hour = timeframe_results.get("1h", {})
    four_hour = timeframe_results.get("4h", {})

    if (
        one_hour.get("data_quality") != "VALID"
        or four_hour.get("data_quality") != "VALID"
    ):
        logger.warning(
            "HIGH_RISK CHECK SKIPPED | "
            "1h quality=%s | 4h quality=%s",
            one_hour.get("data_quality"),
            four_hour.get("data_quality"),
        )
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

    logger.info(
        "BTC HIGH_RISK DIAGNOSTICS | "
        "1h trend=%s close=%s MA20=%s MA50=%s MA200=%s "
        "RSI=%s MACD_HIST=%s ADX=%s | "
        "4h trend=%s close=%s MA20=%s MA50=%s MA200=%s "
        "RSI=%s MACD_HIST=%s ADX=%s",
        one_hour.get("trend"),
        one_hour.get("close"),
        one_hour.get("sma_20"),
        one_hour.get("sma_50"),
        one_hour.get("sma_200"),
        one_hour_rsi,
        one_hour.get("macd_histogram"),
        one_hour_adx,
        four_hour.get("trend"),
        four_hour.get("close"),
        four_hour.get("sma_20"),
        four_hour.get("sma_50"),
        four_hour.get("sma_200"),
        four_hour_rsi,
        four_hour.get("macd_histogram"),
        four_hour_adx,
    )

    logger.info(
        "BTC HIGH_RISK CONDITIONS | "
        "strong_downtrend=%s | "
        "oversold_confirmation=%s | "
        "adx_confirmation=%s | "
        "RSI threshold=%.2f | ADX threshold=%.2f",
        strong_downtrend,
        oversold_confirmation,
        adx_confirmation,
        HIGH_RISK_RSI_MAX,
        STRONG_ADX_MIN,
    )

    if (
        strong_downtrend
        and (
            oversold_confirmation
            or adx_confirmation
        )
    ):
        if oversold_confirmation:
            warnings.append(
                "HIGH_RISK triggered by oversold RSI "
                "confirmation on both 1h and 4h."
            )

        if adx_confirmation:
            warnings.append(
                "HIGH_RISK triggered by strong ADX confirmation."
            )

        warnings.append(
            "BTC shows confirmed bearish conditions "
            "on both 1h and 4h."
        )

        logger.warning(
            "BTC MARKET HIGH_RISK CONFIRMED."
        )

        return True, warnings

    logger.info("BTC HIGH_RISK NOT CONFIRMED.")

    return False, warnings


# ==================================================
# 7. EXTERNAL MARKET DATA
# ==================================================

def analyze_external_data(external_data=None):
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

    if dominance is not None and 0 <= dominance <= 100:
        result["btc_dominance"] = dominance

        dominance_trend = external_data.get(
            "btc_dominance_trend"
        )

        if dominance_trend in ("RISING", "FALLING"):
            result["btc_dominance_status"] = dominance_trend
        else:
            result["btc_dominance_status"] = "AVAILABLE"

    if market_change is not None:
        result["total_market_cap_change_24h_pct"] = market_change

        if market_change > 2:
            result["total_market_status"] = "BULLISH"

        elif market_change < -2:
            result["total_market_status"] = "BEARISH"

        else:
            result["total_market_status"] = "NEUTRAL"

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
    mapping = {
        "BULLISH": "LOW_TO_MODERATE",
        "NEUTRAL": "MODERATE",
        "BEARISH": "HIGH",
        "HIGH_RISK": "VERY_HIGH",
        "UNKNOWN": "UNKNOWN",
    }

    return mapping.get(market_status, "UNKNOWN")


# ==================================================
# 10. MAIN MARKET ANALYSIS
# ==================================================

def analyze_market(btc_data, external_data=None):
    """
    Main market analysis.

    btc_data must contain DataFrames for 15m, 1h and 4h.
    External data is optional and is never fabricated.
    """

    if not isinstance(btc_data, dict):
        return {
            "market_status": "UNKNOWN",
            "btc_trend": "UNKNOWN",
            "btc_rsi": None,
            "btc_volume_status": "UNKNOWN",
            "btc_dominance": None,
            "btc_dominance_status": "UNKNOWN",
            "total_market_cap_change_24h_pct": None,
            "total_market_status": "UNKNOWN",
            "fear_greed_index": None,
            "sentiment_status": "UNKNOWN",
            "risk_level": "UNKNOWN",
            "warnings": [
                "btc_data must be a timeframe dictionary."
            ],
            "data_quality": "INVALID",
            "timeframes": {},
            "signal_policy": {
                "allow_new_signals": False,
                "market_caution": True,
            },
        }

    warnings = []
    timeframe_results = {}

    for timeframe in REQUIRED_TIMEFRAMES:
        timeframe_df = btc_data.get(timeframe)

        timeframe_results[timeframe] = analyze_btc_timeframe(
            timeframe_df,
            timeframe,
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

    market_status, classification_warnings = classify_market(
        btc_trend,
        timeframe_results,
        external_result,
    )

    warnings.extend(classification_warnings)

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

    risk_level = determine_risk_level(market_status)

    if external_result["btc_dominance_status"] == "UNKNOWN":
        warnings.append("BTC dominance data unavailable.")

    if external_result["total_market_status"] == "UNKNOWN":
        warnings.append("Total crypto market cap data unavailable.")

    if external_result["sentiment_status"] == "UNKNOWN":
        warnings.append("Fear and Greed data unavailable.")

    return {
        "market_status": market_status,
        "btc_trend": btc_trend,
        "btc_rsi": one_hour_rsi,
        "btc_volume_status": btc_volume_status,

        "btc_dominance": external_result["btc_dominance"],
        "btc_dominance_status": external_result["btc_dominance_status"],

        "total_market_cap_change_24h_pct": (
            external_result["total_market_cap_change_24h_pct"]
        ),
        "total_market_status": external_result["total_market_status"],

        "fear_greed_index": external_result["fear_greed_index"],
        "sentiment_status": external_result["sentiment_status"],

        "risk_level": risk_level,
        "warnings": list(dict.fromkeys(warnings)),
        "data_quality": data_quality,
        "timeframes": timeframe_results,

        "signal_policy": {
            "allow_new_signals": market_status not in (
                "HIGH_RISK",
                "UNKNOWN",
            ),
            "market_caution": market_status in (
                "BEARISH",
                "NEUTRAL",
            ),
        },
    }


# ==================================================
# 11. MARKET FILTER VALIDATION
# ==================================================


def validate_market_context(market_context):
    """
    Validate BTC market context before allowing new signals.

    Rejects:
    - Missing or malformed market context
    - HIGH_RISK and UNKNOWN market conditions
    - Incomplete or partial market data
    - Inconsistent risk levels
    - Missing or contradictory signal policies
    """

    if not isinstance(market_context, dict):
        return False

    status = market_context.get("market_status")

    if status not in VALID_MARKET_STATUSES:
        return False

    if status in ("HIGH_RISK", "UNKNOWN"):
        return False

    # All required BTC timeframes must be valid.
    if market_context.get("data_quality") != "VALID":
        return False

    # Verify the risk level against the actual market status.
    expected_risk_levels = {
        "BULLISH": "LOW_TO_MODERATE",
        "NEUTRAL": "MODERATE",
        "BEARISH": "HIGH",
        "HIGH_RISK": "VERY_HIGH",
        "UNKNOWN": "UNKNOWN",
    }

    expected_risk = expected_risk_levels.get(status)

    if market_context.get("risk_level") != expected_risk:
        return False

    # Signal policy must exist and explicitly allow new signals.
    signal_policy = market_context.get("signal_policy")

    if not isinstance(signal_policy, dict):
        return False

    if signal_policy.get("allow_new_signals") is not True:
        return False

    # Market caution must match the market classification.
    expected_caution = status in ("BEARISH", "NEUTRAL")

    if signal_policy.get("market_caution") is not expected_caution:
        return False

    return True


# ==================================================
# 12. MODULE STATUS
# ==================================================

def get_market_filter_config():
    return {
        "required_timeframes": REQUIRED_TIMEFRAMES,
        "rsi_period": RSI_PERIOD,
        "adx_period": ADX_PERIOD,
        "min_candles_for_ma200": MIN_CANDLES_FOR_MA200,
        "bullish_rsi_min": BULLISH_RSI_MIN,
        "bearish_rsi_max": BEARISH_RSI_MAX,
        "high_risk_rsi_max": HIGH_RISK_RSI_MAX,
        "strong_adx_min": STRONG_ADX_MIN,
        "high_volume_rvol": HIGH_VOLUME_RVOL,
    }
