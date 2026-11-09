
"""
Binance Spot V3 Smart Signal Scanner
Coin Selection Engine

Responsibilities:
- Select eligible Binance Spot USDT symbols.
- Support both snake_case and Binance camelCase ticker fields.
- Filter by 24h quote volume and trade count.
- Validate order-book spread and liquidity.
- Reject invalid, illiquid, and leveraged-token symbols.
- Return structured candidate records.

No trading signals are generated in this module.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any

from config import FILTER_CONFIG


logger = logging.getLogger(__name__)


# =========================================================
# CONFIGURATION HELPERS
# =========================================================

def _normalize_key(value: str) -> str:
    return str(value).lower().replace("_", "").replace("-", "").replace(" ", "")


def _find_config_value(config: Any, names: tuple, default: Any) -> Any:
    if not isinstance(config, dict):
        return default

    wanted = {_normalize_key(name) for name in names}

    for key, value in config.items():
        if _normalize_key(key) in wanted:
            return value

    for value in config.values():
        if isinstance(value, dict):
            result = _find_config_value(value, names, None)
            if result is not None:
                return result

    return default


MIN_QUOTE_VOLUME = float(
    _find_config_value(
        FILTER_CONFIG,
        ("MIN_24H_QUOTE_VOLUME_USDT", "MIN_QUOTE_VOLUME_USDT"),
        3_000_000,
    )
)

MIN_TRADES = int(
    _find_config_value(
        FILTER_CONFIG,
        ("MIN_24H_TRADES", "MIN_TRADES"),
        1000,
    )
)

MAX_SPREAD_PERCENT = float(
    _find_config_value(
        FILTER_CONFIG,
        ("MAX_SPREAD_PERCENT", "MAX_SPREAD_PCT"),
        0.15,
    )
)

REQUIRE_ORDER_BOOK = bool(
    _find_config_value(
        FILTER_CONFIG,
        ("REQUIRE_ORDER_BOOK",),
        True,
    )
)

MIN_ORDER_BOOK_DEPTH = float(
    _find_config_value(
        FILTER_CONFIG,
        ("MIN_ORDER_BOOK_DEPTH_USDT", "MIN_ORDER_BOOK_DEPTH"),
        0,
    )
)


# =========================================================
# SYMBOL VALIDATION
# =========================================================

LEVERAGED_SUFFIXES = (
    "UPUSDT",
    "DOWNUSDT",
    "BULLUSDT",
    "BEARUSDT",
)

EXCLUDED_SYMBOLS = {
    "TSLAUSDT",
    "AAPLUSDT",
    "NVDAUSDT",
    "AMZNUSDT",
    "GOOGLUSDT",
    "METAUSDT",
    "MSFTUSDT",
    "MSTRUSDT",
    "COINUSDT",
    "HOODUSDT",
}


def _is_valid_symbol(symbol: str) -> bool:
    if not isinstance(symbol, str):
        return False

    symbol = symbol.upper().strip()

    if not symbol.endswith("USDT"):
        return False

    if len(symbol) <= 4:
        return False

    if symbol in EXCLUDED_SYMBOLS:
        return False

    if symbol.endswith(LEVERAGED_SUFFIXES):
        return False

    return True


# =========================================================
# GENERAL DATA VALIDATION
# =========================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError, OverflowError):
        return default


def _get_field(data: dict, *names: str, default=None):
    """
    Read either snake_case or camelCase field names.
    """

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
# TICKER NORMALIZATION
# =========================================================

def _normalize_ticker_data(ticker_data: Any) -> dict:
    """
    Supported input formats:

    1. Dictionary keyed by symbol:
       {
           "BTCUSDT": {
               "quote_volume": "...",
               "trade_count": "..."
           }
       }

    2. Binance raw ticker list:
       [
           {
               "symbol": "BTCUSDT",
               "quoteVolume": "...",
               "count": "..."
           }
       ]
    """

    result = {}

    if isinstance(ticker_data, dict):

        for symbol, ticker in ticker_data.items():

            if not isinstance(ticker, dict):
                continue

            normalized_symbol = str(symbol).upper().strip()

            if not _is_valid_symbol(normalized_symbol):
                continue

            result[normalized_symbol] = ticker

    elif isinstance(ticker_data, list):

        for ticker in ticker_data:

            if not isinstance(ticker, dict):
                continue

            symbol = _get_field(ticker, "symbol")

            if not symbol:
                continue

            symbol = str(symbol).upper().strip()

            if not _is_valid_symbol(symbol):
                continue

            result[symbol] = ticker

    else:
        logger.warning("Unsupported ticker data format.")

    return result


# =========================================================
# ORDER BOOK ANALYSIS
# =========================================================

def analyze_order_book(order_book: dict) -> dict:
    """
    Calculate:
    - Best bid
    - Best ask
    - Spread percentage
    - Bid depth
    - Ask depth
    - Total depth
    - Liquidity status

    Binance order-book levels:
        [[price, quantity], ...]
    """

    result = {
        "valid": False,
        "best_bid": 0.0,
        "best_ask": 0.0,
        "spread_percent": None,
        "bid_depth_usdt": 0.0,
        "ask_depth_usdt": 0.0,
        "total_depth_usdt": 0.0,
        "liquid": False,
        "reason": None,
    }

    if not isinstance(order_book, dict):
        result["reason"] = "INVALID_ORDER_BOOK"
        return result

    bids = order_book.get("bids")
    asks = order_book.get("asks")

    if not isinstance(bids, list) or not isinstance(asks, list):
        result["reason"] = "MISSING_BIDS_OR_ASKS"
        return result

    if not bids or not asks:
        result["reason"] = "EMPTY_ORDER_BOOK"
        return result

    try:
        valid_bids = []
        valid_asks = []

        for level in bids:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue

            price = _safe_float(level[0])
            quantity = _safe_float(level[1])

            if price > 0 and quantity > 0:
                valid_bids.append((price, quantity))

        for level in asks:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue

            price = _safe_float(level[0])
            quantity = _safe_float(level[1])

            if price > 0 and quantity > 0:
                valid_asks.append((price, quantity))

        if not valid_bids or not valid_asks:
            result["reason"] = "INVALID_ORDER_BOOK_LEVELS"
            return result

        best_bid = max(price for price, _ in valid_bids)
        best_ask = min(price for price, _ in valid_asks)

        if best_bid <= 0 or best_ask <= 0:
            result["reason"] = "INVALID_BEST_PRICE"
            return result

        if best_ask <= best_bid:
            result["reason"] = "CROSSED_ORDER_BOOK"
            return result

        mid_price = (best_bid + best_ask) / 2

        spread_percent = (
            (best_ask - best_bid) / mid_price
        ) * 100

        bid_depth = sum(
            price * quantity
            for price, quantity in valid_bids
        )

        ask_depth = sum(
            price * quantity
            for price, quantity in valid_asks
        )

        total_depth = bid_depth + ask_depth

        result.update({
            "valid": True,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_percent": spread_percent,
            "bid_depth_usdt": bid_depth,
            "ask_depth_usdt": ask_depth,
            "total_depth_usdt": total_depth,
            "liquid": (
                spread_percent <= MAX_SPREAD_PERCENT
                and total_depth >= MIN_ORDER_BOOK_DEPTH
            ),
            "reason": None,
        })

        return result

    except Exception as exc:
        logger.warning("Order-book analysis failed: %s", exc)
        result["reason"] = "ORDER_BOOK_ANALYSIS_ERROR"
        return result


# =========================================================
# MAIN COIN SELECTION ENGINE
# =========================================================

def select_coins(
    symbols: list,
    ticker_data: Any,
    order_book_data: dict,
) -> list:
    """
    Select eligible Binance Spot USDT candidates.

    Returns:
        List of candidate dictionaries.

    This function does not generate BUY signals.
    """

    if not isinstance(symbols, list):
        logger.error("Symbols must be a list.")
        return []

    if not isinstance(order_book_data, dict):
        order_book_data = {}

    ticker_map = _normalize_ticker_data(ticker_data)

    candidates = []

    for raw_symbol in symbols:

        if not isinstance(raw_symbol, str):
            continue

        symbol = raw_symbol.upper().strip()

        if not _is_valid_symbol(symbol):
            continue

        ticker = ticker_map.get(symbol)

        if not isinstance(ticker, dict):
            continue

        # Accept snake_case and Binance camelCase.

        quote_volume = _safe_float(
            _get_field(
                ticker,
                "quote_volume",
                "quoteVolume",
            )
        )

        trade_count = int(
            _safe_float(
                _get_field(
                    ticker,
                    "trade_count",
                    "count",
                )
            )
        )

        last_price = _safe_float(
            _get_field(
                ticker,
                "last_price",
                "lastPrice",
            )
        )

        price_change = _safe_float(
            _get_field(
                ticker,
                "price_change_percent",
                "priceChangePercent",
            )
        )

        base_volume = _safe_float(
            _get_field(
                ticker,
                "volume",
            )
        )

        high_price = _safe_float(
            _get_field(
                ticker,
                "high_price",
                "highPrice",
            )
        )

        low_price = _safe_float(
            _get_field(
                ticker,
                "low_price",
                "lowPrice",
            )
        )

        # Mandatory ticker validation.

        if (
            quote_volume < MIN_QUOTE_VOLUME
            or trade_count < MIN_TRADES
            or last_price <= 0
        ):
            continue

        if high_price > 0 and low_price > 0:
            if high_price < low_price:
                continue

        # Order-book validation.

        order_book = order_book_data.get(symbol)

        if order_book is None:

            if REQUIRE_ORDER_BOOK:
                continue

            order_analysis = {
                "valid": False,
                "best_bid": 0.0,
                "best_ask": 0.0,
                "spread_percent": None,
                "bid_depth_usdt": 0.0,
                "ask_depth_usdt": 0.0,
                "total_depth_usdt": 0.0,
                "liquid": False,
                "reason": "ORDER_BOOK_NOT_AVAILABLE",
            }

        else:

            order_analysis = analyze_order_book(order_book)

            if REQUIRE_ORDER_BOOK and not order_analysis["valid"]:
                continue

            if REQUIRE_ORDER_BOOK and not order_analysis["liquid"]:
                continue

        # Structured candidate record.

        candidate = {
            "symbol": symbol,
            "last_price": last_price,
            "quote_volume_24h": quote_volume,
            "base_volume_24h": base_volume,
            "trade_count_24h": trade_count,
            "price_change_24h_pct": price_change,
            "high_price_24h": high_price,
            "low_price_24h": low_price,

            "order_book": order_analysis,

            "spread_percent": order_analysis["spread_percent"],
            "best_bid": order_analysis["best_bid"],
            "best_ask": order_analysis["best_ask"],

            "bid_depth_usdt": order_analysis["bid_depth_usdt"],
            "ask_depth_usdt": order_analysis["ask_depth_usdt"],
            "total_depth_usdt": order_analysis["total_depth_usdt"],

            "liquidity_status": (
                "VALID" if order_analysis["liquid"]
                else "NOT_VERIFIED"
            ),

            "selection_status": "ELIGIBLE",
            "selected_at": datetime.now(timezone.utc).isoformat(),
        }

        candidates.append(candidate)

    # Highest 24h quote volume first.

    candidates.sort(
        key=lambda item: item["quote_volume_24h"],
        reverse=True,
    )

    logger.info(
        "Coin selection completed: %s eligible candidates.",
        len(candidates),
    )

    return candidates


# =========================================================
# CANDIDATE VALIDATION
# =========================================================

def validate_candidate(candidate: dict) -> bool:
    """
    Final structural validation before passing
    candidate data to the Entry Engine.
    """

    if not isinstance(candidate, dict):
        return False

    symbol = candidate.get("symbol")

    if not _is_valid_symbol(symbol):
        return False

    if _safe_float(candidate.get("last_price")) <= 0:
        return False

    if (
        _safe_float(candidate.get("quote_volume_24h"))
        < MIN_QUOTE_VOLUME
    ):
        return False

    if (
        int(_safe_float(candidate.get("trade_count_24h")))
        < MIN_TRADES
    ):
        return False

    if REQUIRE_ORDER_BOOK:

        order_book = candidate.get("order_book")

        if not isinstance(order_book, dict):
            return False

        if not order_book.get("valid", False):
            return False

        if not order_book.get("liquid", False):
            return False

    return True


# =========================================================
# CONFIGURATION SNAPSHOT
# =========================================================

def get_selector_config() -> dict:
    return {
        "MIN_QUOTE_VOLUME": MIN_QUOTE_VOLUME,
        "MIN_TRADES": MIN_TRADES,
        "MAX_SPREAD_PERCENT": MAX_SPREAD_PERCENT,
        "REQUIRE_ORDER_BOOK": REQUIRE_ORDER_BOOK,
        "MIN_ORDER_BOOK_DEPTH": MIN_ORDER_BOOK_DEPTH,
        "QUOTE_ASSET": "USDT",
        "SPOT_ONLY": True,
        "EXCLUDE_LEVERAGED_TOKENS": True,
    }
