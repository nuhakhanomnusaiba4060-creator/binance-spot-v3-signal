
"""
Binance Spot V3 - Entry Signal Generation Engine
Balanced Breakout + Retest + Early Breakout Hold.

- Binance Spot USDT only.
- Closed candles only.
- Balanced SCALP and SWING evaluation.
- Uses actual config.py exports.
- Strong BUY and Excellent BUY only.
- No Futures or Margin.
"""

import logging
import math
from typing import Any

import pandas as pd

import config as cfg
from indicators import (
    calculate_all_indicators,
    support_resistance,
    validate_dataframe,
)

logger = logging.getLogger(__name__)


# =========================================================
# CONFIG COMPATIBILITY
# =========================================================

STRATEGIES = getattr(
    cfg,
    "STRATEGIES",
    getattr(cfg, "STRATEGY_CONFIG", {}),
)

MARKET_CONFIG = getattr(
    cfg,
    "MARKET_CONFIG",
    getattr(cfg, "MARKET_FILTER_CONFIG", {}),
)

FILTER_CONFIG = getattr(
    cfg,
    "FILTER_CONFIG",
    getattr(cfg, "COIN_SELECTION_CONFIG", {}),
)

SIGNAL_CONFIG = getattr(
    cfg,
    "SIGNAL_CONFIG",
    getattr(cfg, "SCORING_CONFIG", {}),
)

INDICATOR_CONFIG = getattr(
    cfg,
    "INDICATOR_CONFIG",
    {},
)

RISK_CONFIG = getattr(
    cfg,
    "RISK_CONFIG",
    {},
)


# =========================================================
# SAFE HELPERS
# =========================================================

def _num(value, default=None):
    try:
        if value is None:
            return default

        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (TypeError, ValueError, OverflowError):
        return default


def _get(data, key, default=None):
    if not isinstance(data, dict):
        return default

    if key in data:
        return data[key]

    wanted = (
        str(key)
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )

    for k, value in data.items():
        normalized = (
            str(k)
            .lower()
            .replace("_", "")
            .replace("-", "")
            .replace(" ", "")
        )

        if normalized == wanted:
            return value

    return default


def _nested(data, *keys, default=None):
    current = data

    for key in keys:
        if not isinstance(current, dict):
            return default

        current = _get(current, key, None)

        if current is None:
            return default

    return current


def _bool(value, default=False):
    if value is None:
        return default

    if isinstance(value, str):
        return value.strip().lower() in (
            "1", "true", "yes", "on", "enabled"
        )

    return bool(value)


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _last(df, column, default=None):
    if not isinstance(df, pd.DataFrame):
        return default

    if column not in df.columns or df.empty:
        return default

    return _num(df[column].iloc[-1], default)


def _column(df, *names):
    if not isinstance(df, pd.DataFrame):
        return None

    lookup = {
        str(col).lower(): col
        for col in df.columns
    }

    for name in names:
        found = lookup.get(name.lower())

        if found is not None:
            return found

    return None


def _value(df, *names, default=None):
    column = _column(df, *names)

    if column is None:
        return default

    return _last(df, column, default)


def _config_value(data, key, default):
    value = _get(data, key, default)

    if value is None:
        return default

    return value


def _score_config(key, default):
    value = _num(
        _get(SIGNAL_CONFIG, key, default),
        default,
    )

    return value


# =========================================================
# CONFIGURED STRATEGIES
# =========================================================

def _strategy_config(strategy):
    strategy = str(strategy).upper()

    raw = _get(STRATEGIES, strategy, {})

    if not isinstance(raw, dict):
        raw = {}

    if strategy == "SCALP":
        defaults = {
            "ENABLED": True,
            "TRIGGER_TIMEFRAME": "5m",
            "CONFIRMATION_TIMEFRAMES": ["15m", "30m"],
            "MIN_RVOL": 1.15,
            "MIN_ADX": 18.0,
            "RSI_MIN": 48.0,
            "RSI_MAX": 72.0,
            "MAX_ROC_PERCENT": 4.0,
            "MAX_BB_WIDTH": 0.20,
            "BREAKOUT_LOOKBACK": 20,
        }

    else:
        defaults = {
            "ENABLED": True,
            "TRIGGER_TIMEFRAME": "15m",
            "CONFIRMATION_TIMEFRAMES": ["30m", "1h"],
            "MIN_RVOL": 1.15,
            "MIN_ADX": 20.0,
            "RSI_MIN": 48.0,
            "RSI_MAX": 74.0,
            "MAX_ROC_PERCENT": 5.5,
            "MAX_BB_WIDTH": 0.25,
            "BREAKOUT_LOOKBACK": 20,
        }

    result = dict(defaults)
    result.update(raw)

    result["ENABLED"] = _bool(
        result.get("ENABLED"),
        True,
    )

    return result


def _global_strategy(key, default):
    return _get(STRATEGIES, key, default)


def _strong_threshold():
    return int(
        _score_config(
            "STRONG_MIN_SCORE",
            9,
        )
    )


def _excellent_threshold():
    return int(
        _score_config(
            "EXCELLENT_MIN_SCORE",
            12,
        )
    )


def _max_score():
    return int(
        _score_config(
            "MAX_SCORE",
            15,
        )
    )


