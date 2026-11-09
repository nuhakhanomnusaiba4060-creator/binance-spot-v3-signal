
"""
Binance Spot V3 Smart Signal Scanner
Entry Signal Generation Engine

Responsibilities:
- Evaluate scalp and swing entry setups.
- Confirm breakout, candle close and retest.
- Validate multi-timeframe trend and buyer confirmation.
- Calculate a 12-component setup score.
- Reject weak, late and invalid entries.
- Return structured signal candidates for risk validation.

Spot market only.
No Futures or Margin.
No Stop Loss or position sizing is calculated here.
"""

import logging
import math
from typing import Any

import pandas as pd

from config import SIGNAL_CONFIG, TIMEFRAMES
from indicators import calculate_all_indicators


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CONFIG HELPERS
# ---------------------------------------------------------

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


MIN_SCORE = int(_setting("MIN_SCORE", 9))
STRONG_MIN_SCORE = int(_setting("STRONG_MIN_SCORE", 9))
EXCELLENT_MIN_SCORE = int(_setting("EXCELLENT_MIN_SCORE", 11))
MAX_SCORE = int(_setting("MAX_SCORE", 12))

MIN_RVOL = 1.5
MAX_RSI = 74
MAX_EMA_EXTENSION_PCT = 3.0

BREAKOUT_LOOKBACK = 20
RETEST_TOLERANCE_PCT = 0.5


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def _number(value, default=None):
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError):
        return default


def _latest(df, column, default=None):
    if not isinstance(df, pd.DataFrame):
        return default

    if column not in df.columns or df.empty:
        return default

    return _number(df[column].iloc[-1], default)


def _previous(df, column, default=None):
    if not isinstance(df, pd.DataFrame):
        return default

    if column not in df.columns or len(df) < 2:
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
    """
    Validate and calculate indicators for one timeframe.
    """

    if not isinstance(df, pd.DataFrame):
        return None

    if len(df) < 30:
        return None

    required = ("open", "high", "low", "close", "volume")

    if any(column not in df.columns for column in required):
        return None

    result = df.copy()

    for column in required:
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result = result.dropna(
        subset=list(required)
    )

    if len(result) < 30:
        return None

    if (
        (result["close"] <= 0).any()
        or (result["high"] <= 0).any()
        or (result["low"] <= 0).any()
        or (result["volume"] < 0).any()
    ):
        return None

    if (
        (result["high"] < result["low"]).any()
        or (result["high"] < result["close"]).any()
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

    symbol = symbol.upper().strip()

    return (
        symbol.endswith("USDT")
        and len(symbol) > 4
        and not symbol.endswith(
            ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
        )
    )


# ---------------------------------------------------------
# INDICATOR SNAPSHOT
# ---------------------------------------------------------

def _indicator_snapshot(df):
    """
    Read indicator values using the current indicators.py
    output and common alternative column names.
    """

    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}

    close = _latest(df, "close")
    open_price = _latest(df, "open")
    high = _latest(df, "high")
    low = _latest(df, "low")
    volume = _latest(df, "volume")
    previous_volume = _previous(df, "volume")

    return {
        "close": close,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "previous_volume": previous_volume,

        "ema_9": _value_from_columns(
            df, ["ema_9", "ema9"]
        ),
        "ema_20": _value_from_columns(
            df, ["ema_20", "ema20"]
        ),
        "sma_20": _value_from_columns(
            df, ["sma_20", "sma20"]
        ),
        "sma_50": _value_from_columns(
            df, ["sma_50", "sma50"]
        ),
        "sma_200": _value_from_columns(
            df, ["sma_200", "sma200"]
        ),
        "rsi": _value_from_columns(
            df, ["rsi", "rsi_14", "rsi14"]
        ),
        "macd_histogram": _value_from_columns(
            df,
            [
                "macd_histogram",
                "macd_hist",
                "macd_hist_12_26_9",
            ],
        ),
        "adx": _value_from_columns(
            df, ["adx", "adx_14", "adx14"]
        ),
        "atr": _value_from_columns(
            df, ["atr", "atr_14", "atr14"]
        ),
        "vwap": _value_from_columns(
            df, ["vwap", "session_vwap"]
        ),
        "rvol": _value_from_columns(
            df,
            [
                "relative_volume",
                "rvol",
                "relative_volume_20",
            ],
        ),
        "obv": _value_from_columns(
            df, ["obv"]
        ),
        "cmf": _value_from_columns(
            df, ["cmf", "cmf_20", "cmf20"]
        ),
    }


# ---------------------------------------------------------
# TREND VALIDATION
# ---------------------------------------------------------

def _trend_is_bullish(snapshot):
    close = snapshot.get("close")
    ema_9 = snapshot.get("ema_9")
    ema_20 = snapshot.get("ema_20")

    if None in (close, ema_9, ema_20):
        return False

    return (
        close > ema_20
        and ema_9 > ema_20
    )


def _moving_average_is_bullish(snapshot):
    close = snapshot.get("close")
    sma_20 = snapshot.get("sma_20")
    sma_50 = snapshot.get("sma_50")

    if None in (close, sma_20, sma_50):
        return False

    return (
        close > sma_20
        and sma_20 > sma_50
    )


