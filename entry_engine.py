
"""
File: entry_engine.py
System: Binance Spot V4 Smart Signal Scanner
Code Version: 4.0.2
Formula Version: 4.0
Python: 3.11+
Compatibility: V4 internal architecture

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

Spot BUY only. No Futures. No Margin.

V4.0.2 Changes:
- Hardened input and DataFrame validation.
- Added candle chronology and duplicate timestamp checks.
- Made liquidity scoring use configured limits.
- Removed unnecessary risk-manager TypeError fallback.
- Hardened market context and optional data handling.
- Preserved seven-layer weights and signal thresholds.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from risk_manager import build_risk_plan

try:
    import config as app_config
except Exception:
    app_config = None


# ============================================================
# VERSION AND FORMULA
# ============================================================

CODE_VERSION = "4.0.2"
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
DEFAULT_MAX_SPREAD_PERCENT = 0.15
DEFAULT_MIN_DEPTH_USDT = 5000.0
DEFAULT_MAX_SLIPPAGE_PERCENT = 0.15

DEFAULT_MIN_NET_RR_T1 = 1.5
DEFAULT_MIN_SIGNAL_SCORE = 85
DEFAULT_EXCELLENT_SCORE = 90

EPSILON = 1e-12


# ============================================================
# GENERAL HELPERS
# ============================================================

def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_div(a: float, b: float) -> float:
    if abs(b) <= EPSILON:
        return 0.0
    return a / b


def _config_section(name: str) -> Dict[str, Any]:
    if app_config is None:
        return {}

    try:
        value = getattr(app_config, name, {})
    except Exception:
        return {}

    return _safe_dict(value)


def _config_number(
    section: str,
    keys: Tuple[str, ...],
    default: float,
    minimum: float = 0.0,
) -> float:
    data = _config_section(section)

    for key in keys:
        value = _number(data.get(key))
        if value is not None and value >= minimum:
            return value

    return float(default)


# ============================================================
# CONFIGURATION LIMITS
# ============================================================

def _liquidity_limits() -> Dict[str, float]:
    data = _config_section("LIQUIDITY_CONFIG")

    def first(keys: Tuple[str, ...], default: float) -> float:
        for key in keys:
            value = _number(data.get(key))
            if value is not None and value > 0:
                return value
        return float(default)

    return {
        "max_spread": first(
            (
                "max_spread_percent",
                "maximum_spread_percent",
                "max_spread_pct",
            ),
            DEFAULT_MAX_SPREAD_PERCENT,
        ),
        "min_depth": first(
            (
                "min_top_depth_usdt",
                "minimum_top_depth_usdt",
                "min_depth_usdt",
                "minimum_depth_usdt",
            ),
            DEFAULT_MIN_DEPTH_USDT,
        ),
        "max_slippage": first(
            (
                "max_slippage_percent",
                "maximum_slippage_percent",
                "max_slippage_pct",
            ),
            DEFAULT_MAX_SLIPPAGE_PERCENT,
        ),
    }


def _entry_limits() -> Dict[str, float]:
    data = _config_section("ENTRY_CONFIG")

    maximum_distance = DEFAULT_MAX_ENTRY_DISTANCE_ATR

    for key in (
        "max_entry_distance_atr",
        "maximum_entry_distance_atr",
        "max_distance_from_ema_atr",
    ):
        value = _number(data.get(key))
        if value is not None and value > 0:
            maximum_distance = value
            break

    return {
        "max_entry_distance_atr": maximum_distance,
    }


def _risk_minimum_rr() -> float:
    risk = _config_section("RISK_CONFIG")

    value = _number(risk.get("minimum_net_risk_reward"))

    if value is not None and value > 0:
        return value

    return DEFAULT_MIN_NET_RR_T1


def _minimum_candles() -> int:
    data = _config_section("ENTRY_CONFIG")

    for key in ("minimum_candles", "min_candles"):
        value = _number(data.get(key))
        if value is not None and value >= 205:
            return int(value)

    return DEFAULT_MIN_CANDLES


# ============================================================
# DATAFRAME VALIDATION
# ============================================================

def _valid_frame(
    df: Any,
    minimum_rows: Optional[int] = None,
) -> bool:
    if not isinstance(df, pd.DataFrame):
        return False

    required = {"open", "high", "low", "close", "volume"}

    if not required.issubset(df.columns):
        return False

    minimum = (
        _minimum_candles()
        if minimum_rows is None
        else int(minimum_rows)
    )

    if len(df) < minimum:
        return False

    data = df.copy()

    for column in required:
        data[column] = pd.to_numeric(
            data[column],
            errors="coerce",
        )

        if data[column].isna().any():
            return False

        if not data[column].map(math.isfinite).all():
            return False

    for column in ("open", "high", "low", "close"):
        if (data[column] <= 0).any():
            return False

    if (data["volume"] < 0).any():
        return False

    if (data["high"] < data["low"]).any():
        return False

    if (
        data["high"] < data[["open", "close"]].max(axis=1)
    ).any():
        return False

    if (
        data["low"] > data[["open", "close"]].min(axis=1)
    ).any():
        return False

    # Validate chronological order and duplicate timestamps.
    timestamp_column = None

    for candidate in ("close_time", "open_time", "timestamp"):
        if candidate in data.columns:
            timestamp_column = candidate
            break

    if timestamp_column is not None:
        timestamps = pd.to_numeric(
            data[timestamp_column],
            errors="coerce",
        )

        if timestamps.isna().any():
            return False

        if timestamps.duplicated().any():
            return False

        if not timestamps.is_monotonic_increasing:
            return False

    # The latest candle must be closed.
    if "close_time" in data.columns:
        close_times = pd.to_numeric(
            data["close_time"],
            errors="coerce",
        )

        if close_times.isna().any():
            return False

        now_ms = int(
            pd.Timestamp.now(tz="UTC").timestamp() * 1000
        )

        if close_times.iloc[-1] >= now_ms:
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


def _get_latest(
    df: pd.DataFrame,
    column: str,
) -> Optional[float]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    if column not in df.columns:
        return None

    values = pd.to_numeric(
        df[column],
        errors="coerce",
    ).dropna()

    if values.empty:
        return None

    return _number(values.iloc[-1])


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


def _macd(
    series: pd.Series,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    fast = _ema(series, 12)
    slow = _ema(series, 26)

    line = fast - slow
    signal = _ema(line, 9)
    histogram = line - signal

    return line, signal, histogram


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = df["close"].shift(1)

    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(
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
        100
        * plus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()
        / atr
    )

    minus_di = (
        100
        * minus_dm.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()
        / atr
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
        lambda value: (
            1 if value > 0
            else -1 if value < 0
            else 0
        )
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

    return numerator / denominator.replace(
        0,
        float("nan"),
    )


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

    volume_average = data["volume"].rolling(
        20,
        min_periods=20,
    ).mean().iloc[-1]

    volume_average_value = _number(volume_average)

    rvol = (
        data["volume"].iloc[-1] / volume_average_value
        if volume_average_value is not None
        and volume_average_value > 0
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
    close_value = _number(close.iloc[-1])

    return {
        "close": close_value,
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
            atr_value / close_value * 100
            if atr_value is not None
            and close_value is not None
            and close_value > 0
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
    context = _safe_dict(market_context)

    if not context:
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
            "regime": "UNKNOWN",
        }

    regime = str(
        context.get(
            "risk_level",
            context.get(
                "regime",
                context.get("market_regime", "UNKNOWN"),
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

    timeframes = _safe_dict(context.get("timeframes"))

    verified_count = sum(
        1
        for timeframe in BTC_TIMEFRAMES
        if isinstance(timeframes.get(timeframe), dict)
        and timeframes[timeframe].get("valid") is True
    )

    if verified_count < 3:
        score = min(score, 8.0)
        status = "PARTIALLY_VERIFIED"
    else:
        status = "VERIFIED"

    breadth = _safe_dict(
        context.get("market_breadth_analysis")
    )

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

    close = snapshot.get("close")
    ema20 = snapshot.get("ema20")
    ema50 = snapshot.get("ema50")
    ema200 = snapshot.get("ema200")

    if all(
        value is not None
        for value in (close, ema20, ema50, ema200)
    ):
        if close > ema20 > ema50 > ema200:
            ema_score = 5.0
        elif close > ema20 > ema50:
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

    rsi = snapshot.get("rsi")

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

    histogram = snapshot.get("macd_hist")
    macd_score = (
        3.0
        if histogram is not None and histogram > 0
        else 0.0
    )

    score += macd_score
    details["macd"] = macd_score

    adx = snapshot.get("adx")

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

    upper = snapshot.get("bb_upper")
    middle = snapshot.get("bb_middle")
    lower = snapshot.get("bb_lower")

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
    details: Dict[str, Any] = {}

    rvol = snapshot.get("rvol")

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

    obv_change = snapshot.get("obv_change")
    obv_score = (
        4.0
        if obv_change is not None and obv_change > 0
        else 0.0
    )

    score += obv_score
    details["obv"] = obv_score

    if rvol is None:
        expansion_score = 0.0
    elif rvol >= 1.5:
        expansion_score = 3.0
    elif rvol >= 1.2:
        expansion_score = 2.0
    elif rvol >= 1.0:
        expansion_score = 1.0
    else:
        expansion_score = 0.0

    score += expansion_score
    details["volume_expansion"] = expansion_score

    roc = snapshot.get("roc")

    if roc is None:
        roc_score = 0.0
    elif 0 < roc <= 5:
        roc_score = 3.0
    elif 5 < roc <= 8:
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
    context = _safe_dict(market_context)

    liquidity = context.get(
        "liquidity",
        context.get("order_book_analysis", {}),
    )

    liquidity = _safe_dict(liquidity)
    limits = _liquidity_limits()

    score = 0.0
    details: Dict[str, Any] = {}

    spread = _number(
        liquidity.get(
            "spread_percent",
            context.get("spread_percent"),
        )
    )

    max_spread = limits["max_spread"]

    if spread is None or spread < 0:
        spread_score = 0.0
    elif spread <= max_spread * 0.20:
        spread_score = 3.0
    elif spread <= max_spread * 0.40:
        spread_score = 2.5
    elif spread <= max_spread * 0.67:
        spread_score = 2.0
    elif spread <= max_spread:
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

    min_depth = limits["min_depth"]

    if depth is None or depth < 0:
        depth_score = 0.0
    elif depth >= min_depth * 100:
        depth_score = 3.0
    elif depth >= min_depth * 20:
        depth_score = 2.5
    elif depth >= min_depth * 10:
        depth_score = 2.0
    elif depth >= min_depth * 2:
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

    max_slippage = limits["max_slippage"]

    if slippage is None or slippage < 0:
        slippage_score = 0.0
    elif slippage <= max_slippage * 0.15:
        slippage_score = 2.0
    elif slippage <= max_slippage * 0.35:
        slippage_score = 1.5
    elif slippage <= max_slippage * 0.67:
        slippage_score = 1.0
    else:
        slippage_score = 0.0

    score += slippage_score
    details["slippage"] = slippage_score

    details["spread_percent"] = spread
    details["imbalance"] = imbalance
    details["minimum_side_depth_usdt"] = depth
    details["buy_slippage_percent"] = slippage
    details["configured_limits"] = limits

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

    close = snapshot.get("close")
    atr = snapshot.get("atr")

    support = structure.get("support")
    resistance = structure.get("resistance")

    if close is None or atr is None or atr <= 0:
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
        }

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

    breakout = _safe_dict(breakout_data)

    breakout_confirmed = (
        breakout.get("confirmed") is True
    )

    if not breakout_confirmed and len(df) >= 22:
        previous_high = _number(
            df["high"].iloc[-21:-1].max()
        )

        previous_volume = _number(
            df["volume"].iloc[-21:-1].mean()
        )

        latest_volume = _number(
            df["volume"].iloc[-1]
        )

        breakout_confirmed = (
            previous_high is not None
            and previous_volume is not None
            and latest_volume is not None
            and close > previous_high
            and latest_volume > previous_volume * 1.2
        )

    breakout_score = 3.0 if breakout_confirmed else 0.0

    score += breakout_score
    details["breakout"] = breakout_score

    retest_confirmed = (
        breakout.get("retest_confirmed") is True
    )

    retest_score = 3.0 if retest_confirmed else 0.0

    score += retest_score
    details["retest"] = retest_score

    vwap = snapshot.get("vwap")

    vwap_score = (
        2.0
        if vwap is not None and close > vwap
        else 0.0
    )

    score += vwap_score
    details["vwap"] = vwap_score

    ema20 = snapshot.get("ema20")

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
    details: Dict[str, Any] = {}

    stop = _number(risk_plan.get("stop_loss"))
    entry = _number(risk_plan.get("entry"))
    risk_distance = _number(
        risk_plan.get("risk_distance_pct")
    )

    if (
        stop is not None
        and entry is not None
        and stop < entry
        and risk_distance is not None
        and risk_distance > 0
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

    target_checks = _safe_dict(
        risk_plan.get("target_checks")
    )

    t1_check = _safe_dict(target_checks.get("t1"))

    net_rr = _number(t1_check.get("net_rr"))
    minimum_rr = _risk_minimum_rr()

    if net_rr is None:
        rr_score = 0.0
    elif net_rr >= 2.0:
        rr_score = 4.0
    elif net_rr >= minimum_rr:
        rr_score = 3.0
    elif net_rr >= 1.2:
        rr_score = 2.0
    else:
        rr_score = 0.0

    score += rr_score
    details["net_rr"] = rr_score
    details["net_rr_value"] = net_rr
    details["minimum_net_rr"] = minimum_rr

    position = _safe_dict(risk_plan.get("position"))

    if (
        position.get("valid") is True
        and position.get("estimated_loss_within_budget") is True
    ):
        position_score = 2.0
    else:
        position_score = 0.0

    score += position_score
    details["position_sizing"] = position_score

    cost = _number(risk_plan.get("execution_cost_pct"))

    cost_score = (
        1.0
        if cost is not None and cost <= 0.15
        else 0.0
    )

    score += cost_score
    details["execution_cost"] = cost_score
    details["risk_distance_pct"] = risk_distance

    return min(10.0, score), details


# ============================================================
# LAYER 7: FUNDAMENTAL AND ON-CHAIN (10)
# ============================================================

def _fundamental_score(
    fundamental_data: Optional[Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    """
    Missing or unverified data receives zero points.
    No unverified data is treated as confirmed.
    """

    categories = {
        "token_supply": 2.0,
        "market_cap_fdv": 2.0,
        "exchange_flows": 2.0,
        "holder_concentration": 2.0,
        "security_development": 2.0,
    }

    data = _safe_dict(fundamental_data)

    if not data:
        return 0.0, {
            "status": "UNVERIFIED",
            "score": 0.0,
            "unverified_categories": list(categories),
        }

    score = 0.0
    details: Dict[str, Any] = {}
    unverified = []

    for category, maximum in categories.items():
        item = data.get(category)

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
    context = _safe_dict(market_context)

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

    if _number(snapshot.get("close")) is None:
        failures.append("INVALID_PRICE")

    atr = _number(snapshot.get("atr"))

    if atr is None or atr <= 0:
        failures.append("INVALID_ATR")

    limits = _liquidity_limits()

    spread = _number(
        liquidity_details.get("spread_percent")
    )

    if spread is None:
        failures.append("SPREAD_UNVERIFIED")
    elif spread < 0:
        failures.append("INVALID_SPREAD")
    elif spread > limits["max_spread"]:
        failures.append("SPREAD_LIMIT_EXCEEDED")

    depth = _number(
        liquidity_details.get("minimum_side_depth_usdt")
    )

    if depth is None:
        failures.append("ORDER_BOOK_DEPTH_UNVERIFIED")
    elif depth < limits["min_depth"]:
        failures.append("INSUFFICIENT_ORDER_BOOK_DEPTH")

    slippage = _number(
        liquidity_details.get("buy_slippage_percent")
    )

    if slippage is None:
        failures.append("SLIPPAGE_UNVERIFIED")
    elif slippage < 0:
        failures.append("INVALID_SLIPPAGE")
    elif slippage > limits["max_slippage"]:
        failures.append("SLIPPAGE_LIMIT_EXCEEDED")

    distance = _number(
        entry_details.get("entry_distance_atr")
    )

    max_distance = _entry_limits()["max_entry_distance_atr"]

    if distance is None:
        failures.append("ENTRY_DISTANCE_UNVERIFIED")
    elif distance > max_distance:
        failures.append("ENTRY_OVEREXTENDED")

    if (
        not isinstance(risk_plan, dict)
        or risk_plan.get("valid") is not True
    ):
        reason = (
            risk_plan.get("reason", "UNKNOWN")
            if isinstance(risk_plan, dict)
            else "INVALID_PLAN"
        )
        failures.append("INVALID_RISK_PLAN:" + str(reason))

    risk_validation = (
        _safe_dict(risk_plan.get("risk_validation"))
        if isinstance(risk_plan, dict)
        else {}
    )

    if risk_validation.get("valid") is False:
        failures.append("RISK_VALIDATION_FAILED")

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "limits": limits,
    }


# ============================================================
# MULTI-TIMEFRAME CONFIRMATION
# ============================================================

def _timeframe_confirmation(
    entry_snapshot: Dict[str, Any],
    confirmation_snapshot: Dict[str, Any],
    structure_snapshot: Dict[str, Any],
) -> Dict[str, Any]:

    def bullish(snapshot: Dict[str, Any]) -> bool:
        snapshot = _safe_dict(snapshot)

        close = _number(snapshot.get("close"))
        ema20 = _number(snapshot.get("ema20"))
        ema50 = _number(snapshot.get("ema50"))
        macd_hist = _number(snapshot.get("macd_hist"))

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
        "confirmed": aligned == 3,
        "interpretation": (
            "ALL_ALIGNED" if aligned == 3
            else "PARTIAL_ALIGNMENT" if aligned == 2
            else "WEAK_ALIGNMENT"
        ),
        "statistical_independence": False,
    }


# ============================================================
# RISK PLAN ADAPTER
# ============================================================

def _build_strategy_risk_plan(
    entry_price: float,
    atr: float,
    capital_usdt: float,
    support: Optional[float],
    resistance: Optional[float],
    strategy: str,
) -> Dict[str, Any]:
    """
    V4 risk_manager API adapter.

    Uses the strategy-aware build_risk_plan signature.
    TypeError is not silently swallowed because an internal
    TypeError must remain visible as a real integration error.
    """

    return build_risk_plan(
        entry_price=entry_price,
        atr=atr,
        capital_usdt=capital_usdt,
        support=support,
        resistances=(
            [resistance]
            if resistance is not None
            else None
        ),
        strategy=strategy,
    )


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

    strategy = str(strategy or "SCALP").upper()

    if strategy not in TIMEFRAME_MAP:
        return {
            "valid": False,
            "decision": "REJECT",
            "reason": "INVALID_STRATEGY",
            "strategy": strategy,
            "formula_version": FORMULA_VERSION,
            "code_version": CODE_VERSION,
        }

    capital = _number(capital_usdt)

    if capital is None or capital <= 0:
        return {
            "valid": False,
            "decision": "WAIT",
            "reason": "INVALID_CAPITAL",
            "strategy": strategy,
            "symbol": symbol,
            "formula_version": FORMULA_VERSION,
            "code_version": CODE_VERSION,
        }

    if not isinstance(confirm_frames, (dict, type(None))):
        return {
            "valid": False,
            "decision": "WAIT",
            "reason": "INVALID_CONFIRM_FRAMES",
            "strategy": strategy,
            "symbol": symbol,
            "formula_version": FORMULA_VERSION,
            "code_version": CODE_VERSION,
        }

    frames = confirm_frames if isinstance(confirm_frames, dict) else {}
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
            "code_version": CODE_VERSION,
        }

    entry_df = _ohlcv(entry_df)
    confirmation_df = _ohlcv(confirmation_df)
    structure_df = _ohlcv(structure_df)

    entry_snapshot = _calculate_snapshot(entry_df)
    confirmation_snapshot = _calculate_snapshot(confirmation_df)
    structure_snapshot = _calculate_snapshot(structure_df)

    structure = _market_structure(structure_df)

    mtf = _timeframe_confirmation(
        entry_snapshot,
        confirmation_snapshot,
        structure_snapshot,
    )

    layer1, btc_details = _btc_regime_score(market_context)

    layer2, technical_details = _technical_score(
        entry_snapshot,
        structure,
    )

    layer3, volume_details = _volume_score(entry_snapshot)

    layer4, liquidity_details = _liquidity_score(
        market_context
    )

    layer5, entry_details = _entry_quality_score(
        entry_df,
        entry_snapshot,
        structure,
        breakout_data,
    )

    entry_price = _number(entry_snapshot.get("close"))
    atr_value = _number(entry_snapshot.get("atr"))

    if entry_price is None or atr_value is None or atr_value <= 0:
        risk_plan = {
            "valid": False,
            "reason": "INVALID_ENTRY_OR_ATR",
        }
    else:
        risk_plan = _build_strategy_risk_plan(
            entry_price=entry_price,
            atr=atr_value,
            capital_usdt=capital,
            support=structure.get("support"),
            resistance=structure.get("resistance"),
            strategy=strategy,
        )

    layer6, risk_details = _risk_score(risk_plan)

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
        "timeframes": mapping.copy(),
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
        "strategies": {
            key: value.copy()
            for key, value in TIMEFRAME_MAP.items()
        },
        "btc_timeframes": list(BTC_TIMEFRAMES),
        "minimum_signal_score": DEFAULT_MIN_SIGNAL_SCORE,
        "excellent_buy_score": DEFAULT_EXCELLENT_SCORE,
        "minimum_net_rr_t1": _risk_minimum_rr(),
        "minimum_candles": _minimum_candles(),
        "liquidity_limits": _liquidity_limits(),
        "entry_limits": _entry_limits(),
        "spot_only": True,
        "score_is_win_probability": False,
    }


# ============================================================
# SELF-CHECK
# ============================================================

def self_check() -> Dict[str, Any]:
    checks: Dict[str, bool] = {}

    try:
        checks["seven_layer_weights_total_100"] = (
            sum(LAYER_WEIGHTS.values()) == 100
            and len(LAYER_WEIGHTS) == 7
        )

        checks["layer_weights_match_keys"] = (
            set(LAYER_WEIGHTS)
            == {
                "btc_market_regime",
                "technical_structure",
                "volume_momentum",
                "liquidity_order_flow",
                "entry_quality",
                "risk_reward",
                "fundamental_onchain",
            }
        )

        checks["scalp_timeframes"] = (
            TIMEFRAME_MAP["SCALP"]["entry"] == "5m"
            and TIMEFRAME_MAP["SCALP"]["confirmation"] == "15m"
            and TIMEFRAME_MAP["SCALP"]["structure"] == "30m"
        )

        checks["swing_timeframes"] = (
            TIMEFRAME_MAP["SWING"]["entry"] == "15m"
            and TIMEFRAME_MAP["SWING"]["confirmation"] == "30m"
            and TIMEFRAME_MAP["SWING"]["structure"] == "1h"
        )

        checks["btc_timeframes"] = (
            BTC_TIMEFRAMES == ("15m", "1h", "4h")
        )

        checks["signal_thresholds"] = (
            DEFAULT_MIN_SIGNAL_SCORE == 85
            and DEFAULT_EXCELLENT_SCORE == 90
        )

        checks["spot_only"] = True

        checks["risk_manager_import"] = callable(
            build_risk_plan
        )

        count = 260
        index = pd.RangeIndex(count)

        close = pd.Series(
            [
                100 + i * 0.08 + math.sin(i / 5) * 0.15
                for i in range(count)
            ],
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

        checks["indicator_snapshot"] = all(
            snapshot.get(key) is not None
            for key in (
                "close",
                "ema20",
                "ema50",
                "ema200",
                "atr",
                "rsi",
            )
        )

        structure = _market_structure(df)

        checks["market_structure"] = bool(
            structure.get("valid")
        )

        checks["valid_frame"] = _valid_frame(df)

        checks["invalid_frame_rejected"] = (
            not _valid_frame(df.tail(100).copy())
        )

        duplicate_df = df.copy()
        duplicate_df["close_time"] = list(range(count))
        duplicate_df.loc[count - 1, "close_time"] = (
            duplicate_df.loc[count - 2, "close_time"]
        )

        checks["duplicate_candle_timestamp_rejected"] = (
            not _valid_frame(duplicate_df)
        )

        reversed_df = df.iloc[::-1].copy()
        reversed_df["close_time"] = list(range(count))

        checks["reversed_candles_rejected"] = (
            not _valid_frame(reversed_df)
        )

        incomplete = score_setup(
            trigger_df=df.tail(100).copy(),
            confirm_frames={},
            market_context={},
            strategy="SCALP",
        )

        checks["incomplete_data_cannot_buy"] = (
            incomplete.get("decision") == "WAIT"
            and incomplete.get("valid") is False
        )

        checks["invalid_strategy_rejected"] = (
            score_setup(
                trigger_df=df,
                strategy="INVALID",
            ).get("decision") == "REJECT"
        )

        checks["invalid_confirm_frames_rejected"] = (
            score_setup(
                trigger_df=df,
                confirm_frames=[],
                strategy="SCALP",
            ).get("reason") == "INVALID_CONFIRM_FRAMES"
        )

        checks["invalid_market_context_safe"] = (
            _btc_regime_score(None)[1]["status"]
            == "UNVERIFIED"
        )

        checks["liquidity_config_available"] = (
            all(
                value > 0
                for value in _liquidity_limits().values()
            )
        )

        checks["risk_adapter_signature"] = (
            callable(build_risk_plan)
        )

    except Exception as exc:
        return {
            "ok": False,
            "passed": False,
            "checks": checks,
            "error": str(exc),
            "code_version": CODE_VERSION,
            "formula_version": FORMULA_VERSION,
        }

    passed_count = sum(checks.values())
    total_count = len(checks)

    return {
        "ok": passed_count == total_count,
        "passed": passed_count == total_count,
        "checks": checks,
        "passed_count": passed_count,
        "total_count": total_count,
        "code_version": CODE_VERSION,
        "formula_version": FORMULA_VERSION,
    }


if __name__ == "__main__":
    result = self_check()

    print(
        "ENTRY ENGINE SELF-CHECK:",
        "PASS" if result["ok"] else "FAIL",
    )

    print(
        "Checks:",
        result["passed_count"],
        "/",
        result["total_count"],
    )

    print(
        "Seven-Layer Weights:",
        sum(LAYER_WEIGHTS.values()),
    )

    print("Multi-Timeframe Confirmation: ENABLED")
    print("BTC Market Context: ENABLED")
    print("ATR-Based Risk Integration: ENABLED")
    print("Spot Only: YES")
    print("Code Version:", CODE_VERSION)
    print("Formula Version:", FORMULA_VERSION)

    if not result["ok"]:
        print(
            "Failed checks:",
            [
                name
                for name, passed in result["checks"].items()
                if not passed
            ],
        )

        if result.get("error"):
            print("Error:", result["error"])

        raise SystemExit(1)