# =========================================================
# DATA PREPARATION
# =========================================================

def _prepare_df(df, timeframe=None):
    if not isinstance(df, pd.DataFrame):
        return None

    if len(df) < 30:
        return None

    data = df.copy()

    try:
        if callable(validate_dataframe):
            result = validate_dataframe(data)

            if isinstance(result, pd.DataFrame):
                data = result

            elif result is False:
                return None

    except Exception as exc:
        logger.debug(
            "Data validation warning: %s",
            exc,
        )

    try:
        calculated = calculate_all_indicators(data)

        if isinstance(calculated, pd.DataFrame):
            data = calculated

        elif isinstance(calculated, dict):
            for key, value in calculated.items():
                if isinstance(value, pd.Series):
                    data[key] = value

    except Exception as exc:
        logger.warning(
            "Indicator calculation failed: %s",
            exc,
        )
        return None

    required = ("open", "high", "low", "close", "volume")

    lookup = {
        str(col).lower(): col
        for col in data.columns
    }

    for name in required:
        if name not in lookup:
            return None

        original = lookup[name]

        if original != name:
            data[name] = data[original]

    for name in required:
        data[name] = pd.to_numeric(
            data[name],
            errors="coerce",
        )

    data = data.dropna(
        subset=list(required)
    )

    if len(data) < 30:
        return None

    return data


# =========================================================
# INDICATOR HELPERS
# =========================================================

def _ema_values(df):
    close = df["close"]

    ema20 = _value(
        df,
        "ema20",
        "EMA20",
        "ema_20",
    )

    ema50 = _value(
        df,
        "ema50",
        "EMA50",
        "ema_50",
    )

    if ema20 is None:
        ema20 = close.ewm(
            span=20,
            adjust=False,
        ).mean().iloc[-1]

    if ema50 is None:
        ema50 = close.ewm(
            span=50,
            adjust=False,
        ).mean().iloc[-1]

    return (
        _num(ema20),
        _num(ema50),
    )


def _sma_values(df):
    close = df["close"]

    sma20 = _value(
        df,
        "sma20",
        "SMA20",
        "ma20",
        "MA20",
    )

    sma50 = _value(
        df,
        "sma50",
        "SMA50",
        "ma50",
        "MA50",
    )

    sma200 = _value(
        df,
        "sma200",
        "SMA200",
        "ma200",
        "MA200",
    )

    if sma20 is None:
        sma20 = close.rolling(20).mean().iloc[-1]

    if sma50 is None:
        sma50 = close.rolling(50).mean().iloc[-1]

    if sma200 is None and len(close) >= 200:
        sma200 = close.rolling(200).mean().iloc[-1]

    return (
        _num(sma20),
        _num(sma50),
        _num(sma200),
    )


def _rsi(df):
    return _value(
        df,
        "rsi",
        "rsi14",
        "RSI",
        "RSI14",
    )


def _atr(df):
    return _value(
        df,
        "atr",
        "atr14",
        "ATR",
        "ATR14",
    )


def _adx(df):
    return _value(
        df,
        "adx",
        "adx14",
        "ADX",
        "ADX14",
    )


def _rvol(df):
    value = _value(
        df,
        "rvol",
        "relative_volume",
        "relativevolume",
        "RVOL",
    )

    if value is not None:
        return value

    if len(df) < 21:
        return None

    baseline = df["volume"].iloc[-21:-1].mean()

    if baseline <= 0:
        return None

    return _num(
        df["volume"].iloc[-1] / baseline
    )


def _roc_percent(df, period=5):
    if len(df) <= period:
        return None

    old = _num(df["close"].iloc[-period - 1])
    current = _num(df["close"].iloc[-1])

    if old is None or old <= 0 or current is None:
        return None

    return (current / old - 1.0) * 100.0


def _bb_width(df):
    value = _value(
        df,
        "bb_width",
        "bbwidth",
        "bollinger_width",
        "BB_WIDTH",
    )

    if value is not None:
        return value

    upper = _value(
        df,
        "bb_upper",
        "bb_upper_20",
        "BB_UPPER",
    )

    lower = _value(
        df,
        "bb_lower",
        "bb_lower_20",
        "BB_LOWER",
    )

    middle = _value(
        df,
        "bb_middle",
        "bb_mid",
        "BB_MIDDLE",
    )

    if (
        upper is None
        or lower is None
        or middle is None
        or middle <= 0
    ):
        return None

    return (upper - lower) / middle


def _macd_histogram(df):
    return _value(
        df,
        "macd_hist",
        "macd_histogram",
        "MACD_HIST",
        "histogram",
    )


# =========================================================
# TREND ANALYSIS
# =========================================================

