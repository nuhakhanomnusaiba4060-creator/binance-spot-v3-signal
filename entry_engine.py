
"""
Binance Spot V3 Smart Signal Scanner
Coin Selection Engine

Responsibilities:
- Select eligible Binance Spot USDT symbols.
- Filter by 24h quote volume and trade count.
- Validate order-book spread and liquidity data.
- Reject invalid, illiquid, and leveraged-token symbols.
- Return structured candidate records.

No trading signals are generated in this module.
"""

import logging
import math
from typing import Any

from config import FILTER_CONFIG


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CONFIG HELPERS
# ---------------------------------------------------------

def _normalize_key(value: str) -> str:
    return str(value).lower().replace("_", "").replace("-", "").replace(" ", "")


def _find_config_value(data: Any, target: str):
    if not isinstance(data, dict):
        return None

    target_key = _normalize_key(target)

    for key, value in data.items():
        if _normalize_key(key) == target_key:
            return value

    for value in data.values():
        if isinstance(value, dict):
            result = _find_config_value(value, target)
            if result is not None:
                return result

    return None


def _setting(key: str, default: Any):
    value = _find_config_value(FILTER_CONFIG, key)
    return default if value is None else value


MIN_QUOTE_VOLUME = float(
    _setting("MIN_24H_QUOTE_VOLUME_USDT", 3_000_000)
)

MIN_TRADE_COUNT = int(
    _setting("MIN_24H_TRADES", 1000)
)

MAX_SPREAD_PCT = float(
    _setting("MAX_SPREAD_PERCENT", 0.15)
)

REQUIRE_ORDER_BOOK = bool(
    _setting("REQUIRE_ORDER_BOOK", True)
)

MIN_ORDER_BOOK_DEPTH_USDT = float(
    _setting("MIN_ORDER_BOOK_DEPTH_USDT", 0)
)

LEVERAGED_SUFFIXES = (
    "UPUSDT",
    "DOWNUSDT",
    "BULLUSDT",
    "BEARUSDT",
)


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def _to_float(value: Any, default=None):
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_ticker_data(ticker_data):
    """
    Accepts either:
        {"BTCUSDT": {...}, "ETHUSDT": {...}}

    Or:
        [{"symbol": "BTCUSDT", ...}, ...]
    """

    if isinstance(ticker_data, dict):
        result = {}

        for symbol, data in ticker_data.items():
            if isinstance(data, dict):
                result[str(symbol).upper()] = data

        return result

    if isinstance(ticker_data, list):
        result = {}

        for item in ticker_data:
            if not isinstance(item, dict):
                continue

            symbol = item.get("symbol")

            if symbol:
                result[str(symbol).upper()] = item

        return result

    return {}


def _normalize_order_book_data(order_book_data):
    if not isinstance(order_book_data, dict):
        return {}

    return {
        str(symbol).upper(): data
        for symbol, data in order_book_data.items()
        if isinstance(data, dict)
    }


