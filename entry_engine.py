
"""
Binance Spot V3 Smart Signal Scanner
Entry Signal Generation Engine

Balanced breakout + retest + early breakout hold.
Spot market only.
"""

import logging
import math
from typing import Any

import pandas as pd

from config import SIGNAL_CONFIG
from indicators import calculate_all_indicators

logger = logging.getLogger(__name__)


# =========================================================
# CONFIG HELPERS
# =========================================================

def _normalize_key(value):
    return str(value).lower().replace("_", "").replace("-", "").replace(" ", "")


def _find_config_value(data, target):
    if not isinstance(data, dict):
        return None

    target_key = _normalize_key(target)

    for key, value in data.items():
        if _normalize_key(key) == target_key:
            return value

    for value in data.values():
        if isinstance(value, dict):
            result = _find_config_value(value, target)
            if result is not None:
                return result

    return None


def _setting(key, default):
    value = _find_config_value(SIGNAL_CONFIG, key)
    return default if value is None else value


MIN_SCORE = int(_setting("MIN_SCORE", 9))
STRONG_MIN_SCORE = int(_setting("STRONG_MIN_SCORE", 9))
EXCELLENT_MIN_SCORE = int(_setting("EXCELLENT_MIN_SCORE", 12))
MAX_SCORE = int(_setting("MAX_SCORE", 15))


# =========================================================
# STRATEGY-SPECIFIC THRESHOLDS
# =========================================================

SCALP_CONFIG = {
    "MIN_RVOL": 1.0,
    "MIN_ADX": 14.0,
    "RSI_MIN": 45.0,
    "RSI_MAX": 72.0,
    "MAX_ROC": 4.0,
    "MAX_BB_WIDTH": 0.25,
    "MAX_EMA_EXTENSION_PCT": 3.5,
}

SWING_CONFIG = {
    "MIN_RVOL": 1.1,
    "MIN_ADX": 16.0,
    "RSI_MIN": 47.0,
    "RSI_MAX": 74.0,
    "MAX_ROC": 5.0,
    "MAX_BB_WIDTH": 0.28,
    "MAX_EMA_EXTENSION_PCT": 4.0,
}

MAX_RSI = 76
BREAKOUT_LOOKBACK = 20
RETEST_TOLERANCE_PCT = 0.5
MAX_BREAKOUT_EXTENSION_PCT = 2.5

MAX_CONSECUTIVE_BULLISH = 4
MIN_CANDLE_BODY_PCT = 2.0
RVOL_SPIKE_THRESHOLD = 3.0
RVOL_COLLAPSE_RATIO = 0.5
MIN_UPSIDE_TO_RESISTANCE_PCT = 1.0

APPROVED_CLASSIFICATIONS = ("STRONG BUY", "EXCELLENT BUY")
APPROVED_STRATEGIES = ("SCALP", "SWING")


# =========================================================
# TIMEFRAME-AWARE LOOKBACK
# =========================================================

TIMEFRAME_LOOKBACK_MAP = {
    "1m": 30,
    "3m": 25,
    "5m": 20,
    "15m": 10,
    "30m": 8,
    "1h": 6,
    "2h": 6,
    "4h": 5,
    "1d": 4,
}


def _get_lookback(timeframe):
    return TIMEFRAME_LOOKBACK_MAP.get(str(timeframe).lower(), 20)


# =========================================================
# DYNAMIC CONFIG
# =========================================================

def _get_dynamic_config(strategy, market_status):
    """
    Balanced thresholds:
    BULLISH: normal confirmation.
    NEUTRAL: moderately relaxed.
    BEARISH: selective, but not excessively restrictive.
    """

    base_config = SCALP_CONFIG if strategy == "SCALP" else SWING_CONFIG
    config = dict(base_config)
    market_status = str(market_status).upper()

    if market_status == "BULLISH":
        return config

    if market_status == "NEUTRAL":
        config["MIN_RVOL"] = max(
            0.85,
            base_config["MIN_RVOL"] - 0.15,
        )
        config["MIN_ADX"] = max(
            12.0,
            base_config["MIN_ADX"] - 2.0,
        )
        return config

    if market_status == "BEARISH":
        config["MIN_RVOL"] = max(
            1.0,
            base_config["MIN_RVOL"],
        )
        config["MIN_ADX"] = max(
            16.0,
            base_config["MIN_ADX"],
        )
        return config

    return config


# =========================================================
# GENERAL HELPERS
# =========================================================

def _number(value, default=None):
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError, OverflowError):
        return default