def _trend_state(df):
    if df is None or len(df) < 30:
        return "UNKNOWN"

    close = _num(df["close"].iloc[-1])

    ema20, ema50 = _ema_values(df)
    sma20, sma50, sma200 = _sma_values(df)

    if close is None:
        return "UNKNOWN"

    bullish_points = 0
    bearish_points = 0

    if ema20 is not None and close > ema20:
        bullish_points += 1

    elif ema20 is not None:
        bearish_points += 1

    if ema50 is not None and close > ema50:
        bullish_points += 1

    elif ema50 is not None:
        bearish_points += 1

    if sma20 is not None and close > sma20:
        bullish_points += 1

    elif sma20 is not None:
        bearish_points += 1

    if sma50 is not None and sma20 is not None:
        if sma20 > sma50:
            bullish_points += 1
        else:
            bearish_points += 1

    if sma200 is not None:
        if close > sma200:
            bullish_points += 1
        else:
            bearish_points += 1

    if bullish_points >= 3 and bullish_points > bearish_points:
        return "BULLISH"

    if bearish_points >= 3 and bearish_points > bullish_points:
        return "BEARISH"

    return "NEUTRAL"


def _confirmation_analysis(confirm_frames):
    if not isinstance(confirm_frames, dict):
        return {
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "total": 0,
            "states": {},
        }

    states = {}

    for timeframe, frame in confirm_frames.items():
        prepared = _prepare_df(
            frame,
            timeframe,
        )

        if prepared is None:
            states[str(timeframe)] = "UNKNOWN"
            continue

        states[str(timeframe)] = _trend_state(
            prepared
        )

    return {
        "bullish": sum(
            value == "BULLISH"
            for value in states.values()
        ),
        "bearish": sum(
            value == "BEARISH"
            for value in states.values()
        ),
        "neutral": sum(
            value == "NEUTRAL"
            for value in states.values()
        ),
        "total": len(states),
        "states": states,
    }


# =========================================================
# MARKET CONTEXT
# =========================================================

def _market_status(context):
    if not isinstance(context, dict):
        return "NEUTRAL"

    status = str(
        _get(
            context,
            "market_status",
            _get(context, "status", "NEUTRAL"),
        )
    ).upper()

    aliases = {
        "BULL": "BULLISH",
        "BULLISH": "BULLISH",
        "BEAR": "BEARISH",
        "BEARISH": "BEARISH",
        "SIDEWAYS": "NEUTRAL",
        "NEUTRAL": "NEUTRAL",
        "HIGH RISK": "HIGH_RISK",
        "HIGH-RISK": "HIGH_RISK",
        "HIGH_RISK": "HIGH_RISK",
        "UNKNOWN": "UNKNOWN",
    }

    return aliases.get(status, "NEUTRAL")


def _market_risk(context):
    if not isinstance(context, dict):
        return "MODERATE"

    risk = str(
        _get(
            context,
            "risk_level",
            _get(context, "risk", "MODERATE"),
        )
    ).upper()

    aliases = {
        "LOW": "LOW",
        "MODERATE": "MODERATE",
        "MEDIUM": "MODERATE",
        "HIGH": "HIGH",
        "EXTREME": "EXTREME",
        "HIGH_RISK": "HIGH",
    }

    return aliases.get(risk, "MODERATE")


def _btc_trend(context):
    if not isinstance(context, dict):
        return "NEUTRAL"

    value = str(
        _get(
            context,
            "btc_trend",
            _get(
                context,
                "btc_status",
                "NEUTRAL",
            ),
        )
    ).upper()

    if "BULL" in value:
        return "BULLISH"

    if "BEAR" in value:
        return "BEARISH"

    return "NEUTRAL"


def _validate_market_context(context):
    status = _market_status(context)
    risk = _market_risk(context)
    btc = _btc_trend(context)

    if status in ("HIGH_RISK", "UNKNOWN"):
        return False, f"MARKET_{status}", {
            "market_status": status,
            "risk_level": risk,
            "btc_trend": btc,
        }

    if risk in ("EXTREME",):
        return False, "EXTREME_MARKET_RISK", {
            "market_status": status,
            "risk_level": risk,
            "btc_trend": btc,
        }

    if status == "BEARISH":
        selective = _bool(
            _get(
                MARKET_CONFIG,
                "ALLOW_SELECTIVE_SIGNALS_ON_BEARISH",
                False,
            )
        )

        if not selective:
            return False, "BEARISH_MARKET", {
                "market_status": status,
                "risk_level": risk,
                "btc_trend": btc,
            }

    if btc == "BEARISH" and risk == "HIGH":
        return False, "BTC_BEARISH_HIGH_RISK", {
            "market_status": status,
            "risk_level": risk,
            "btc_trend": btc,
        }

    return True, None, {
        "market_status": status,
        "risk_level": risk,
        "btc_trend": btc,
    }


# =========================================================
# RELATIVE VOLUME
# =========================================================

def _has_rvol_collapse(df, strategy_config):
    """
    Balanced RVOL protection.

    A normal decline from a previous volume spike is not
    automatically rejected. Reject only when current volume
    is both weak and collapsing sharply.
    """
    if len(df) < 5:
        return False, "INSUFFICIENT_RVOL_HISTORY"

    current = _rvol(df)

    if current is None:
        return False, None

    previous = []

    for index in range(max(0, len(df) - 4), len(df) - 1):
        subset = df.iloc[:index + 1]

        if len(subset) < 21:
            continue

        baseline = subset["volume"].iloc[-21:-1].mean()

        if baseline <= 0:
            continue

        value = _num(
            subset["volume"].iloc[-1] / baseline
        )

        if value is not None:
            previous.append(value)

    if not previous:
        return False, None

    peak = max(previous)

    min_rvol = _num(
        strategy_config.get("MIN_RVOL"),
        1.15,
    )

    # Reject only if current RVOL is weak and collapses
    # significantly from a recent spike.
    if (
        peak >= 2.5
        and current < 0.75
        and current < peak * 0.30
        and current < min_rvol * 0.65
    ):
        return True, "RVOL_COLLAPSE_AFTER_SPIKE"

    return False, None


