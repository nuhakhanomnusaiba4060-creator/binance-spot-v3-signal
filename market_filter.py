
"""
File: market_filter.py
System: Binance Spot V3 Smart Signal Scanner
Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Test Status: NOT RUN

BTC Market Regime and Market Breadth Engine.

Dependencies:
- config.py
- indicators.py

Supported regimes:
STRONG_BULLISH, BULLISH, NEUTRAL, BEARISH, HIGH_RISK

Only closed-candle data should be supplied.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np
import pandas as pd

from config import (
    BTC_REGIME_CONFIG,
    INDICATOR_CONFIG,
    HARD_GATE_CONFIG,
    get_config,
)
from indicators import (
    validate_dataframe,
    calculate_all_indicators,
    calculate_atr,
    calculate_rsi,
)


REGIME_STRONG_BULLISH = "STRONG_BULLISH"
REGIME_BULLISH = "BULLISH"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_BEARISH = "BEARISH"
REGIME_HIGH_RISK = "HIGH_RISK"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    result = _finite(value)
    return result if result is not None else default


def _latest_value(
    frame: pd.DataFrame,
    column: str,
) -> float | None:
    if column not in frame.columns or frame.empty:
        return None
    return _finite(frame[column].iloc[-1])


def _ema_alignment(snapshot: dict[str, Any]) -> str:
    ema20 = _finite(snapshot.get("ema_20"))
    ema50 = _finite(snapshot.get("ema_50"))
    ema200 = _finite(snapshot.get("ema_200"))
    close = _finite(snapshot.get("close"))

    if None in (ema20, ema50, ema200, close):
        return "UNVERIFIED"

    if close > ema20 > ema50 > ema200:
        return "BULLISH"

    if close < ema20 < ema50 < ema200:
        return "BEARISH"

    if ema20 > ema50 and close > ema50:
        return "MILD_BULLISH"

    if ema20 < ema50 and close < ema50:
        return "MILD_BEARISH"

    return "MIXED"


def _direction_from_alignment(alignment: str) -> int:
    return {
        "BULLISH": 2,
        "MILD_BULLISH": 1,
        "MIXED": 0,
        "MILD_BEARISH": -1,
        "BEARISH": -2,
    }.get(alignment, 0)


def analyze_btc_timeframe(
    df: pd.DataFrame,
    timeframe: str,
) -> dict[str, Any]:
    """
    Analyze BTC on one timeframe.

    Requires sufficient closed candles for EMA200 and indicator
    warm-up. Returns an explicit invalid result instead of guessing.
    """

    timeframe = str(timeframe).lower()

    if not validate_dataframe(df, min_rows=205):
        return {
            "timeframe": timeframe,
            "valid": False,
            "status": "INVALID_OR_INSUFFICIENT_DATA",
            "direction": "UNKNOWN",
            "score": 0,
            "errors": [
                "At least 205 valid OHLCV candles are required."
            ],
        }

    try:
        enriched = calculate_all_indicators(df)
        row = enriched.iloc[-1]

        snapshot = {
            key: _finite(row.get(key))
            for key in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "ema_20",
                "ema_50",
                "ema_200",
                "rsi",
                "adx",
                "atr",
                "macd",
                "macd_signal",
                "macd_histogram",
                "vwap",
                "rvol",
                "obv",
                "cmf",
            )
        }

        alignment = _ema_alignment(snapshot)
        direction_score = _direction_from_alignment(alignment)

        rsi = snapshot["rsi"]
        adx = snapshot["adx"]
        close = snapshot["close"]
        atr = snapshot["atr"]
        histogram = snapshot["macd_histogram"]
        vwap = snapshot["vwap"]

        if None in (rsi, adx, close, atr) or close <= 0:
            raise ValueError("Required indicator values are unavailable.")

        atr_percent = (atr / close) * 100.0

        momentum_score = 0

        if histogram is not None:
            if histogram > 0:
                momentum_score += 1
            elif histogram < 0:
                momentum_score -= 1

        if rsi >= 55:
            momentum_score += 1
        elif rsi <= 45:
            momentum_score -= 1

        if vwap is not None:
            if close > vwap:
                momentum_score += 1
            elif close < vwap:
                momentum_score -= 1

        # ADX measures trend strength, not trend direction.
        trend_strength = (
            "STRONG" if adx >= 25
            else "DEVELOPING" if adx >= 20
            else "WEAK"
        )

        combined_score = direction_score + momentum_score

        if combined_score >= 3:
            direction = "BULLISH"
        elif combined_score <= -3:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return {
            "timeframe": timeframe,
            "valid": True,
            "status": "OK",
            "direction": direction,
            "alignment": alignment,
            "direction_score": direction_score,
            "momentum_score": momentum_score,
            "combined_score": combined_score,
            "trend_strength": trend_strength,
            "rsi": round(rsi, 4),
            "adx": round(adx, 4),
            "atr": round(atr, 8),
            "atr_percent": round(atr_percent, 4),
            "close": round(close, 8),
            "vwap": (
                round(vwap, 8) if vwap is not None else None
            ),
            "rvol": (
                round(snapshot["rvol"], 4)
                if snapshot["rvol"] is not None else None
            ),
            "macd_histogram": (
                round(histogram, 10)
                if histogram is not None else None
            ),
            "errors": [],
        }

    except Exception as exc:
        return {
            "timeframe": timeframe,
            "valid": False,
            "status": "ANALYSIS_ERROR",
            "direction": "UNKNOWN",
            "score": 0,
            "errors": [str(exc)],
        }


def analyze_btc_volume(
    timeframe_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate BTC volume participation across available timeframes.
    Missing volume data remains unverified.
    """

    values: list[float] = []

    for timeframe, result in timeframe_results.items():
        if not isinstance(result, dict) or not result.get("valid"):
            continue

        rvol = _finite(result.get("rvol"))

        if rvol is not None:
            values.append(rvol)

    if not values:
        return {
            "valid": False,
            "status": "UNVERIFIED",
            "average_rvol": None,
            "volume_condition": "UNKNOWN",
            "bullish_confirmation": False,
        }

    average_rvol = float(np.mean(values))

    if average_rvol >= 1.5:
        condition = "STRONG"
    elif average_rvol >= 1.0:
        condition = "NORMAL"
    else:
        condition = "WEAK"

    return {
        "valid": True,
        "status": "OK",
        "average_rvol": round(average_rvol, 4),
        "volume_condition": condition,
        "bullish_confirmation": average_rvol >= 1.0,
        "timeframes_available": len(values),
    }


