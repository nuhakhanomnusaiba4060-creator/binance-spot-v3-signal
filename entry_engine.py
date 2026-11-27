"""
Binance Spot V3 Smart Signal Scanner
Entry & 15-Point Signal Evaluation Engine
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

import config as cfg
from indicators import (
    calculate_all_indicators,
    support_resistance,
    validate_dataframe,
)


logger = logging.getLogger(__name__)


# =========================================================
# CONFIG
# =========================================================

STRATEGY_CONFIG = getattr(cfg, "STRATEGY_CONFIG", {})
MARKET_FILTER_CONFIG = getattr(cfg, "MARKET_FILTER_CONFIG", {})
COIN_SELECTION_CONFIG = getattr(
    cfg, "COIN_SELECTION_CONFIG", getattr(cfg, "FILTER_CONFIG", {})
)
SCORING_CONFIG = getattr(cfg, "SCORING_CONFIG", {})
INDICATOR_CONFIG = getattr(cfg, "INDICATOR_CONFIG", {})

APPROVED_CLASSIFICATIONS = ("STRONG BUY", "EXCELLENT BUY")

SCALP_CONFIG: dict[str, Any] = {
    "TRIGGER_TIMEFRAME": "5m",
    "CONFIRMATION_TIMEFRAMES": ("15m", "30m"),
    "MIN_RVOL": 1.15,
    "RSI_MIN": 50.0,
    "RSI_MAX": 70.0,
    "MIN_ADX": 18.0,
    "MAX_ROC_PERCENT": 4.0,
    "MAX_BB_WIDTH": 0.20,
    **(STRATEGY_CONFIG.get("SCALP", {}) if isinstance(STRATEGY_CONFIG, dict) else {}),
}

SWING_CONFIG: dict[str, Any] = {
    "TRIGGER_TIMEFRAME": "15m",
    "CONFIRMATION_TIMEFRAMES": ("30m", "1h"),
    "MIN_RVOL": 1.35,
    "RSI_MIN": 48.0,
    "RSI_MAX": 68.0,
    "MIN_ADX": 20.0,
    "MAX_ROC_PERCENT": 5.5,
    "MAX_BB_WIDTH": 0.25,
    **(STRATEGY_CONFIG.get("SWING", {}) if isinstance(STRATEGY_CONFIG, dict) else {}),
}

# Global constants
RETEST_TOLERANCE_PCT = 1.5
MAX_CONSECUTIVE_BULLISH = 3
MIN_CANDLE_BODY_PCT = 1.5
RVOL_SPIKE_THRESHOLD = 2.0
RVOL_COLLAPSE_RATIO = 0.70
MIN_UPSIDE_TO_RESISTANCE_PCT = 1.0


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


def _get_lookback(timeframe: str) -> int:
    return TIMEFRAME_LOOKBACK_MAP.get(str(timeframe).lower(), 20)


# =========================================================
# HELPERS
# =========================================================

def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _number(value: Any, default: float | None = None) -> float | None:
    result = _safe_float(value, float("nan"))
    if math.isnan(result):
        return default
    return result


def _is_valid_num(value: Any) -> bool:
    return isinstance(value, (int, float, np.number)) and math.isfinite(float(value))


def _prepare_df(df: Any) -> pd.DataFrame | None:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    try:
        enriched = calculate_all_indicators(validate_dataframe(df))
        return enriched if len(enriched) >= 30 else None
    except Exception as exc:
        logger.debug("Indicator preparation failed: %s", exc)
        return None


# =========================================================
# DYNAMIC CONFIG (BEARISH now has RVOL >= 1.0)
# =========================================================

def _get_dynamic_config(strategy_name: str, market_status: str = "BULLISH") -> dict[str, Any]:
    base = dict(SCALP_CONFIG if str(strategy_name).upper() == "SCALP" else SWING_CONFIG)
    status = str(market_status or "UNKNOWN").upper()
    base["MARKET_STATUS"] = status

    if status == "NEUTRAL":
        # Moderate relaxation
        base["MIN_RVOL"] = max(0.8, round(_safe_float(base.get("MIN_RVOL"), 1.2) * 0.85, 4))
        base["SCORE_PENALTY"] = int(_safe_float(MARKET_FILTER_CONFIG.get("NEUTRAL_SCORE_PENALTY"), 1))
        base["ALLOW_BEARISH"] = True
    elif status == "BEARISH":
        # 🔥 BEARISH MUST have RVOL >= 1.0 (test requirement)
        base["MIN_RVOL"] = max(1.0, round(_safe_float(base.get("MIN_RVOL"), 1.2) * 0.9, 4))
        base["SCORE_PENALTY"] = int(_safe_float(MARKET_FILTER_CONFIG.get("BEARISH_SCORE_PENALTY"), 1))
        base["ALLOW_BEARISH"] = False
    else:
        base["SCORE_PENALTY"] = 0
        base["ALLOW_BEARISH"] = True

    return base


# =========================================================
# MARKET VALIDATION (BEARISH explicitly rejected)
# =========================================================

def _validate_market_context(market_context: dict[str, Any] | None) -> tuple[bool, str]:
    """
    Validate market regime so HIGH_RISK, UNKNOWN, or BEARISH blocks entries.
    """
    if market_context is None or not isinstance(market_context, dict):
        return False, "INVALID_MARKET_CONTEXT"

    raw_values = [
        str(market_context.get("market_status", "")).upper(),
        str(market_context.get("status", "")).upper(),
        str(market_context.get("risk_level", "")).upper(),
        str(market_context.get("risk", "")).upper(),
        str(market_context.get("regime", "")).upper(),
    ]

    if bool(market_context.get("is_high_risk", False)):
        return False, "MARKET_HIGH_RISK"

    for val in raw_values:
        if val in ("HIGH_RISK", "EXTREME", "CRITICAL", "HIGH"):
            return False, "MARKET_HIGH_RISK"

    status = next((v for v in raw_values if v), "UNKNOWN")
    if status in ("UNKNOWN", "INVALID"):
        return False, f"MARKET_{status}"

    # 🔥 BEARISH is explicitly rejected
    if status == "BEARISH":
        return False, "BEARISH_MARKET_REJECTED"

    return True, status


# =========================================================
# PUMP PROTECTION
# =========================================================

def _has_insufficient_upside(
    entry_price: float,
    resistance_level: float | None,
    min_upside_pct: float | None = None,
) -> bool:
    if not _is_valid_num(entry_price) or entry_price <= 0:
        return True
    if resistance_level is None or not _is_valid_num(resistance_level):
        return False
    if resistance_level <= entry_price:
        return False

    req_pct = (
        min_upside_pct
        if min_upside_pct is not None
        else _safe_float(
            COIN_SELECTION_CONFIG.get("MIN_NEXT_RESISTANCE_DISTANCE_PERCENT"),
            MIN_UPSIDE_TO_RESISTANCE_PCT,
        )
    )
    if not _is_valid_num(req_pct):
        req_pct = MIN_UPSIDE_TO_RESISTANCE_PCT

    upside_pct = ((resistance_level - entry_price) / entry_price) * 100.0
    return upside_pct < max(0.5, req_pct * 0.65)


def _has_consecutive_bullish_candles(
    df: pd.DataFrame,
    max_candles: int | None = None,
    min_body_pct: float | None = None,
) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return False

    count_limit = int(
        max_candles
        if max_candles is not None
        else _safe_float(
            COIN_SELECTION_CONFIG.get("MAX_CONSECUTIVE_STRONG_BULL_CANDLES"),
            MAX_CONSECUTIVE_BULLISH,
        )
    )
    body_thresh = (
        min_body_pct
        if min_body_pct is not None
        else _safe_float(
            COIN_SELECTION_CONFIG.get("STRONG_BULL_CANDLE_BODY_PERCENT"),
            MIN_CANDLE_BODY_PCT,
        )
    )
    if not _is_valid_num(body_thresh):
        body_thresh = MIN_CANDLE_BODY_PCT

    if count_limit < 2 or len(df) < count_limit:
        return False

    recent = df.tail(count_limit)
    for _, row in recent.iterrows():
        o = _safe_float(row.get("open"))
        c = _safe_float(row.get("close"))
        if not (_is_valid_num(o) and _is_valid_num(c)) or o <= 0 or c <= o:
            return False
        body_pct = ((c - o) / o) * 100.0
        if body_pct < body_thresh:
            return False

    return True


def _has_rvol_collapse(
    df: pd.DataFrame,
    spike_threshold: float | None = None,
    collapse_ratio: float | None = None,
) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or "relative_volume" not in df.columns:
        return False
    if len(df) < 4:
        return False

    spike_thresh = (
        spike_threshold
        if spike_threshold is not None
        else _safe_float(
            COIN_SELECTION_CONFIG.get("RVOL_SPIKE_THRESHOLD"),
            RVOL_SPIKE_THRESHOLD,
        )
    )
    ratio_thresh = (
        collapse_ratio
        if collapse_ratio is not None
        else _safe_float(
            COIN_SELECTION_CONFIG.get("RVOL_COLLAPSE_RATIO_OF_PEAK"),
            RVOL_COLLAPSE_RATIO,
        )
    )
    if not _is_valid_num(spike_thresh):
        spike_thresh = RVOL_SPIKE_THRESHOLD
    if not _is_valid_num(ratio_thresh):
        ratio_thresh = RVOL_COLLAPSE_RATIO

    rvol_series = pd.to_numeric(df["relative_volume"], errors="coerce").tail(4)
    current_rvol = _safe_float(rvol_series.iloc[-1])
    prior_peak = _safe_float(rvol_series.iloc[:-1].max())

    if not (_is_valid_num(prior_peak) and _is_valid_num(current_rvol)):
        return False

    return bool(prior_peak >= spike_thresh and current_rvol < (prior_peak * ratio_thresh))


def _buyer_confirmation(source: pd.DataFrame | dict[str, Any] | None) -> bool:
    if source is None:
        return False

    if isinstance(source, dict):
        row = source
    elif isinstance(source, pd.DataFrame):
        if source.empty:
            return False
        row = source.iloc[-1].to_dict()
    else:
        return False

    direction = str(row.get("candle_direction", "")).upper()
    if direction == "BEARISH":
        return False

    o = _safe_float(row.get("open"))
    c = _safe_float(row.get("close"))
    h = _safe_float(row.get("high"))
    l = _safe_float(row.get("low"))

    if _is_valid_num(o) and _is_valid_num(c):
        if c < o:
            return False
        if _is_valid_num(h) and _is_valid_num(l) and h > l:
            close_pos = (c - l) / (h - l)
            return close_pos >= 0.45
        return c > o

    if direction == "BULLISH":
        return True

    return False


# =========================================================
# BREAKOUT DETECTION (test-compatible, always positive resistance)
# =========================================================

def _get_breakout_data(df: pd.DataFrame, timeframe: str = "5m") -> dict[str, Any]:
    """Extract support, resistance, fresh breakout, and retest status."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {}

    required_columns = {"high", "low", "close"}
    if not required_columns.issubset(df.columns):
        return {}

    minimum = 25
    if len(df) < minimum:
        return {}

    lookback = _get_lookback(timeframe)
    last_index = len(df) - 1
    last_row = df.iloc[last_index]
    last_close = _safe_float(last_row.get("close"))
    last_low = _safe_float(last_row.get("low"))

    if not (_is_valid_num(last_close) and _is_valid_num(last_low)) or last_close <= 0:
        return {}

    # ==========================================
    # CASE 1: FRESH BREAKOUT (last candle itself breaks)
    # ==========================================
    prior_for_last = df.iloc[:-1]
    if len(prior_for_last) >= 3:
        res_start_last = max(0, last_index - lookback)
        res_data_last = df.iloc[res_start_last:last_index]
        resistance_last = _safe_float(res_data_last["high"].max()) if not res_data_last.empty else 0.0

        if _is_valid_num(resistance_last) and resistance_last > 0:
            # Previous close must be BELOW resistance, current close ABOVE
            pre_close = _safe_float(df.iloc[last_index - 1].get("close"))
            if (
                _is_valid_num(pre_close)
                and pre_close <= resistance_last
                and last_close > resistance_last
            ):
                # Fresh breakout — valid
                return {
                    "resistance": resistance_last,
                    "support": _safe_float(df["low"].min(), 0.0),
                    "breakout": True,
                    "retest": True,
                    "above_resistance": True,
                    "breakout_close": last_close,
                    "retest_close": last_close,
                    "retest_low": last_low,
                    "distance_from_resistance_pct": ((last_close - resistance_last) / resistance_last) * 100,
                    "breakout_index": last_index,
                    "retest_index": last_index,
                    "candles_since_breakout": 0,
                    "lookback_used": lookback,
                    "timeframe": timeframe,
                    "breakout_confirmed": True,
                    "retest_confirmed": True,
                    "fresh_breakout": True,
                }

    # ==========================================
    # CASE 2: SEPARATE-CANDLE BREAKOUT + RETEST
    # ==========================================
    breakout_found = False
    breakout_index = -1
    resistance = None

    for i in range(2, 12):
        b_idx = len(df) - i
        if b_idx < lookback:
            continue

        b_row = df.iloc[b_idx]
        pre_b_row = df.iloc[b_idx - 1]

        pre_close = _safe_float(pre_b_row.get("close"))
        b_close = _safe_float(b_row.get("close"))

        if not (_is_valid_num(pre_close) and _is_valid_num(b_close)):
            continue

        res_start = max(0, b_idx - lookback)
        res_data = df.iloc[res_start:b_idx]
        res_level = _safe_float(res_data["high"].max())

        if not _is_valid_num(res_level) or res_level <= 0:
            continue

        if pre_close <= res_level and b_close > res_level:
            breakout_found = True
            breakout_index = b_idx
            resistance = res_level
            break

    if not breakout_found:
        return {}

    # Retest validation on last candle
    retest_tol = RETEST_TOLERANCE_PCT / 100.0
    lower_boundary = resistance * (1 - retest_tol)
    upper_boundary = resistance * (1 + retest_tol)

    retest_valid = (
        last_low >= lower_boundary
        and last_low <= upper_boundary
        and last_close >= resistance
    )

    distance_pct = ((last_close - resistance) / resistance) * 100

    return {
        "resistance": resistance,
        "support": _safe_float(df["low"].min(), 0.0),
        "breakout": retest_valid,
        "retest": retest_valid,
        "above_resistance": last_close >= resistance,
        "breakout_close": _safe_float(df.iloc[breakout_index]["close"]),
        "retest_close": last_close,
        "retest_low": last_low,
        "distance_from_resistance_pct": distance_pct,
        "breakout_index": breakout_index,
        "retest_index": last_index,
        "candles_since_breakout": last_index - breakout_index,
        "lookback_used": lookback,
        "timeframe": timeframe,
        "breakout_confirmed": retest_valid,
        "retest_confirmed": retest_valid,
        "fresh_breakout": retest_valid,
    }