# =========================================================
# SUPPORT AND RESISTANCE
# =========================================================

def _support_resistance_levels(df):
    support = None
    resistance = None
    supports = []
    resistances = []

    try:
        result = support_resistance(df)

        if isinstance(result, dict):
            support = _num(
                _get(
                    result,
                    "support",
                    _get(result, "nearest_support"),
                )
            )

            resistance = _num(
                _get(
                    result,
                    "resistance",
                    _get(result, "nearest_resistance"),
                )
            )

            supports = _get(
                result,
                "supports",
                [],
            ) or []

            resistances = _get(
                result,
                "resistances",
                [],
            ) or []

        elif isinstance(result, (tuple, list)):
            if len(result) >= 2:
                support = _num(result[0])
                resistance = _num(result[1])

    except Exception as exc:
        logger.debug(
            "Support resistance calculation warning: %s",
            exc,
        )

    close = _num(df["close"].iloc[-1])

    if close is None:
        return None, None, [], []

    # Fallback from recent swing structure.
    if support is None:
        support = _num(
            df["low"].iloc[-20:-1].min()
        )

    if resistance is None:
        resistance = _num(
            df["high"].iloc[-20:-1].max()
        )

    if not isinstance(supports, (list, tuple)):
        supports = []

    if not isinstance(resistances, (list, tuple)):
        resistances = []

    supports = [
        _num(x)
        for x in supports
        if _num(x) is not None
    ]

    resistances = [
        _num(x)
        for x in resistances
        if _num(x) is not None
    ]

    if support is not None and support < close:
        supports.append(support)

    if resistance is not None and resistance > close:
        resistances.append(resistance)

    supports = sorted(
        set(x for x in supports if x < close),
        reverse=True,
    )

    resistances = sorted(
        set(x for x in resistances if x > close)
    )

    nearest_support = (
        supports[0]
        if supports
        else None
    )

    nearest_resistance = (
        resistances[0]
        if resistances
        else None
    )

    return (
        nearest_support,
        nearest_resistance,
        supports,
        resistances,
    )


# =========================================================
# BREAKOUT AND RETEST
# =========================================================

def _get_breakout_data(
    df,
    timeframe="5m",
    lookback=None,
):
    if not isinstance(df, pd.DataFrame) or len(df) < 25:
        return {
            "breakout": False,
            "retest": False,
            "retest_confirmed": False,
            "breakout_level": None,
            "breakout_index": None,
            "retest_index": None,
            "breakout_age": None,
            "method": "NONE",
        }

    strategy = (
        "SWING"
        if str(timeframe).lower() in (
            "15m", "30m", "1h", "2h", "4h"
        )
        else "SCALP"
    )

    strategy_config = _strategy_config(strategy)

    if lookback is None:
        lookback = int(
            _num(
                _global_strategy(
                    "BREAKOUT_LOOKBACK_CANDLES",
                    strategy_config.get(
                        "BREAKOUT_LOOKBACK",
                        20,
                    ),
                ),
                20,
            )
        )

    lookback = int(
        _clamp(lookback, 8, 50)
    )

    recent = df.tail(lookback + 5).copy()

    if len(recent) < lookback + 2:
        return {
            "breakout": False,
            "retest": False,
            "retest_confirmed": False,
            "breakout_level": None,
            "breakout_index": None,
            "retest_index": None,
            "breakout_age": None,
            "method": "NONE",
        }

    highs = recent["high"].reset_index(drop=True)
    lows = recent["low"].reset_index(drop=True)
    closes = recent["close"].reset_index(drop=True)
    opens = recent["open"].reset_index(drop=True)

    current_index = len(recent) - 1

    # Current candle is excluded from the breakout level.
    reference_start = max(
        0,
        current_index - lookback,
    )

    reference_end = current_index

    previous_high = _num(
        highs.iloc[reference_start:reference_end].max()
    )

    if previous_high is None or previous_high <= 0:
        return {
            "breakout": False,
            "retest": False,
            "retest_confirmed": False,
            "breakout_level": None,
            "breakout_index": None,
            "retest_index": None,
            "breakout_age": None,
            "method": "NONE",
        }

    current_close = _num(closes.iloc[-1])
    current_low = _num(lows.iloc[-1])
    current_open = _num(opens.iloc[-1])

    if current_close is None or current_low is None:
        return {
            "breakout": False,
            "retest": False,
            "retest_confirmed": False,
            "breakout_level": previous_high,
            "breakout_index": None,
            "retest_index": None,
            "breakout_age": None,
            "method": "NONE",
        }

    breakout_buffer = previous_high * 0.0005

    current_breakout = (
        current_close > previous_high + breakout_buffer
    )

    # Search for an earlier closed breakout candle.
    breakout_index = None

    search_start = max(
        1,
        current_index - 4,
    )

    for index in range(search_start, current_index + 1):
        historical_level = _num(
            highs.iloc[
                max(0, index - lookback):index
            ].max()
        )

        historical_close = _num(
            closes.iloc[index]
        )

        if (
            historical_level is not None
            and historical_close is not None
            and historical_close > historical_level
        ):
            breakout_index = index
            break

    if breakout_index is None and current_breakout:
        breakout_index = current_index

    if breakout_index is None:
        return {
            "breakout": False,
            "retest": False,
            "retest_confirmed": False,
            "breakout_level": previous_high,
            "breakout_index": None,
            "retest_index": None,
            "breakout_age": None,
            "method": "NONE",
        }

    # The retest must happen after the breakout candle.
    retest_index = None

    tolerance = _num(
        _global_strategy(
            "RETEST_TOLERANCE_PERCENT",
            0.5,
        ),
        0.5,
    ) / 100.0

    for index in range(
        breakout_index + 1,
        current_index + 1,
    ):
        candle_low = _num(lows.iloc[index])
        candle_close = _num(closes.iloc[index])

        if candle_low is None or candle_close is None:
            continue

        touched = (
            candle_low
            <= previous_high * (1.0 + tolerance)
        )

        held = (
            candle_close
            >= previous_high * (1.0 - tolerance)
        )

        if touched and held:
            retest_index = index

    retest_confirmed = (
        retest_index is not None
        and retest_index == current_index
        and current_close >= previous_high
        and current_close >= current_open
    )

    # If breakout is the current candle, do not label it retest.
    age = current_index - breakout_index

    return {
        "breakout": True,
        "retest": retest_index is not None,
        "retest_confirmed": retest_confirmed,
        "breakout_level": round(previous_high, 12),
        "breakout_index": breakout_index,
        "retest_index": retest_index,
        "breakout_age": age,
        "method": (
            "BREAKOUT_RETEST"
            if retest_confirmed
            else "BREAKOUT_HOLD"
            if current_breakout
            else "BREAKOUT"
        ),
    }