def _is_valid_symbol(symbol: str) -> bool:
    if not isinstance(symbol, str):
        return False

    symbol = symbol.upper().strip()

    if not symbol.endswith("USDT"):
        return False

    if len(symbol) <= 4:
        return False

    if any(symbol.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return False

    return True


# ---------------------------------------------------------
# ORDER BOOK VALIDATION
# ---------------------------------------------------------

def analyze_order_book(order_book):
    """
    Returns spread, bid/ask depth and liquidity status.

    Expected Binance structure:
        {
            "bids": [["price", "quantity"], ...],
            "asks": [["price", "quantity"], ...]
        }
    """

    if not isinstance(order_book, dict):
        return {
            "valid": False,
            "spread_pct": None,
            "bid_depth_usdt": None,
            "ask_depth_usdt": None,
            "total_depth_usdt": None,
            "status": "UNKNOWN",
            "reason": "Order book missing",
        }

    bids = order_book.get("bids")
    asks = order_book.get("asks")

    if not isinstance(bids, list) or not isinstance(asks, list):
        return {
            "valid": False,
            "spread_pct": None,
            "bid_depth_usdt": None,
            "ask_depth_usdt": None,
            "total_depth_usdt": None,
            "status": "INVALID",
            "reason": "Invalid bids or asks",
        }

    if not bids or not asks:
        return {
            "valid": False,
            "spread_pct": None,
            "bid_depth_usdt": None,
            "ask_depth_usdt": None,
            "total_depth_usdt": None,
            "status": "INVALID",
            "reason": "Empty order book",
        }

    try:
        best_bid = _to_float(bids[0][0])
        best_ask = _to_float(asks[0][0])

        if (
            best_bid is None
            or best_ask is None
            or best_bid <= 0
            or best_ask <= 0
            or best_ask <= best_bid
        ):
            raise ValueError("Invalid best bid/ask")

        midpoint = (best_bid + best_ask) / 2

        spread_pct = (
            (best_ask - best_bid) / midpoint
        ) * 100

        bid_depth = 0.0
        ask_depth = 0.0

        for level in bids:
            if len(level) < 2:
                continue

            price = _to_float(level[0])
            quantity = _to_float(level[1])

            if price is not None and quantity is not None:
                if price > 0 and quantity > 0:
                    bid_depth += price * quantity

        for level in asks:
            if len(level) < 2:
                continue

            price = _to_float(level[0])
            quantity = _to_float(level[1])

            if price is not None and quantity is not None:
                if price > 0 and quantity > 0:
                    ask_depth += price * quantity

        total_depth = bid_depth + ask_depth

        if total_depth < MIN_ORDER_BOOK_DEPTH_USDT:
            status = "LOW_DEPTH"
        elif spread_pct > MAX_SPREAD_PCT:
            status = "HIGH_SPREAD"
        else:
            status = "VALID"

        return {
            "valid": status == "VALID",
            "spread_pct": round(spread_pct, 5),
            "bid_depth_usdt": round(bid_depth, 2),
            "ask_depth_usdt": round(ask_depth, 2),
            "total_depth_usdt": round(total_depth, 2),
            "status": status,
            "reason": None if status == "VALID" else status,
        }

    except (ValueError, TypeError, IndexError, ZeroDivisionError):
        return {
            "valid": False,
            "spread_pct": None,
            "bid_depth_usdt": None,
            "ask_depth_usdt": None,
            "total_depth_usdt": None,
            "status": "INVALID",
            "reason": "Order book calculation failed",
        }


# ---------------------------------------------------------
# COIN SELECTION
# ---------------------------------------------------------

def select_coins(symbols, ticker_data, order_book_data):
    """
    Select eligible Binance Spot USDT candidates.

    Parameters:
        symbols:
            List of eligible USDT symbols from data_provider.py.

        ticker_data:
            Binance 24h ticker data, either list or dictionary.

        order_book_data:
            Dictionary keyed by symbol containing order books.

    Returns:
        List of candidate dictionaries sorted by 24h quote volume.

    Important:
        This module only selects candidates.
        It does not generate BUY signals.
    """

    if not isinstance(symbols, (list, tuple, set)):
        logger.error("Invalid symbols input")
        return []

    ticker_map = _normalize_ticker_data(ticker_data)
    order_book_map = _normalize_order_book_data(order_book_data)

    if not ticker_map:
        logger.warning("Ticker data unavailable")
        return []

    candidates = []

    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper().strip()

        if not _is_valid_symbol(symbol):
            continue

        ticker = ticker_map.get(symbol)

        if not isinstance(ticker, dict):
            continue

        quote_volume = _to_float(
            ticker.get("quoteVolume")
        )

        trade_count = _to_int(
            ticker.get("count")
        )

        last_price = _to_float(
            ticker.get("lastPrice")
        )

        price_change_pct = _to_float(
            ticker.get("priceChangePercent")
        )

        if (
            quote_volume is None
            or trade_count <= 0
            or last_price is None
            or last_price <= 0
        ):
            continue

        # 24h liquidity filter
        if quote_volume < MIN_QUOTE_VOLUME:
            continue

        # Minimum trading activity
        if trade_count < MIN_TRADE_COUNT:
            continue

        # Order book validation
        order_book = order_book_map.get(symbol)

        book_result = analyze_order_book(order_book)

        if REQUIRE_ORDER_BOOK and not book_result["valid"]:
            continue

        if (
            book_result["spread_pct"] is not None
            and book_result["spread_pct"] > MAX_SPREAD_PCT
        ):
            continue

        candidates.append({
            "symbol": symbol,
            "last_price": last_price,
            "quote_volume_24h": round(quote_volume, 2),
            "trade_count_24h": trade_count,
            "price_change_24h_pct": price_change_pct,
            "spread_pct": book_result["spread_pct"],
            "bid_depth_usdt": book_result["bid_depth_usdt"],
            "ask_depth_usdt": book_result["ask_depth_usdt"],
            "total_depth_usdt": book_result["total_depth_usdt"],
            "order_book_status": book_result["status"],
            "liquidity_status": "VALID",
            "selection_status": "CANDIDATE",
            "warnings": [],
        })

    # Highest 24h quote volume first
    candidates.sort(
        key=lambda item: item["quote_volume_24h"],
        reverse=True,
    )

    logger.info(
        "Coin selection completed: %s candidates from %s symbols",
        len(candidates),
        len(symbols),
    )

    return candidates


# ---------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------

def validate_candidate(candidate):
    """
    Validate one candidate record.
    """

    if not isinstance(candidate, dict):
        return False

    required_fields = (
        "symbol",
        "last_price",
        "quote_volume_24h",
        "trade_count_24h",
        "selection_status",
    )

    if any(field not in candidate for field in required_fields):
        return False

    if not _is_valid_symbol(candidate["symbol"]):
        return False

    if candidate["selection_status"] != "CANDIDATE":
        return False

    if candidate["last_price"] <= 0:
        return False

    if candidate["quote_volume_24h"] < MIN_QUOTE_VOLUME:
        return False

    if candidate["trade_count_24h"] < MIN_TRADE_COUNT:
        return False

    return True


def get_selector_config():
    return {
        "min_quote_volume_usdt": MIN_QUOTE_VOLUME,
        "min_trade_count": MIN_TRADE_COUNT,
        "max_spread_pct": MAX_SPREAD_PCT,
        "require_order_book": REQUIRE_ORDER_BOOK,
        "min_order_book_depth_usdt": MIN_ORDER_BOOK_DEPTH_USDT,
    }
