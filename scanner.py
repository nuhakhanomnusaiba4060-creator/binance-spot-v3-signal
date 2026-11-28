
"""
Binance Spot V3 Smart Signal Scanner
V4 Formula Integration Controller

System Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Market: Binance Spot USDT ONLY
Test Status: NOT RUN

Responsibilities:
- Fetch Binance Spot market data and closed candles.
- Analyze BTC market regime.
- Select liquid USDT Spot candidates.
- Run the V4 seven-layer, 100-point signal engine.
- Normalize V4 risk plans for existing tracker and Telegram interfaces.
- Register approved signals and deliver Telegram notifications.
- Update existing tracked signals without blocking new signal analysis.
"""

from __future__ import annotations

import logging
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import config as cfg

from coin_selector import select_coins
from data_provider import (
    get_24h_ticker,
    get_klines,
    get_order_book,
    get_usdt_symbols,
)
from entry_engine import evaluate_scalp, evaluate_swing
from market_filter import analyze_market
from signal_tracker import (
    check_duplicate,
    expire_old_signals,
    expire_unfilled_entries,
    load_history,
    register_signal,
    update_signal_status,
)
from telegram_bot import (
    credentials_available,
    send_signal,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=getattr(
        logging,
        str(os.getenv("LOG_LEVEL", "INFO")).upper(),
        logging.INFO,
    ),
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# VERSION AND CONFIGURATION
# ============================================================

CODE_VERSION = "4.0.0"
FORMULA_VERSION = "4.0"

QUOTE_ASSET = "USDT"

KLINE_LIMIT = 300
ORDER_BOOK_LIMIT = 100

MAX_ORDERBOOK_CANDIDATES = 30
MAX_SIGNALS_PER_RUN = 3

STRATEGIES_ENABLED = {
    "SCALP": True,
    "SWING": True,
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


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError, OverflowError):
        return default


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _positive(
    value: Any,
    default: float = 0.0,
) -> float:
    number = _safe_float(value, default)

    if number is None or number <= 0:
        return default

    return number


def _env_bool(
    name: str,
    default: bool,
) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in ("1", "true", "yes", "on"):
        return True

    if normalized in ("0", "false", "no", "off"):
        return False

    raise ValueError(
        f"Invalid Boolean environment variable: {name}"
    )


def _get_config_section(name: str) -> dict:
    value = getattr(cfg, name, {})

    return value if isinstance(value, dict) else {}


def _config_number(
    section: dict,
    key: str,
    default: float,
) -> float:
    value = _safe_float(section.get(key), default)

    if value is None:
        return default

    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_dataframe(frame: Any) -> bool:
    return (
        frame is not None
        and hasattr(frame, "empty")
        and not frame.empty
        and len(frame) >= 50
    )


def _operation_succeeded(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and result.get("success") is True
    )


def _get_ticker_map(tickers: Any) -> dict[str, dict]:
    """
    Convert Binance's 24h ticker LIST into a symbol-indexed map.
    """
    if isinstance(tickers, dict):
        if "symbol" in tickers:
            symbol = str(tickers.get("symbol", "")).upper()
            return {symbol: tickers} if symbol else {}

        return {
            str(symbol).upper(): value
            for symbol, value in tickers.items()
            if isinstance(value, dict)
        }

    if not isinstance(tickers, list):
        raise ValueError("Invalid Binance 24h ticker response.")

    result = {}

    for ticker in tickers:
        if not isinstance(ticker, dict):
            continue

        symbol = str(ticker.get("symbol", "")).upper().strip()

        if symbol:
            result[symbol] = ticker

    return result


def _ticker_price(ticker: dict) -> float:
    return _positive(
        ticker.get("lastPrice", ticker.get("last_price"))
    )


def _ticker_quote_volume(ticker: dict) -> float:
    return _positive(
        ticker.get(
            "quoteVolume",
            ticker.get("quote_volume"),
        )
    )


def _is_usdt_symbol(symbol: str) -> bool:
    symbol = str(symbol or "").upper().strip()

    return (
        symbol.endswith(QUOTE_ASSET)
        and len(symbol) > len(QUOTE_ASSET)
    )


# ============================================================
# ENVIRONMENT
# ============================================================

RUNTIME_CONFIG = _get_config_section("RUNTIME_CONFIG")
RISK_CONFIG = _get_config_section("RISK_CONFIG")
SYMBOL_CONFIG = _get_config_section("SYMBOL_CONFIG")
SIGNAL_CONFIG = _get_config_section("SIGNAL_CONFIG")
EXECUTION_COST_CONFIG = _get_config_section(
    "EXECUTION_COST_CONFIG"
)

DRY_RUN = _env_bool(
    "DRY_RUN",
    bool(RUNTIME_CONFIG.get("dry_run", False)),
)

CAPITAL_USDT = _positive(
    os.getenv(
        "SCANNER_CAPITAL_USDT",
        RUNTIME_CONFIG.get("capital_usdt", 100.0),
    ),
    100.0,
)

MAX_SIGNALS_PER_RUN = _safe_int(
    os.getenv(
        "MAX_SIGNALS_PER_RUN",
        RUNTIME_CONFIG.get("max_signals_per_run", 3),
    ),
    3,
)

MAX_SIGNALS_PER_RUN = max(
    1,
    min(MAX_SIGNALS_PER_RUN, 10),
)


# ============================================================
# CONFIGURATION VALIDATION
# ============================================================

def validate_scanner_configuration() -> None:
    if CAPITAL_USDT <= 0:
        raise ValueError(
            "SCANNER_CAPITAL_USDT must be greater than zero."
        )

    if KLINE_LIMIT < 220:
        raise ValueError(
            "KLINE_LIMIT must be at least 220."
        )

    if MAX_SIGNALS_PER_RUN < 1:
        raise ValueError(
            "MAX_SIGNALS_PER_RUN must be positive."
        )

    if not DRY_RUN and not credentials_available():
        raise ValueError(
            "Telegram credentials are missing."
        )

    if not bool(RUNTIME_CONFIG.get("spot_only", True)):
        raise ValueError(
            "This scanner must remain Spot-only."
        )

    logger.info(
        "Scanner configuration validated."
    )

    logger.info(
        "Code Version: %s | Formula Version: %s",
        CODE_VERSION,
        FORMULA_VERSION,
    )

    logger.info(
        "Mode: %s",
        "DRY RUN" if DRY_RUN else "LIVE",
    )

    logger.info(
        "Market: Binance Spot USDT"
    )

    logger.info(
        "Capital: %.2f USDT",
        CAPITAL_USDT,
    )


# ============================================================
# BTC MARKET DATA
# ============================================================

def fetch_btc_market_data() -> dict:
    logger.info("Fetching BTC market data.")

    result = {}

    for timeframe in ("15m", "1h", "4h"):
        frame = get_klines(
            "BTCUSDT",
            timeframe,
            limit=KLINE_LIMIT,
            closed_only=True,
        )

        if not _valid_dataframe(frame):
            raise RuntimeError(
                f"Invalid BTC {timeframe} closed candles."
            )

        result[timeframe] = frame

    return result


def fetch_market_context() -> dict:
    btc_data = fetch_btc_market_data()

    context = analyze_market(
        btc_data,
        external_data=None,
    )

    if not isinstance(context, dict):
        raise RuntimeError(
            "Market filter returned invalid context."
        )

    regime = str(
        context.get(
            "regime",
            context.get("market_status", "UNKNOWN"),
        )
    ).upper()

    if regime == "UNKNOWN":
        raise RuntimeError(
            "BTC market regime is unverified."
        )

    context = deepcopy(context)

    # The entry engine reads risk_level before regime.
    # Normalize it to the actual BTC regime so that
    # LOW/MEDIUM/ELEVATED risk labels are not mistaken
    # for UNKNOWN directional regimes.
    context["regime"] = regime
    context["risk_level"] = regime

    context["market_status"] = regime

    context["allow_new_buy"] = bool(
        context.get("allow_new_buy", True)
    )

    if regime == "HIGH_RISK":
        context["allow_new_buy"] = False

    trend_analysis = context.get(
        "btc_trend_analysis",
        {},
    )

    if isinstance(trend_analysis, dict):
        context["btc_trend"] = trend_analysis.get(
            "trend",
            regime,
        )
    else:
        context["btc_trend"] = regime

    logger.info(
        "BTC regime: %s | Trend: %s | New BUY: %s",
        regime,
        context.get("btc_trend"),
        context["allow_new_buy"],
    )

    return context


# ============================================================
# MARKET CANDIDATE SELECTION
# ============================================================

def prefilter_tickers(
    ticker_map: dict,
    symbols: list,
) -> list:
    minimum_volume = _config_number(
        SYMBOL_CONFIG,
        "minimum_24h_quote_volume_usdt",
        1_000_000.0,
    )

    excluded_symbols = {
        str(item).upper()
        for item in SYMBOL_CONFIG.get(
            "exclude_symbols",
            [],
        )
    }

    excluded_suffixes = tuple(
        str(item).upper()
        for item in SYMBOL_CONFIG.get(
            "excluded_suffixes",
            [],
        )
    )

    allowed_symbols = {
        str(item).upper()
        for item in symbols
    }

    eligible = []

    for symbol, ticker in ticker_map.items():
        if symbol not in allowed_symbols:
            continue

        if not _is_usdt_symbol(symbol):
            continue

        if symbol in excluded_symbols:
            continue

        if excluded_suffixes and symbol.endswith(
            excluded_suffixes
        ):
            continue

        if not isinstance(ticker, dict):
            continue

        quote_volume = _ticker_quote_volume(ticker)

        if quote_volume < minimum_volume:
            continue

        if _ticker_price(ticker) <= 0:
            continue

        eligible.append(ticker)

    eligible.sort(
        key=_ticker_quote_volume,
        reverse=True,
    )

    return eligible[:MAX_ORDERBOOK_CANDIDATES]


def fetch_order_books(
    tickers: list,
) -> dict:
    order_books = {}

    logger.info(
        "Fetching order books for %d candidates.",
        len(tickers),
    )

    for ticker in tickers:
        symbol = str(
            ticker.get("symbol", "")
        ).upper()

        if not symbol:
            continue

        try:
            order_books[symbol] = get_order_book(
                symbol,
                limit=ORDER_BOOK_LIMIT,
            )

        except Exception as exc:
            logger.warning(
                "Order book unavailable for %s: %s",
                symbol,
                exc,
            )

    return order_books


def collect_candidates(
    ticker_map: dict | None = None,
) -> list:
    logger.info(
        "Loading eligible Binance Spot USDT symbols."
    )

    symbols = get_usdt_symbols()

    if not isinstance(symbols, list) or not symbols:
        raise RuntimeError(
            "No eligible Binance Spot USDT symbols."
        )

    if ticker_map is None:
        ticker_map = _get_ticker_map(
            get_24h_ticker()
        )

    shortlisted = prefilter_tickers(
        ticker_map,
        symbols,
    )

    logger.info(
        "Candidates after 24h volume filter: %d",
        len(shortlisted),
    )

    if not shortlisted:
        return []

    order_books = fetch_order_books(shortlisted)

    selector_config = {}

    try:
        from coin_selector import get_coin_selector_config

        selector_config = get_coin_selector_config()

        if not isinstance(selector_config, dict):
            selector_config = {}

    except Exception:
        selector_config = {}

    selection = select_coins(
        tickers=shortlisted,
        order_books=order_books,
        max_symbols=MAX_ORDERBOOK_CANDIDATES,
        order_value_usdt=min(
            CAPITAL_USDT,
            100.0,
        ),
    )

    if not isinstance(selection, list):
        raise RuntimeError(
            "Coin selector returned an invalid result."
        )

    candidates = []

    for candidate in selection:
        if not isinstance(candidate, dict):
            continue

        if candidate.get("selection_status") != "ACCEPTED":
            continue

        symbol = str(
            candidate.get("symbol", "")
        ).upper()

        if not _is_usdt_symbol(symbol):
            continue

        if _ticker_price(ticker_map.get(symbol, {})) <= 0:
            continue

        candidates.append(candidate)

    logger.info(
        "Final liquidity-approved candidates: %d",
        len(candidates),
    )

    return candidates


# ============================================================
# SYMBOL CANDLE DATA
# ============================================================

def fetch_symbol_market_data(
    symbol: str,
) -> dict:
    if not _is_usdt_symbol(symbol):
        raise ValueError(
            "Only USDT Spot symbols are supported."
        )

    market_data = {}

    for timeframe in ("5m", "15m", "30m", "1h"):
        frame = get_klines(
            symbol,
            timeframe,
            limit=KLINE_LIMIT,
            closed_only=True,
        )

        if not _valid_dataframe(frame):
            raise RuntimeError(
                f"Invalid {timeframe} closed candles for {symbol}."
            )

        market_data[timeframe] = frame

    return market_data


# ============================================================
# CANDIDATE MARKET CONTEXT
# ============================================================

def build_candidate_market_context(
    btc_context: dict,
    candidate: dict,
) -> dict:
    context = deepcopy(btc_context)

    context["liquidity"] = {
        "spread_percent": _safe_float(
            candidate.get("spread_percent")
        ),
        "imbalance": _safe_float(
            candidate.get("order_book_imbalance")
        ),
        "minimum_side_depth_usdt": _safe_float(
            candidate.get("minimum_side_depth_usdt")
        ),
        "buy_slippage_percent": _safe_float(
            candidate.get("buy_slippage_percent")
        ),
    }

    context["order_book_analysis"] = context["liquidity"]

    context["spread_percent"] = context["liquidity"][
        "spread_percent"
    ]

    context["formula_version"] = FORMULA_VERSION

    return context


# ============================================================
# RISK PLAN NORMALIZATION
# ============================================================

def _risk_cost_rates() -> tuple[float, float, float]:
    """
    Return fee and slippage rates as decimal fractions
    for Telegram's net-profit estimator.

    Config values are percentage units.
    """
    entry_fee_pct = _config_number(
        EXECUTION_COST_CONFIG,
        "entry_fee_pct",
        0.1,
    )

    exit_fee_pct = _config_number(
        EXECUTION_COST_CONFIG,
        "exit_fee_pct",
        0.1,
    )

    slippage_pct = _config_number(
        EXECUTION_COST_CONFIG,
        "slippage_pct",
        0.1,
    )

    return (
        max(0.0, entry_fee_pct / 100.0),
        max(0.0, exit_fee_pct / 100.0),
        max(0.0, slippage_pct / 200.0),
    )


def normalize_risk_plan(
    raw_plan: dict,
    entry_price: float,
) -> dict:
    """
    Convert risk_manager.build_risk_plan() output into
    the established signal_tracker and telegram_bot format.
    """
    if not isinstance(raw_plan, dict):
        raise ValueError(
            "Risk manager returned invalid data."
        )

    if raw_plan.get("valid") is not True:
        raise ValueError(
            "Risk manager rejected the plan: "
            + str(raw_plan.get("reason", "UNKNOWN"))
        )

    stop = _positive(raw_plan.get("stop_loss"))

    if stop <= 0 or stop >= entry_price:
        raise ValueError(
            "Invalid Spot BUY Stop Loss."
        )

    raw_targets = raw_plan.get("targets", {})
    raw_position = raw_plan.get("position", {})
    raw_validation = raw_plan.get(
        "risk_validation",
        {},
    )

    if not isinstance(raw_targets, dict):
        raise ValueError("Invalid target data.")

    if not isinstance(raw_position, dict):
        raise ValueError("Invalid position data.")

    if not isinstance(raw_validation, dict):
        raise ValueError("Invalid risk validation.")

    if raw_validation.get("valid") is not True:
        raise ValueError("Risk validation failed.")

    entry_fee_rate, exit_fee_rate, slippage_rate = (
        _risk_cost_rates()
    )

    quantity = _positive(
        raw_position.get("quantity")
    )

    position_value = _positive(
        raw_position.get("position_value_usdt")
    )

    estimated_loss = _positive(
        raw_position.get("estimated_loss_usdt")
    )

    if quantity <= 0 or position_value <= 0:
        raise ValueError(
            "Position size is invalid."
        )

    if estimated_loss <= 0:
        raise ValueError(
            "Estimated risk amount is invalid."
        )

    target_checks = raw_validation.get(
        "target_checks",
        {},
    )

    if not isinstance(target_checks, dict):
        target_checks = {}

    targets = {}

    for name in ("t1", "t2", "t3"):
        price = _positive(raw_targets.get(name))

        if price <= entry_price:
            targets[name] = None
            continue

        check = target_checks.get(name, {})

        if not isinstance(check, dict):
            check = {}

        net_rr = _safe_float(
            check.get("net_rr")
        )

        targets[name] = {
            "price": price,
            "risk_reward": net_rr,
        }

    if not isinstance(targets.get("t1"), dict):
        raise ValueError(
            "A valid T1 target is required."
        )

    stop_distance_pct = (
        (entry_price - stop) / entry_price
    ) * 100.0

    actual_risk_pct = (
        estimated_loss / CAPITAL_USDT
    ) * 100.0

    effective_entry = entry_price * (
        1.0 + entry_fee_rate + slippage_rate
    )

    normalized_position = {
        "quantity": quantity,
        "position_value_usdt": position_value,
        "actual_estimated_loss_usdt": estimated_loss,
        "actual_risk_percent": actual_risk_pct,
        "effective_entry_price": effective_entry,
        "fee_rate_per_side": entry_fee_rate,
        "slippage_rate_per_side": slippage_rate,
        "estimated_loss_within_budget": bool(
            raw_position.get(
                "estimated_loss_within_budget",
                False,
            )
        ),
    }

    normalized_validation = {
        "valid": True,
        "reason": "VALID",
        "target_checks": target_checks,
    }

    return {
        "status": "VALID",
        "valid": True,
        "direction": "BUY",
        "spot_only": True,
        "formula_version": FORMULA_VERSION,
        "entry_price": entry_price,
        "stop_loss": {
            "stop_loss": stop,
            "risk_percent": stop_distance_pct,
            "method": "ATR + SUPPORT STRUCTURE",
        },
        "targets": targets,
        "position_size": normalized_position,
        "validation": normalized_validation,
        "risk_distance_pct": stop_distance_pct,
        "execution_cost_pct": raw_plan.get(
            "execution_cost_pct"
        ),
        "raw_risk_plan": raw_plan,
    }


# ============================================================
# SIGNAL NORMALIZATION
# ============================================================

def normalize_engine_signal(
    result: dict,
    symbol: str,
    strategy: str,
    candidate: dict,
    market_context: dict,
) -> dict | None:
    if not isinstance(result, dict):
        return None

    classification = str(
        result.get("classification", "")
    ).upper().strip()

    if classification not in (
        "STRONG BUY",
        "EXCELLENT BUY",
    ):
        return None

    if result.get("valid") is not True:
        return None

    score = _safe_float(result.get("score"))

    if score is None or not 0 <= score <= 100:
        return None

    entry_data = result.get("entry", {})

    if not isinstance(entry_data, dict):
        return None

    entry_price = _positive(
        entry_data.get("price")
    )

    atr = _positive(
        entry_data.get("atr")
    )

    if entry_price <= 0 or atr <= 0:
        return None

    raw_risk_plan = result.get("risk_plan")

    risk_plan = normalize_risk_plan(
        raw_risk_plan,
        entry_price,
    )

    structure = result.get("structure", {})

    if not isinstance(structure, dict):
        structure = {}

    layer_scores = result.get("layers", {})

    if not isinstance(layer_scores, dict):
        layer_scores = {}

    mtf = result.get("mtf_confirmation", {})

    if not isinstance(mtf, dict):
        mtf = {}

    signal = {
        "symbol": symbol,
        "strategy": strategy,
        "classification": classification,
        "signal": classification,
        "decision": "BUY",
        "status": "APPROVED",
        "score": round(score, 2),
        "max_score": 100,
        "formula_version": FORMULA_VERSION,
        "code_version": CODE_VERSION,
        "score_is_win_probability": False,

        "entry_price": entry_price,
        "current_price": _positive(
            candidate.get("last_price"),
            entry_price,
        ),
        "last_price": _positive(
            candidate.get("last_price"),
            entry_price,
        ),

        "atr": atr,
        "atr_value": atr,
        "rsi": entry_data.get("rsi"),
        "rvol": entry_data.get("rvol"),
        "adx": entry_data.get("adx"),

        "support_level": structure.get("support"),
        "nearest_support": structure.get("support"),
        "resistance_levels": (
            [structure["resistance"]]
            if structure.get("resistance") is not None
            else []
        ),

        "quote_volume_24h": candidate.get(
            "quote_volume_24h"
        ),
        "spread_percent": candidate.get(
            "spread_percent"
        ),
        "liquidity_score": candidate.get(
            "liquidity_score"
        ),

        "btc_trend": market_context.get(
            "btc_trend",
            "UNKNOWN",
        ),
        "market_status": market_context.get(
            "market_status",
            "UNKNOWN",
        ),
        "risk_level": market_context.get(
            "risk_level",
            "UNKNOWN",
        ),

        "layers": layer_scores,
        "mtf_confirmation": mtf,
        "hard_gates": result.get("hard_gates", {}),
        "fundamental_status": result.get(
            "fundamental_status",
            "UNVERIFIED",
        ),

        "risk_plan": risk_plan,
        "generated_at": _utc_now(),
        "created_at": _utc_now(),

        "warnings": [
            "Fundamental ও on-chain তথ্য সম্পূর্ণ যাচাই করা হয়নি।"
        ] if result.get("fundamental_status") == "UNVERIFIED" else [],
    }

    return signal


# ============================================================
# SIGNAL EVALUATION
# ============================================================

def evaluate_candidate(
    candidate: dict,
    btc_context: dict,
) -> list:
    symbol = str(
        candidate.get("symbol", "")
    ).upper()

    if not _is_usdt_symbol(symbol):
        return []

    try:
        market_data = fetch_symbol_market_data(symbol)

    except Exception as exc:
        logger.warning(
            "Candle data failed for %s: %s",
            symbol,
            exc,
        )
        return []

    candidate_context = build_candidate_market_context(
        btc_context,
        candidate,
    )

    strategies = []

    if STRATEGIES_ENABLED["SCALP"]:
        strategies.append(
            (
                "SCALP",
                evaluate_scalp,
                market_data["5m"],
                {
                    "15m": market_data["15m"],
                    "30m": market_data["30m"],
                },
            )
        )

    if STRATEGIES_ENABLED["SWING"]:
        strategies.append(
            (
                "SWING",
                evaluate_swing,
                market_data["15m"],
                {
                    "30m": market_data["30m"],
                    "1h": market_data["1h"],
                },
            )
        )

    signals = []

    for strategy, evaluator, trigger_df, confirm_frames in strategies:
        try:
            result = evaluator(
                trigger_df=trigger_df,
                confirm_frames=confirm_frames,
                market_context=candidate_context,
                breakout_data=None,
                fundamental_data=None,
                capital_usdt=CAPITAL_USDT,
            )

            if not isinstance(result, dict):
                continue

            signal = normalize_engine_signal(
                result=result,
                symbol=symbol,
                strategy=strategy,
                candidate=candidate,
                market_context=candidate_context,
            )

            if signal is None:
                logger.info(
                    "%s %s: %s | Score: %s",
                    symbol,
                    strategy,
                    result.get("reason", result.get("classification")),
                    result.get("score"),
                )
                continue

            signals.append(signal)

        except Exception as exc:
            logger.exception(
                "%s %s evaluation failed: %s",
                symbol,
                strategy,
                exc,
            )

    return signals


# ============================================================
# DUPLICATE PREVENTION
# ============================================================

def is_duplicate_signal(
    symbol: str,
    strategy: str,
    history: dict,
) -> bool:
    try:
        return bool(
            check_duplicate(
                symbol=symbol,
                strategy=strategy,
                history=history,
            )
        )

    except Exception as exc:
        logger.error(
            "Duplicate check failed for %s: %s",
            symbol,
            exc,
        )

        # Fail closed: do not send if duplicate status is unknown.
        return True


# ============================================================
# EXISTING SIGNAL TRACKING
# ============================================================

def update_existing_signals(
    ticker_map: dict,
) -> None:
    try:
        expire_old_signals()
        expire_unfilled_entries()

        history = load_history()

        if not isinstance(history, dict):
            return

        signals = history.get("signals", [])

        if not isinstance(signals, list):
            return

        for item in signals:
            if not isinstance(item, dict):
                continue

            status = str(
                item.get("status", "")
            ).upper()

            if status not in (
                "ACTIVE",
                "TARGET_1_HIT",
                "TARGET_2_HIT",
            ):
                continue

            symbol = str(
                item.get("symbol", "")
            ).upper()

            ticker = ticker_map.get(symbol)

            if not isinstance(ticker, dict):
                continue

            current_price = _ticker_price(ticker)

            if current_price <= 0:
                continue

            signal_id = (
                item.get("signal_id")
                or item.get("id")
            )

            if not signal_id:
                continue

            result = update_signal_status(
                signal_id,
                current_price,
            )

            if not _operation_succeeded(result):
                logger.warning(
                    "Tracking update failed for %s: %s",
                    symbol,
                    result,
                )

    except Exception as exc:
        logger.exception(
            "Existing signal tracking failed: %s",
            exc,
        )


# ============================================================
# REGISTRATION AND TELEGRAM DELIVERY
# ============================================================

def deliver_signal(
    signal: dict,
    history: dict,
) -> bool:
    symbol = str(
        signal.get("symbol", "")
    ).upper()

    strategy = str(
        signal.get("strategy", "")
    ).upper()

    if not _is_usdt_symbol(symbol):
        return False

    if signal.get("classification") not in (
        "STRONG BUY",
        "EXCELLENT BUY",
    ):
        return False

    if not isinstance(
        signal.get("risk_plan"),
        dict,
    ):
        return False

    if DRY_RUN:
        logger.info(
            "[DRY RUN] %s | %s | %.2f/100",
            symbol,
            signal.get("classification"),
            _safe_float(signal.get("score"), 0.0),
        )
        return False

    if is_duplicate_signal(
        symbol,
        strategy,
        history,
    ):
        logger.info(
            "Duplicate signal skipped: %s %s",
            symbol,
            strategy,
        )
        return False

    # Register before Telegram delivery so that a notification
    # retry cannot create duplicate ledger entries.
    try:
        registration = register_signal(signal)

    except Exception as exc:
        logger.exception(
            "Signal registration failed for %s: %s",
            symbol,
            exc,
        )
        return False

    if not _operation_succeeded(registration):
        logger.error(
            "Signal registration rejected for %s: %s",
            symbol,
            registration,
        )
        return False

    logger.info(
        "Signal registered: %s | ID: %s",
        symbol,
        registration.get("signal_id"),
    )

    try:
        refreshed = load_history()

        if isinstance(refreshed, dict):
            history.clear()
            history.update(refreshed)

    except Exception as exc:
        logger.warning(
            "History refresh failed: %s",
            exc,
        )

    try:
        telegram_result = send_signal(signal)

    except Exception as exc:
        logger.exception(
            "Telegram delivery exception for %s: %s",
            symbol,
            exc,
        )
        return False

    if not _operation_succeeded(telegram_result):
        logger.error(
            "Telegram delivery failed for %s: %s",
            symbol,
            telegram_result,
        )
        return False

    logger.info(
        "Telegram delivery successful: %s",
        symbol,
    )

    return True


# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner() -> dict:
    started_at = datetime.now(timezone.utc)

    report = {
        "code_version": CODE_VERSION,
        "formula_version": FORMULA_VERSION,
        "started_at": started_at.isoformat(),
        "mode": "DRY_RUN" if DRY_RUN else "LIVE",
        "market": "BINANCE_SPOT_USDT",
        "market_status": "UNKNOWN",
        "btc_trend": "UNKNOWN",
        "symbols_scanned": 0,
        "candidates_selected": 0,
        "signals_generated": 0,
        "signals_sent": 0,
        "errors": [],
    }

    logger.info("=" * 60)
    logger.info("BINANCE SPOT V4 FORMULA SCANNER STARTED")
    logger.info("=" * 60)

    try:
        validate_scanner_configuration()

        # 1. BTC regime
        btc_context = fetch_market_context()

        report["market_status"] = btc_context.get(
            "market_status",
            "UNKNOWN",
        )

        report["btc_trend"] = btc_context.get(
            "btc_trend",
            "UNKNOWN",
        )

        if (
            report["market_status"] == "HIGH_RISK"
            or btc_context.get("allow_new_buy") is False
        ):
            logger.warning(
                "BTC HIGH RISK: New Spot BUY signals blocked."
            )
            return report

        # 2. Fetch 24h ticker once.
        ticker_map = _get_ticker_map(
            get_24h_ticker()
        )

        if not ticker_map:
            raise RuntimeError(
                "Binance returned no valid 24h ticker data."
            )

        # 3. Update previous signals.
        if not DRY_RUN:
            update_existing_signals(ticker_map)

        # 4. Select liquid candidates.
        candidates = collect_candidates(
            ticker_map=ticker_map,
        )

        report["candidates_selected"] = len(candidates)

        if not candidates:
            logger.info(
                "No liquidity-approved candidates found."
            )
            return report

        # 5. Load signal history.
        history = load_history()

        if not isinstance(history, dict):
            history = {"signals": []}

        # 6. Run V4 seven-layer engine.
        all_signals = []

        for candidate in candidates:
            report["symbols_scanned"] += 1

            candidate_signals = evaluate_candidate(
                candidate,
                btc_context,
            )

            all_signals.extend(candidate_signals)

        # 7. Highest score first.
        all_signals.sort(
            key=lambda item: (
                _safe_float(item.get("score"), 0.0),
                1 if item.get("strategy") == "SWING" else 0,
            ),
            reverse=True,
        )

        # Avoid duplicate symbol signals in the same run.
        selected_signals = []
        seen_symbols = set()

        for signal in all_signals:
            symbol = signal["symbol"]

            if symbol in seen_symbols:
                continue

            seen_symbols.add(symbol)
            selected_signals.append(signal)

            if len(selected_signals) >= MAX_SIGNALS_PER_RUN:
                break

        report["signals_generated"] = len(
            selected_signals
        )

        # 8. Register and send.
        for signal in selected_signals:
            try:
                delivered = deliver_signal(
                    signal,
                    history,
                )

                if delivered:
                    report["signals_sent"] += 1

            except Exception as exc:
                logger.exception(
                    "Signal delivery failed for %s",
                    signal.get("symbol", "UNKNOWN"),
                )

                report["errors"].append(
                    str(exc)
                )

        return report

    except Exception as exc:
        logger.exception(
            "Scanner execution failed."
        )

        report["errors"].append(
            str(exc)
        )

        return report

    finally:
        report["finished_at"] = (
            datetime.now(timezone.utc).isoformat()
        )

        logger.info(
            "Scanner finished | Candidates: %s | "
            "Generated: %s | Sent: %s | Errors: %s",
            report["candidates_selected"],
            report["signals_generated"],
            report["signals_sent"],
            len(report["errors"]),
        )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    final_report = run_scanner()

    logger.info(
        "FINAL SCAN REPORT: %s",
        final_report,
    )