def _latest(df, column, default=None):
    if (
        not isinstance(df, pd.DataFrame)
        or column not in df.columns
        or df.empty
    ):
        return default

    return _number(df[column].iloc[-1], default)


def _previous(df, column, default=None):
    if (
        not isinstance(df, pd.DataFrame)
        or column not in df.columns
        or len(df) < 2
    ):
        return default

    return _number(df[column].iloc[-2], default)


def _find_column(df, names):
    if not isinstance(df, pd.DataFrame):
        return None

    normalized = {
        _normalize_key(column): column
        for column in df.columns
    }

    for name in names:
        result = normalized.get(_normalize_key(name))

        if result is not None:
            return result

    return None


def _value_from_columns(df, names, default=None):
    column = _find_column(df, names)

    if column is None:
        return default

    return _latest(df, column, default)


def _prepare_dataframe(df):
    if not isinstance(df, pd.DataFrame):
        return None

    required = (
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    minimum = max(30, BREAKOUT_LOOKBACK + 3)

    if len(df) < minimum:
        return None

    if any(column not in df.columns for column in required):
        return None

    result = df.copy()

    for column in required:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result = result.dropna(subset=list(required))

    if len(result) < minimum:
        return None

    numeric_values = result[list(required)].to_numpy(dtype=float)

    if not all(
        math.isfinite(float(value))
        for value in numeric_values.ravel()
    ):
        return None

    if (
        (result["open"] <= 0).any()
        or (result["high"] <= 0).any()
        or (result["low"] <= 0).any()
        or (result["close"] <= 0).any()
        or (result["volume"] < 0).any()
    ):
        return None

    if (
        (result["high"] < result["low"]).any()
        or (result["high"] < result["open"]).any()
        or (result["high"] < result["close"]).any()
        or (result["low"] > result["open"]).any()
        or (result["low"] > result["close"]).any()
    ):
        return None

    try:
        result = calculate_all_indicators(result)

    except Exception as exc:
        logger.warning(
            "Indicator calculation failed: %s",
            str(exc),
        )
        return None

    if not isinstance(result, pd.DataFrame) or result.empty:
        return None

    return result.reset_index(drop=True)


def _valid_symbol(symbol):
    if not isinstance(symbol, str):
        return False

    symbol = symbol.strip().upper()

    if not symbol.endswith("USDT"):
        return False

    base_asset = symbol[:-4]

    if (
        not base_asset
        or not base_asset.isascii()
        or not base_asset.isalnum()
    ):
        return False

    if symbol.endswith(
        ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
    ):
        return False

    return True


# =========================================================
# INDICATOR SNAPSHOT
# =========================================================

def _indicator_snapshot(df):
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}

    return {
        "close": _latest(df, "close"),
        "open": _latest(df, "open"),
        "high": _latest(df, "high"),
        "low": _latest(df, "low"),
        "volume": _latest(df, "volume"),
        "previous_volume": _previous(df, "volume"),

        "ema_9": _value_from_columns(df, ["ema_9"]),
        "ema_20": _value_from_columns(df, ["ema_20"]),

        "sma_20": _value_from_columns(df, ["sma_20"]),
        "sma_50": _value_from_columns(df, ["sma_50"]),
        "sma_200": _value_from_columns(df, ["sma_200"]),

        "rsi": _value_from_columns(df, ["rsi"]),

        "macd_histogram": _value_from_columns(
            df,
            ["macd_histogram"],
        ),

        "adx": _value_from_columns(df, ["adx"]),
        "atr": _value_from_columns(df, ["atr"]),
        "vwap": _value_from_columns(df, ["vwap"]),

        "rvol": _value_from_columns(
            df,
            ["relative_volume"],
        ),

        "bb_width": _value_from_columns(
            df,
            ["bb_width"],
        ),

        "roc": _value_from_columns(df, ["roc"]),

        "volume_momentum": _value_from_columns(
            df,
            ["volume_momentum"],
        ),

        "obv": _value_from_columns(df, ["obv"]),
        "cmf": _value_from_columns(df, ["cmf"]),
    }


# =========================================================
# TREND VALIDATION
# =========================================================

def _trend_is_bullish(snapshot):
    close = snapshot.get("close")
    ema_9 = snapshot.get("ema_9")
    ema_20 = snapshot.get("ema_20")

    if None in (close, ema_9, ema_20):
        return False

    return close > ema_20 and ema_9 > ema_20


def _moving_average_is_bullish(snapshot):
    close = snapshot.get("close")
    sma_20 = snapshot.get("sma_20")
    sma_50 = snapshot.get("sma_50")

    if None in (close, sma_20, sma_50):
        return False

    return close > sma_20 and sma_20 > sma_50


