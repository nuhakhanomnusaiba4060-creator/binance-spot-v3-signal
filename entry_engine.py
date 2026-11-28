"""
File: entry_engine.py
System: Binance Spot V3 Smart Signal Scanner
Code Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Compatibility: New internal architecture
Test Status: NOT RUN

Seven-Layer Multi-Timeframe Spot Signal Engine.

SCALP:
    Entry: 5m
    Confirmation: 15m
    Structure: 30m

SWING:
    Entry: 15m
    Confirmation: 30m
    Structure: 1h

BTC Context:
    15m / 1h / 4h

Spot only. No Futures. No Margin.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from risk_manager import (
    build_risk_plan,
    calculate_execution_cost_pct,
)


# ============================================================
# VERSION AND FORMULA CONFIGURATION
# ============================================================

CODE_VERSION = "4.0.0"
FORMULA_VERSION = "4.0"

LAYER_WEIGHTS = {
    "btc_market_regime": 15,
    "technical_structure": 20,
    "volume_momentum": 15,
    "liquidity_order_flow": 15,
    "entry_quality": 15,
    "risk_reward": 10,
    "fundamental_onchain": 10,
}

CLASSIFICATIONS = {
    "EXCELLENT BUY": 90,
    "STRONG BUY": 85,
    "WATCHLIST": 75,
    "WAIT": 60,
}

TIMEFRAME_MAP = {
    "SCALP": {
        "entry": "5m",
        "confirmation": "15m",
        "structure": "30m",
    },
    "SWING": {
        "entry": "15m",
        "confirmation": "30m",
        "structure": "1h",
    },
}

BTC_TIMEFRAMES = ("15m", "1h", "4h")

DEFAULT_MIN_CANDLES = 205
DEFAULT_MAX_ENTRY_DISTANCE_ATR = 1.5
DEFAULT_MAX_SPREAD_PERCENT = 0.25
DEFAULT_MIN_DEPTH_USDT = 10_000.0
DEFAULT_MAX_SLIPPAGE_PERCENT = 0.20

DEFAULT_MIN_NET_RR_T1 = 1.2
DEFAULT_MIN_SIGNAL_SCORE = 85
DEFAULT_EXCELLENT_SCORE = 90

EPSILON = 1e-12


# ============================================================
# GENERAL HELPERS
# ============================================================

def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except (TypeError, ValueError, OverflowError):
        return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_div(a: float, b: float) -> float:
    if abs(b) <= EPSILON:
        return 0.0
    return a / b


def _get_latest(df: pd.DataFrame, column: str) -> Optional[float]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    if column not in df.columns:
        return None

    values = pd.to_numeric(df[column], errors="coerce").dropna()

    if values.empty:
        return None

    return _number(values.iloc[-1])


def _valid_frame(
    df: Any,
    minimum_rows: int = DEFAULT_MIN_CANDLES,
) -> bool:
    if not isinstance(df, pd.DataFrame):
        return False

    if len(df) < minimum_rows:
        return False

    required = {"open", "high", "low", "close", "volume"}

    if not required.issubset(df.columns):
        return False

    for column in required:
        values = pd.to_numeric(df[column], errors="coerce")

        if values.isna().any():
            return False

        if not values.map(math.isfinite).all():
            return False

    if (df["close"] <= 0).any():
        return False

    if (df["high"] < df["low"]).any():
        return False

    if (df["volume"] < 0).any():
        return False

    if (
        df["high"] < df[["open", "close"]].max(axis=1)
    ).any():
        return False

    if (
        df["low"] > df[["open", "close"]].min(axis=1)
    ).any():
        return False

    if "close_time" in df.columns:
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)

        if (pd.to_numeric(df["close_time"], errors="coerce") >= now_ms).any():
            return False

    return True


def _ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    return result


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))

    result = 100 - (100 / (1 + rs))

    result = result.mask(
        (avg_loss == 0) & (avg_gain > 0),
        100.0,
    )

    result = result.mask(
        (avg_gain == 0) & (avg_loss > 0),
        0.0,
    )

    result = result.mask(
        (avg_gain == 0) & (avg_loss == 0),
        50.0,
    )

    return result


def _macd(series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    fast = _ema(series, 12)
    slow = _ema(series, 26)

    line = fast - slow
    signal = _ema(line, 9)
    histogram = line - signal

    return line, signal, histogram


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = df["close"].shift(1)

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_diff = df["high"].diff()
    low_diff = -df["low"].diff()

    plus_dm = high_diff.where(
        (high_diff > low_diff) & (high_diff > 0),
        0.0,
    )

    minus_dm = low_diff.where(
        (low_diff > high_diff) & (low_diff > 0),
        0.0,
    )

    atr = _atr(df, period).replace(0, float("nan"))

    plus_di = (
        100 * plus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean() / atr
    )

    minus_di = (
        100 * minus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean() / atr
    )

    denominator = (plus_di + minus_di).replace(
        0,
        float("nan"),
    )

    dx = (
        100 * (plus_di - minus_di).abs() / denominator
    )

    return dx.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = df["close"].diff().apply(
        lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    )

    return (direction * df["volume"]).cumsum()


def _vwap(df: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (
        df["high"] + df["low"] + df["close"]
    ) / 3.0

    numerator = (typical * df["volume"]).rolling(
        period,
        min_periods=period,
    ).sum()

    denominator = df["volume"].rolling(
        period,
        min_periods=period,
    ).sum()

    return numerator / denominator.replace(0, float("nan"))


def _bollinger(
    series: pd.Series,
    period: int = 20,
    deviation: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    middle = series.rolling(
        period,
        min_periods=period,
    ).mean()

    std = series.rolling(
        period,
        min_periods=period,
    ).std(ddof=0)

    upper = middle + deviation * std
    lower = middle - deviation * std

    return upper, middle, lower


def _calculate_snapshot(df: pd.DataFrame) -> Dict[str, Any]:
    data = _ohlcv(df)

    close = data["close"]

    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)

    rsi = _rsi(close)
    macd_line, macd_signal, macd_hist = _macd(close)

    atr = _atr(data)
    adx = _adx(data)

    rvol = (
        data["volume"].iloc[-1]
        / data["volume"].rolling(20).mean().iloc[-1]
        if _number(data["volume"].rolling(20).mean().iloc[-1])
        not in (None, 0)
        else None
    )

    obv = _obv(data)
    obv_change = (
        obv.iloc[-1] - obv.iloc[-6]
        if len(obv) >= 6
        else None
    )

    vwap = _vwap(data)
    bb_upper, bb_middle, bb_lower = _bollinger(close)

    roc = (
        (close.iloc[-1] / close.iloc[-10] - 1) * 100
        if len(close) >= 10 and close.iloc[-10] > 0
        else None
    )

    atr_value = _number(atr.iloc[-1])

    return {
        "close": _number(close.iloc[-1]),
        "previous_close": _number(close.iloc[-2]),
        "ema20": _number(ema20.iloc[-1]),
        "ema50": _number(ema50.iloc[-1]),
        "ema200": _number(ema200.iloc[-1]),
        "rsi": _number(rsi.iloc[-1]),
        "macd": _number(macd_line.iloc[-1]),
        "macd_signal": _number(macd_signal.iloc[-1]),
        "macd_hist": _number(macd_hist.iloc[-1]),
        "atr": atr_value,
        "atr_percent": (
            atr_value / close.iloc[-1] * 100
            if atr_value and close.iloc[-1] > 0
            else None
        ),
        "adx": _number(adx.iloc[-1]),
        "rvol": _number(rvol),
        "obv": _number(obv.iloc[-1]),
        "obv_change": _number(obv_change),
        "vwap": _number(vwap.iloc[-1]),
        "bb_upper": _number(bb_upper.iloc[-1]),
        "bb_middle": _number(bb_middle.iloc[-1]),
        "bb_lower": _number(bb_lower.iloc[-1]),
        "roc": _number(roc),
        "volume": _number(data["volume"].iloc[-1]),
    }


# ============================================================
# MARKET STRUCTURE
# ============================================================

def _market_structure(
    df: pd.DataFrame,
    lookback: int = 20,
) -> Dict[str, Any]:
    data = _ohlcv(df)

    if len(data) < lookback + 3:
        return {
            "valid": False,
            "higher_high": False,
            "higher_low": False,
            "bos_bullish": False,
            "choch_bullish": False,
            "support": None,
            "resistance": None,
        }

    previous = data.iloc[-lookback - 1:-1]
    latest = data.iloc[-1]

    prior_high = float(previous["high"].max())
    prior_low = float(previous["low"].min())

    higher_high = (
        float(latest["high"]) > prior_high
        and float(latest["close"]) > prior_high
    )

    recent_half = data.iloc[-10:-1]
    older_half = data.iloc[-20:-10]

    higher_low = (
        float(recent_half["low"].min())
        > float(older_half["low"].min())
    )

    previous_trend = (
        float(data["close"].iloc[-10])
        > float(data["close"].iloc[-20])
    )

    current_trend = (
        float(data["close"].iloc[-1])
        > float(data["close"].iloc[-10])
    )

    choch_bullish = not previous_trend and current_trend

    return {
        "valid": True,
        "higher_high": higher_high,
        "higher_low": higher_low,
        "bos_bullish": higher_high,
        "choch_bullish": choch_bullish,
        "support": prior_low,
        "resistance": prior_high,
    }


# ============================================================
# LAYER 1: BTC AND MARKET REGIME (15)
# ============================================================

def _btc_regime_score(
    market_context: Optional[Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    if not isinstance(market_context, dict):
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
            "regime": "UNKNOWN",
        }

    regime = str(
        market_context.get(
            "risk_level",
            market_context.get(
                "regime",
                market_context.get("market_regime", "UNKNOWN"),
            ),
        )
    ).upper()

    if "HIGH_RISK" in regime or "HIGH RISK" in regime:
        return 0.0, {
            "status": "VERIFIED",
            "score": 0.0,
            "regime": "HIGH_RISK",
            "hard_block": True,
        }

    if "STRONG_BULL" in regime:
        score = 15.0
    elif "BULL" in regime:
        score = 12.0
    elif "NEUTRAL" in regime:
        score = 8.0
    elif "BEAR" in regime:
        score = 4.0
    else:
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
            "regime": "UNKNOWN",
        }

    timeframes = market_context.get("timeframes", {})

    if isinstance(timeframes, dict):
        verified_count = sum(
            1 for tf in BTC_TIMEFRAMES
            if isinstance(timeframes.get(tf), dict)
            and timeframes[tf].get("valid", False)
        )
    else:
        verified_count = 0

    if verified_count < 3:
        score = min(score, 8.0)
        status = "PARTIALLY_VERIFIED"
    else:
        status = "VERIFIED"

    breadth = market_context.get(
        "market_breadth_analysis",
        {},
    )

    if isinstance(breadth, dict):
        breadth_status = str(
            breadth.get("status", "")
        ).upper()

        breadth_direction = str(
            breadth.get("direction", "")
        ).upper()

        if breadth_status == "VERIFIED":
            if breadth_direction in {"BULLISH", "POSITIVE"}:
                score = min(15.0, score + 1.0)
            elif breadth_direction in {"BEARISH", "NEGATIVE"}:
                score = max(0.0, score - 1.0)

    return score, {
        "status": status,
        "score": score,
        "regime": regime,
        "verified_btc_timeframes": verified_count,
    }


# ============================================================
# LAYER 2: TECHNICAL STRUCTURE (20)
# ============================================================

def _technical_score(
    snapshot: Dict[str, Any],
    structure: Dict[str, Any],
) -> Tuple[float, Dict[str, Any]]:
    score = 0.0
    details: Dict[str, Any] = {}

    close = snapshot["close"]
    ema20 = snapshot["ema20"]
    ema50 = snapshot["ema50"]
    ema200 = snapshot["ema200"]

    # EMA alignment: 5 points.
    if all(x is not None for x in (close, ema20, ema50, ema200)):
        if close > ema20 > ema50 > ema200:
            ema_score = 5.0
        elif close > ema20 and ema20 > ema50:
            ema_score = 3.5
        elif close > ema50:
            ema_score = 2.5
        elif close > ema200:
            ema_score = 1.5
        else:
            ema_score = 0.0
    else:
        ema_score = 0.0

    score += ema_score
    details["ema_alignment"] = ema_score

    # RSI: 3 points.
    rsi = snapshot["rsi"]

    if rsi is None:
        rsi_score = 0.0
    elif 52 <= rsi <= 68:
        rsi_score = 3.0
    elif 48 <= rsi < 52 or 68 < rsi <= 72:
        rsi_score = 2.0
    elif 40 <= rsi < 48:
        rsi_score = 1.0
    else:
        rsi_score = 0.0

    score += rsi_score
    details["rsi"] = rsi_score

    # MACD histogram: 3 points.
    histogram = snapshot["macd_hist"]

    macd_score = (
        3.0 if histogram is not None and histogram > 0
        else 0.0
    )

    score += macd_score
    details["macd"] = macd_score

    # ADX: 3 points.
    adx = snapshot["adx"]

    if adx is None:
        adx_score = 0.0
    elif adx >= 25:
        adx_score = 3.0
    elif adx >= 20:
        adx_score = 2.0
    elif adx >= 18:
        adx_score = 1.0
    else:
        adx_score = 0.0

    score += adx_score
    details["adx"] = adx_score

    # Market structure: 4 points.
    structure_score = 0.0

    if structure.get("higher_high"):
        structure_score += 1.5

    if structure.get("higher_low"):
        structure_score += 1.5

    if structure.get("bos_bullish"):
        structure_score += 0.5

    if structure.get("choch_bullish"):
        structure_score += 0.5

    structure_score = min(4.0, structure_score)

    score += structure_score
    details["market_structure"] = structure_score

    # Bollinger: 2 points.
    upper = snapshot["bb_upper"]
    middle = snapshot["bb_middle"]
    lower = snapshot["bb_lower"]

    if close is not None and upper is not None and middle is not None:
        if middle <= close < upper:
            bb_score = 2.0
        elif lower is not None and lower <= close < middle:
            bb_score = 1.0
        else:
            bb_score = 0.0
    else:
        bb_score = 0.0

    score += bb_score
    details["bollinger"] = bb_score

    return min(20.0, score), details


# ============================================================
# LAYER 3: VOLUME AND MOMENTUM (15)
# ============================================================

def _volume_score(
    snapshot: Dict[str, Any],
) -> Tuple[float, Dict[str, Any]]:
    score = 0.0
    details = {}

    # Relative volume: 5 points.
    rvol = snapshot["rvol"]

    if rvol is None:
        rvol_score = 0.0
    elif rvol >= 2.0:
        rvol_score = 5.0
    elif rvol >= 1.5:
        rvol_score = 4.0
    elif rvol >= 1.2:
        rvol_score = 3.0
    elif rvol >= 1.0:
        rvol_score = 1.5
    else:
        rvol_score = 0.0

    score += rvol_score
    details["rvol"] = rvol_score

    # OBV direction: 4 points.
    obv_change = snapshot["obv_change"]

    obv_score = (
        4.0 if obv_change is not None and obv_change > 0
        else 0.0
    )

    score += obv_score
    details["obv"] = obv_score

    # Volume expansion: 3 points.
    volume_score = 0.0

    if rvol is not None:
        if rvol >= 1.5:
            volume_score = 3.0
        elif rvol >= 1.2:
            volume_score = 2.0
        elif rvol >= 1.0:
            volume_score = 1.0

    score += volume_score
    details["volume_expansion"] = volume_score

    # Rate of change: 3 points.
    roc = snapshot["roc"]

    if roc is None:
        roc_score = 0.0
    elif roc > 0 and roc <= 5:
        roc_score = 3.0
    elif roc > 5 and roc <= 8:
        roc_score = 2.0
    elif roc > 8:
        roc_score = 1.0
    else:
        roc_score = 0.0

    score += roc_score
    details["roc"] = roc_score

    return min(15.0, score), details


# ============================================================
# LAYER 4: LIQUIDITY AND ORDER FLOW (15)
# ============================================================

def _liquidity_score(
    market_context: Optional[Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    context = market_context or {}

    liquidity = context.get(
        "liquidity",
        context.get("order_book_analysis", {}),
    )

    if not isinstance(liquidity, dict):
        liquidity = {}

    score = 0.0
    details: Dict[str, Any] = {}

    spread = _number(
        liquidity.get(
            "spread_percent",
            context.get("spread_percent"),
        )
    )

    if spread is None:
        spread_score = 0.0
    elif spread <= 0.03:
        spread_score = 3.0
    elif spread <= 0.06:
        spread_score = 2.5
    elif spread <= 0.10:
        spread_score = 2.0
    elif spread <= 0.15:
        spread_score = 1.0
    else:
        spread_score = 0.0

    score += spread_score
    details["spread"] = spread_score

    imbalance = _number(
        liquidity.get(
            "imbalance",
            liquidity.get("order_book_imbalance"),
        )
    )

    if imbalance is None:
        imbalance_score = 0.0
    elif imbalance >= 0.30:
        imbalance_score = 4.0
    elif imbalance >= 0.15:
        imbalance_score = 3.0
    elif imbalance > 0:
        imbalance_score = 2.0
    else:
        imbalance_score = 0.0

    score += imbalance_score
    details["order_book_imbalance"] = imbalance_score

    depth = _number(
        liquidity.get(
            "minimum_side_depth_usdt",
            liquidity.get("total_depth_usdt"),
        )
    )

    if depth is None:
        depth_score = 0.0
    elif depth >= 500_000:
        depth_score = 3.0
    elif depth >= 100_000:
        depth_score = 2.5
    elif depth >= 50_000:
        depth_score = 2.0
    elif depth >= 10_000:
        depth_score = 1.0
    else:
        depth_score = 0.0

    score += depth_score
    details["depth"] = depth_score

    trade_flow = _number(
        liquidity.get(
            "trade_flow",
            liquidity.get("cvd_proxy"),
        )
    )

    if trade_flow is None:
        flow_score = 0.0
    elif trade_flow > 0.30:
        flow_score = 3.0
    elif trade_flow > 0.10:
        flow_score = 2.0
    elif trade_flow > 0:
        flow_score = 1.0
    else:
        flow_score = 0.0

    score += flow_score
    details["trade_flow"] = flow_score

    slippage = _number(
        liquidity.get(
            "buy_slippage_percent",
            liquidity.get("slippage_percent"),
        )
    )

    if slippage is None:
        slippage_score = 0.0
    elif slippage <= 0.02:
        slippage_score = 2.0
    elif slippage <= 0.05:
        slippage_score = 1.5
    elif slippage <= 0.10:
        slippage_score = 1.0
    else:
        slippage_score = 0.0

    score += slippage_score
    details["slippage"] = slippage_score

    details["spread_percent"] = spread
    details["imbalance"] = imbalance
    details["minimum_side_depth_usdt"] = depth
    details["buy_slippage_percent"] = slippage

    return min(15.0, score), details


# ============================================================
# LAYER 5: ENTRY QUALITY (15)
# ============================================================

def _entry_quality_score(
    df: pd.DataFrame,
    snapshot: Dict[str, Any],
    structure: Dict[str, Any],
    breakout_data: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    score = 0.0
    details: Dict[str, Any] = {}

    close = snapshot["close"]
    atr = snapshot["atr"]

    support = structure.get("support")
    resistance = structure.get("resistance")

    if close is None or atr is None or atr <= 0:
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
        }

    # Support / resistance context: 4 points.
    sr_score = 0.0

    if support is not None and support < close:
        distance = (close - support) / atr

        if distance <= 1.0:
            sr_score = 4.0
        elif distance <= 2.0:
            sr_score = 3.0
        elif distance <= 3.0:
            sr_score = 2.0
        else:
            sr_score = 1.0

    score += sr_score
    details["support_resistance"] = sr_score

    # Breakout confirmation: 3 points.
    breakout = breakout_data or {}

    breakout_confirmed = bool(
        breakout.get("confirmed", False)
    )

    if not breakout_confirmed and len(df) >= 22:
        previous_high = float(
            df["high"].iloc[-21:-1].max()
        )

        breakout_confirmed = (
            close > previous_high
            and float(df["volume"].iloc[-1])
            > float(df["volume"].iloc[-21:-1].mean()) * 1.2
        )

    breakout_score = 3.0 if breakout_confirmed else 0.0

    score += breakout_score
    details["breakout"] = breakout_score

    # Retest: 3 points.
    retest_confirmed = bool(
        breakout.get("retest_confirmed", False)
    )

    retest_score = 3.0 if retest_confirmed else 0.0

    score += retest_score
    details["retest"] = retest_score

    # VWAP: 2 points.
    vwap = snapshot["vwap"]

    if vwap is None:
        vwap_score = 0.0
    elif close > vwap:
        vwap_score = 2.0
    else:
        vwap_score = 0.0

    score += vwap_score
    details["vwap"] = vwap_score

    # ATR entry distance: 3 points.
    ema20 = snapshot["ema20"]

    if ema20 is None:
        entry_distance_score = 0.0
        entry_distance_atr = None
    else:
        entry_distance_atr = abs(close - ema20) / atr

        if entry_distance_atr <= 0.5:
            entry_distance_score = 3.0
        elif entry_distance_atr <= 1.0:
            entry_distance_score = 2.0
        elif entry_distance_atr <= 1.5:
            entry_distance_score = 1.0
        else:
            entry_distance_score = 0.0

    score += entry_distance_score

    details["atr_entry_distance"] = entry_distance_score
    details["entry_distance_atr"] = entry_distance_atr
    details["support"] = support
    details["resistance"] = resistance

    return min(15.0, score), details


# ============================================================
# LAYER 6: RISK AND REWARD (10)
# ============================================================

def _risk_score(
    risk_plan: Dict[str, Any],
) -> Tuple[float, Dict[str, Any]]:
    if not isinstance(risk_plan, dict):
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
        }

    if not risk_plan.get("valid", False):
        return 0.0, {
            "status": "INVALID",
            "score": 0.0,
            "reason": risk_plan.get("reason"),
        }

    score = 0.0
    details = {}

    # ATR Stop Loss: 3 points.
    stop = _number(risk_plan.get("stop_loss"))
    entry = _number(risk_plan.get("entry"))
    risk_distance = _number(risk_plan.get("risk_distance_pct"))

    if (
        stop is not None
        and entry is not None
        and stop < entry
        and risk_distance is not None
    ):
        if 0.5 <= risk_distance <= 3.0:
            sl_score = 3.0
        elif risk_distance <= 5.0:
            sl_score = 2.0
        else:
            sl_score = 0.0
    else:
        sl_score = 0.0

    score += sl_score
    details["atr_stop"] = sl_score

    # Net R:R: 4 points.
    t1_check = risk_plan.get(
        "target_checks",
        {},
    ).get("t1", {})

    net_rr = _number(t1_check.get("net_rr"))

    if net_rr is None:
        rr_score = 0.0
    elif net_rr >= 2.0:
        rr_score = 4.0
    elif net_rr >= 1.5:
        rr_score = 3.0
    elif net_rr >= 1.2:
        rr_score = 2.0
    else:
        rr_score = 0.0

    score += rr_score
    details["net_rr"] = rr_score

    # Position sizing: 2 points.
    position = risk_plan.get("position", {})

    if (
        isinstance(position, dict)
        and position.get("valid")
        and position.get("estimated_loss_within_budget")
    ):
        position_score = 2.0
    else:
        position_score = 0.0

    score += position_score
    details["position_sizing"] = position_score

    # Fee and slippage: 1 point.
    cost = _number(risk_plan.get("execution_cost_pct"))

    if cost is None:
        cost_score = 0.0
    elif cost <= 0.15:
        cost_score = 1.0
    else:
        cost_score = 0.0

    score += cost_score
    details["execution_cost"] = cost_score

    details["net_rr_value"] = net_rr
    details["risk_distance_pct"] = risk_distance

    return min(10.0, score), details


# ============================================================
# LAYER 7: FUNDAMENTAL AND ON-CHAIN (10)
# ============================================================

def _fundamental_score(
    fundamental_data: Optional[Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    """
    Missing data earns zero points and is marked UNVERIFIED.

    No fabricated fundamental or on-chain values are permitted.
    """
    if not isinstance(fundamental_data, dict):
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
            "unverified_categories": [
                "token_supply",
                "market_cap_fdv",
                "exchange_flows",
                "holder_concentration",
                "security_development",
            ],
        }

    score = 0.0
    details = {}

    categories = {
        "token_supply": 2.0,
        "market_cap_fdv": 2.0,
        "exchange_flows": 2.0,
        "holder_concentration": 2.0,
        "security_development": 2.0,
    }

    unverified = []

    for category, maximum in categories.items():
        item = fundamental_data.get(category)

        if not isinstance(item, dict):
            unverified.append(category)
            details[category] = {
                "status": "UNVERIFIED",
                "score": 0.0,
            }
            continue

        status = str(item.get("status", "")).upper()

        if status not in {"VERIFIED", "CONFIRMED"}:
            unverified.append(category)
            details[category] = {
                "status": "UNVERIFIED",
                "score": 0.0,
            }
            continue

        value = _number(item.get("score"))

        if value is None:
            unverified.append(category)
            details[category] = {
                "status": "UNVERIFIED",
                "score": 0.0,
            }
            continue

        category_score = _clamp(value, 0.0, maximum)
        score += category_score

        details[category] = {
            "status": "VERIFIED",
            "score": category_score,
        }

    return min(10.0, score), {
        "status": "VERIFIED" if not unverified else "PARTIAL",
        "score": score,
        "categories": details,
        "unverified_categories": unverified,
    }


# ============================================================
# HARD GATES
# ============================================================

def _hard_gate_checks(
    snapshot: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
    liquidity_details: Dict[str, Any],
    entry_details: Dict[str, Any],
    risk_plan: Dict[str, Any],
) -> Dict[str, Any]:
    failures = []

    context = market_context or {}

    # BTC High Risk.
    regime = str(
        context.get(
            "risk_level",
            context.get("regime", ""),
        )
    ).upper()

    if "HIGH_RISK" in regime or "HIGH RISK" in regime:
        failures.append("BTC_HIGH_RISK")

    if context.get("allow_new_buy") is False:
        failures.append("BTC_BUY_BLOCKED")

    # Required technical data.
    if snapshot.get("close") is None:
        failures.append("INVALID_PRICE")

    if snapshot.get("atr") is None or snapshot["atr"] <= 0:
        failures.append("INVALID_ATR")

    # Liquidity gates.
    spread = liquidity_details.get("spread_percent")

    if spread is None:
        failures.append("SPREAD_UNVERIFIED")
    elif spread > DEFAULT_MAX_SPREAD_PERCENT:
        failures.append("SPREAD_LIMIT_EXCEEDED")

    depth = liquidity_details.get("minimum_side_depth_usdt")

    if depth is None:
        failures.append("ORDER_BOOK_DEPTH_UNVERIFIED")
    elif depth < DEFAULT_MIN_DEPTH_USDT:
        failures.append("INSUFFICIENT_ORDER_BOOK_DEPTH")

    slippage = liquidity_details.get("buy_slippage_percent")

    if slippage is None:
        failures.append("SLIPPAGE_UNVERIFIED")
    elif slippage > DEFAULT_MAX_SLIPPAGE_PERCENT:
        failures.append("SLIPPAGE_LIMIT_EXCEEDED")

    # Overextended entry.
    distance = entry_details.get("entry_distance_atr")

    if distance is None:
        failures.append("ENTRY_DISTANCE_UNVERIFIED")
    elif distance > DEFAULT_MAX_ENTRY_DISTANCE_ATR:
        failures.append("ENTRY_OVEREXTENDED")

    # Risk plan.
    if not risk_plan.get("valid", False):
        failures.append(
            "INVALID_RISK_PLAN:" + str(risk_plan.get("reason"))
        )

    return {
        "passed": len(failures) == 0,
        "failures": failures,
    }


# ============================================================
# MULTI-TIMEFRAME CONFIRMATION
# ============================================================

def _timeframe_confirmation(
    entry_snapshot: Dict[str, Any],
    confirmation_snapshot: Dict[str, Any],
    structure_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Three timeframe checks.

    Correlated timeframes are not counted as independent statistical
    confirmations. They are directional alignment checks only.
    """
    def bullish(snapshot: Dict[str, Any]) -> bool:
        close = snapshot.get("close")
        ema20 = snapshot.get("ema20")
        ema50 = snapshot.get("ema50")
        macd_hist = snapshot.get("macd_hist")

        return (
            close is not None
            and ema20 is not None
            and ema50 is not None
            and macd_hist is not None
            and close > ema20
            and ema20 > ema50
            and macd_hist > 0
        )

    entry_bullish = bullish(entry_snapshot)
    confirmation_bullish = bullish(confirmation_snapshot)
    structure_bullish = bullish(structure_snapshot)

    aligned = sum(
        (
            entry_bullish,
            confirmation_bullish,
            structure_bullish,
        )
    )

    return {
        "entry_bullish": entry_bullish,
        "confirmation_bullish": confirmation_bullish,
        "structure_bullish": structure_bullish,
        "aligned_timeframes": aligned,
        "total_timeframes": 3,
        "confirmed": (
            entry_bullish
            and confirmation_bullish
            and structure_bullish
        ),
        "interpretation": (
            "ALL_ALIGNED" if aligned == 3
            else "PARTIAL_ALIGNMENT" if aligned == 2
            else "WEAK_ALIGNMENT"
        ),
        "statistical_independence": False,
    }