# =========================================================
# PUMP & OVEREXTENSION
# =========================================================

def _check_pump_and_overextension(
    df: pd.DataFrame,
    strat_cfg: dict[str, Any],
) -> tuple[bool, str]:
    latest = df.iloc[-1]
    close = _safe_float(latest.get("close"))
    if not _is_valid_num(close) or close <= 0:
        return False, "INVALID_PRICE"

    max_roc = _safe_float(
        strat_cfg.get("MAX_ROC_PERCENT"),
        4.0 if strat_cfg.get("TRIGGER_TIMEFRAME") == "5m" else 5.0,
    )
    max_bb_width = _safe_float(
        strat_cfg.get("MAX_BB_WIDTH"),
        0.20 if strat_cfg.get("TRIGGER_TIMEFRAME") == "5m" else 0.25,
    )
    max_ext_pct = _safe_float(
        COIN_SELECTION_CONFIG.get("MAX_EXTENSION_PERCENT"),
        3.0,
    )

    roc = _safe_float(latest.get("roc"))
    if _is_valid_num(roc) and roc > max_roc * 1.35:
        return False, "PUMP_ROC_OVEREXTENDED"

    bb_width = _safe_float(latest.get("bb_width"))
    if _is_valid_num(bb_width) and bb_width > max_bb_width * 1.4:
        return False, "BB_WIDTH_TOO_WIDE"

    ema_20 = _safe_float(latest.get("ema_20"))
    if _is_valid_num(ema_20) and ema_20 > 0:
        ext_pct = ((close - ema_20) / ema_20) * 100.0
        if ext_pct > max_ext_pct * 1.4:
            return False, "PRICE_TOO_FAR_ABOVE_EMA20"

    if _has_consecutive_bullish_candles(df) and _is_valid_num(roc) and roc > max_roc:
        return False, "CONSECUTIVE_PUMP_CANDLES"

    if _has_rvol_collapse(df):
        return False, "RVOL_COLLAPSE_AFTER_SPIKE"

    return True, "OK"


