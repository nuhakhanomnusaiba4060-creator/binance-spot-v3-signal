"""
Binance Spot V3 Smart Signal Scanner
Entry Signal Generation Engine

Spot market only.
No Futures or Margin.

Focus: PROFIT-FIRST (quality over quantity)
- SCALP / SWING separate scoring (strict thresholds)
- Breakout + separate candle retest
- Pump protection (consecutive bullish, RVOL collapse, insufficient upside)
- Early-pump indicators (BB squeeze, ROC, volume momentum)
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
    return (
        str(value)
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


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


MIN_SCORE = int(_setting("MIN_SCORE", 10))
STRONG_MIN_SCORE = int(_setting("STRONG_MIN_SCORE", 10))
EXCELLENT_MIN_SCORE = int(_setting("EXCELLENT_MIN_SCORE", 13))
MAX_SCORE = int(_setting("MAX_SCORE", 15))


# =========================================================
# STRATEGY-SPECIFIC THRESHOLDS (Profit-Quality Balanced)
# =========================================================

SCALP_CONFIG = {
    "MIN_RVOL": 1.4,               # ফেক পাম্প বাদ দিতে 1.4x ভলিউম
    "MIN_ADX": 18.0,               # শক্তিশালী ট্রেন্ড নিশ্চিত করতে
    "RSI_MIN": 50.0,               # মোমেন্টাম নিশ্চিত করতে
    "RSI_MAX": 68.0,               # ওভারবট হওয়ার আগেই এন্ট্রি
    "MAX_ROC": 3.5,                # এর বেশি বাড়লে "লেট এন্ট্রি" বাদ যাবে
    "MAX_BB_WIDTH": 0.20,          # বেশি ভলাটাইল কয়েন বাদ
    "MAX_EMA_EXTENSION_PCT": 3.0,  # EMA20 থেকে বেশি দূরে থাকলে বাদ
}

SWING_CONFIG = {
    "MIN_RVOL": 1.5,               # সুইংয়ের জন্য আরও শক্তিশালী ভলিউম
    "MIN_ADX": 22.0,               # সুইংয়ে শক্তিশালী ট্রেন্ড দরকার
    "RSI_MIN": 52.0,
    "RSI_MAX": 70.0,
    "MAX_ROC": 4.5,
    "MAX_BB_WIDTH": 0.25,
    "MAX_EMA_EXTENSION_PCT": 3.5,
}

# Global safety limits
MAX_RSI = 74
BREAKOUT_LOOKBACK = 20
RETEST_TOLERANCE_PCT = 0.5
MAX_BREAKOUT_EXTENSION_PCT = 2.0

# 🔥 Pump Protection constants
MAX_CONSECUTIVE_BULLISH = 3
MIN_CANDLE_BODY_PCT = 1.5
RVOL_SPIKE_THRESHOLD = 2.0
RVOL_COLLAPSE_RATIO = 0.7
MIN_UPSIDE_TO_RESISTANCE_PCT = 1.5

APPROVED_CLASSIFICATIONS = (
    "STRONG BUY",
    "EXCELLENT BUY",
)

APPROVED_STRATEGIES = ("SCALP", "SWING")


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
    normalized = {_normalize_key(c): c for c in df.columns}
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

    required = ("open", "high", "low", "close", "volume")
    minimum = max(30, BREAKOUT_LOOKBACK + 2)

    if len(df) < minimum:
        return None

    if any(column not in df.columns for column in required):
        return None

    result = df.copy()

    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.dropna(subset=list(required))

    if len(result) < minimum:
        return None

    # Drop latest unclosed candle
    if len(result) > 1:
        result = result.iloc[:-1]

    numeric_values = result[list(required)].to_numpy(dtype=float)

    if not all(math.isfinite(float(v)) for v in numeric_values.ravel()):
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
        logger.warning("Indicator calculation failed: %s", str(exc))
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
    if not base_asset or not base_asset.isascii() or not base_asset.isalnum():
        return False
    if symbol.endswith(("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")):
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
        "ema_9": _value_from_columns(df, ["ema_9", "ema9"]),
        "ema_20": _value_from_columns(df, ["ema_20", "ema20"]),
        "sma_20": _value_from_columns(df, ["sma_20", "sma20"]),
        "sma_50": _value_from_columns(df, ["sma_50", "sma50"]),
        "sma_200": _value_from_columns(df, ["sma_200", "sma200"]),
        "rsi": _value_from_columns(df, ["rsi", "rsi_14", "rsi14"]),
        "macd_histogram": _value_from_columns(df, ["macd_histogram", "macd_hist"]),
        "adx": _value_from_columns(df, ["adx", "adx_14", "adx14"]),
        "atr": _value_from_columns(df, ["atr", "atr_14", "atr14"]),
        "vwap": _value_from_columns(df, ["vwap", "session_vwap"]),
        "rvol": _value_from_columns(df, ["relative_volume", "rvol"]),
        "bb_width": _value_from_columns(df, ["bb_width"]),
        "roc": _value_from_columns(df, ["roc"]),
        "volume_momentum": _value_from_columns(df, ["volume_momentum"]),
        "obv": _value_from_columns(df, ["obv"]),
        "cmf": _value_from_columns(df, ["cmf", "cmf_20", "cmf20"]),
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
# 🔥 PUMP PROTECTION
# =========================================================

def _has_consecutive_bullish_candles(df, max_count=MAX_CONSECUTIVE_BULLISH, min_body_pct=MIN_CANDLE_BODY_PCT):
    if not isinstance(df, pd.DataFrame) or len(df) < max_count + 2:
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
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    return max_consecutive >= max_count


def _has_rvol_collapse(df, spike_threshold=RVOL_SPIKE_THRESHOLD, collapse_ratio=RVOL_COLLAPSE_RATIO):
    if "relative_volume" not in df.columns or len(df) < 6:
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

    if recent_peak >= spike_threshold and current < recent_peak * collapse_ratio:
        return True

    return False


def _has_insufficient_upside(df, current_price, breakout_resistance=None, min_upside_pct=MIN_UPSIDE_TO_RESISTANCE_PCT):
    if current_price <= 0:
        return False

    resistance_levels = _find_resistance_levels(df)

    if breakout_resistance is not None and breakout_resistance > current_price:
        resistance_levels.append(breakout_resistance)

    above = [level for level in resistance_levels if level > current_price]

    if not above:
        return False

    next_resistance = min(above)
    upside_pct = (next_resistance - current_price) / current_price * 100

    return upside_pct < min_upside_pct


# =========================================================
# BREAKOUT AND SEPARATE-CANDLE RETEST
# =========================================================

def _get_breakout_data(df):
    if not isinstance(df, pd.DataFrame):
        return {}

    minimum = BREAKOUT_LOOKBACK + 5
    if len(df) < minimum:
        return {}

    required_columns = {"high", "low", "close"}
    if not required_columns.issubset(df.columns):
        return {}

    retest_index = len(df) - 1
    retest_candle = df.iloc[retest_index]

    resistance_start_latest = retest_index - BREAKOUT_LOOKBACK
    if resistance_start_latest >= 0:
        res_data_latest = df.iloc[resistance_start_latest:retest_index]
        res_level_latest = _number(res_data_latest["high"].max())
        if res_level_latest is not None and _number(retest_candle["close"]) > res_level_latest:
            return {}

    breakout_found = False
    breakout_index = -1
    resistance = None

    for i in range(2, 5):
        b_idx = len(df) - i
        resistance_start = b_idx - BREAKOUT_LOOKBACK
        if resistance_start < 0:
            continue

        res_data = df.iloc[resistance_start:b_idx]
        res_level = _number(res_data["high"].max())

        b_candle = df.iloc[b_idx]
        pre_b_candle = df.iloc[b_idx - 1]

        if (
            _number(pre_b_candle["close"]) <= res_level
            and _number(b_candle["close"]) > res_level
        ):
            breakout_found = True
            breakout_index = b_idx
            resistance = res_level
            break

    if not breakout_found:
        return {}

    breakout_candle = df.iloc[breakout_index]
    retest_close = _number(retest_candle["close"])
    retest_low = _number(retest_candle["low"])

    if None in (resistance, retest_close, retest_low):
        return {}

    lower_boundary = resistance * (1 - RETEST_TOLERANCE_PCT / 100)
    upper_boundary = resistance * (1 + RETEST_TOLERANCE_PCT / 100)

    retest_candle_valid = (
        retest_low >= lower_boundary
        and retest_low <= upper_boundary
        and retest_close >= resistance
    )

    breakout = retest_candle_valid
    distance_pct = ((retest_close - resistance) / resistance) * 100

    return {
        "resistance": resistance,
        "breakout": breakout,
        "retest": breakout,
        "above_resistance": retest_close >= resistance,
        "breakout_close": _number(breakout_candle["close"]),
        "retest_close": retest_close,
        "retest_low": retest_low,
        "distance_from_resistance_pct": distance_pct,
        "breakout_index": breakout_index,
        "retest_index": retest_index,
    }


# =========================================================
# SUPPORT AND RESISTANCE
# =========================================================

def _find_support(df, lookback=30):
    if not isinstance(df, pd.DataFrame) or len(df) < 5:
        return None
    recent = df.iloc[-lookback:]
    support = _number(recent["low"].min())
    if support is None or support <= 0:
        return None
    return support


def _find_resistance_levels(df, lookback=100):
    if not isinstance(df, pd.DataFrame) or len(df) < 10:
        return []
    recent = df.iloc[-(lookback + 1):-1]
    highs = recent["high"].tolist()
    levels = []
    for index in range(1, len(highs) - 1):
        current = _number(highs[index])
        left = _number(highs[index - 1])
        right = _number(highs[index + 1])
        if None in (current, left, right):
            continue
        if current >= left and current >= right:
            levels.append(current)
    return sorted(set(level for level in levels if level > 0))


# =========================================================
# BUYER CONFIRMATION
# =========================================================

def _buyer_confirmation(snapshot):
    close = snapshot.get("close")
    open_price = snapshot.get("open")
    volume = snapshot.get("volume")
    previous_volume = snapshot.get("previous_volume")
    if None in (close, open_price, volume, previous_volume):
        return False
    return close > open_price and volume >= previous_volume


# =========================================================
# MARKET CONTEXT VALIDATION
# =========================================================

def _validate_market_context(market_context):
    if not isinstance(market_context, dict):
        return False, "MISSING_MARKET_CONTEXT"

    market_status = str(market_context.get("market_status", "UNKNOWN")).upper()
    risk_level = str(market_context.get("risk_level", "UNKNOWN")).upper()
    btc_trend = str(market_context.get("btc_trend", "UNKNOWN")).upper()

    if market_status not in ("BULLISH", "NEUTRAL", "BEARISH"):
        return False, "INVALID_MARKET_STATUS"
    if btc_trend not in ("BULLISH", "NEUTRAL", "BEARISH"):
        return False, "INVALID_BTC_TREND"
    if market_context.get("data_quality") != "VALID":
        return False, "INVALID_MARKET_DATA_QUALITY"
    if risk_level in ("UNKNOWN", "EXTREME", "VERY_HIGH"):
        return False, "MARKET_RISK_" + risk_level
    if risk_level == "HIGH":
        if market_status != "BEARISH" or btc_trend != "BEARISH":
            return False, "MARKET_RISK_HIGH"

    signal_policy = market_context.get("signal_policy")
    if not isinstance(signal_policy, dict):
        return False, "MISSING_SIGNAL_POLICY"
    if signal_policy.get("allow_new_signals") is not True:
        return False, "NEW_SIGNALS_NOT_ALLOWED"

    expected_caution = market_status in ("BEARISH", "NEUTRAL")
    if signal_policy.get("market_caution") is not expected_caution:
        return False, "MARKET_CAUTION_MISMATCH"

    return True, None


# =========================================================
# SCORING ENGINE
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

    components = setup_data.get("components", {})
    if not isinstance(components, dict):
        components = {}

    score = sum(1 for value in components.values() if value is True)
    score = min(score, MAX_SCORE)

    btc_trend = str(setup_data.get("btc_trend", "UNKNOWN")).upper()
    market_status = str(setup_data.get("market_status", "UNKNOWN")).upper()

    required_score = MIN_SCORE

    if market_status == "NEUTRAL" or btc_trend == "NEUTRAL":
        required_score -= 2

    if btc_trend == "BEARISH" or market_status == "BEARISH":
        required_score += 1

    if score >= EXCELLENT_MIN_SCORE and score >= required_score:
        classification = "EXCELLENT BUY"
    elif score >= max(STRONG_MIN_SCORE, required_score):
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

def validate_entry(df, market_context, strategy="SCALP"):
    strategy = str(strategy).upper()

    if strategy not in APPROVED_STRATEGIES:
        return {"valid": False, "reason": "INVALID_STRATEGY"}

    config = SCALP_CONFIG if strategy == "SCALP" else SWING_CONFIG

    prepared = _prepare_dataframe(df)
    if prepared is None:
        return {"valid": False, "reason": "INVALID_TRIGGER_DATA"}

    market_valid, market_reason = _validate_market_context(market_context)
    if not market_valid:
        return {"valid": False, "reason": market_reason}

    snapshot = _indicator_snapshot(prepared)

    required = ("close", "open", "ema_20", "rsi", "atr", "rvol")
    if any(snapshot.get(key) is None for key in required):
        return {"valid": False, "reason": "MISSING_REQUIRED_INDICATORS"}

    close = snapshot["close"]
    ema_20 = snapshot["ema_20"]
    rsi = snapshot["rsi"]
    rvol = snapshot["rvol"]

    if snapshot["atr"] <= 0 or ema_20 <= 0:
        return {"valid": False, "reason": "INVALID_ATR_OR_EMA"}

    if rsi < 0 or rsi > 100:
        return {"valid": False, "reason": "INVALID_RSI"}

    if rsi > MAX_RSI:
        return {"valid": False, "reason": "RSI_OVEREXTENDED"}

    if rvol < config["MIN_RVOL"]:
        return {"valid": False, "reason": "LOW_RELATIVE_VOLUME"}

    if _has_consecutive_bullish_candles(prepared):
        return {"valid": False, "reason": "CONSECUTIVE_BULLISH_CANDLES"}

    if _has_rvol_collapse(prepared):
        return {"valid": False, "reason": "RVOL_COLLAPSE_AFTER_SPIKE"}

    roc = snapshot.get("roc")
    if roc is not None and roc > config["MAX_ROC"]:
        return {"valid": False, "reason": "PRICE_OVEREXTENDED"}

    bb_width = snapshot.get("bb_width")
    if bb_width is not None and bb_width > config["MAX_BB_WIDTH"]:
        return {"valid": False, "reason": "BOLLINGER_TOO_WIDE"}

    extension_pct = (close - ema_20) / ema_20 * 100
    if extension_pct > config["MAX_EMA_EXTENSION_PCT"]:
        return {"valid": False, "reason": "ENTRY_TOO_LATE"}

    breakout_data = _get_breakout_data(prepared)
    if not breakout_data:
        return {"valid": False, "reason": "BREAKOUT_DATA_UNAVAILABLE"}

    if not breakout_data["breakout"]:
        return {"valid": False, "reason": "NO_FRESH_BREAKOUT"}

    if not breakout_data["retest"]:
        return {"valid": False, "reason": "SEPARATE_CANDLE_RETEST_NOT_CONFIRMED"}

    if not breakout_data["above_resistance"]:
        return {"valid": False, "reason": "RETEST_CLOSE_BELOW_RESISTANCE"}

    if breakout_data["distance_from_resistance_pct"] > MAX_BREAKOUT_EXTENSION_PCT:
        return {"valid": False, "reason": "BREAKOUT_TOO_EXTENDED"}

    if _has_insufficient_upside(
        prepared, close, breakout_data.get("resistance")
    ):
        return {"valid": False, "reason": "INSUFFICIENT_UPSIDE_TO_RESISTANCE"}

    if not _buyer_confirmation(snapshot):
        return {"valid": False, "reason": "BUYER_CONFIRMATION_FAILED"}

    return {
        "valid": True,
        "reason": None,
        "strategy": strategy,
        "entry_price": close,
        "current_price": close,
        "support": _find_support(prepared),
        "resistance": breakout_data["resistance"],
        "breakout": True,
        "retest": True,
        "buyer_confirmation": True,
        "breakout_close": breakout_data["breakout_close"],
        "retest_close": breakout_data["retest_close"],
        "extension_pct": round(extension_pct, 4),
        "atr": snapshot["atr"],
        "rsi": rsi,
        "rvol": rvol,
    }


# =========================================================
# STRATEGY-SPECIFIC COMPONENT BUILDERS
# =========================================================

def _build_components_scalp(trigger, entry_validation, trend_ok, market_status, btc_trend):
    return {
        "market_condition": market_status == "BULLISH",
        "btc_context": btc_trend == "BULLISH",
        "multi_timeframe_trend": trend_ok,
        "ema_trend": _trend_is_bullish(trigger),
        "moving_average_trend": _moving_average_is_bullish(trigger),
        "rsi_momentum": (
            trigger.get("rsi") is not None
            and SCALP_CONFIG["RSI_MIN"] <= trigger["rsi"] <= SCALP_CONFIG["RSI_MAX"]
        ),
        "macd_momentum": (
            trigger.get("macd_histogram") is not None
            and trigger["macd_histogram"] > 0
        ),
        "adx_strength": (
            trigger.get("adx") is not None
            and trigger["adx"] >= SCALP_CONFIG["MIN_ADX"]
        ),
        "relative_volume": (
            trigger.get("rvol") is not None
            and trigger["rvol"] >= SCALP_CONFIG["MIN_RVOL"]
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
            and entry_validation.get("retest") is True
        ),
        "bb_squeeze": (
            trigger.get("bb_width") is not None
            and trigger["bb_width"] < 0.15
        ),
        "early_momentum": (
            trigger.get("roc") is not None
            and 0.3 <= trigger["roc"] <= SCALP_CONFIG["MAX_ROC"]
        ),
        "volume_acceleration": (
            trigger.get("volume_momentum") is not None
            and trigger["volume_momentum"] >= 1.15
        ),
    }


def _build_components_swing(trigger, entry_validation, trend_ok, market_status, btc_trend):
    return {
        "market_condition": market_status == "BULLISH",
        "btc_context": btc_trend == "BULLISH",
        "multi_timeframe_trend": trend_ok,
        "ema_trend": _trend_is_bullish(trigger),
        "moving_average_trend": _moving_average_is_bullish(trigger),
        "rsi_momentum": (
            trigger.get("rsi") is not None
            and SWING_CONFIG["RSI_MIN"] <= trigger["rsi"] <= SWING_CONFIG["RSI_MAX"]
        ),
        "macd_momentum": (
            trigger.get("macd_histogram") is not None
            and trigger["macd_histogram"] > 0
        ),
        "adx_strength": (
            trigger.get("adx") is not None
            and trigger["adx"] >= SWING_CONFIG["MIN_ADX"]
        ),
        "relative_volume": (
            trigger.get("rvol") is not None
            and trigger["rvol"] >= SWING_CONFIG["MIN_RVOL"]
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
            and entry_validation.get("retest") is True
        ),
        "bb_squeeze": (
            trigger.get("bb_width") is not None
            and trigger["bb_width"] < 0.18
        ),
        "early_momentum": (
            trigger.get("roc") is not None
            and 0.3 <= trigger["roc"] <= SWING_CONFIG["MAX_ROC"]
        ),
        "volume_acceleration": (
            trigger.get("volume_momentum") is not None
            and trigger["volume_momentum"] >= 1.10
        ),
    }


# =========================================================
# MAIN EVALUATION
# =========================================================

def _evaluate(symbol, market_data, market_context, strategy):
    strategy = str(strategy).upper()

    if strategy not in APPROVED_STRATEGIES:
        return {"symbol": symbol, "classification": "REJECT", "reason": "INVALID_STRATEGY"}

    if not _valid_symbol(symbol):
        return {"symbol": symbol, "classification": "REJECT", "reason": "INVALID_USDT_SYMBOL"}

    if not isinstance(market_data, dict):
        return {"symbol": symbol, "classification": "REJECT", "reason": "INVALID_MARKET_DATA"}

    market_valid, market_reason = _validate_market_context(market_context)
    if not market_valid:
        return {"symbol": symbol, "strategy": strategy, "classification": "REJECT", "reason": market_reason}

    if strategy == "SCALP":
        trigger_tf = "5m"
        confirmation_tfs = ("15m", "30m")
    else:
        trigger_tf = "15m"
        confirmation_tfs = ("30m", "1h")

    required_tfs = (trigger_tf,) + confirmation_tfs

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
        snapshots[timeframe] = _indicator_snapshot(prepared)

    trigger = snapshots[trigger_tf]
    confirmation_snapshots = [snapshots[tf] for tf in confirmation_tfs]

    entry_validation = validate_entry(prepared_data[trigger_tf], market_context, strategy)
    if not entry_validation.get("valid"):
        return {
            "symbol": symbol,
            "strategy": strategy,
            "classification": "REJECT",
            "reason": entry_validation.get("reason"),
        }

    trend_ok = _check_confirmation_trend(confirmation_snapshots)
    buyer_ok = entry_validation.get("buyer_confirmation", False)

    market_status = str(market_context.get("market_status", "UNKNOWN")).upper()
    btc_trend = str(market_context.get("btc_trend", "UNKNOWN")).upper()

    if strategy == "SCALP":
        components = _build_components_scalp(
            trigger, entry_validation, trend_ok, market_status, btc_trend
        )
    else:
        components = _build_components_swing(
            trigger, entry_validation, trend_ok, market_status, btc_trend
        )

    if not trend_ok:
        return {
            "symbol": symbol,
            "strategy": strategy,
            "classification": "REJECT",
            "reason": "MULTI_TIMEFRAME_TREND_FAILED",
            "components": components,
        }

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

    resistance_levels = _find_resistance_levels(trigger_df)
    if resistance is not None:
        resistance_levels.append(resistance)

    resistance_levels = sorted(
        set(level for level in resistance_levels if level > entry_validation["entry_price"])
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
        "retest_confirmed": True,
        "buyer_confirmation": True,
        "entry_status": "CANDIDATE",
        "risk_status": "PENDING_RISK_VALIDATION",
        "risk_plan": None,
        "warnings": [],
    }

    if btc_trend == "BEARISH":
        signal["warnings"].append("BTC trend is bearish; extra caution required")
    if market_status == "BEARISH":
        signal["warnings"].append("Overall market condition is bearish")

    return signal


# =========================================================
# PUBLIC FUNCTIONS
# =========================================================

def evaluate_scalp(symbol, market_data, indicators=None, market_context=None):
    return _evaluate(symbol=symbol, market_data=market_data, market_context=market_context, strategy="SCALP")


def evaluate_swing(symbol, market_data, indicators=None, market_context=None):
    return _evaluate(symbol=symbol, market_data=market_data, market_context=market_context, strategy="SWING")