def _check_confirmation_trend(snapshots):
    """
    Both confirmation timeframes must support the trend.
    EMA and SMA confirmation are checked together.
    """

    if len(snapshots) < 2:
        return False

    for snapshot in snapshots:
        if not _trend_is_bullish(snapshot):
            return False

        if not _moving_average_is_bullish(snapshot):
            return False

    return True


# ---------------------------------------------------------
# BREAKOUT AND RETEST
# ---------------------------------------------------------

def _get_breakout_data(df):
    """
    Resistance is calculated from previous closed candles.
    The current candle is excluded from resistance.
    """

    if not isinstance(df, pd.DataFrame):
        return {}

    if len(df) < BREAKOUT_LOOKBACK + 2:
        return {}

    previous = df.iloc[-(BREAKOUT_LOOKBACK + 1):-1]

    resistance = _number(
        previous["high"].max()
    )

    current = df.iloc[-1]
    previous_candle = df.iloc[-2]

    close = _number(current["close"])
    low = _number(current["low"])
    previous_close = _number(previous_candle["close"])

    if None in (resistance, close, low, previous_close):
        return {}

    breakout = (
        close > resistance
        and previous_close <= resistance
    )

    retest = (
        low <= resistance * (1 + RETEST_TOLERANCE_PCT / 100)
        and close >= resistance
    )

    above_resistance = close > resistance

    return {
        "resistance": resistance,
        "breakout": breakout,
        "retest": retest,
        "above_resistance": above_resistance,
        "distance_from_resistance_pct": (
            (close - resistance) / resistance * 100
        ),
    }


def _find_support(df, lookback=30):
    if not isinstance(df, pd.DataFrame):
        return None

    if len(df) < 5:
        return None

    recent = df.iloc[-lookback:]

    support = _number(
        recent["low"].min()
    )

    if support is None or support <= 0:
        return None

    return support


def _find_resistance_levels(df, lookback=100):
    """
    Return resistance levels from previous candles.
    Current candle is excluded.
    """

    if not isinstance(df, pd.DataFrame) or len(df) < 10:
        return []

    recent = df.iloc[-(lookback + 1):-1]

    highs = recent["high"].tolist()

    levels = []

    for index in range(1, len(highs) - 1):
        current = _number(highs[index])

        if current is None:
            continue

        left = _number(highs[index - 1])
        right = _number(highs[index + 1])

        if left is None or right is None:
            continue

        if current >= left and current >= right:
            levels.append(current)

    return sorted(
        set(level for level in levels if level > 0)
    )


# ---------------------------------------------------------
# BUYER CONFIRMATION
# ---------------------------------------------------------

def _buyer_confirmation(snapshot):
    close = snapshot.get("close")
    open_price = snapshot.get("open")
    volume = snapshot.get("volume")
    previous_volume = snapshot.get("previous_volume")

    if None in (close, open_price, volume, previous_volume):
        return False

    green_candle = close > open_price
    volume_confirmation = volume >= previous_volume

    return green_candle and volume_confirmation


# ---------------------------------------------------------
# MARKET CONTEXT
# ---------------------------------------------------------

def _validate_market_context(market_context):
    if not isinstance(market_context, dict):
        return False, "MISSING_MARKET_CONTEXT"

    market_status = str(
        market_context.get("market_status", "UNKNOWN")
    ).upper()

    risk_level = str(
        market_context.get("risk_level", "UNKNOWN")
    ).upper()

    btc_trend = str(
        market_context.get("btc_trend", "UNKNOWN")
    ).upper()

    if market_status in ("UNKNOWN", "HIGH_RISK"):
        return False, "MARKET_STATUS_" + market_status

    if risk_level in ("HIGH", "EXTREME", "UNKNOWN"):
        return False, "MARKET_RISK_" + risk_level

    if btc_trend == "UNKNOWN":
        return False, "BTC_TREND_UNKNOWN"

    # Bearish BTC is not an automatic rejection.
    # It requires a higher setup score.
    return True, None


# ---------------------------------------------------------
# SCORING ENGINE
# ---------------------------------------------------------

def score_setup(setup_data):
    """
    12-point scoring model.

    Missing indicators receive no points.
    Mandatory rejection rules override the score.
    """

    if not isinstance(setup_data, dict):
        return {
            "score": 0,
            "max_score": MAX_SCORE,
            "classification": "REJECT",
            "components": {},
        }

    components = setup_data.get("components", {})

    if not isinstance(components, dict):
        components = {}

    score = sum(
        1 for value in components.values()
        if value is True
    )

    score = min(score, MAX_SCORE)

    btc_trend = str(
        setup_data.get("btc_trend", "UNKNOWN")
    ).upper()

    market_status = str(
        setup_data.get("market_status", "UNKNOWN")
    ).upper()

    required_score = MIN_SCORE

    if btc_trend == "BEARISH":
        required_score += 1

    if market_status == "BEARISH":
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


# ---------------------------------------------------------
# ENTRY VALIDATION
# ---------------------------------------------------------