# =========================================================
# BUYER CONFIRMATION
# =========================================================

def _buyer_confirmation(df):
    if len(df) < 2:
        return False

    current = df.iloc[-1]

    open_price = _num(current["open"])
    high = _num(current["high"])
    low = _num(current["low"])
    close = _num(current["close"])

    if None in (
        open_price,
        high,
        low,
        close,
    ):
        return False

    candle_range = high - low

    if candle_range <= 0:
        return False

    body = close - open_price
    close_position = (close - low) / candle_range

    # Strong bullish candle.
    if body > 0 and close_position >= 0.60:
        return True

    # Neutral candle with strong closing position.
    if body >= 0 and close_position >= 0.72:
        return True

    # Previous candle high breakout with a positive close.
    previous_high = _num(
        df["high"].iloc[-2]
    )

    if (
        previous_high is not None
        and close > previous_high
        and close >= open_price
    ):
        return True

    return False


# =========================================================
# PUMP AND OVEREXTENSION PROTECTION
# =========================================================

def _check_pump_and_overextension(
    df,
    strategy_config,
):
    close = _num(df["close"].iloc[-1])

    if close is None or close <= 0:
        return False, "INVALID_PRICE"

    roc = _roc_percent(df, 5)

    max_roc = _num(
        strategy_config.get("MAX_ROC_PERCENT"),
        4.0,
    )

    if roc is not None and roc > max_roc:
        return False, "EXCESSIVE_SHORT_TERM_PUMP"

    bb_width = _bb_width(df)

    max_width = _num(
        strategy_config.get("MAX_BB_WIDTH"),
        0.25,
    )

    if (
        bb_width is not None
        and bb_width > max_width
    ):
        return False, "EXTREME_BOLLINGER_WIDTH"

    ema20, _ = _ema_values(df)

    if ema20 is not None and ema20 > 0:
        extension = (
            close / ema20 - 1.0
        ) * 100.0

        max_extension = _num(
            _global_strategy(
                "MAX_ENTRY_EXTENSION_PERCENT",
                2.5,
            ),
            2.5,
        )

        if extension > max_extension:
            return False, "PRICE_TOO_FAR_ABOVE_EMA20"

    # Reject only extreme consecutive bullish candles.
    if len(df) >= 5:
        last = df.tail(4)

        bullish_count = int(
            (
                last["close"] > last["open"]
            ).sum()
        )

        total_move = (
            last["close"].iloc[-1]
            / last["close"].iloc[0]
            - 1.0
        ) * 100.0

        if bullish_count == 4 and total_move > max_roc:
            return False, "CONSECUTIVE_PUMP_CANDLES"

    collapsed, reason = _has_rvol_collapse(
        df,
        strategy_config,
    )

    if collapsed:
        return False, reason

    return True, None


# =========================================================
# UPSIDE VALIDATION
# =========================================================

def _has_insufficient_upside(
    entry,
    resistance,
    atr=None,
):
    entry = _num(entry)
    resistance = _num(resistance)
    atr = _num(atr)

    if entry is None or entry <= 0:
        return True

    # Resistance is unavailable: do not automatically reject.
    if resistance is None:
        return False

    # Resistance below entry is not an upside target.
    if resistance <= entry:
        return False

    upside_percent = (
        (resistance - entry) / entry
    ) * 100.0

    # Avoid entries directly under resistance.
    if upside_percent < 0.25:
        return True

    # ATR-aware minimum room.
    if atr is not None and atr > 0:
        minimum_room = max(
            0.25,
            (atr / entry) * 100.0 * 0.5,
        )

        if upside_percent < minimum_room:
            return True

    return False