def _check_confirmation_trend(snapshots):
    if len(snapshots) < 2:
        return False

    for snapshot in snapshots:
        if not _trend_is_bullish(snapshot):
            return False

        if not _moving_average_is_bullish(snapshot):
            return False

    return True


# =========================================================
# PUMP PROTECTION
# =========================================================

def _has_consecutive_bullish_candles(
    df,
    max_count=MAX_CONSECUTIVE_BULLISH,
    min_body_pct=MIN_CANDLE_BODY_PCT,
):
    if (
        not isinstance(df, pd.DataFrame)
        or len(df) < max_count + 2
    ):
        return False

    candles = df.iloc[-(max_count + 2):-1]

    consecutive = 0
    max_consecutive = 0

    for _, row in candles.iterrows():
        open_p = float(row["open"])
        close_p = float(row["close"])

        if open_p <= 0:
            continue

        body_pct = (close_p - open_p) / open_p * 100

        if body_pct >= min_body_pct:
            consecutive += 1
            max_consecutive = max(
                max_consecutive,
                consecutive,
            )
        else:
            consecutive = 0

    return max_consecutive >= max_count


def _has_rvol_collapse(
    df,
    spike_threshold=RVOL_SPIKE_THRESHOLD,
    collapse_ratio=RVOL_COLLAPSE_RATIO,
):
    if (
        not isinstance(df, pd.DataFrame)
        or "relative_volume" not in df.columns
        or len(df) < 6
    ):
        return False

    rvol = df["relative_volume"].dropna()

    if len(rvol) < 6:
        return False

    recent = rvol.iloc[-6:-1]
    current = rvol.iloc[-1]

    if recent.empty or current is None:
        return False

    recent_peak = recent.max()

    if recent_peak is None or recent_peak <= 0:
        return False

    if (
        recent_peak >= spike_threshold
        and current < recent_peak * collapse_ratio
    ):
        return True

    return False


def _has_insufficient_upside(
    df,
    current_price,
    breakout_resistance=None,
    min_upside_pct=MIN_UPSIDE_TO_RESISTANCE_PCT,
):
    if current_price <= 0:
        return False

    resistance_levels = _find_resistance_levels(df)

    if (
        breakout_resistance is not None
        and breakout_resistance > current_price
    ):
        resistance_levels.append(breakout_resistance)

    above = [
        level
        for level in resistance_levels
        if level > current_price
    ]

    if not above:
        return False

    next_resistance = min(above)

    upside_pct = (
        (next_resistance - current_price)
        / current_price
        * 100
    )

    return upside_pct < min_upside_pct


# =========================================================
# TIMEFRAME-AWARE BREAKOUT
# =========================================================

def _get_breakout_data(df, timeframe="5m"):
    """
    Detect recent confirmed breakout.

    Accepted setups:
    1. Fresh breakout on latest closed candle.
    2. Retest of resistance followed by a hold.
    3. Early hold above broken resistance.

    The latest row must be a CLOSED candle.
    """

    if not isinstance(df, pd.DataFrame):
        return {}

    lookback = _get_lookback(timeframe)
    minimum = lookback + 3

    required_columns = {
        "high",
        "low",
        "close",
    }

    if (
        len(df) < minimum
        or not required_columns.issubset(df.columns)
    ):
        return {}

    latest_index = len(df) - 1
    latest = df.iloc[latest_index]

    latest_close = _number(latest["close"])
    latest_low = _number(latest["low"])

    if (
        latest_close is None
        or latest_low is None
        or latest_close <= 0
    ):
        return {}

    breakout_index = None
    resistance = None

    first_index = max(
        lookback,
        len(df) - 10,
    )

    # Search recent closed candles for a genuine breakout.
    for b_idx in range(
        latest_index,
        first_index - 1,
        -1,
    ):
        previous_close = _number(
            df.iloc[b_idx - 1]["close"]
        )

        breakout_close = _number(
            df.iloc[b_idx]["close"]
        )

        if (
            previous_close is None
            or breakout_close is None
        ):
            continue

        resistance_data = df.iloc[
            b_idx - lookback:b_idx
        ]

        resistance_level = _number(
            resistance_data["high"].max()
        )

        if (
            resistance_level is None
            or resistance_level <= 0
        ):
            continue

        if (
            previous_close <= resistance_level
            and breakout_close > resistance_level
        ):
            breakout_index = b_idx
            resistance = resistance_level
            break

    if (
        breakout_index is None
        or resistance is None
    ):
        return {}

    lower_boundary = resistance * (
        1 - RETEST_TOLERANCE_PCT / 100
    )

    upper_boundary = resistance * (
        1 + RETEST_TOLERANCE_PCT / 100
    )

    retest_valid = (
        lower_boundary <= latest_low <= upper_boundary
        and latest_close >= resistance * 0.995
    )

    fresh_breakout = (
        breakout_index == latest_index
    )

    breakout_hold = (
        latest_close >= resistance
        and latest_low >= resistance * 0.99
    )

    valid_breakout = (
        retest_valid
        or fresh_breakout
        or breakout_hold
    )

    distance_pct = (
        (latest_close - resistance)
        / resistance
        * 100
    )

    return {
        "resistance": resistance,

        "breakout": bool(valid_breakout),
        "retest": bool(retest_valid),
        "breakout_hold": bool(breakout_hold),
        "fresh_breakout": bool(fresh_breakout),

        "above_resistance": (
            latest_close >= resistance * 0.995
        ),

        "breakout_close": _number(
            df.iloc[breakout_index]["close"]
        ),

        "retest_close": latest_close,
        "retest_low": latest_low,

        "distance_from_resistance_pct": distance_pct,

        "breakout_index": breakout_index,
        "retest_index": latest_index,

        "candles_since_breakout": (
            latest_index - breakout_index
        ),

        "lookback_used": lookback,
    }