def validate_entry(
    df,
    market_context,
    strategy="SCALP",
):
    """
    Validate trigger timeframe entry conditions.
    Returns a structured validation result.
    """

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

    if any(snapshot.get(key) is None for key in required):
        return {
            "valid": False,
            "reason": "MISSING_REQUIRED_INDICATORS",
        }

    close = snapshot["close"]
    ema_20 = snapshot["ema_20"]
    rsi = snapshot["rsi"]
    atr = snapshot["atr"]
    rvol = snapshot["rvol"]

    if atr <= 0:
        return {
            "valid": False,
            "reason": "INVALID_ATR",
        }

    if rsi > MAX_RSI:
        return {
            "valid": False,
            "reason": "RSI_OVEREXTENDED",
        }

    if rvol < MIN_RVOL:
        return {
            "valid": False,
            "reason": "LOW_RELATIVE_VOLUME",
        }

    extension_pct = (
        (close - ema_20) / ema_20 * 100
        if ema_20 > 0
        else 999
    )

    if extension_pct > MAX_EMA_EXTENSION_PCT:
        return {
            "valid": False,
            "reason": "ENTRY_TOO_LATE",
        }

    breakout_data = _get_breakout_data(prepared)

    if not breakout_data:
        return {
            "valid": False,
            "reason": "BREAKOUT_DATA_UNAVAILABLE",
        }

    if not breakout_data["above_resistance"]:
        return {
            "valid": False,
            "reason": "NO_CONFIRMED_BREAKOUT",
        }

    # Reject excessively extended breakout candles.
    if breakout_data["distance_from_resistance_pct"] > 1.5:
        return {
            "valid": False,
            "reason": "BREAKOUT_TOO_EXTENDED",
        }

    return {
        "valid": True,
        "reason": None,
        "strategy": str(strategy).upper(),
        "entry_price": close,
        "current_price": close,
        "support": _find_support(prepared),
        "resistance": breakout_data["resistance"],
        "breakout": breakout_data["breakout"],
        "retest": breakout_data["retest"],
        "extension_pct": round(extension_pct, 4),
        "atr": atr,
        "rsi": rsi,
        "rvol": rvol,
    }


# ---------------------------------------------------------
# MAIN EVALUATION
# ---------------------------------------------------------

def _evaluate(
    symbol,
    market_data,
    market_context,
    strategy,
):
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
            "classification": "REJECT",
            "reason": market_reason,
        }

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

    trend_ok = _check_confirmation_trend(
        confirmation_snapshots
    )

    buyer_ok = _buyer_confirmation(trigger)

    market_status = str(
        market_context.get("market_status", "UNKNOWN")
    ).upper()

    btc_trend = str(
        market_context.get("btc_trend", "UNKNOWN")
    ).upper()

    # 12 scoring components
    components = {
        "market_condition": market_status == "BULLISH",
        "btc_context": btc_trend == "BULLISH",
        "multi_timeframe_trend": trend_ok,
        "ema_trend": _trend_is_bullish(trigger),
        "moving_average_trend": _moving_average_is_bullish(trigger),
        "rsi_momentum": (
            trigger.get("rsi") is not None
            and 50 <= trigger["rsi"] <= 68
        ),
        "macd_momentum": (
            trigger.get("macd_histogram") is not None
            and trigger["macd_histogram"] > 0
        ),
        "adx_strength": (
            trigger.get("adx") is not None
            and trigger["adx"] >= 18
        ),
        "relative_volume": (
            trigger.get("rvol") is not None
            and trigger["rvol"] >= MIN_RVOL
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
            entry_validation.get("breakout")
            or entry_validation.get("retest")
        ),
    }

    # Mandatory rejection conditions.
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

    if classification not in (
        "STRONG BUY",
        "EXCELLENT BUY",
    ):
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

    # Include the confirmed breakout resistance.
    if resistance is not None:
        resistance_levels.append(resistance)

    resistance_levels = sorted(
        set(
            level for level in resistance_levels
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

        "breakout_confirmed": entry_validation["breakout"],
        "retest_confirmed": entry_validation["retest"],
        "buyer_confirmation": buyer_ok,

        "entry_status": "CANDIDATE",
        "risk_status": "PENDING_RISK_VALIDATION",
        "risk_plan": None,

        "warnings": [],
    }

    if btc_trend == "BEARISH":
        signal["warnings"].append(
            "BTC trend is bearish; setup requires extra caution"
        )

    if market_status == "BEARISH":
        signal["warnings"].append(
            "Overall market condition is bearish"
        )

    if not entry_validation["retest"]:
        signal["warnings"].append(
            "Breakout confirmed but retest not confirmed"
        )

    return signal


# ---------------------------------------------------------
# PUBLIC FUNCTIONS
# ---------------------------------------------------------

def evaluate_scalp(
    symbol,
    market_data,
    indicators=None,
    market_context=None,
):
    """
    Scalp:
        Trigger: 5m
        Confirmation: 15m and 30m
    """

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
    """
    Swing:
        Trigger: 15m
        Confirmation: 30m
        Trend: 1h
    """

    return _evaluate(
        symbol=symbol,
        market_data=market_data,
        market_context=market_context,
        strategy="SWING",
    )