# =========================================================
# SCORING ENGINE
# =========================================================

def score_setup(
    trigger_df,
    confirm_frames=None,
    market_context=None,
    strategy="SCALP",
    breakout_data=None,
):
    strategy = str(strategy).upper()

    prepared = _prepare_df(
        trigger_df,
    )

    if prepared is None:
        return {
            "score": 0,
            "max_score": _max_score(),
            "classification": "REJECT",
            "reasons": ["INVALID_TRIGGER_DATA"],
        }

    close = _num(
        prepared["close"].iloc[-1]
    )

    rsi = _rsi(prepared)
    rvol = _rvol(prepared)
    adx = _adx(prepared)
    macd_hist = _macd_histogram(prepared)

    ema20, ema50 = _ema_values(prepared)
    sma20, sma50, sma200 = _sma_values(prepared)

    confirmation = _confirmation_analysis(
        confirm_frames or {}
    )

    if breakout_data is None:
        breakout_data = _get_breakout_data(
            prepared,
            timeframe=_strategy_config(
                strategy
            ).get("TRIGGER_TIMEFRAME", "5m"),
        )

    buyer_confirmed = _buyer_confirmation(
        prepared
    )

    score = 0
    reasons = []

    # -----------------------------------------------------
    # 1. PRICE / EMA TREND
    # -----------------------------------------------------

    if (
        close is not None
        and ema20 is not None
        and close > ema20
    ):
        score += 1
        reasons.append("PRICE_ABOVE_EMA20")

    if (
        ema20 is not None
        and ema50 is not None
        and ema20 > ema50
    ):
        score += 1
        reasons.append("EMA_BULLISH_ALIGNMENT")

    # -----------------------------------------------------
    # 2. SMA TREND
    # -----------------------------------------------------

    if (
        close is not None
        and sma20 is not None
        and close > sma20
    ):
        score += 1
        reasons.append("PRICE_ABOVE_SMA20")

    if (
        sma20 is not None
        and sma50 is not None
        and sma20 > sma50
    ):
        score += 1
        reasons.append("SMA20_ABOVE_SMA50")

    if (
        sma200 is not None
        and close is not None
        and close > sma200
    ):
        score += 1
        reasons.append("PRICE_ABOVE_SMA200")

    # -----------------------------------------------------
    # 3. MOMENTUM
    # -----------------------------------------------------

    if rsi is not None and 50 <= rsi <= 68:
        score += 1
        reasons.append("RSI_BULLISH_MOMENTUM")

    if (
        macd_hist is not None
        and macd_hist > 0
    ):
        score += 1
        reasons.append("MACD_POSITIVE")

    # -----------------------------------------------------
    # 4. VOLUME
    # -----------------------------------------------------

    if rvol is not None and rvol >= 1.15:
        score += 1
        reasons.append("RELATIVE_VOLUME_CONFIRMATION")

    # -----------------------------------------------------
    # 5. TREND STRENGTH
    # -----------------------------------------------------

    if adx is not None and adx >= 20:
        score += 1
        reasons.append("ADX_TREND_STRENGTH")

    # -----------------------------------------------------
    # 6. BREAKOUT / RETEST
    # -----------------------------------------------------

    if breakout_data.get("retest_confirmed"):
        score += 2
        reasons.append("CONFIRMED_BREAKOUT_RETEST")

    elif breakout_data.get("breakout"):
        score += 1
        reasons.append("BREAKOUT_CONFIRMED")

    # -----------------------------------------------------
    # 7. BUYER CONFIRMATION
    # -----------------------------------------------------

    if buyer_confirmed:
        score += 1
        reasons.append("BUYER_CONFIRMATION")

    # -----------------------------------------------------
    # 8. MULTI-TIMEFRAME CONFIRMATION
    # -----------------------------------------------------

    if confirmation["bullish"] >= 2:
        score += 2
        reasons.append("MULTI_TF_BULLISH")

    elif confirmation["bullish"] >= 1:
        score += 1
        reasons.append("PARTIAL_TF_BULLISH")

    # -----------------------------------------------------
    # 9. MARKET CONTEXT
    # -----------------------------------------------------

    status = _market_status(
        market_context or {}
    )

    btc = _btc_trend(
        market_context or {}
    )

    if status == "BULLISH":
        score += 1
        reasons.append("BULLISH_MARKET_CONTEXT")

    if btc == "BULLISH":
        score += 1
        reasons.append("BTC_TREND_SUPPORTIVE")

    # Maximum score is controlled by config.
    maximum = _max_score()

    score = min(
        int(score),
        maximum,
    )

    strong = _strong_threshold()
    excellent = _excellent_threshold()

    if score >= excellent:
        classification = "EXCELLENT BUY"

    elif score >= strong:
        classification = "STRONG BUY"

    else:
        classification = "REJECT"

    return {
        "score": score,
        "max_score": maximum,
        "classification": classification,
        "reasons": reasons,
        "rsi": rsi,
        "rvol": rvol,
        "adx": adx,
        "macd_hist": macd_hist,
        "confirmation": confirmation,
        "breakout": breakout_data,
        "buyer_confirmation": buyer_confirmed,
    }