# =========================================================
# SUPPORT / RESISTANCE
# =========================================================

def _find_support(df, lookback=30):
    if (
        not isinstance(df, pd.DataFrame)
        or len(df) < 5
    ):
        return None

    recent = df.iloc[-lookback:]

    support = _number(
        recent["low"].min()
    )

    if support is None or support <= 0:
        return None

    return support


def _find_resistance_levels(df, lookback=100):
    if (
        not isinstance(df, pd.DataFrame)
        or len(df) < 20
    ):
        return []

    recent = df.iloc[-(lookback + 1):-1]

    highs = recent["high"].tolist()
    closes = recent["close"].tolist()

    if not highs:
        return []

    current_price = (
        _number(closes[-1])
        if closes
        else None
    )

    if (
        current_price is None
        or current_price <= 0
    ):
        return []

    levels = []

    for index in range(3, len(highs) - 3):
        current = _number(highs[index])

        left_highs = [
            _number(highs[i])
            for i in range(index - 3, index)
        ]

        right_highs = [
            _number(highs[i])
            for i in range(index + 1, index + 4)
        ]

        if any(
            value is None
            for value in left_highs + right_highs
        ):
            continue

        if (
            current >= max(left_highs)
            and current >= max(right_highs)
        ):
            if current > current_price * 1.005:
                levels.append(current)

    return sorted(
        set(
            level
            for level in levels
            if level > 0
        )
    )


# =========================================================
# BUYER CONFIRMATION
# =========================================================

def _buyer_confirmation(snapshot):
    close = snapshot.get("close")
    open_price = snapshot.get("open")
    high = snapshot.get("high")
    low = snapshot.get("low")
    volume = snapshot.get("volume")
    previous_volume = snapshot.get("previous_volume")

    if None in (
        close,
        open_price,
        high,
        low,
        volume,
        previous_volume,
    ):
        return False

    candle_range = high - low

    if (
        candle_range <= 0
        or close <= open_price
    ):
        return False

    close_position = (
        (close - low) / candle_range
    )

    volume_confirmed = (
        previous_volume > 0
        and volume >= previous_volume * 0.75
    )

    strong_close = close_position >= 0.65

    return bool(
        volume_confirmed or strong_close
    )


# =========================================================
# MARKET CONTEXT VALIDATION
# =========================================================

