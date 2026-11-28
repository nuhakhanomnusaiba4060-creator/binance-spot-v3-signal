
"""
File: market_filter.py
System: Binance Spot V4 Smart Signal Scanner
Version: 4.0.2
Formula Version: 4.0
Python: 3.11+

BTC Market Regime and Market Breadth Engine.

V4 rules:
- BEARISH is not automatically HIGH_RISK.
- HIGH_RISK requires abnormal market conditions.
- Invalid or missing BTC timeframe data blocks new BUY.
- Bearish market remains eligible for evaluation, subject to
  stricter downstream entry and risk validation.
- Only closed-candle data should be supplied.

Compatibility:
- Standard self-check result includes "ok" and "passed".
- Existing V4 function signatures and output fields preserved.
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
)

from indicators import (
    validate_dataframe,
    calculate_all_indicators,
)


REGIME_STRONG_BULLISH = "STRONG_BULLISH"
REGIME_BULLISH = "BULLISH"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_BEARISH = "BEARISH"
REGIME_HIGH_RISK = "HIGH_RISK"

REQUIRED_TIMEFRAMES = ("15m", "1h", "4h")

DEFAULT_HIGH_VOLATILITY_ATR_PERCENT = 3.0
DEFAULT_EXTREME_RSI_LOW = 20.0
DEFAULT_EXTREME_RSI_HIGH = 85.0
DEFAULT_HIGH_RISK_TIMEFRAME_COUNT = 2


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    result = _finite(value)
    return result if result is not None else default


def _config_lookup(
    names: tuple[str, ...],
    default: float,
) -> float:
    """
    Read an optional numeric setting from BTC_REGIME_CONFIG
    or HARD_GATE_CONFIG without assuming a specific nesting layout.
    """

    wanted = {
        str(name).lower().replace("-", "_")
        for name in names
    }

    def search(value: Any) -> float | None:
        if not isinstance(value, dict):
            return None

        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")

            if normalized in wanted:
                result = _finite(item)
                if result is not None:
                    return result

        for item in value.values():
            if isinstance(item, dict):
                result = search(item)
                if result is not None:
                    return result

        return None

    for source in (BTC_REGIME_CONFIG, HARD_GATE_CONFIG):
        result = search(source)
        if result is not None:
            return result

    return default


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

    if any(value is None for value in (
        ema20, ema50, ema200, close
    )):
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

    At least 205 valid candles are required for EMA200
    and indicator warm-up.
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

        if not isinstance(enriched, pd.DataFrame) or enriched.empty:
            raise ValueError(
                "Indicator calculation returned empty data."
            )

        row = enriched.iloc[-1]

        required_columns = (
            "close",
            "ema_20",
            "ema_50",
            "ema_200",
            "rsi",
            "adx",
            "atr",
        )

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

        missing = [
            key for key in required_columns
            if snapshot.get(key) is None
        ]

        if missing:
            raise ValueError(
                "Required indicators unavailable: "
                + ", ".join(missing)
            )

        close = snapshot["close"]
        atr = snapshot["atr"]
        rsi = snapshot["rsi"]
        adx = snapshot["adx"]

        if close <= 0 or atr <= 0:
            raise ValueError("Invalid close or ATR value.")

        if not 0 <= rsi <= 100:
            raise ValueError(
                "RSI value is outside the valid range."
            )

        alignment = _ema_alignment(snapshot)
        direction_score = _direction_from_alignment(alignment)

        histogram = snapshot["macd_histogram"]
        vwap = snapshot["vwap"]

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

        atr_percent = (atr / close) * 100.0

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
                round(vwap, 8)
                if vwap is not None else None
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
    """Evaluate BTC volume participation across timeframes."""

    values: list[float] = []

    for result in timeframe_results.values():
        if not isinstance(result, dict) or not result.get("valid"):
            continue

        rvol = _finite(result.get("rvol"))

        if rvol is not None and rvol >= 0:
            values.append(rvol)

    if not values:
        return {
            "valid": False,
            "status": "UNVERIFIED",
            "average_rvol": None,
            "volume_condition": "UNKNOWN",
            "bullish_confirmation": False,
            "timeframes_available": 0,
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
    Combine BTC 15m, 1h and 4h observations.

    Higher timeframes receive greater weight.
    Bearish trend alone does not mean HIGH_RISK.
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

    if total_weight <= 0:
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

    Three bearish timeframes do NOT automatically trigger HIGH_RISK.

    HIGH_RISK is triggered by:
    - Abnormally high ATR volatility on multiple timeframes.
    - Extreme RSI on multiple timeframes.

    Missing or invalid required timeframe data remains fail-closed.
    """

    high_volatility_threshold = _config_lookup(
        (
            "high_volatility_atr_percent",
            "high_risk_atr_percent",
            "atr_high_risk_percent",
            "extreme_atr_percent",
        ),
        DEFAULT_HIGH_VOLATILITY_ATR_PERCENT,
    )

    extreme_rsi_low = _config_lookup(
        (
            "extreme_rsi_low",
            "high_risk_rsi_low",
            "rsi_extreme_low",
        ),
        DEFAULT_EXTREME_RSI_LOW,
    )

    extreme_rsi_high = _config_lookup(
        (
            "extreme_rsi_high",
            "high_risk_rsi_high",
            "rsi_extreme_high",
        ),
        DEFAULT_EXTREME_RSI_HIGH,
    )

    required_count = int(_config_lookup(
        (
            "high_risk_timeframe_count",
            "minimum_high_risk_timeframes",
            "risk_confirmation_timeframes",
        ),
        DEFAULT_HIGH_RISK_TIMEFRAME_COUNT,
    ))

    required_count = max(
        1,
        min(required_count, len(REQUIRED_TIMEFRAMES)),
    )

    missing = []

    for timeframe in REQUIRED_TIMEFRAMES:
        result = timeframe_results.get(timeframe)

        if not isinstance(result, dict) or not result.get("valid"):
            missing.append(timeframe)

    if missing:
        return {
            "valid": False,
            "high_risk": True,
            "status": "DATA_UNVERIFIED",
            "reasons": [
                "Required BTC timeframe data missing or invalid: "
                + ", ".join(missing)
            ],
            "high_volatility_timeframes": 0,
            "extreme_rsi_timeframes": 0,
            "bearish_timeframes": 0,
        }

    high_volatility_timeframes: list[str] = []
    extreme_rsi_timeframes: list[str] = []
    bearish_timeframes = 0

    for timeframe in REQUIRED_TIMEFRAMES:
        result = timeframe_results[timeframe]

        atr_percent = _finite(result.get("atr_percent"))
        rsi = _finite(result.get("rsi"))
        direction = result.get("direction")

        if (
            atr_percent is not None
            and atr_percent >= high_volatility_threshold
        ):
            high_volatility_timeframes.append(timeframe)

        if (
            rsi is not None
            and (
                rsi <= extreme_rsi_low
                or rsi >= extreme_rsi_high
            )
        ):
            extreme_rsi_timeframes.append(timeframe)

        if direction == "BEARISH":
            bearish_timeframes += 1

    reasons: list[str] = []

    if len(high_volatility_timeframes) >= required_count:
        reasons.append(
            "BTC volatility is elevated across multiple timeframes."
        )

    if len(extreme_rsi_timeframes) >= required_count:
        reasons.append(
            "BTC RSI is at an extreme across multiple timeframes."
        )

    is_high_risk = bool(reasons)

    return {
        "valid": True,
        "high_risk": is_high_risk,
        "status": "HIGH_RISK" if is_high_risk else "NORMAL",
        "reasons": reasons,
        "high_volatility_timeframes": len(
            high_volatility_timeframes
        ),
        "high_volatility_timeframe_list": high_volatility_timeframes,
        "extreme_rsi_timeframes": len(extreme_rsi_timeframes),
        "extreme_rsi_timeframe_list": extreme_rsi_timeframes,
        "bearish_timeframes": bearish_timeframes,
        "bearish_is_high_risk_trigger": False,
        "thresholds": {
            "high_volatility_atr_percent": high_volatility_threshold,
            "extreme_rsi_low": extreme_rsi_low,
            "extreme_rsi_high": extreme_rsi_high,
            "required_timeframes": required_count,
        },
    }