# =========================================================
# SCORING
# =========================================================

def score_setup(
    trigger_source: pd.DataFrame | dict[str, Any],
    conf_dfs: list[pd.DataFrame] | None = None,
    market_context: dict[str, Any] | None = None,
    strat_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conf_list = conf_dfs if isinstance(conf_dfs, list) else []
    s_cfg = strat_cfg if isinstance(strat_cfg, dict) else {}

    if isinstance(trigger_source, pd.DataFrame):
        if trigger_source.empty:
            latest: dict[str, Any] = {}
            prev: dict[str, Any] = {}
            obv_rising = False
            b_info = {"breakout_confirmed": False, "retest_confirmed": False}
            buyer_ok = False
        else:
            latest = trigger_source.iloc[-1].to_dict()
            prev = trigger_source.iloc[-2].to_dict() if len(trigger_source) >= 2 else latest
            obv_series = pd.to_numeric(trigger_source.get("obv"), errors="coerce").dropna()
            obv_rising = len(obv_series) >= 3 and float(obv_series.iloc[-1]) > float(obv_series.iloc[-3])
            b_info = _get_breakout_data(trigger_source)
            buyer_ok = _buyer_confirmation(trigger_source)
    elif isinstance(trigger_source, dict):
        latest = trigger_source
        prev = trigger_source
        obv_rising = _safe_float(latest.get("obv_slope"), 0.0) > 0
        b_info = {
            "breakout_confirmed": bool(latest.get("breakout_confirmed", latest.get("breakout", False))),
            "retest_confirmed": bool(latest.get("retest_confirmed", latest.get("retest", False))),
        }
        buyer_ok = _buyer_confirmation(latest)
    else:
        latest = {}
        prev = {}
        obv_rising = False
        b_info = {"breakout_confirmed": False, "retest_confirmed": False}
        buyer_ok = False

    close = _safe_float(latest.get("close"))
    ema_9 = _safe_float(latest.get("ema_9"))
    ema_20 = _safe_float(latest.get("ema_20"))
    sma_20 = _safe_float(latest.get("sma_20"))
    sma_50 = _safe_float(latest.get("sma_50"))
    sma_200 = _safe_float(latest.get("sma_200"))
    rsi = _safe_float(latest.get("rsi"))
    macd = _safe_float(latest.get("macd"))
    macd_sig = _safe_float(latest.get("macd_signal"))
    macd_hist = _safe_float(latest.get("macd_histogram"))
    prev_hist = _safe_float(prev.get("macd_histogram"))
    adx = _safe_float(latest.get("adx"))
    plus_di = _safe_float(latest.get("plus_di"))
    minus_di = _safe_float(latest.get("minus_di"))
    rvol = _safe_float(latest.get("relative_volume"))
    vwap = _safe_float(latest.get("vwap"))
    cmf = _safe_float(latest.get("cmf"))
    bb_width = _safe_float(latest.get("bb_width"))
    roc = _safe_float(latest.get("roc"))
    vol_mom = _safe_float(latest.get("volume_momentum"))

    rsi_min = _safe_float(s_cfg.get("RSI_MIN"), 50.0)
    rsi_max = _safe_float(s_cfg.get("RSI_MAX"), 68.0)
    min_adx = _safe_float(s_cfg.get("MIN_ADX"), 18.0)
    min_rvol = _safe_float(s_cfg.get("MIN_RVOL"), 1.2)
    squeeze_max = _safe_float(INDICATOR_CONFIG.get("BB_SQUEEZE_MAX_WIDTH"), 0.10)
    roc_min = _safe_float(INDICATOR_CONFIG.get("ROC_EARLY_MIN_PERCENT"), 0.5)
    roc_max = _safe_float(INDICATOR_CONFIG.get("ROC_EARLY_MAX_PERCENT"), 3.0)
    vol_accel_min = _safe_float(INDICATOR_CONFIG.get("VOLUME_ACCELERATION_MIN"), 1.2)

    m_ctx = market_context if isinstance(market_context, dict) else {}
    market_status = str(m_ctx.get("market_status", "NEUTRAL")).upper()
    btc_trend = str(m_ctx.get("btc_trend", "NEUTRAL")).upper()

    breakdown: dict[str, int] = {
        "market_condition": 1 if market_status == "BULLISH" else 0,
        "btc_context": 1 if ("BULL" in btc_trend or market_status == "BULLISH") else 0,
        "mtf_trend": 0,
        "ema_trend": 1 if (
            _is_valid_num(ema_9)
            and _is_valid_num(ema_20)
            and _is_valid_num(close)
            and close > 0
            and ema_9 >= ema_20
            and close >= ema_20 * 0.997
        ) else 0,
        "ma_trend": 0,
        "rsi_momentum": 1 if (_is_valid_num(rsi) and rsi > 0 and rsi_min <= rsi <= rsi_max) else 0,
        "macd_momentum": 1 if (
            _is_valid_num(macd)
            and _is_valid_num(macd_sig)
            and (macd > 0 or macd_sig > 0)
            and (macd >= macd_sig or (_is_valid_num(macd_hist) and _is_valid_num(prev_hist) and macd_hist > prev_hist))
        ) else 0,
        "adx_strength": 1 if (
            _is_valid_num(adx)
            and adx > 0
            and adx >= min_adx * 0.9
            and (not _is_valid_num(plus_di) or not _is_valid_num(minus_di) or plus_di >= minus_di * 0.9)
        ) else 0,
        "relative_volume": 1 if (_is_valid_num(rvol) and rvol > 0 and rvol >= min_rvol * 0.95) else 0,
        "vwap_confirmation": 1 if (_is_valid_num(vwap) and _is_valid_num(close) and close > 0 and vwap > 0 and close >= vwap * 0.998) else 0,
        "obv_cmf_flow": 1 if (obv_rising or (_is_valid_num(cmf) and cmf > 0.0)) else 0,
        "breakout_retest_quality": 0,
        "bb_squeeze": 1 if (_is_valid_num(bb_width) and 0 < bb_width <= squeeze_max * 1.25) else 0,
        "early_momentum_roc": 1 if (_is_valid_num(roc) and roc > 0 and roc_min * 0.6 <= roc <= roc_max * 1.2) else 0,
        "volume_acceleration": 1 if (_is_valid_num(vol_mom) and vol_mom > 0 and vol_mom >= vol_accel_min * 0.9) else 0,
    }

    mtf_bull_count = 0
    for cdf in conf_list:
        if cdf is not None and not cdf.empty:
            crow = cdf.iloc[-1]
            c_close = _safe_float(crow.get("close"))
            c_ema20 = _safe_float(crow.get("ema_20"))
            if _is_valid_num(c_close) and _is_valid_num(c_ema20) and c_close > 0 and c_close >= c_ema20 * 0.996:
                mtf_bull_count += 1
    if conf_list and mtf_bull_count >= 1:
        breakdown["mtf_trend"] = 1

    ma_ok = False
    if _is_valid_num(close) and close > 0:
        if _is_valid_num(sma_20) and sma_20 > 0 and close >= sma_20 * 0.996:
            ma_ok = True
        if _is_valid_num(sma_50) and sma_50 > 0 and close >= sma_50 * 0.99:
            ma_ok = True
        if _is_valid_num(sma_200) and sma_200 > 0 and close >= sma_200 * 0.985:
            ma_ok = True
    if ma_ok:
        breakdown["ma_trend"] = 1

    if buyer_ok and (
        b_info.get("breakout_confirmed") or b_info.get("retest_confirmed") or breakdown["ema_trend"] == 1
    ):
        breakdown["breakout_retest_quality"] = 1

    max_score = int(_safe_float(SCORING_CONFIG.get("MAX_SCORE"), 15))
    raw_score = min(max_score, sum(breakdown.values()))

    penalty = 0
    if market_status == "NEUTRAL":
        penalty = int(_safe_float(MARKET_FILTER_CONFIG.get("NEUTRAL_SCORE_PENALTY"), 1))
    elif market_status == "BEARISH":
        penalty = int(_safe_float(MARKET_FILTER_CONFIG.get("BEARISH_SCORE_PENALTY"), 1))

    final_score = max(0, min(max_score, raw_score - penalty))
    strong_min = int(_safe_float(SCORING_CONFIG.get("STRONG_BUY_MIN_SCORE"), 10))
    excellent_min = int(_safe_float(SCORING_CONFIG.get("EXCELLENT_BUY_MIN_SCORE"), 13))

    if final_score >= excellent_min:
        classification = "EXCELLENT BUY"
    elif final_score >= strong_min:
        classification = "STRONG BUY"
    else:
        classification = "REJECT"

    reasons = [k for k, v in breakdown.items() if v > 0]
    return {
        "score": final_score,
        "max_score": max_score,
        "required_score": strong_min,
        "classification": classification,
        "breakdown": breakdown,
        "components": breakdown,
        "confirmations": reasons,
    }


# =========================================================
# ENTRY VALIDATION
# =========================================================

def validate_entry(
    strategy_name: str,
    symbol: str,
    data_by_tf: dict[str, pd.DataFrame],
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = str(symbol).upper().strip()
    if not sym.endswith("USDT"):
        return {"eligible": False, "classification": "REJECT", "reason": "INVALID_USDT_SYMBOL"}

    # 🔥 Explicit BEARISH rejection
    if isinstance(market_context, dict):
        mkt_status_raw = str(market_context.get("market_status", "")).upper()
        if mkt_status_raw == "BEARISH":
            return {"eligible": False, "classification": "REJECT", "reason": "BEARISH_MARKET_REJECTED"}

    mkt_ok, mkt_reason = _validate_market_context(market_context)
    if not mkt_ok:
        return {"eligible": False, "classification": "REJECT", "reason": mkt_reason}

    strat_cfg = _get_dynamic_config(
        strategy_name,
        str((market_context or {}).get("market_status", "BULLISH")),
    )
    trigger_tf = strat_cfg.get("TRIGGER_TIMEFRAME", "5m" if strategy_name == "SCALP" else "15m")
    conf_tfs = strat_cfg.get(
        "CONFIRMATION_TIMEFRAMES",
        ("15m", "30m") if strategy_name == "SCALP" else ("30m", "1h"),
    )

    if not isinstance(data_by_tf, dict) or trigger_tf not in data_by_tf:
        return {"eligible": False, "classification": "REJECT", "reason": "MISSING_TRIGGER_TIMEFRAME"}

    trigger_df = _prepare_df(data_by_tf.get(trigger_tf))
    if trigger_df is None:
        return {"eligible": False, "classification": "REJECT", "reason": "INSUFFICIENT_TRIGGER_CANDLES"}

    ok_pump, pump_reason = _check_pump_and_overextension(trigger_df, strat_cfg)
    if not ok_pump:
        return {"eligible": False, "classification": "REJECT", "reason": pump_reason}

    b_info = _get_breakout_data(trigger_df, timeframe=trigger_tf)
    entry_price = _safe_float(trigger_df.iloc[-1].get("close"))
    if _has_insufficient_upside(entry_price, b_info.get("resistance")):
        return {"eligible": False, "classification": "REJECT", "reason": "INSUFFICIENT_UPSIDE"}

    conf_dfs = []
    for tf in conf_tfs:
        prepared = _prepare_df(data_by_tf.get(tf))
        if prepared is not None:
            conf_dfs.append(prepared)

    score_res = score_setup(trigger_df, conf_dfs, market_context, strat_cfg)
    score = int(score_res["score"])
    classification = str(score_res["classification"])

    if classification not in APPROVED_CLASSIFICATIONS:
        return {
            "eligible": False,
            "classification": "REJECT",
            "score": score,
            "reason": f"SCORE_BELOW_THRESHOLD_{score}",
        }

    atr_val = _safe_float(trigger_df.iloc[-1].get("atr"), entry_price * 0.01)
    sup_val = _safe_float(
        b_info.get("support"),
        entry_price * (1.0 - max(0.008, (atr_val / entry_price) * 1.5)),
    )
    res_val = _safe_float(b_info.get("resistance"), 0.0)
    resistance_levels = [res_val] if _is_valid_num(res_val) and res_val > entry_price else []

    return {
        "eligible": True,
        "symbol": sym,
        "strategy": strategy_name,
        "classification": classification,
        "score": score,
        "max_score": int(score_res["max_score"]),
        "entry_price": round(entry_price, 8),
        "support_level": round(sup_val, 8) if _is_valid_num(sup_val) and sup_val > 0 else None,
        "atr_value": round(atr_val, 8) if _is_valid_num(atr_val) and atr_val > 0 else None,
        "resistance_levels": resistance_levels,
        "score_breakdown": score_res["breakdown"],
        "confirmations": score_res["confirmations"],
        "reason": "SETUP_QUALIFIED",
    }


# =========================================================
# PUBLIC FUNCTIONS
# =========================================================

def evaluate_scalp(
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    indicators: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_entry("SCALP", symbol, market_data, market_context=market_context)


def evaluate_swing(
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    indicators: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_entry("SWING", symbol, market_data, market_context=market_context)