def _validate_market_context(market_context):
    if not isinstance(market_context, dict):
        return False, "MISSING_MARKET_CONTEXT"

    market_status = str(
        market_context.get(
            "market_status",
            "UNKNOWN",
        )
    ).upper()

    risk_level = str(
        market_context.get(
            "risk_level",
            "UNKNOWN",
        )
    ).upper()

    btc_trend = str(
        market_context.get(
            "btc_trend",
            "UNKNOWN",
        )
    ).upper()

    if market_status not in (
        "BULLISH",
        "NEUTRAL",
        "BEARISH",
    ):
        return False, "INVALID_MARKET_STATUS"

    if btc_trend not in (
        "BULLISH",
        "NEUTRAL",
        "BEARISH",
    ):
        return False, "INVALID_BTC_TREND"

    if market_context.get("data_quality") != "VALID":
        return False, "INVALID_MARKET_DATA_QUALITY"

    if risk_level in (
        "UNKNOWN",
        "HIGH",
        "EXTREME",
        "VERY_HIGH",
    ):
        return False, "MARKET_RISK_" + risk_level

    signal_policy = market_context.get(
        "signal_policy"
    )

    if not isinstance(signal_policy, dict):
        return False, "MISSING_SIGNAL_POLICY"

    if signal_policy.get("allow_new_signals") is not True:
        return False, "NEW_SIGNALS_NOT_ALLOWED"

    expected_caution = market_status in (
        "BEARISH",
        "NEUTRAL",
    )

    if (
        signal_policy.get("market_caution")
        is not expected_caution
    ):
        return False, "MARKET_CAUTION_MISMATCH"

    return True, None


# =========================================================
# SCORING
# =========================================================

def score_setup(setup_data):
    if not isinstance(setup_data, dict):
        return {
            "score": 0,
            "max_score": MAX_SCORE,
            "required_score": MIN_SCORE,
            "classification": "REJECT",
            "components": {},
        }

    components = setup_data.get(
        "components",
        {},
    )

    if not isinstance(components, dict):
        components = {}

    score = sum(
        1
        for value in components.values()
        if value is True
    )

    score = min(
        score,
        MAX_SCORE,
    )

    btc_trend = str(
        setup_data.get(
            "btc_trend",
            "UNKNOWN",
        )
    ).upper()

    market_status = str(
        setup_data.get(
            "market_status",
            "UNKNOWN",
        )
    ).upper()

    required_score = MIN_SCORE

    if (
        market_status in ("NEUTRAL", "UNKNOWN")
        or btc_trend in ("NEUTRAL", "UNKNOWN")
    ):
        required_score -= 1

    if (
        btc_trend == "BEARISH"
        or market_status == "BEARISH"
    ):
        required_score += 1

    if (
        score >= EXCELLENT_MIN_SCORE
        and score >= required_score
    ):
        classification = "EXCELLENT BUY"

    elif score >= max(
        STRONG_MIN_SCORE,
        required_score,
    ):
        classification = "STRONG BUY"

    else:
        classification = "REJECT"

    return {
        "score": score,
        "max_score": MAX_SCORE,
        "required_score": required_score,
        "classification": classification,
        "components": components,
    }


# =========================================================
# ENTRY VALIDATION
# =========================================================

