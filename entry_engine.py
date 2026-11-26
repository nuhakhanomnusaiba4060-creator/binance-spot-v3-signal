"""
Binance Spot V3 Smart Signal Scanner
Entry & 15-Point Signal Evaluation Engine

Evaluates SCALP (5m trigger / 15m, 30m confirmation) and
SWING (15m trigger / 30m, 1h confirmation) setups while protecting
against late pump chases and over-filtering valid setups.
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


STRATEGY_CONFIG = getattr(cfg, "STRATEGY_CONFIG", {})
MARKET_FILTER_CONFIG = getattr(cfg, "MARKET_FILTER_CONFIG", {})
COIN_SELECTION_CONFIG = getattr(
    cfg,
    "COIN_SELECTION_CONFIG",
    getattr(cfg, "FILTER_CONFIG", {}),
)
SCORING_CONFIG = getattr(cfg, "SCORING_CONFIG", {})
INDICATOR_CONFIG = getattr(cfg, "INDICATOR_CONFIG", {})


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError, OverflowError):
        return default


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


def _check_pump_and_overextension(
    df: pd.DataFrame,
    strat_cfg: dict[str, Any],
) -> tuple[bool, str]:
    """
    Reject clear late-stage pump chases or collapsed volume spikes
    without blocking early breakouts or valid pullbacks.
    """
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
    max_bull_candles = int(
        _safe_float(
            COIN_SELECTION_CONFIG.get("MAX_CONSECUTIVE_STRONG_BULL_CANDLES"),
            3,
        )
    )
    min_bull_body_pct = _safe_float(
        COIN_SELECTION_CONFIG.get("STRONG_BULL_CANDLE_BODY_PERCENT"),
        1.5,
    )
    rvol_spike_thresh = _safe_float(
        COIN_SELECTION_CONFIG.get("RVOL_SPIKE_THRESHOLD"),
        2.0,
    )
    rvol_collapse_ratio = _safe_float(
        COIN_SELECTION_CONFIG.get("RVOL_COLLAPSE_RATIO_OF_PEAK"),
        0.70,
    )

    roc = _safe_float(latest.get("roc"))
    if _is_valid_num(roc) and abs(roc) > max_roc * 1.35 and roc > 0:
        return False, "PUMP_ROC_OVEREXTENDED"

    bb_width = _safe_float(latest.get("bb_width"))
    if _is_valid_num(bb_width) and bb_width > max_bb_width * 1.4:
        return False, "BB_WIDTH_TOO_WIDE"

    ema_20 = _safe_float(latest.get("ema_20"))
    if _is_valid_num(ema_20) and ema_20 > 0:
        ext_pct = ((close - ema_20) / ema_20) * 100.0
        if ext_pct > max_ext_pct * 1.4:
            return False, "PRICE_TOO_FAR_ABOVE_EMA20"

    # Check consecutive strong bullish price candles
    if max_bull_candles >= 2 and len(df) >= max_bull_candles:
        recent = df.tail(max_bull_candles)
        strong_count = 0
        for _, row in recent.iterrows():
            o = _safe_float(row.get("open"))
            c = _safe_float(row.get("close"))
            if _is_valid_num(o) and _is_valid_num(c) and o > 0 and c > o:
                body_pct = ((c - o) / o) * 100.0
                if body_pct >= min_bull_body_pct:
                    strong_count += 1
        if strong_count >= max_bull_candles and roc > max_roc:
            return False, "CONSECUTIVE_PUMP_CANDLES"

    # Check RVOL spike followed by sharp drop
    if "relative_volume" in df.columns and len(df) >= 4:
        rvol_series = pd.to_numeric(df["relative_volume"], errors="coerce").tail(4)
        current_rvol = _safe_float(rvol_series.iloc[-1])
        prior_peak = _safe_float(rvol_series.iloc[:-1].max())
        if (
            _is_valid_num(prior_peak)
            and prior_peak >= rvol_spike_thresh
            and _is_valid_num(current_rvol)
            and current_rvol < (prior_peak * rvol_collapse_ratio)
        ):
            return False, "RVOL_COLLAPSE_AFTER_SPIKE"

    return True, "OK"


def _score_setup(
    trigger_df: pd.DataFrame,
    conf_dfs: list[pd.DataFrame],
    market_context: dict[str, Any] | None,
    strat_cfg: dict[str, Any],
) -> tuple[int, dict[str, int], list[str]]:
    """
    Compute 15-point setup score aligned with Config Specification v2.0.
    """
    latest = trigger_df.iloc[-1]
    prev = trigger_df.iloc[-2] if len(trigger_df) >= 2 else latest

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

    obv_series = pd.to_numeric(trigger_df.get("obv"), errors="coerce").dropna()
    obv_rising = len(obv_series) >= 3 and float(obv_series.iloc[-1]) > float(obv_series.iloc[-3])

    rsi_min = _safe_float(strat_cfg.get("RSI_MIN"), 50.0)
    rsi_max = _safe_float(strat_cfg.get("RSI_MAX"), 68.0)
    min_adx = _safe_float(strat_cfg.get("MIN_ADX"), 18.0)
    min_rvol = _safe_float(strat_cfg.get("MIN_RVOL"), 1.2)
    squeeze_max = _safe_float(INDICATOR_CONFIG.get("BB_SQUEEZE_MAX_WIDTH"), 0.10)
    roc_min = _safe_float(INDICATOR_CONFIG.get("ROC_EARLY_MIN_PERCENT"), 0.5)
    roc_max = _safe_float(INDICATOR_CONFIG.get("ROC_EARLY_MAX_PERCENT"), 3.0)
    vol_accel_min = _safe_float(INDICATOR_CONFIG.get("VOLUME_ACCELERATION_MIN"), 1.2)

    m_ctx = market_context if isinstance(market_context, dict) else {}
    market_status = str(m_ctx.get("market_status", "UNKNOWN")).upper()
    btc_trend = str(m_ctx.get("btc_trend", "UNKNOWN")).upper()

    breakdown: dict[str, int] = {
        "market_condition": 1 if market_status == "BULLISH" else 0,
        "btc_context": 1 if ("BULL" in btc_trend or market_status == "BULLISH") else 0,
        "mtf_trend": 0,
        "ema_trend": 1 if (_is_valid_num(ema_9) and _is_valid_num(ema_20) and ema_9 >= ema_20 and close >= ema_20 * 0.997) else 0,
        "ma_trend": 0,
        "rsi_momentum": 1 if (_is_valid_num(rsi) and rsi_min <= rsi <= rsi_max) else 0,
        "macd_momentum": 1 if (
            _is_valid_num(macd)
            and _is_valid_num(macd_sig)
            and (macd >= macd_sig or (_is_valid_num(macd_hist) and _is_valid_num(prev_hist) and macd_hist > prev_hist))
        ) else 0,
        "adx_strength": 1 if (
            _is_valid_num(adx)
            and adx >= min_adx * 0.9
            and (not _is_valid_num(plus_di) or not _is_valid_num(minus_di) or plus_di >= minus_di * 0.9)
        ) else 0,
        "relative_volume": 1 if (_is_valid_num(rvol) and rvol >= min_rvol * 0.95) else 0,
        "vwap_confirmation": 1 if (_is_valid_num(vwap) and close >= vwap * 0.998) else 0,
        "obv_cmf_flow": 1 if (obv_rising or (_is_valid_num(cmf) and cmf > 0.0)) else 0,
        "breakout_retest_quality": 0,
        "bb_squeeze": 1 if (_is_valid_num(bb_width) and bb_width <= squeeze_max * 1.25) else 0,
        "early_momentum_roc": 1 if (_is_valid_num(roc) and roc_min * 0.6 <= roc <= roc_max * 1.2) else 0,
        "volume_acceleration": 1 if (_is_valid_num(vol_mom) and vol_mom >= vol_accel_min * 0.9) else 0,
    }

    # Multi-timeframe confirmation check
    mtf_bull_count = 0
    for cdf in conf_dfs:
        if cdf is not None and not cdf.empty:
            crow = cdf.iloc[-1]
            c_close = _safe_float(crow.get("close"))
            c_ema20 = _safe_float(crow.get("ema_20"))
            if _is_valid_num(c_close) and _is_valid_num(c_ema20) and c_close >= c_ema20 * 0.996:
                mtf_bull_count += 1
    if conf_dfs and mtf_bull_count >= 1:
        breakdown["mtf_trend"] = 1

    # Moving average trend check
    ma_ok = False
    if _is_valid_num(sma_20) and close >= sma_20 * 0.996:
        ma_ok = True
    if _is_valid_num(sma_50) and close >= sma_50 * 0.99:
        ma_ok = True
    if _is_valid_num(sma_200) and close >= sma_200 * 0.985:
        ma_ok = True
    if ma_ok:
        breakdown["ma_trend"] = 1

    # Breakout / retest quality check
    levels = support_resistance(trigger_df)
    res_level = _safe_float(levels.get("resistance"))
    sup_level = _safe_float(levels.get("support"))
    retest_tol = _safe_float(INDICATOR_CONFIG.get("RETEST_TOLERANCE_PERCENT"), 0.5) / 100.0

    bullish_bar = _safe_float(latest.get("close")) >= _safe_float(latest.get("open"))
    near_or_above_sup = _is_valid_num(sup_level) and close >= sup_level * (1.0 - retest_tol)
    breakout_or_push = _is_valid_num(res_level) and close >= res_level * (1.0 - retest_tol)
    if bullish_bar and (near_or_above_sup or breakout_or_push or breakdown["ema_trend"] == 1):
        breakdown["breakout_retest_quality"] = 1

    raw_score = sum(breakdown.values())

    penalty = 0
    if market_status == "NEUTRAL":
        penalty = int(_safe_float(MARKET_FILTER_CONFIG.get("NEUTRAL_SCORE_PENALTY"), 2))
    elif market_status == "BEARISH":
        penalty = int(_safe_float(MARKET_FILTER_CONFIG.get("BEARISH_SCORE_PENALTY"), 1))

    final_score = max(0, raw_score - penalty)
    reasons = [k for k, v in breakdown.items() if v > 0]
    return final_score, breakdown, reasons


def _evaluate_strategy(
    strategy_name: str,
    symbol: str,
    data_by_tf: dict[str, pd.DataFrame],
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = str(symbol).upper().strip()
    if not sym.endswith("USDT"):
        return {"eligible": False, "classification": "REJECT", "reason": "INVALID_USDT_SYMBOL"}

    m_ctx = market_context if isinstance(market_context, dict) else {}
    market_status = str(m_ctx.get("market_status", "BULLISH")).upper()
    if market_status in ("HIGH_RISK", "UNKNOWN"):
        return {
            "eligible": False,
            "classification": "REJECT",
            "reason": f"MARKET_{market_status}",
        }

    strat_cfg = STRATEGY_CONFIG.get(strategy_name, {})
    trigger_tf = strat_cfg.get("TRIGGER_TIMEFRAME", "5m" if strategy_name == "SCALP" else "15m")
    conf_tfs = strat_cfg.get("CONFIRMATION_TIMEFRAMES", ("15m", "30m") if strategy_name == "SCALP" else ("30m", "1h"))

    if not isinstance(data_by_tf, dict) or trigger_tf not in data_by_tf:
        return {"eligible": False, "classification": "REJECT", "reason": "MISSING_TRIGGER_TIMEFRAME"}

    trigger_df = _prepare_df(data_by_tf.get(trigger_tf))
    if trigger_df is None:
        return {"eligible": False, "classification": "REJECT", "reason": "INSUFFICIENT_TRIGGER_CANDLES"}

    ok_pump, pump_reason = _check_pump_and_overextension(trigger_df, strat_cfg)
    if not ok_pump:
        return {"eligible": False, "classification": "REJECT", "reason": pump_reason}

    conf_dfs = []
    for tf in conf_tfs:
        prepared = _prepare_df(data_by_tf.get(tf))
        if prepared is not None:
            conf_dfs.append(prepared)

    score, breakdown, reasons = _score_setup(trigger_df, conf_dfs, m_ctx, strat_cfg)

    strong_min = int(_safe_float(SCORING_CONFIG.get("STRONG_BUY_MIN_SCORE"), 10))
    excellent_min = int(_safe_float(SCORING_CONFIG.get("EXCELLENT_BUY_MIN_SCORE"), 13))

    if score >= excellent_min:
        classification = "EXCELLENT BUY"
    elif score >= strong_min:
        classification = "STRONG BUY"
    else:
        return {
            "eligible": False,
            "classification": "REJECT",
            "score": score,
            "reason": f"SCORE_BELOW_THRESHOLD_{score}",
        }

    latest = trigger_df.iloc[-1]
    entry_price = _safe_float(latest.get("close"))
    atr_val = _safe_float(latest.get("atr"), entry_price * 0.01)
    levels = support_resistance(trigger_df)
    sup_val = _safe_float(levels.get("support"), entry_price * (1.0 - max(0.008, (atr_val / entry_price) * 1.5)))
    res_val = _safe_float(levels.get("resistance"), 0.0)

    resistance_levels = [res_val] if _is_valid_num(res_val) and res_val > entry_price else []

    return {
        "eligible": True,
        "symbol": sym,
        "strategy": strategy_name,
        "classification": classification,
        "score": score,
        "max_score": int(_safe_float(SCORING_CONFIG.get("MAX_SCORE"), 15)),
        "entry_price": round(entry_price, 8),
        "support_level": round(sup_val, 8) if _is_valid_num(sup_val) and sup_val > 0 else None,
        "atr_value": round(atr_val, 8) if _is_valid_num(atr_val) and atr_val > 0 else None,
        "resistance_levels": resistance_levels,
        "score_breakdown": breakdown,
        "confirmations": reasons,
        "reason": "SETUP_QUALIFIED",
    }


def evaluate_scalp(
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    indicators: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _evaluate_strategy("SCALP", symbol, market_data, market_context=market_context)


def evaluate_swing(
    symbol: str,
    market_data: dict[str, pd.DataFrame],
    indicators: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _evaluate_strategy("SWING", symbol, market_data, market_context=market_context)
