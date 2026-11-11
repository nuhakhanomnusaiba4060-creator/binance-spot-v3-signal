
"""
Binance Spot V3 Smart Signal Scanner
Main Scanner Controller

Responsibilities:
- Run Binance Spot USDT market scans.
- Analyze BTC market conditions.
- Select liquid Spot candidates.
- Evaluate scalp and swing setups.
- Validate risk before sending Telegram signals.
- Track active signals for up to 48 hours.

Spot only. No Futures. No Margin.
"""

import os
import math
import logging
from datetime import datetime, timezone
from typing import Any

from config import (
    CONFIG,
    FILTER_CONFIG,
    RISK_CONFIG,
    API_CONFIG,
)

from data_provider import (
    get_usdt_symbols,
    get_klines,
    get_24h_ticker,
    get_order_book,
)

from market_filter import analyze_market

from coin_selector import (
    select_coins,
    validate_candidate,
)

from entry_engine import (
    evaluate_scalp,
    evaluate_swing,
)

from risk_manager import build_risk_plan

from telegram_bot import (
    send_connection_test,
    send_signal,
    credentials_available,
)

from signal_tracker import (
    load_history,
    check_duplicate,
    register_signal,
    expire_old_signals,
    update_signal_status,
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# ENVIRONMENT CONFIGURATION
# =========================================================

def _env_bool(name: str, default: bool) -> bool:
    """
    Parse environment boolean safely.
    Invalid values raise an error instead of silently
    changing the scanner mode.
    """

    value = os.getenv(name)

    if value is None:
        return default

    normalized = value.strip().lower()

    if normalized in ("1", "true", "yes", "on"):
        return True

    if normalized in ("0", "false", "no", "off"):
        return False

    raise ValueError(
        f"Invalid {name} value: {value!r}. "
        "Use true/false, 1/0, yes/no, or on/off."
    )


def _parse_capital() -> float:
    """
    DRY RUN:
        Use SCANNER_CAPITAL_USDT if supplied.
        Otherwise use CONFIG simulation capital.

    LIVE:
        SCANNER_CAPITAL_USDT must be supplied explicitly.
    """

    raw = os.getenv("SCANNER_CAPITAL_USDT")

    if raw is None or not raw.strip():

        if DRY_RUN:
            capital = CONFIG.get(
                "SIMULATION_CAPITAL_USDT",
                100.0,
            )
        else:
            capital = 0.0

    else:
        try:
            capital = float(raw.strip())
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "SCANNER_CAPITAL_USDT must be a valid number."
            ) from exc

    try:
        capital = float(capital)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "Configured capital is invalid."
        ) from exc

    if not math.isfinite(capital) or capital < 0:
        raise ValueError(
            "Capital must be finite and non-negative."
        )

    return capital


DRY_RUN = _env_bool(
    "DRY_RUN",
    CONFIG.get("DEFAULT_DRY_RUN", True),
)

CAPITAL_USDT = _parse_capital()

MAX_ORDERBOOK_CANDIDATES = 30

KLINE_LIMIT = 300

ORDER_BOOK_LIMIT = 100

MAX_SIGNALS_PER_RUN = 3

STRATEGIES_ENABLED = {
    "SCALP": True,
    "SWING": True,
}


# =========================================================
# CONFIGURATION HELPERS
# =========================================================