def validate_entry(
    df,
    market_context,
    strategy="SCALP",
):
    strategy = str(strategy).upper()

    if strategy not in APPROVED_STRATEGIES:
        return {
            "valid": False,
            "reason": "INVALID_STRATEGY",
        }

    if not isinstance(market_context, dict):
        return {
            "valid": False,
            "reason": "MISSING_MARKET_CONTEXT",
        }

    market_status = str(
        market_context.get(
            "market_status",
            "UNKNOWN",
        )
    ).upper()

    config = _get_dynamic_config(
        strategy,
        market_status,
    )

    prepared = _prepare_dataframe(df)

    if prepared is None:
        return {
            "valid": False,
            "reason": "INVALID_TRIGGER_DATA",
        }

    market_valid, market_reason = _validate_market_context(
        market_context
    )

    if not market_valid:
        return {
            "valid": False,
            "reason": market_reason,
        }

    snapshot = _indicator_snapshot(prepared)

    required = (
        "close",
        "open",
        "ema_20",
        "rsi",
        "atr",
        "rvol",
    )

    if any(
        snapshot.get(key) is None
        for key in required
    ):
        return {
            "valid": False,
            "reason": "MISSING_REQUIRED_INDICATORS",
        }

    close = snapshot["close"]
    ema_20 = snapshot["ema_20"]
    rsi = snapshot["rsi"]
    rvol = snapshot["rvol"]

    if (
        snapshot["atr"] <= 0
        or ema_20 <= 0
    ):
        return {
            "valid": False,
            "reason": "INVALID_ATR_OR_EMA",
        }

    if rsi < 0 or rsi > 100:
        return {
            "valid": False,
            "reason": "INVALID_RSI",
        }

    if rsi > MAX_RSI:
        return {
            "valid": False,
            "reason": "RSI_OVEREXTENDED",
        }

    if rvol < config["MIN_RVOL"]:
        logger.info(
            "RVOL REJECT | %s | market=%s | RVOL=%.4f | min=%.2f | close=%.6f",
            strategy,
            market_status,
            rvol,
            config["MIN_RVOL"],
            close,
        )

        return {
            "valid": False,
            "reason": "LOW_RELATIVE_VOLUME",
        }

    if _has_consecutive_bullish_candles(prepared):
        return {
            "valid": False,
            "reason": "CONSECUTIVE_BULLISH_CANDLES",
        }

    if _has_rvol_collapse(prepared):
        return {
            "valid": False,
            "reason": "RVOL_COLLAPSE_AFTER_SPIKE",
        }

    roc = snapshot.get("roc")

    if (
        roc is not None
        and roc > config["MAX_ROC"]
    ):
        return {
            "valid": False,
            "reason": "PRICE_OVEREXTENDED",
        }

    bb_width = snapshot.get("bb_width")

    if (
        bb_width is not None
        and bb_width > config["MAX_BB_WIDTH"]
    ):
        return {
            "valid": False,
            "reason": "BOLLINGER_TOO_WIDE",
        }

    extension_pct = (
        (close - ema_20)
        / ema_20
        * 100
    )

    if extension_pct > config["MAX_EMA_EXTENSION_PCT"]:
        return {
            "valid": False,
            "reason": "ENTRY_TOO_LATE",
        }

    trigger_tf = (
        "5m"
        if strategy == "SCALP"
        else "15m"
    )

    breakout_data = _get_breakout_data(
        prepared,
        timeframe=trigger_tf,
    )

    if not breakout_data:
        return {
            "valid": False,
            "reason": "BREAKOUT_DATA_UNAVAILABLE",
        }

    if not breakout_data["breakout"]:
        return {
            "valid": False,
            "reason": "NO_FRESH_BREAKOUT",
        }

    if not breakout_data["above_resistance"]:
        return {
            "valid": False,
            "reason": "PRICE_BELOW_BREAKOUT_LEVEL",
        }

    if (
        breakout_data["distance_from_resistance_pct"]
        > MAX_BREAKOUT_EXTENSION_PCT
    ):
        return {
            "valid": False,
            "reason": "BREAKOUT_TOO_EXTENDED",
        }

    if _has_insufficient_upside(
        prepared,
        close,
        breakout_data.get("resistance"),
    ):
        return {
            "valid": False,
            "reason": "INSUFFICIENT_UPSIDE_TO_RESISTANCE",
        }

    if not _buyer_confirmation(snapshot):
        return {
            "valid": False,
            "reason": "BUYER_CONFIRMATION_FAILED",
        }

    return {
        "valid": True,
        "reason": None,
        "strategy": strategy,

        "entry_price": close,
        "current_price": close,

        "support": _find_support(prepared),
        "resistance": breakout_data["resistance"],

        "breakout": True,
        "retest": bool(
            breakout_data.get("retest")
        ),

        "breakout_hold": bool(
            breakout_data.get("breakout_hold")
        ),

        "fresh_breakout": bool(
            breakout_data.get("fresh_breakout")
        ),

        "buyer_confirmation": True,

        "breakout_close": breakout_data["breakout_close"],
        "retest_close": breakout_data["retest_close"],

        "extension_pct": round(
            extension_pct,
            4,
        ),

        "atr": snapshot["atr"],
        "rsi": rsi,
        "rvol": rvol,
    }


# =========================================================
# COMPONENT BUILDERS
# =========================================================

def _build_components_scalp(
    trigger,
    entry_validation,
    trend_ok,
    market_status,
    btc_trend,
):
    config = _get_dynamic_config(
        "SCALP",
        market_status,
    )

    return {
        "market_condition": market_status == "BULLISH",
        "btc_context": btc_trend == "BULLISH",

        "multi_timeframe_trend": trend_ok,

        "ema_trend": _trend_is_bullish(trigger),

        "moving_average_trend": _moving_average_is_bullish(
            trigger
        ),

        "rsi_momentum": (
            trigger.get("rsi") is not None
            and SCALP_CONFIG["RSI_MIN"]
            <= trigger["rsi"]
            <= SCALP_CONFIG["RSI_MAX"]
        ),

        "macd_momentum": (
            trigger.get("macd_histogram") is not None
            and trigger["macd_histogram"] > 0
        ),

        "adx_strength": (
            trigger.get("adx") is not None
            and trigger["adx"] >= config["MIN_ADX"]
        ),

        "relative_volume": (
            trigger.get("rvol") is not None
            and trigger["rvol"] >= config["MIN_RVOL"]
        ),

        "vwap_confirmation": (
            trigger.get("vwap") is not None
            and trigger.get("close") is not None
            and trigger["close"] > trigger["vwap"]
        ),

        "buyer_flow": (
            trigger.get("obv") is not None
            and trigger.get("cmf") is not None
            and trigger["cmf"] > 0
        ),

        "breakout_retest": (
            entry_validation.get("breakout") is True
            and (
                entry_validation.get("retest") is True
                or entry_validation.get("breakout_hold") is True
                or entry_validation.get("fresh_breakout") is True
            )
        ),

        "bb_squeeze": (
            trigger.get("bb_width") is not None
            and trigger["bb_width"] < 0.12
        ),

        "early_momentum": (
            trigger.get("roc") is not None
            and 0.5 <= trigger["roc"] <= SCALP_CONFIG["MAX_ROC"]
        ),

        "volume_acceleration": (
            trigger.get("volume_momentum") is not None
            and trigger["volume_momentum"] >= 1.1
        ),
    }