# ============================================================
# MAIN ENGINE
# ============================================================

def score_setup(
    trigger_df: pd.DataFrame,
    confirm_frames: Optional[Dict[str, pd.DataFrame]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    strategy: str = "SCALP",
    breakout_data: Optional[Dict[str, Any]] = None,
    fundamental_data: Optional[Dict[str, Any]] = None,
    capital_usdt: float = 100.0,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Score a candidate using seven layers.

    Returns a complete analysis dictionary.
    It does not send Telegram messages.
    """
    strategy = str(strategy or "SCALP").upper()

    if strategy not in TIMEFRAME_MAP:
        return {
            "valid": False,
            "decision": "REJECT",
            "reason": "INVALID_STRATEGY",
            "strategy": strategy,
            "formula_version": FORMULA_VERSION,
        }

    frames = confirm_frames or {}
    mapping = TIMEFRAME_MAP[strategy]

    entry_df = trigger_df
    confirmation_df = frames.get(mapping["confirmation"])
    structure_df = frames.get(mapping["structure"])

    required_frames = {
        mapping["entry"]: entry_df,
        mapping["confirmation"]: confirmation_df,
        mapping["structure"]: structure_df,
    }

    invalid_frames = [
        timeframe
        for timeframe, frame in required_frames.items()
        if not _valid_frame(frame)
    ]

    if invalid_frames:
        return {
            "valid": False,
            "decision": "WAIT",
            "reason": "INVALID_OR_INSUFFICIENT_TIMEFRAME_DATA",
            "invalid_timeframes": invalid_frames,
            "strategy": strategy,
            "symbol": symbol,
            "formula_version": FORMULA_VERSION,
        }

    entry_df = _ohlcv(entry_df)
    confirmation_df = _ohlcv(confirmation_df)
    structure_df = _ohlcv(structure_df)

    entry_snapshot = _calculate_snapshot(entry_df)
    confirmation_snapshot = _calculate_snapshot(confirmation_df)
    structure_snapshot = _calculate_snapshot(structure_df)

    structure = _market_structure(structure_df)

    # Multi-timeframe confirmation.
    mtf = _timeframe_confirmation(
        entry_snapshot,
        confirmation_snapshot,
        structure_snapshot,
    )

    # Layer 1.
    layer1, btc_details = _btc_regime_score(market_context)

    # Layer 2.
    layer2, technical_details = _technical_score(
        entry_snapshot,
        structure,
    )

    # Layer 3.
    layer3, volume_details = _volume_score(entry_snapshot)

    # Layer 4.
    layer4, liquidity_details = _liquidity_score(market_context)

    # Layer 5.
    layer5, entry_details = _entry_quality_score(
        entry_df,
        entry_snapshot,
        structure,
        breakout_data,
    )

    # Risk plan.
    risk_plan = build_risk_plan(
        entry_price=entry_snapshot["close"],
        atr=entry_snapshot["atr"],
        capital_usdt=capital_usdt,
        support=structure.get("support"),
        resistances=(
            [structure["resistance"]]
            if structure.get("resistance") is not None
            else None
        ),
    )

    # Layer 6.
    layer6, risk_details = _risk_score(risk_plan)

    # Layer 7.
    layer7, fundamental_details = _fundamental_score(
        fundamental_data
    )

    layers = {
        "btc_market_regime": {
            "weight": 15,
            "score": layer1,
            "details": btc_details,
        },
        "technical_structure": {
            "weight": 20,
            "score": layer2,
            "details": technical_details,
        },
        "volume_momentum": {
            "weight": 15,
            "score": layer3,
            "details": volume_details,
        },
        "liquidity_order_flow": {
            "weight": 15,
            "score": layer4,
            "details": liquidity_details,
        },
        "entry_quality": {
            "weight": 15,
            "score": layer5,
            "details": entry_details,
        },
        "risk_reward": {
            "weight": 10,
            "score": layer6,
            "details": risk_details,
        },
        "fundamental_onchain": {
            "weight": 10,
            "score": layer7,
            "details": fundamental_details,
        },
    }

    raw_score = sum(
        item["score"] for item in layers.values()
    )

    # MTF is a confirmation requirement, not an additional layer.
    if mtf["aligned_timeframes"] == 2:
        mtf_adjustment = -3.0
    elif mtf["aligned_timeframes"] <= 1:
        mtf_adjustment = -8.0
    else:
        mtf_adjustment = 0.0

    final_score = _clamp(
        raw_score + mtf_adjustment,
        0.0,
        100.0,
    )

    hard_gates = _hard_gate_checks(
        entry_snapshot,
        market_context,
        liquidity_details,
        entry_details,
        risk_plan,
    )

    if not hard_gates["passed"]:
        classification = "REJECT"
        decision = "WAIT"
    elif final_score >= DEFAULT_EXCELLENT_SCORE:
        classification = "EXCELLENT BUY"
        decision = "BUY"
    elif final_score >= DEFAULT_MIN_SIGNAL_SCORE:
        classification = "STRONG BUY"
        decision = "BUY"
    elif final_score >= CLASSIFICATIONS["WATCHLIST"]:
        classification = "WATCHLIST"
        decision = "WAIT"
    elif final_score >= CLASSIFICATIONS["WAIT"]:
        classification = "WAIT"
        decision = "WAIT"
    else:
        classification = "REJECT"
        decision = "WAIT"

    return {
        "valid": hard_gates["passed"],
        "symbol": symbol,
        "strategy": strategy,
        "timeframes": mapping,
        "decision": decision,
        "classification": classification,
        "score": round(final_score, 2),
        "raw_layer_score": round(raw_score, 2),
        "mtf_adjustment": mtf_adjustment,
        "score_is_win_probability": False,
        "formula_version": FORMULA_VERSION,
        "code_version": CODE_VERSION,
        "layers": layers,
        "mtf_confirmation": mtf,
        "hard_gates": hard_gates,
        "entry": {
            "price": entry_snapshot["close"],
            "atr": entry_snapshot["atr"],
            "atr_percent": entry_snapshot["atr_percent"],
            "rsi": entry_snapshot["rsi"],
            "adx": entry_snapshot["adx"],
            "rvol": entry_snapshot["rvol"],
            "ema20": entry_snapshot["ema20"],
            "ema50": entry_snapshot["ema50"],
            "ema200": entry_snapshot["ema200"],
        },
        "structure": structure,
        "risk_plan": risk_plan,
        "fundamental_status": fundamental_details["status"],
        "created_at": pd.Timestamp.now(
            tz="UTC"
        ).isoformat(),
    }


# ============================================================
# ENTRY VALIDATION
# ============================================================

def validate_entry(
    trigger_df: pd.DataFrame,
    confirm_frames: Optional[Dict[str, pd.DataFrame]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    strategy: str = "SCALP",
    breakout_data: Optional[Dict[str, Any]] = None,
    fundamental_data: Optional[Dict[str, Any]] = None,
    capital_usdt: float = 100.0,
) -> Dict[str, Any]:
    result = score_setup(
        trigger_df=trigger_df,
        confirm_frames=confirm_frames,
        market_context=market_context,
        strategy=strategy,
        breakout_data=breakout_data,
        fundamental_data=fundamental_data,
        capital_usdt=capital_usdt,
    )

    if not result.get("valid"):
        result["entry_valid"] = False
        return result

    if result.get("decision") != "BUY":
        result["entry_valid"] = False
        return result

    result["entry_valid"] = True
    return result


# ============================================================
# STRATEGY WRAPPERS
# ============================================================

def evaluate_scalp(
    trigger_df: pd.DataFrame,
    confirm_frames: Optional[Dict[str, pd.DataFrame]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    breakout_data: Optional[Dict[str, Any]] = None,
    fundamental_data: Optional[Dict[str, Any]] = None,
    capital_usdt: float = 100.0,
) -> Dict[str, Any]:
    return score_setup(
        trigger_df=trigger_df,
        confirm_frames=confirm_frames,
        market_context=market_context,
        strategy="SCALP",
        breakout_data=breakout_data,
        fundamental_data=fundamental_data,
        capital_usdt=capital_usdt,
    )


def evaluate_swing(
    trigger_df: pd.DataFrame,
    confirm_frames: Optional[Dict[str, pd.DataFrame]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    breakout_data: Optional[Dict[str, Any]] = None,
    fundamental_data: Optional[Dict[str, Any]] = None,
    capital_usdt: float = 100.0,
) -> Dict[str, Any]:
    return score_setup(
        trigger_df=trigger_df,
        confirm_frames=confirm_frames,
        market_context=market_context,
        strategy="SWING",
        breakout_data=breakout_data,
        fundamental_data=fundamental_data,
        capital_usdt=capital_usdt,
    )


# ============================================================
# CONFIGURATION SNAPSHOT
# ============================================================

def get_entry_engine_config() -> Dict[str, Any]:
    return {
        "code_version": CODE_VERSION,
        "formula_version": FORMULA_VERSION,
        "layer_weights": LAYER_WEIGHTS.copy(),
        "total_layer_weight": sum(LAYER_WEIGHTS.values()),
        "strategies": TIMEFRAME_MAP.copy(),
        "btc_timeframes": list(BTC_TIMEFRAMES),
        "minimum_signal_score": DEFAULT_MIN_SIGNAL_SCORE,
        "excellent_buy_score": DEFAULT_EXCELLENT_SCORE,
        "minimum_candles": DEFAULT_MIN_CANDLES,
        "spot_only": True,
        "score_is_win_probability": False,
    }


# ============================================================
# SELF-CHECK
# ============================================================

def self_check() -> bool:
    """Deterministic offline checks."""

    assert sum(LAYER_WEIGHTS.values()) == 100

    assert TIMEFRAME_MAP["SCALP"]["entry"] == "5m"
    assert TIMEFRAME_MAP["SCALP"]["confirmation"] == "15m"
    assert TIMEFRAME_MAP["SCALP"]["structure"] == "30m"

    assert TIMEFRAME_MAP["SWING"]["entry"] == "15m"
    assert TIMEFRAME_MAP["SWING"]["confirmation"] == "30m"
    assert TIMEFRAME_MAP["SWING"]["structure"] == "1h"

    # Generate deterministic synthetic OHLCV data.
    count = 260

    index = pd.RangeIndex(count)

    close = pd.Series(
        [100 + i * 0.08 + math.sin(i / 5) * 0.15 for i in range(count)],
        index=index,
    )

    df = pd.DataFrame({
        "open": close - 0.03,
        "high": close + 0.20,
        "low": close - 0.20,
        "close": close,
        "volume": [
            1000 + (i % 12) * 30
            for i in range(count)
        ],
    })

    snapshot = _calculate_snapshot(df)

    assert snapshot["close"] is not None
    assert snapshot["ema20"] is not None
    assert snapshot["ema50"] is not None
    assert snapshot["ema200"] is not None
    assert snapshot["atr"] is not None
    assert snapshot["rsi"] is not None

    structure = _market_structure(df)

    assert structure["valid"]

    # Incomplete timeframe data must not produce a BUY.
    incomplete = score_setup(
        trigger_df=df.tail(100).copy(),
        confirm_frames={},
        market_context={},
        strategy="SCALP",
    )

    assert incomplete["decision"] == "WAIT"
    assert not incomplete["valid"]

    return True


if __name__ == "__main__":
    try:
        self_check()

        print("ENTRY ENGINE SELF-CHECK: PASS")
        print("Seven-Layer Weights: 100")
        print("Multi-Timeframe Confirmation: ENABLED")
        print("BTC Market Context: ENABLED")
        print("ATR-Based Risk Integration: ENABLED")
        print("Spot Only: YES")

    except Exception as exc:
        print(f"ENTRY ENGINE SELF-CHECK: FAIL - {exc}")
        raise