def _normalize_key(value: str) -> str:
    return (
        str(value)
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def _find_config_value(
    config: Any,
    names: tuple,
    default: Any,
) -> Any:

    if not isinstance(config, dict):
        return default

    wanted = {
        _normalize_key(name)
        for name in names
    }

    for key, value in config.items():

        if _normalize_key(key) in wanted:
            return value

    for value in config.values():

        if isinstance(value, dict):

            result = _find_config_value(
                value,
                names,
                None,
            )

            if result is not None:
                return result

    return default


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:

    try:
        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default


def _get_field(
    data: dict,
    *names: str,
    default=None,
):

    if not isinstance(data, dict):
        return default

    normalized = {
        _normalize_key(key): value
        for key, value in data.items()
    }

    for name in names:

        key = _normalize_key(name)

        if key in normalized:
            return normalized[key]

    return default


# =========================================================
# SCANNER VALIDATION
# =========================================================

def validate_scanner_configuration() -> None:

    if not math.isfinite(CAPITAL_USDT):
        raise ValueError(
            "Capital must be finite."
        )

    if CAPITAL_USDT < 0:
        raise ValueError(
            "SCANNER_CAPITAL_USDT cannot be negative."
        )

    if not DRY_RUN and CAPITAL_USDT <= 0:
        raise ValueError(
            "Live mode requires a positive "
            "SCANNER_CAPITAL_USDT value."
        )

    if not DRY_RUN:

        if not credentials_available():
            raise ValueError(
                "Telegram credentials are missing."
            )

    if MAX_ORDERBOOK_CANDIDATES < 1:
        raise ValueError(
            "MAX_ORDERBOOK_CANDIDATES must be positive."
        )

    if KLINE_LIMIT < 220:
        raise ValueError(
            "KLINE_LIMIT must be at least 220."
        )

    logger.info(
        "Scanner configuration validated."
    )

    logger.info(
        "Mode: %s",
        "DRY RUN" if DRY_RUN else "LIVE",
    )

    logger.info(
        "Capital: %.2f USDT",
        CAPITAL_USDT,
    )


# =========================================================
# MARKET DATA
# =========================================================

def fetch_btc_market_data() -> dict:

    logger.info(
        "Fetching BTC market data."
    )

    btc_data = {}

    for timeframe in (
        "15m",
        "1h",
        "4h",
    ):

        try:
            btc_data[timeframe] = get_klines(
                "BTCUSDT",
                timeframe,
                limit=KLINE_LIMIT,
            )

        except Exception as exc:

            logger.error(
                "BTC %s data failed: %s",
                timeframe,
                exc,
            )

            btc_data[timeframe] = None

    if any(
        btc_data.get(tf) is None
        or btc_data[tf].empty
        for tf in (
            "15m",
            "1h",
            "4h",
        )
    ):

        raise RuntimeError(
            "Required BTC market data is incomplete."
        )

    return btc_data


def fetch_market_context() -> dict:

    btc_data = fetch_btc_market_data()

    market_context = analyze_market(
        btc_data,
        external_data=None,
    )

    if not isinstance(market_context, dict):
        raise RuntimeError(
            "Market filter returned invalid data."
        )

    logger.info(
        "BTC trend: %s | Market: %s | Risk: %s",
        market_context.get("btc_trend"),
        market_context.get("market_status"),
        market_context.get("risk_level"),
    )

    return market_context


# =========================================================
# TICKER FILTERING
# =========================================================

def get_ticker_value(
    ticker: dict,
    *names,
) -> float:

    return _safe_float(
        _get_field(
            ticker,
            *names,
        )
    )


def prefilter_symbols(
    symbols: list,
    ticker_data: Any,
) -> list:

    min_volume = _safe_float(
        _find_config_value(
            FILTER_CONFIG,
            (
                "MIN_24H_QUOTE_VOLUME_USDT",
                "MIN_QUOTE_VOLUME_USDT",
            ),
            3_000_000,
        ),
        3_000_000,
    )

    min_trades = int(
        _safe_float(
            _find_config_value(
                FILTER_CONFIG,
                (
                    "MIN_24H_TRADES",
                    "MIN_TRADES",
                ),
                1000,
            ),
            1000,
        )
    )

    if not isinstance(ticker_data, dict):
        return []

    eligible = []

    for symbol in symbols:

        ticker = ticker_data.get(symbol)

        if not isinstance(ticker, dict):
            continue

        quote_volume = get_ticker_value(
            ticker,
            "quote_volume",
            "quoteVolume",
        )

        trade_count = int(
            get_ticker_value(
                ticker,
                "trade_count",
                "count",
            )
        )

        if (
            quote_volume >= min_volume
            and trade_count >= min_trades
        ):

            eligible.append(
                (symbol, quote_volume)
            )

    eligible.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    return [
        symbol
        for symbol, _ in eligible[
            :MAX_ORDERBOOK_CANDIDATES
        ]
    ]


# =========================================================
# ORDER BOOK COLLECTION
# =========================================================

def fetch_order_books(
    symbols: list,
) -> dict:

    order_books = {}

    logger.info(
        "Fetching order books for %s candidates.",
        len(symbols),
    )

    for symbol in symbols:

        try:
            order_books[symbol] = get_order_book(
                symbol,
                limit=ORDER_BOOK_LIMIT,
            )

        except Exception as exc:

            logger.warning(
                "Order book failed for %s: %s",
                symbol,
                exc,
            )

    return order_books


# =========================================================
# COIN SELECTION
# =========================================================

def collect_candidates() -> list:

    logger.info(
        "Loading Binance Spot USDT symbols."
    )

    symbols = get_usdt_symbols()

    if not symbols:
        raise RuntimeError(
            "No eligible USDT Spot symbols returned."
        )

    logger.info(
        "Eligible symbols received: %s",
        len(symbols),
    )

    ticker_data = get_24h_ticker()

    if not isinstance(ticker_data, dict):
        raise RuntimeError(
            "Invalid 24h ticker response."
        )

    shortlisted = prefilter_symbols(
        symbols,
        ticker_data,
    )

    logger.info(
        "Candidates after volume filter: %s",
        len(shortlisted),
    )

    if not shortlisted:
        return []

    order_books = fetch_order_books(
        shortlisted
    )

    candidates = select_coins(
        shortlisted,
        ticker_data,
        order_books,
    )

    valid_candidates = [
        candidate
        for candidate in candidates
        if validate_candidate(candidate)
    ]

    logger.info(
        "Final eligible candidates: %s",
        len(valid_candidates),
    )

    return valid_candidates


# =========================================================
# CANDLE DATA COLLECTION
# =========================================================

def fetch_symbol_market_data(
    symbol: str,
) -> dict:

    market_data = {}

    timeframes = (
        "5m",
        "15m",
        "30m",
        "1h",
    )

    for timeframe in timeframes:

        market_data[timeframe] = get_klines(
            symbol,
            timeframe,
            limit=KLINE_LIMIT,
        )

        if (
            market_data[timeframe] is None
            or market_data[timeframe].empty
        ):

            raise RuntimeError(
                f"Missing {timeframe} candles for {symbol}"
            )

    return market_data


# =========================================================
# SIGNAL VALIDATION
# =========================================================

def is_eligible_signal(
    signal: Any,
) -> bool:

    if not isinstance(signal, dict):
        return False

    classification = str(
        signal.get("classification", "")
    ).upper()

    if classification not in (
        "STRONG BUY",
        "EXCELLENT BUY",
    ):
        return False

    symbol = str(
        signal.get("symbol", "")
    ).upper()

    if not symbol.endswith("USDT"):
        return False

    if _safe_float(
        signal.get("entry_price")
    ) <= 0:
        return False

    return True


def get_signal_support(
    signal: dict,
):

    return (
        signal.get("support_level")
        or signal.get("nearest_support")
        or signal.get("support")
    )


def get_signal_atr(
    signal: dict,
):

    return (
        signal.get("atr_value")
        or signal.get("atr")
    )


def get_signal_resistances(
    signal: dict,
) -> list:

    levels = signal.get(
        "resistance_levels",
        [],
    )

    if not isinstance(levels, list):
        return []

    return [
        _safe_float(level)
        for level in levels
        if _safe_float(level) > 0
    ]


# =========================================================
# RISK MANAGEMENT
# =========================================================

def attach_risk_plan(
    signal: dict,
) -> dict:

    entry_price = _safe_float(
        signal.get("entry_price")
    )

    if entry_price <= 0:
        raise ValueError(
            "Invalid signal entry price."
        )

    risk_percent = _safe_float(
        _find_config_value(
            RISK_CONFIG,
            ("MAX_RISK_PERCENT",),
            1.0,
        ),
        1.0,
    )

    fee_rate = _safe_float(
        _find_config_value(
            RISK_CONFIG,
            (
                "FEE_RATE",
                "TRADING_FEE_RATE",
            ),
            0.001,
        ),
        0.001,
    )

    slippage_rate = _safe_float(
        _find_config_value(
            RISK_CONFIG,
            ("SLIPPAGE_RATE",),
            0.001,
        ),
        0.001,
    )

    risk_plan = build_risk_plan(
        capital=CAPITAL_USDT,
        entry_price=entry_price,
        support_level=get_signal_support(signal),
        atr=get_signal_atr(signal),
        resistance_levels=get_signal_resistances(signal),
        risk_percent=risk_percent,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )

    if not isinstance(risk_plan, dict):
        raise ValueError(
            "Invalid risk plan response."
        )

    signal["risk_plan"] = risk_plan

    signal["risk_status"] = risk_plan.get(
        "status",
        "REJECT",
    )

    signal["strategy"] = signal.get(
        "strategy",
        "UNKNOWN",
    )

    if risk_plan.get("status") != "VALID":
        raise ValueError(
            "Risk manager rejected the setup."
        )

    validation = risk_plan.get(
        "validation",
        {},
    )

    if not isinstance(validation, dict):
        raise ValueError(
            "Missing risk validation."
        )

    if validation.get("valid") is not True:
        raise ValueError(
            "Risk validation failed."
        )

    return signal


# =========================================================
# DUPLICATE PROTECTION
# =========================================================

def is_duplicate_signal(
    symbol: str,
    strategy: str,
    history: dict,
) -> bool:

    try:
        return bool(
            check_duplicate(
                symbol,
                strategy,
                history=history,
            )
        )

    except Exception as exc:

        logger.error(
            "Duplicate check failed for %s: %s",
            symbol,
            exc,
        )

        # Fail closed: do not send if duplicate
        # status cannot be verified.

        return True


# =========================================================
# SIGNAL TRACKING
# =========================================================

def update_existing_signals(
    ticker_data: dict,
) -> None:

    try:

        expire_old_signals()

        history = load_history()

        if not isinstance(history, dict):
            return

        signals = history.get(
            "signals",
            [],
        )

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

            symbol = item.get("symbol")

            if not symbol:
                continue

            ticker = ticker_data.get(symbol)

            if not isinstance(ticker, dict):
                continue

            current_price = get_ticker_value(
                ticker,
                "last_price",
                "lastPrice",
            )

            if current_price <= 0:
                continue

            signal_id = (
                item.get("signal_id")
                or item.get("id")
            )

            if not signal_id:
                continue

            update_signal_status(
                signal_id,
                current_price,
            )

    except Exception as exc:

        logger.error(
            "Signal tracking update failed: %s",
            exc,
        )


# =========================================================
# TELEGRAM DELIVERY
# =========================================================

def deliver_signal(
    signal: dict,
    history: dict,
) -> bool:

    if not is_eligible_signal(signal):
        return False

    symbol = signal["symbol"]

    strategy = str(
        signal.get("strategy", "")
    ).upper()

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

    if DRY_RUN:

        logger.info(
            "[DRY RUN] Valid signal: %s | %s | Score %s",
            symbol,
            signal.get("classification"),
            signal.get("score"),
        )

        return False

    # Save signal before sending to avoid
    # repeated alerts if a later scan runs.

    result = register_signal(signal)

    if not result:

        logger.error(
            "Signal registration failed: %s",
            symbol,
        )

        return False

    try:

        sent = send_signal(signal)

        if sent is False:

            logger.error(
                "Telegram delivery failed: %s",
                symbol,
            )

            return False

        logger.info(
            "Telegram signal processed: %s",
            symbol,
        )

        return True

    except Exception as exc:

        logger.error(
            "Telegram error for %s: %s",
            symbol,
            exc,
        )

        return False


# =========================================================
# STRATEGY EVALUATION
# =========================================================

def evaluate_candidate(
    candidate: dict,
    market_context: dict,
) -> list:

    symbol = candidate["symbol"]

    results = []

    try:

        market_data = fetch_symbol_market_data(
            symbol
        )

    except Exception as exc:

        logger.warning(
            "Candle data failed for %s: %s",
            symbol,
            exc,
        )

        return results

    strategies = []

    if STRATEGIES_ENABLED["SCALP"]:

        strategies.append(
            (
                "SCALP",
                evaluate_scalp,
                {
                    "5m": market_data["5m"],
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
                {
                    "15m": market_data["15m"],
                    "30m": market_data["30m"],
                    "1h": market_data["1h"],
                },
            )
        )

    for (
        strategy_name,
        evaluator,
        strategy_data,
    ) in strategies:

        try:

            signal = evaluator(
                symbol,
                strategy_data,
                indicators=None,
                market_context=market_context,
            )

            if not is_eligible_signal(signal):
                continue

            signal["strategy"] = strategy_name

            signal["current_price"] = (
                candidate["last_price"]
            )

            signal["last_price"] = (
                candidate["last_price"]
            )

            signal["quote_volume_24h"] = (
                candidate["quote_volume_24h"]
            )

            signal["spread_percent"] = (
                candidate["spread_percent"]
            )

            signal["market_status"] = (
                market_context.get("market_status")
            )

            signal["btc_trend"] = (
                market_context.get("btc_trend")
            )

            signal["generated_at"] = (
                datetime.now(timezone.utc).isoformat()
            )

            signal = attach_risk_plan(signal)

            results.append(signal)

        except Exception as exc:

            logger.info(
                "%s evaluation rejected for %s: %s",
                strategy_name,
                symbol,
                exc,
            )

    return results


# =========================================================
# MAIN SCANNER
# =========================================================

def run_scanner() -> dict:

    started_at = datetime.now(timezone.utc)

    report = {
        "started_at": started_at.isoformat(),
        "mode": "DRY_RUN" if DRY_RUN else "LIVE",
        "market_status": "UNKNOWN",
        "btc_trend": "UNKNOWN",
        "symbols_scanned": 0,
        "candidates_selected": 0,
        "signals_generated": 0,
        "signals_sent": 0,
        "errors": [],
    }

    logger.info("=" * 55)
    logger.info(
        "BINANCE SPOT V3 SCANNER STARTED"
    )
    logger.info("=" * 55)

    try:

        # 1. CONFIGURATION VALIDATION

        validate_scanner_configuration()

        # 2. BTC MARKET ANALYSIS

        market_context = fetch_market_context()

        report["market_status"] = market_context.get(
            "market_status",
            "UNKNOWN",
        )

        report["btc_trend"] = market_context.get(
            "btc_trend",
            "UNKNOWN",
        )

        market_status = report["market_status"]

        if market_status == "UNKNOWN":

            logger.warning(
                "Market filter rejected scanning: UNKNOWN"
            )

            return report

        if market_status == "HIGH_RISK":

            logger.warning(
                "BTC HIGH_RISK: Continuing candidate scan "
                "with strict entry and risk validation."
            )

        # 3. COIN SELECTION
        # collect_candidates() fetches the 24h ticker
        # internally. Do not fetch it again here.

        candidates = collect_candidates()

        report["candidates_selected"] = len(
            candidates
        )

        if not candidates:

            logger.info(
                "No eligible candidates found."
            )

            return report

        # 4. TRACK EXISTING SIGNALS
        # Ticker data is needed here only in LIVE mode.
        # DRY RUN does not update or register signals.

        if not DRY_RUN:

            ticker_data = get_24h_ticker()

            if not isinstance(ticker_data, dict):
                ticker_data = {}

            update_existing_signals(
                ticker_data
            )

        history = load_history()

        if not isinstance(history, dict):
            history = {}

        # 5. ENTRY + RISK VALIDATION

        signals = []

        for candidate in candidates:

            if len(signals) >= MAX_SIGNALS_PER_RUN:
                break

            report["symbols_scanned"] += 1

            candidate_signals = evaluate_candidate(
                candidate,
                market_context,
            )

            for signal in candidate_signals:

                if len(signals) >= MAX_SIGNALS_PER_RUN:
                    break

                signals.append(signal)

        report["signals_generated"] = len(
            signals
        )

        # 6. TELEGRAM DELIVERY

        for signal in signals:

            sent = deliver_signal(
                signal,
                history,
            )

            if sent:
                report["signals_sent"] += 1

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

        finished_at = datetime.now(timezone.utc)

        report["finished_at"] = (
            finished_at.isoformat()
        )

        logger.info(
            "Scanner finished | Candidates: %s | "
            "Signals: %s | Sent: %s | Errors: %s",
            report["candidates_selected"],
            report["signals_generated"],
            report["signals_sent"],
            len(report["errors"]),
        )


# =========================================================
# APPLICATION ENTRY POINT
# =========================================================

if __name__ == "__main__":

    result = run_scanner()

    logger.info(
        "FINAL SCAN REPORT: %s",
        result,
    )