def _build_components_swing(
    trigger,
    entry_validation,
    trend_ok,
    market_status,
    btc_trend,
):
    config = _get_dynamic_config(
        "SWING",
        market_status,
    )

    return {
        "market_condition": market_status == "BULLISH",
        "btc_context": btc_trend == "BULLISH",

        "multi_timeframe_trend": trend_ok,

        "ema_trend": _trend_is_bullish(trigger),

        "moving_average_trend": _moving_average_is_bullish(
            trigger
        ),

        "rsi_momentum": (
            trigger.get("rsi") is not None
            and SWING_CONFIG["RSI_MIN"]
            <= trigger["rsi"]
            <= SWING_CONFIG["RSI_MAX"]
        ),

        "macd_momentum": (
            trigger.get("macd_histogram") is not None
            and trigger["macd_histogram"] > 0
        ),

        "adx_strength": (
            trigger.get("adx") is not None
            and trigger["adx"] >= config["MIN_ADX"]
        ),

        "relative_volume": (
            trigger.get("rvol") is not None
            and trigger["rvol"] >= config["MIN_RVOL"]
        ),

        "vwap_confirmation": (
            trigger.get("vwap") is not None
            and trigger.get("close") is not None
            and trigger["close"] > trigger["vwap"]
        ),

        "buyer_flow": (
            trigger.get("obv") is not None
            and trigger.get("cmf") is not None
            and trigger["cmf"] > 0
        ),

        "breakout_retest": (
            entry_validation.get("breakout") is True
            and (
                entry_validation.get("retest") is True
                or entry_validation.get("breakout_hold") is True
                or entry_validation.get("fresh_breakout") is True
            )
        ),

        "bb_squeeze": (
            trigger.get("bb_width") is not None
            and trigger["bb_width"] < 0.15
        ),

        "early_momentum": (
            trigger.get("roc") is not None
            and 0.5 <= trigger["roc"] <= SWING_CONFIG["MAX_ROC"]
        ),

        "volume_acceleration": (
            trigger.get("volume_momentum") is not None
            and trigger["volume_momentum"] >= 1.05
        ),
    }


# =========================================================
# MAIN EVALUATION
# =========================================================