def analyze_external_data(
    external_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Parse optional market breadth data.

    Missing breadth data remains UNVERIFIED.
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
        "market_breadth",
        external_data,
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
    Determine final BTC market regime.

    HIGH_RISK overrides directional classification.
    BEARISH remains a separate directional regime.
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
        reasons = list(risk_result.get("reasons", []))
        reasons.append("BTC market context is incomplete.")

        return {
            "valid": False,
            "regime": REGIME_HIGH_RISK,
            "market_status": "DATA_UNVERIFIED",
            "allow_new_buy": False,
            "risk_level": "HIGH",
            "btc_trend": trend,
            "btc_trend_score": trend_score,
            "risk_reasons": reasons,
            "risk_analysis": risk_result,
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
            "risk_analysis": risk_result,
        }

    breadth = (
        external_result
        if isinstance(external_result, dict)
        else {"valid": False, "condition": "UNKNOWN"}
    )

    breadth_condition = (
        breadth.get("condition", "UNKNOWN")
        if breadth.get("valid")
        else "UNKNOWN"
    )

    regime = trend

    # Breadth can moderate bullish classification,
    # but cannot reverse the BTC trend.
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

    # BEARISH is not a blanket BUY block.
    # Entry Engine must enforce stricter confirmation and risk checks.
    allow_buy = True

    return {
        "valid": True,
        "regime": regime,
        "market_status": regime,
        "allow_new_buy": allow_buy,
        "risk_level": (
            "LOW" if regime == REGIME_STRONG_BULLISH
            else "MEDIUM" if regime in (
                REGIME_BULLISH,
                REGIME_NEUTRAL,
            )
            else "ELEVATED"
        ),
        "btc_trend": trend,
        "btc_trend_score": trend_score,
        "market_breadth": breadth_condition,
        "breadth_verified": bool(breadth.get("valid")),
        "risk_reasons": [],
        "risk_analysis": risk_result,
        "bearish_market_warning": (
            "Bearish BTC trend: require stronger entry confirmation "
            "and strict net risk/reward validation."
            if regime == REGIME_BEARISH
            else None
        ),
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

    Expected input:
      {
        "15m": btc_15m_dataframe,
        "1h": btc_1h_dataframe,
        "4h": btc_4h_dataframe
      }
    """

    if not isinstance(btc_data, dict):
        btc_data = {}

    timeframe_results: dict[str, dict[str, Any]] = {}

    for timeframe in REQUIRED_TIMEFRAMES:
        frame = btc_data.get(timeframe)

        if not isinstance(frame, pd.DataFrame):
            timeframe_results[timeframe] = {
                "timeframe": timeframe,
                "valid": False,
                "status": "MISSING_DATA",
                "direction": "UNKNOWN",
                "errors": [
                    "BTC timeframe DataFrame missing."
                ],
            }
            continue

        timeframe_results[timeframe] = analyze_btc_timeframe(
            frame,
            timeframe,
        )

    trend_result = determine_btc_trend(timeframe_results)
    volume_result = analyze_btc_volume(timeframe_results)
    external_result = analyze_external_data(external_data)

    market_result = classify_market(
        trend_result,
        timeframe_results,
        external_result,
    )

    market_result.update({
        "timeframes": timeframe_results,
        "btc_trend_analysis": trend_result,
        "btc_volume_analysis": volume_result,
        "market_breadth_analysis": external_result,
        "risk_level": determine_risk_level(market_result),
        "formula_version": "4.0",
        "code_version": "4.0.2",
    })

    return market_result


def validate_market_context(
    market_context: dict[str, Any] | None,
) -> bool:
    """
    Validate downstream market context.

    Invalid context must never be treated as bullish.
    """

    if not isinstance(market_context, dict):
        return False

    if not market_context.get("valid", False):
        return False

    regime = market_context.get("regime")

    if regime not in (
        REGIME_STRONG_BULLISH,
        REGIME_BULLISH,
        REGIME_NEUTRAL,
        REGIME_BEARISH,
        REGIME_HIGH_RISK,
    ):
        return False

    timeframe_results = market_context.get("timeframes", {})

    if not isinstance(timeframe_results, dict):
        return False

    for timeframe in REQUIRED_TIMEFRAMES:
        result = timeframe_results.get(timeframe)

        if not isinstance(result, dict) or not result.get("valid"):
            return False

    if regime == REGIME_HIGH_RISK:
        return market_context.get("allow_new_buy") is False

    if market_context.get("allow_new_buy") is not True:
        return False

    return True


def get_market_filter_config() -> dict[str, Any]:
    return {
        "btc_regime": copy.deepcopy(BTC_REGIME_CONFIG),
        "indicators": copy.deepcopy(INDICATOR_CONFIG),
        "hard_gates": copy.deepcopy(HARD_GATE_CONFIG),
    }


def is_new_buy_allowed(
    market_context: dict[str, Any] | None,
) -> bool:
    return (
        validate_market_context(market_context)
        and market_context.get("allow_new_buy") is True
    )


def self_check() -> dict[str, Any]:
    """
    Lightweight internal logic checks.
    Does not fetch market data or generate trading signals.

    Standard result contract:
    - ok: Boolean used by test_system.py
    - passed: Backward-compatible Boolean
    - tests: Individual test results
    """

    results: dict[str, bool] = {}

    bearish_frames = {
        timeframe: {
            "timeframe": timeframe,
            "valid": True,
            "direction": "BEARISH",
            "atr_percent": 1.0,
            "rsi": 40.0,
        }
        for timeframe in REQUIRED_TIMEFRAMES
    }

    normal_bearish_risk = detect_high_risk(bearish_frames)

    results["bearish_alone_is_not_high_risk"] = (
        normal_bearish_risk["valid"]
        and not normal_bearish_risk["high_risk"]
    )

    bearish_trend = determine_btc_trend(bearish_frames)

    bearish_market = classify_market(
        bearish_trend,
        bearish_frames,
        None,
    )

    results["bearish_regime_allows_evaluation"] = (
        bearish_market.get("regime") == REGIME_BEARISH
        and bearish_market.get("allow_new_buy") is True
    )

    high_volatility_frames = copy.deepcopy(bearish_frames)

    high_volatility_frames["15m"]["atr_percent"] = 4.0
    high_volatility_frames["1h"]["atr_percent"] = 4.2

    volatility_risk = detect_high_risk(high_volatility_frames)

    results["multi_timeframe_high_volatility_blocks"] = (
        volatility_risk["valid"]
        and volatility_risk["high_risk"]
    )

    extreme_rsi_frames = copy.deepcopy(bearish_frames)

    extreme_rsi_frames["15m"]["rsi"] = 15.0
    extreme_rsi_frames["1h"]["rsi"] = 18.0

    rsi_risk = detect_high_risk(extreme_rsi_frames)

    results["multi_timeframe_extreme_rsi_blocks"] = (
        rsi_risk["valid"]
        and rsi_risk["high_risk"]
    )

    missing_frames = copy.deepcopy(bearish_frames)
    missing_frames["4h"]["valid"] = False

    missing_risk = detect_high_risk(missing_frames)

    results["missing_data_fails_closed"] = (
        not missing_risk["valid"]
        and missing_risk["high_risk"]
    )

    passed = all(results.values())

    # FIX:
    # test_system.py expects result.get("ok").
    # Keep "passed" to preserve existing compatibility.
    return {
        "ok": passed,
        "passed": passed,
        "tests": results,
        "passed_count": sum(bool(v) for v in results.values()),
        "total_count": len(results),
    }


if __name__ == "__main__":
    print("Binance Spot V4 Market Regime Engine")
    print("Formula Version: 4.0")
    print("Code Version: 4.0.2")

    report = self_check()

    for name, passed in report["tests"].items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")

    print(
        f"Self-check: {report['passed_count']}/"
        f"{report['total_count']} passed"
    )

    print(
        f"Overall: {'PASS' if report['ok'] else 'FAIL'}"
    )