def determine_btc_trend(
    timeframe_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Combine BTC 15m, 1h and 4h results.

    Timeframes are correlated observations, not independent
    confirmations. Higher timeframes receive greater weight.
    """

    weights = {
        "15m": 1.0,
        "1h": 2.0,
        "4h": 3.0,
    }

    weighted_score = 0.0
    total_weight = 0.0
    directions: dict[str, str] = {}
    invalid: list[str] = []

    for timeframe, weight in weights.items():
        result = timeframe_results.get(timeframe)

        if not isinstance(result, dict) or not result.get("valid"):
            invalid.append(timeframe)
            continue

        direction = result.get("direction", "UNKNOWN")
        directions[timeframe] = direction

        score = {
            "BULLISH": 1.0,
            "NEUTRAL": 0.0,
            "BEARISH": -1.0,
        }.get(direction)

        if score is None:
            invalid.append(timeframe)
            continue

        weighted_score += score * weight
        total_weight += weight

    if total_weight == 0:
        return {
            "valid": False,
            "trend": "UNKNOWN",
            "score": 0.0,
            "directions": directions,
            "invalid_timeframes": invalid,
        }

    normalized = weighted_score / total_weight

    if normalized >= 0.65:
        trend = REGIME_STRONG_BULLISH
    elif normalized >= 0.25:
        trend = REGIME_BULLISH
    elif normalized <= -0.65:
        trend = REGIME_BEARISH
    elif normalized <= -0.25:
        trend = REGIME_BEARISH
    else:
        trend = REGIME_NEUTRAL

    return {
        "valid": len(invalid) == 0,
        "trend": trend,
        "score": round(normalized, 4),
        "directions": directions,
        "invalid_timeframes": invalid,
        "note": (
            "Weighted multi-timeframe observation; "
            "timeframes are correlated."
        ),
    }


def detect_high_risk(
    timeframe_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Detect abnormal BTC market risk.

    This is a market-risk gate, not a prediction of a crash.
    """

    reasons: list[str] = []
    valid_results = [
        result
        for result in timeframe_results.values()
        if isinstance(result, dict) and result.get("valid")
    ]

    required = ("15m", "1h", "4h")
    missing = [
        tf for tf in required
        if tf not in timeframe_results
        or not timeframe_results[tf].get("valid", False)
    ]

    if missing:
        return {
            "valid": False,
            "high_risk": True,
            "status": "DATA_UNVERIFIED",
            "reasons": [
                "Required BTC timeframe data missing: "
                + ", ".join(missing)
            ],
        }

    high_volatility_count = 0
    extreme_rsi_count = 0
    bearish_count = 0

    for timeframe in required:
        result = timeframe_results[timeframe]

        atr_percent = _finite(result.get("atr_percent"))
        rsi = _finite(result.get("rsi"))
        direction = result.get("direction")

        # These are configurable safety thresholds.
        if atr_percent is not None and atr_percent >= 3.0:
            high_volatility_count += 1

        if rsi is not None and (rsi <= 20 or rsi >= 85):
            extreme_rsi_count += 1

        if direction == "BEARISH":
            bearish_count += 1

    if high_volatility_count >= 2:
        reasons.append(
            "BTC volatility is elevated on multiple timeframes."
        )

    if extreme_rsi_count >= 2:
        reasons.append(
            "BTC RSI is at an extreme on multiple timeframes."
        )

    if bearish_count == 3:
        reasons.append(
            "BTC trend is bearish across all required timeframes."
        )

    is_high_risk = bool(reasons)

    return {
        "valid": True,
        "high_risk": is_high_risk,
        "status": "HIGH_RISK" if is_high_risk else "NORMAL",
        "reasons": reasons,
        "high_volatility_timeframes": high_volatility_count,
        "extreme_rsi_timeframes": extreme_rsi_count,
        "bearish_timeframes": bearish_count,
    }


def analyze_external_data(
    external_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Parse optional external market breadth information.

    Supported inputs:
      {
        "advancing": 35,
        "declining": 15,
        "unchanged": 5
      }

    Or:
      {
        "market_breadth": {
          "advancing": 35,
          "declining": 15,
          "unchanged": 5
        }
      }

    Missing external data is UNVERIFIED, not fabricated.
    """

    if not isinstance(external_data, dict):
        return {
            "valid": False,
            "status": "UNVERIFIED",
            "breadth_score": None,
            "breadth_ratio": None,
            "condition": "UNKNOWN",
        }

    source = external_data.get(
        "market_breadth", external_data
    )

    if not isinstance(source, dict):
        return {
            "valid": False,
            "status": "UNVERIFIED",
            "breadth_score": None,
            "breadth_ratio": None,
            "condition": "UNKNOWN",
        }

    advancing = _finite(source.get("advancing"))
    declining = _finite(source.get("declining"))
    unchanged = _finite(source.get("unchanged", 0))

    if (
        advancing is None
        or declining is None
        or unchanged is None
        or min(advancing, declining, unchanged) < 0
    ):
        return {
            "valid": False,
            "status": "UNVERIFIED",
            "breadth_score": None,
            "breadth_ratio": None,
            "condition": "UNKNOWN",
        }

    total = advancing + declining + unchanged

    if total <= 0:
        return {
            "valid": False,
            "status": "UNVERIFIED",
            "breadth_score": None,
            "breadth_ratio": None,
            "condition": "UNKNOWN",
        }

    ratio = advancing / max(declining, 1.0)
    score = (advancing - declining) / total

    if score >= 0.30:
        condition = "BULLISH"
    elif score <= -0.30:
        condition = "BEARISH"
    else:
        condition = "NEUTRAL"

    return {
        "valid": True,
        "status": "OK",
        "advancing": int(advancing),
        "declining": int(declining),
        "unchanged": int(unchanged),
        "total": int(total),
        "breadth_ratio": round(ratio, 4),
        "breadth_score": round(score, 4),
        "condition": condition,
    }


def classify_market(
    btc_trend: dict[str, Any] | str,
    timeframe_results: dict[str, dict[str, Any]],
    external_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Determine the final BTC market regime.

    HIGH_RISK overrides directional classification.
    """

    if isinstance(btc_trend, str):
        trend = btc_trend
        trend_valid = trend != "UNKNOWN"
        trend_score = 0.0
    else:
        trend = btc_trend.get("trend", "UNKNOWN")
        trend_valid = bool(btc_trend.get("valid"))
        trend_score = _safe_float(btc_trend.get("score"))

    risk_result = detect_high_risk(timeframe_results)

    if not trend_valid or not risk_result.get("valid"):
        return {
            "valid": False,
            "regime": REGIME_HIGH_RISK,
            "market_status": "DATA_UNVERIFIED",
            "allow_new_buy": False,
            "risk_level": "HIGH",
            "reasons": risk_result.get("reasons", [])
            + ["BTC market context is incomplete."],
        }

    if risk_result.get("high_risk"):
        return {
            "valid": True,
            "regime": REGIME_HIGH_RISK,
            "market_status": "HIGH_RISK",
            "allow_new_buy": False,
            "risk_level": "HIGH",
            "btc_trend": trend,
            "btc_trend_score": trend_score,
            "risk_reasons": risk_result["reasons"],
        }

    breadth = external_result or {
        "valid": False,
        "condition": "UNKNOWN",
    }

    breadth_condition = (
        breadth.get("condition", "UNKNOWN")
        if breadth.get("valid")
        else "UNKNOWN"
    )

    regime = trend

    # Breadth can moderate, but not completely reverse,
    # the BTC multi-timeframe trend.
    if trend in (REGIME_STRONG_BULLISH, REGIME_BULLISH):
        if breadth_condition == "BEARISH":
            regime = REGIME_BULLISH

    elif trend == REGIME_BEARISH:
        regime = REGIME_BEARISH

    if regime not in (
        REGIME_STRONG_BULLISH,
        REGIME_BULLISH,
        REGIME_NEUTRAL,
        REGIME_BEARISH,
    ):
        regime = REGIME_NEUTRAL

    allow_buy = regime != REGIME_HIGH_RISK

    return {
        "valid": True,
        "regime": regime,
        "market_status": regime,
        "allow_new_buy": allow_buy,
        "risk_level": (
            "LOW" if regime == REGIME_STRONG_BULLISH
            else "MEDIUM" if regime in (
                REGIME_BULLISH, REGIME_NEUTRAL
            )
            else "ELEVATED"
        ),
        "btc_trend": trend,
        "btc_trend_score": trend_score,
        "market_breadth": breadth_condition,
        "breadth_verified": bool(breadth.get("valid")),
        "risk_reasons": [],
    }


def determine_risk_level(
    market_status: dict[str, Any] | str,
) -> str:
    if isinstance(market_status, dict):
        if not market_status.get("valid", False):
            return "HIGH"

        regime = market_status.get("regime", "UNKNOWN")
    else:
        regime = market_status

    if regime == REGIME_HIGH_RISK:
        return "HIGH"

    if regime == REGIME_BEARISH:
        return "ELEVATED"

    if regime == REGIME_NEUTRAL:
        return "MEDIUM"

    if regime == REGIME_BULLISH:
        return "MEDIUM"

    if regime == REGIME_STRONG_BULLISH:
        return "LOW"

    return "HIGH"


def analyze_market(
    btc_data: dict[str, pd.DataFrame],
    external_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full BTC market-context analysis.

    btc_data example:
      {
        "15m": btc_15m_dataframe,
        "1h": btc_1h_dataframe,
        "4h": btc_4h_dataframe
      }
    """

    required = ("15m", "1h", "4h")

    timeframe_results: dict[str, dict[str, Any]] = {}

    for timeframe in required:
        frame = btc_data.get(timeframe)

        if not isinstance(frame, pd.DataFrame):
            timeframe_results[timeframe] = {
                "timeframe": timeframe,
                "valid": False,
                "status": "MISSING_DATA",
                "direction": "UNKNOWN",
                "errors": ["BTC timeframe DataFrame missing."],
            }
            continue

        timeframe_results[timeframe] = analyze_btc_timeframe(
            frame, timeframe
        )

    trend_result = determine_btc_trend(timeframe_results)
    volume_result = analyze_btc_volume(timeframe_results)
    external_result = analyze_external_data(external_data)

    market_result = classify_market(
        trend_result,
        timeframe_results,
        external_result,
    )

    market_result.update(
        {
            "timeframes": timeframe_results,
            "btc_trend_analysis": trend_result,
            "btc_volume_analysis": volume_result,
            "market_breadth_analysis": external_result,
            "risk_level": determine_risk_level(market_result),
            "formula_version": "4.0",
        }
    )

    return market_result


def validate_market_context(
    market_context: dict[str, Any] | None,
) -> bool:
    """
    Validate that a market context is safe to pass downstream.

    Invalid or incomplete context must not be treated as bullish.
    """

    if not isinstance(market_context, dict):
        return False

    if not market_context.get("valid", False):
        return False

    if market_context.get("regime") not in (
        REGIME_STRONG_BULLISH,
        REGIME_BULLISH,
        REGIME_NEUTRAL,
        REGIME_BEARISH,
        REGIME_HIGH_RISK,
    ):
        return False

    if market_context.get("regime") == REGIME_HIGH_RISK:
        return market_context.get("allow_new_buy") is False

    if market_context.get("allow_new_buy") is not True:
        return False

    timeframe_results = market_context.get("timeframes", {})

    for timeframe in ("15m", "1h", "4h"):
        result = timeframe_results.get(timeframe)

        if not isinstance(result, dict) or not result.get("valid"):
            return False

    return True


def get_market_filter_config() -> dict[str, Any]:
    return {
        "btc_regime": copy.deepcopy(BTC_REGIME_CONFIG),
        "indicators": copy.deepcopy(INDICATOR_CONFIG),
        "hard_gates": copy.deepcopy(HARD_GATE_CONFIG),
    }


# Compatibility helper for downstream risk controller.
def is_new_buy_allowed(
    market_context: dict[str, Any] | None,
) -> bool:
    return (
        validate_market_context(market_context)
        and market_context.get("allow_new_buy") is True
    )


if __name__ == "__main__":
    print("Binance Spot V3 Smart Signal Scanner")
    print("BTC Market Regime Engine")
    print("Formula Version: 4.0")
    print("Test Status: NOT RUN")
    print("Use test_system.py for repository integration tests.")