def _evaluate(
    symbol,
    market_data,
    market_context,
    strategy,
):
    strategy = str(strategy).upper()

    if strategy not in APPROVED_STRATEGIES:
        return {
            "symbol": symbol,
            "classification": "REJECT",
            "reason": "INVALID_STRATEGY",
        }

    if not _valid_symbol(symbol):
        return {
            "symbol": symbol,
            "classification": "REJECT",
            "reason": "INVALID_USDT_SYMBOL",
        }

    if not isinstance(market_data, dict):
        return {
            "symbol": symbol,
            "classification": "REJECT",
            "reason": "INVALID_MARKET_DATA",
        }

    market_valid, market_reason = _validate_market_context(
        market_context
    )

    if not market_valid:
        return {
            "symbol": symbol,
            "strategy": strategy,
            "classification": "REJECT",
            "reason": market_reason,
        }

    if strategy == "SCALP":
        trigger_tf = "5m"
        confirmation_tfs = (
            "15m",
            "30m",
        )
    else:
        trigger_tf = "15m"
        confirmation_tfs = (
            "30m",
            "1h",
        )

    required_tfs = (
        trigger_tf,
    ) + confirmation_tfs

    snapshots = {}
    prepared_data = {}

    for timeframe in required_tfs:
        df = market_data.get(timeframe)

        prepared = _prepare_dataframe(df)

        if prepared is None:
            return {
                "symbol": symbol,
                "strategy": strategy,
                "classification": "REJECT",
                "reason": "INVALID_" + timeframe.upper() + "_DATA",
            }

        prepared_data[timeframe] = prepared
        snapshots[timeframe] = _indicator_snapshot(
            prepared
        )

    trigger = snapshots[trigger_tf]

    confirmation_snapshots = [
        snapshots[timeframe]
        for timeframe in confirmation_tfs
    ]

    entry_validation = validate_entry(
        prepared_data[trigger_tf],
        market_context,
        strategy,
    )

    if not entry_validation.get("valid"):
        return {
            "symbol": symbol,
            "strategy": strategy,
            "classification": "REJECT",
            "reason": entry_validation.get("reason"),
        }

    # Multi-timeframe trend is a scoring component,
    # not a separate hard rejection.
    trend_ok = _check_confirmation_trend(
        confirmation_snapshots
    )

    buyer_ok = entry_validation.get(
        "buyer_confirmation",
        False,
    )

    market_status = str(
        market_context.get(
            "market_status",
            "UNKNOWN",
        )
    ).upper()

    btc_trend = str(
        market_context.get(
            "btc_trend",
            "UNKNOWN",
        )
    ).upper()

    if strategy == "SCALP":
        components = _build_components_scalp(
            trigger,
            entry_validation,
            trend_ok,
            market_status,
            btc_trend,
        )
    else:
        components = _build_components_swing(
            trigger,
            entry_validation,
            trend_ok,
            market_status,
            btc_trend,
        )

    if not buyer_ok:
        return {
            "symbol": symbol,
            "strategy": strategy,
            "classification": "REJECT",
            "reason": "BUYER_CONFIRMATION_FAILED",
            "components": components,
        }

    scoring = score_setup({
        "components": components,
        "btc_trend": btc_trend,
        "market_status": market_status,
    })

    classification = scoring["classification"]

    if classification not in APPROVED_CLASSIFICATIONS:
        return {
            "symbol": symbol,
            "strategy": strategy,
            "classification": "REJECT",
            "reason": "SCORE_BELOW_REQUIRED_LEVEL",
            "score": scoring["score"],
            "components": components,
        }

    trigger_df = prepared_data[trigger_tf]

    support = entry_validation.get("support")
    resistance = entry_validation.get("resistance")

    resistance_levels = _find_resistance_levels(
        trigger_df
    )

    if resistance is not None:
        resistance_levels.append(resistance)

    resistance_levels = sorted(
        set(
            level
            for level in resistance_levels
            if level > entry_validation["entry_price"]
        )
    )

    signal = {
        "symbol": symbol,
        "strategy": strategy,
        "classification": classification,
        "signal": classification,

        "score": scoring["score"],
        "max_score": scoring["max_score"],
        "required_score": scoring["required_score"],

        "components": components,

        "entry_price": entry_validation["entry_price"],
        "current_price": entry_validation["current_price"],
        "last_price": entry_validation["current_price"],

        "support": support,
        "support_level": support,
        "nearest_support": support,

        "resistance": resistance,
        "resistance_levels": resistance_levels,

        "atr": entry_validation["atr"],
        "atr_value": entry_validation["atr"],

        "rsi": entry_validation["rsi"],
        "rvol": entry_validation["rvol"],

        "market_status": market_status,
        "btc_trend": btc_trend,

        "breakout_confirmed": True,

        "retest_confirmed": bool(
            entry_validation.get("retest")
        ),

        "breakout_hold_confirmed": bool(
            entry_validation.get("breakout_hold")
        ),

        "fresh_breakout_confirmed": bool(
            entry_validation.get("fresh_breakout")
        ),

        "buyer_confirmation": True,

        "entry_status": "CANDIDATE",
        "risk_status": "PENDING_RISK_VALIDATION",

        "risk_plan": None,
        "warnings": [],
    }

    if btc_trend == "BEARISH":
        signal["warnings"].append(
            "BTC trend is bearish; extra caution required"
        )

    if market_status == "BEARISH":
        signal["warnings"].append(
            "Overall market condition is bearish"
        )

    return signal


# =========================================================
# PUBLIC FUNCTIONS
# =========================================================

def evaluate_scalp(
    symbol,
    market_data,
    indicators=None,
    market_context=None,
):
    return _evaluate(
        symbol=symbol,
        market_data=market_data,
        market_context=market_context,
        strategy="SCALP",
    )


def evaluate_swing(
    symbol,
    market_data,
    indicators=None,
    market_context=None,
):
    return _evaluate(
        symbol=symbol,
        market_data=market_data,
        market_context=market_context,
        strategy="SWING",
    )