# =========================================================
# ENTRY VALIDATION
# =========================================================

def validate_entry(
    symbol,
    trigger_df,
    confirm_frames=None,
    market_context=None,
    strategy="SCALP",
):
    strategy = str(strategy).upper()

    if strategy not in ("SCALP", "SWING"):
        return {
            "status": "REJECT",
            "reason": "INVALID_STRATEGY",
        }

    strategy_config = _strategy_config(
        strategy
    )

    if not strategy_config["ENABLED"]:
        return {
            "status": "REJECT",
            "reason": "STRATEGY_DISABLED",
        }

    market_ok, market_reason, market_data = (
        _validate_market_context(
            market_context or {}
        )
    )

    if not market_ok:
        return {
            "status": "REJECT",
            "reason": market_reason,
            "market_context": market_data,
        }

    trigger_tf = str(
        strategy_config.get(
            "TRIGGER_TIMEFRAME",
            "5m",
        )
    )

    trigger = _prepare_df(
        trigger_df,
        trigger_tf,
    )

    if trigger is None:
        return {
            "status": "REJECT",
            "reason": "INVALID_TRIGGER_DATA",
        }

    # Ensure the supplied confirmation frames match
    # the strategy's configured confirmation timeframes.
    confirm_frames = (
        confirm_frames
        if isinstance(confirm_frames, dict)
        else {}
    )

    configured_tfs = strategy_config.get(
        "CONFIRMATION_TIMEFRAMES",
        [],
    )

    if not isinstance(configured_tfs, (list, tuple)):
        configured_tfs = []

    prepared_confirm = {}

    for timeframe in configured_tfs:
        frame = confirm_frames.get(timeframe)

        if frame is None:
            # Try case-insensitive timeframe lookup.
            for key, value in confirm_frames.items():
                if str(key).lower() == str(timeframe).lower():
                    frame = value
                    break

        if frame is not None:
            prepared = _prepare_df(
                frame,
                timeframe,
            )

            if prepared is not None:
                prepared_confirm[timeframe] = prepared

    close = _num(
        trigger["close"].iloc[-1]
    )

    if close is None or close <= 0:
        return {
            "status": "REJECT",
            "reason": "INVALID_ENTRY_PRICE",
        }

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    rsi = _rsi(trigger)

    if rsi is None:
        return {
            "status": "REJECT",
            "reason": "RSI_DATA_UNAVAILABLE",
        }

    rsi_min = _num(
        strategy_config.get("RSI_MIN"),
        48.0,
    )

    rsi_max = _num(
        strategy_config.get("RSI_MAX"),
        72.0,
    )

    if rsi < rsi_min or rsi > rsi_max:
        return {
            "status": "REJECT",
            "reason": "RSI_OUTSIDE_ALLOWED_RANGE",
            "rsi": rsi,
        }

    # -----------------------------------------------------
    # ADX
    # -----------------------------------------------------

    adx = _adx(trigger)

    if adx is not None:
        minimum_adx = _num(
            strategy_config.get("MIN_ADX"),
            18.0,
        )

        if adx < minimum_adx:
            return {
                "status": "REJECT",
                "reason": "ADX_BELOW_THRESHOLD",
                "adx": adx,
            }

    # -----------------------------------------------------
    # RELATIVE VOLUME
    # -----------------------------------------------------

    rvol = _rvol(trigger)

    minimum_rvol = _num(
        strategy_config.get("MIN_RVOL"),
        1.15,
    )

    status = market_data["market_status"]

    # Balanced dynamic adjustment:
    # Neutral market slightly relaxes RVOL requirement.
    if status == "NEUTRAL":
        minimum_rvol *= 0.90

    if market_data["btc_trend"] == "BEARISH":
        minimum_rvol *= 1.05

    if rvol is not None and rvol < minimum_rvol:
        return {
            "status": "REJECT",
            "reason": "RELATIVE_VOLUME_BELOW_THRESHOLD",
            "rvol": rvol,
            "minimum_rvol": round(
                minimum_rvol,
                3,
            ),
        }

    # Missing RVOL is not automatically rejected here,
    # but it receives no volume score.

    # -----------------------------------------------------
    # PUMP / OVEREXTENSION
    # -----------------------------------------------------

    pump_ok, pump_reason = (
        _check_pump_and_overextension(
            trigger,
            strategy_config,
        )
    )

    if not pump_ok:
        return {
            "status": "REJECT",
            "reason": pump_reason,
        }

    # -----------------------------------------------------
    # BREAKOUT / RETEST
    # -----------------------------------------------------

    breakout_data = _get_breakout_data(
        trigger,
        timeframe=trigger_tf,
        lookback=int(
            _num(
                _global_strategy(
                    "BREAKOUT_LOOKBACK_CANDLES",
                    strategy_config.get(
                        "BREAKOUT_LOOKBACK",
                        20,
                    ),
                ),
                20,
            )
        ),
    )

    require_breakout = _bool(
        _global_strategy(
            "REQUIRE_BREAKOUT_CONFIRMATION",
            True,
        ),
        True,
    )

    require_retest = _bool(
        _global_strategy(
            "REQUIRE_RETEST",
            False,
        ),
        False,
    )

    if require_breakout and not breakout_data.get("breakout"):
        return {
            "status": "REJECT",
            "reason": "BREAKOUT_NOT_CONFIRMED",
            "breakout": breakout_data,
        }

    if require_retest and not breakout_data.get("retest_confirmed"):
        return {
            "status": "REJECT",
            "reason": "RETEST_NOT_CONFIRMED",
            "breakout": breakout_data,
        }

    # -----------------------------------------------------
    # BUYER CONFIRMATION
    # -----------------------------------------------------

    require_buyer = _bool(
        _global_strategy(
            "REQUIRE_BUYER_CONFIRMATION",
            True,
        ),
        True,
    )

    buyer_confirmed = _buyer_confirmation(
        trigger
    )

    if require_buyer and not buyer_confirmed:
        return {
            "status": "REJECT",
            "reason": "BUYER_CONFIRMATION_MISSING",
        }

    # -----------------------------------------------------
    # SUPPORT / RESISTANCE
    # -----------------------------------------------------

    (
        support,
        resistance,
        support_levels,
        resistance_levels,
    ) = _support_resistance_levels(
        trigger
    )

    atr = _atr(trigger)

    if _has_insufficient_upside(
        close,
        resistance,
        atr,
    ):
        return {
            "status": "REJECT",
            "reason": "INSUFFICIENT_UPSIDE",
            "entry_price": close,
            "resistance": resistance,
        }

    # -----------------------------------------------------
    # MULTI-TIMEFRAME CONFIRMATION
    # -----------------------------------------------------

    confirmation = _confirmation_analysis(
        prepared_confirm
    )

    # Do not reject all setups when one confirmation TF
    # is neutral. Reject only when all available TFs are bearish.
    if (
        confirmation["total"] > 0
        and confirmation["bearish"] == confirmation["total"]
    ):
        return {
            "status": "REJECT",
            "reason": "ALL_CONFIRMATION_TIMEFRAMES_BEARISH",
            "confirmation": confirmation,
        }

    # -----------------------------------------------------
    # SCORING
    # -----------------------------------------------------

    score_data = score_setup(
        trigger_df=trigger,
        confirm_frames=prepared_confirm,
        market_context=market_context or {},
        strategy=strategy,
        breakout_data=breakout_data,
    )

    score = score_data["score"]
    classification = score_data["classification"]

    if classification == "REJECT":
        return {
            "status": "REJECT",
            "reason": "SCORE_BELOW_THRESHOLD",
            "score": score,
            "max_score": score_data["max_score"],
            "required_score": _strong_threshold(),
            "score_details": score_data,
        }

    # -----------------------------------------------------
    # ENTRY EXTENSION
    # -----------------------------------------------------

    ema20, _ = _ema_values(trigger)

    extension_percent = None

    if ema20 is not None and ema20 > 0:
        extension_percent = (
            (close - ema20) / ema20
        ) * 100.0

    max_extension = _num(
        _global_strategy(
            "MAX_ENTRY_EXTENSION_PERCENT",
            2.5,
        ),
        2.5,
    )

    if (
        extension_percent is not None
        and extension_percent > max_extension
    ):
        return {
            "status": "REJECT",
            "reason": "PRICE_TOO_FAR_ABOVE_EMA20",
            "extension_percent": round(
                extension_percent,
                4,
            ),
        }

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    trend = _trend_state(trigger)

    return {
        "status": "VALID",
        "symbol": str(symbol).upper(),
        "strategy": strategy,
        "timeframe": trigger_tf,
        "signal_type": classification,
        "classification": classification,
        "score": score,
        "max_score": score_data["max_score"],
        "entry_price": round(close, 12),
        "support": support,
        "support_levels": support_levels,
        "resistance": resistance,
        "resistance_levels": resistance_levels,
        "atr": atr,
        "rsi": rsi,
        "rvol": rvol,
        "adx": adx,
        "trend": trend,
        "market_context": market_data,
        "confirmation": confirmation,
        "breakout": breakout_data,
        "buyer_confirmation": buyer_confirmed,
        "extension_percent": (
            round(extension_percent, 4)
            if extension_percent is not None
            else None
        ),
        "score_details": score_data,
        "reasons": score_data["reasons"],
    }


# =========================================================
# PUBLIC SCALP FUNCTION
# =========================================================

def evaluate_scalp(
    symbol,
    trigger_df,
    confirm_frames=None,
    market_context=None,
):
    return validate_entry(
        symbol=symbol,
        trigger_df=trigger_df,
        confirm_frames=confirm_frames,
        market_context=market_context,
        strategy="SCALP",
    )


# =========================================================
# PUBLIC SWING FUNCTION
# =========================================================

def evaluate_swing(
    symbol,
    trigger_df,
    confirm_frames=None,
    market_context=None,
):
    return validate_entry(
        symbol=symbol,
        trigger_df=trigger_df,
        confirm_frames=confirm_frames,
        market_context=market_context,
        strategy="SWING",
    )
