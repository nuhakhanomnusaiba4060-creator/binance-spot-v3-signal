
"""
File: coin_selector.py
System: Binance Spot V4 Smart Signal Scanner
Code Version: 4.0.1
Formula Version: 4.0
Python: 3.11+

Purpose:
- Select eligible Binance Spot USDT pairs.
- Validate 24h market activity.
- Analyze bid/ask spread and order-book depth.
- Estimate order-book imbalance and slippage.
- Reject illiquid, unstable, leveraged and unsuitable assets.

Important:
- Spot only. No Futures or Margin.
- This module selects candidates; it does not generate BUY signals.
- Missing order-book data is marked UNVERIFIED, never fabricated.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ============================================================
# CONFIGURATION
# ============================================================

QUOTE_ASSET = "USDT"

DEFAULT_MIN_QUOTE_VOLUME_24H = 1_000_000.0
DEFAULT_MIN_TRADES_24H = 1_000
DEFAULT_MAX_SPREAD_PERCENT = 0.25
DEFAULT_MIN_DEPTH_USDT = 10_000.0
DEFAULT_MAX_SLIPPAGE_PERCENT = 0.20

DEFAULT_ORDER_BOOK_LEVELS = 10
DEFAULT_DEPTH_LEVELS = 5
DEFAULT_MAX_CANDIDATES = 80

EXCLUDED_BASE_ASSETS = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP",
    "DAI", "USDE", "USDS", "UST", "USTC", "USDD",
    "EUR", "GBP", "AUD", "TRY", "BRL", "BIDR",
    "IDRT", "UAH", "RUB", "NGN", "JPY", "ARS",
    "PAXG",
}

LEVERAGED_SUFFIXES = (
    "UP", "DOWN", "BULL", "BEAR",
)

EXCLUDED_SYMBOL_PATTERNS = (
    r".*USDT\d+$",
    r".*_[0-9]+$",
)

TOKENIZED_ASSET_BASES = {
    "AAPL", "AMZN", "GOOGL", "GOOG", "META", "MSFT",
    "NVDA", "TSLA", "COIN", "MSTR", "SPY", "QQQ",
    "NFLX", "INTC", "AMD", "IBM", "ORCL", "BABA",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError, OverflowError):
        return default


def _positive(value: Any, default: float = 0.0) -> float:
    result = _number(value, default)
    if result is None or result < 0:
        return default
    return result


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _extract_base_asset(symbol: str) -> Optional[str]:
    symbol = str(symbol or "").upper().strip()

    if not symbol.endswith(QUOTE_ASSET):
        return None

    base = symbol[:-len(QUOTE_ASSET)]
    return base or None


def is_eligible_spot_usdt_symbol(
    symbol: str,
    status: str = "TRADING",
    quote_asset: str = "USDT",
    is_spot_trading_allowed: bool = True,
) -> bool:

    symbol = str(symbol or "").upper().strip()
    quote_asset = str(quote_asset or "").upper().strip()

    if not symbol or quote_asset != QUOTE_ASSET:
        return False

    if not symbol.endswith(QUOTE_ASSET):
        return False

    if status and str(status).upper() != "TRADING":
        return False

    if not is_spot_trading_allowed:
        return False

    base = _extract_base_asset(symbol)

    if not base:
        return False

    if base in EXCLUDED_BASE_ASSETS:
        return False

    if base in TOKENIZED_ASSET_BASES:
        return False

    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return False

    for pattern in EXCLUDED_SYMBOL_PATTERNS:
        if re.fullmatch(pattern, symbol):
            return False

    if not re.fullmatch(r"[A-Z0-9]+USDT", symbol):
        return False

    return True


def _ticker_symbol(ticker: Dict[str, Any]) -> str:
    return str(ticker.get("symbol", "")).upper().strip()


def _ticker_value(
    ticker: Dict[str, Any],
    *keys: str,
    default: float = 0.0,
) -> float:

    for key in keys:
        if key in ticker:
            value = _number(ticker.get(key))
            if value is not None:
                return value

    return default


# ============================================================
# MARKET ACTIVITY VALIDATION
# ============================================================

def validate_ticker(
    ticker: Dict[str, Any],
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME_24H,
    min_trades: int = DEFAULT_MIN_TRADES_24H,
) -> Tuple[bool, str, Dict[str, float]]:

    if not isinstance(ticker, dict):
        return False, "INVALID_TICKER", {}

    symbol = _ticker_symbol(ticker)

    if not is_eligible_spot_usdt_symbol(symbol):
        return False, "INELIGIBLE_SYMBOL", {}

    quote_volume = _ticker_value(
        ticker, "quoteVolume", "quote_volume", default=0.0
    )

    base_volume = _ticker_value(
        ticker, "volume", "baseVolume", "base_volume", default=0.0
    )

    last_price = _ticker_value(
        ticker, "lastPrice", "last_price", "price", default=0.0
    )

    trade_count = _ticker_value(
        ticker, "count", "tradeCount", "trade_count", default=0.0
    )

    change_percent = _ticker_value(
        ticker, "priceChangePercent", "change_percent", default=0.0
    )

    if last_price <= 0:
        return False, "INVALID_LAST_PRICE", {}

    if quote_volume < min_quote_volume:
        return False, "LOW_24H_QUOTE_VOLUME", {}

    if trade_count < min_trades:
        return False, "LOW_24H_TRADE_COUNT", {}

    metrics = {
        "quote_volume_24h": quote_volume,
        "base_volume_24h": base_volume,
        "last_price": last_price,
        "trade_count_24h": trade_count,
        "price_change_percent_24h": change_percent,
    }

    return True, "VALID", metrics


# ============================================================
# ORDER BOOK VALIDATION
# ============================================================

def _parse_book_side(
    levels: Any,
) -> List[Tuple[float, float]]:

    parsed: List[Tuple[float, float]] = []

    if not isinstance(levels, (list, tuple)):
        return parsed

    for item in levels:

        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue

        price = _number(item[0])
        quantity = _number(item[1])

        if price is None or quantity is None:
            continue

        if price <= 0 or quantity <= 0:
            continue

        parsed.append((price, quantity))

    return parsed


def validate_order_book(
    order_book: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:

    if not isinstance(order_book, dict):
        return False, "ORDER_BOOK_MISSING", {}

    bids = _parse_book_side(order_book.get("bids"))
    asks = _parse_book_side(order_book.get("asks"))

    if not bids or not asks:
        return False, "ORDER_BOOK_EMPTY_OR_INVALID", {}

    best_bid = max(price for price, _ in bids)
    best_ask = min(price for price, _ in asks)

    if best_bid <= 0 or best_ask <= 0:
        return False, "INVALID_BEST_PRICE", {}

    if best_ask <= best_bid:
        return False, "CROSSED_OR_INVALID_BOOK", {}

    return True, "VALID", {
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
    }


# ============================================================
# SPREAD
# ============================================================

def compute_spread_percent(
    order_book: Dict[str, Any],
) -> Optional[float]:

    valid, _, data = validate_order_book(order_book)

    if not valid:
        return None

    bid = data["best_bid"]
    ask = data["best_ask"]
    midpoint = (bid + ask) / 2.0

    if midpoint <= 0:
        return None

    return ((ask - bid) / midpoint) * 100.0


# ============================================================
# ORDER BOOK DEPTH
# ============================================================

def compute_top_depth_usdt(
    order_book: Dict[str, Any],
    levels: int = DEFAULT_DEPTH_LEVELS,
) -> Optional[Dict[str, float]]:

    valid, _, data = validate_order_book(order_book)

    if not valid:
        return None

    levels = max(1, int(levels))

    bids = sorted(
        data["bids"],
        key=lambda x: x[0],
        reverse=True,
    )[:levels]

    asks = sorted(
        data["asks"],
        key=lambda x: x[0],
    )[:levels]

    bid_depth = sum(price * quantity for price, quantity in bids)
    ask_depth = sum(price * quantity for price, quantity in asks)

    return {
        "bid_depth_usdt": bid_depth,
        "ask_depth_usdt": ask_depth,
        "total_depth_usdt": bid_depth + ask_depth,
        "minimum_side_depth_usdt": min(bid_depth, ask_depth),
    }


# ============================================================
# ORDER BOOK IMBALANCE
# ============================================================

def compute_order_book_imbalance(
    order_book: Dict[str, Any],
    levels: int = DEFAULT_DEPTH_LEVELS,
) -> Optional[float]:

    depth = compute_top_depth_usdt(order_book, levels)

    if not depth:
        return None

    bid_depth = depth["bid_depth_usdt"]
    ask_depth = depth["ask_depth_usdt"]
    total = bid_depth + ask_depth

    if total <= 0:
        return None

    return (bid_depth - ask_depth) / total


# ============================================================
# SLIPPAGE ESTIMATION
# ============================================================

def estimate_market_order_slippage(
    order_book: Dict[str, Any],
    order_value_usdt: float,
    side: str = "BUY",
) -> Optional[float]:

    valid, _, data = validate_order_book(order_book)

    if not valid:
        return None

    order_value = _positive(order_value_usdt)

    if order_value <= 0:
        return None

    side = str(side or "BUY").upper()

    if side == "BUY":
        levels = sorted(data["asks"], key=lambda x: x[0])
        reference_price = data["best_ask"]

    elif side == "SELL":
        levels = sorted(
            data["bids"],
            key=lambda x: x[0],
            reverse=True,
        )
        reference_price = data["best_bid"]

    else:
        return None

    remaining = order_value
    filled_quantity = 0.0
    spent_or_received = 0.0

    for price, quantity in levels:

        available_value = price * quantity
        take_value = min(remaining, available_value)

        if take_value <= 0:
            continue

        take_quantity = take_value / price

        filled_quantity += take_quantity
        spent_or_received += take_value
        remaining -= take_value

        if remaining <= 1e-9:
            break

    if remaining > max(0.01, order_value * 0.001):
        return None

    if filled_quantity <= 0:
        return None

    average_price = spent_or_received / filled_quantity

    if reference_price <= 0:
        return None

    if side == "BUY":
        slippage = (
            (average_price - reference_price) / reference_price
        ) * 100

    else:
        slippage = (
            (reference_price - average_price) / reference_price
        ) * 100

    return max(0.0, slippage)


# ============================================================
# COMPLETE ORDER BOOK ANALYSIS
# ============================================================

def analyze_order_book(
    order_book: Dict[str, Any],
    depth_levels: int = DEFAULT_DEPTH_LEVELS,
    order_value_usdt: float = 100.0,
) -> Dict[str, Any]:

    valid, reason, parsed = validate_order_book(order_book)

    if not valid:
        return {
            "status": "UNVERIFIED",
            "valid": False,
            "reason": reason,
            "spread_percent": None,
            "bid_depth_usdt": None,
            "ask_depth_usdt": None,
            "total_depth_usdt": None,
            "minimum_side_depth_usdt": None,
            "imbalance": None,
            "buy_slippage_percent": None,
            "sell_slippage_percent": None,
        }

    spread = compute_spread_percent(order_book)

    depth = compute_top_depth_usdt(
        order_book,
        depth_levels,
    )

    imbalance = compute_order_book_imbalance(
        order_book,
        depth_levels,
    )

    buy_slippage = estimate_market_order_slippage(
        order_book,
        order_value_usdt,
        "BUY",
    )

    sell_slippage = estimate_market_order_slippage(
        order_book,
        order_value_usdt,
        "SELL",
    )

    return {
        "status": "VERIFIED",
        "valid": True,
        "reason": "VALID",
        "spread_percent": spread,
        "bid_depth_usdt": depth["bid_depth_usdt"] if depth else None,
        "ask_depth_usdt": depth["ask_depth_usdt"] if depth else None,
        "total_depth_usdt": depth["total_depth_usdt"] if depth else None,
        "minimum_side_depth_usdt": (
            depth["minimum_side_depth_usdt"] if depth else None
        ),
        "imbalance": imbalance,
        "buy_slippage_percent": buy_slippage,
        "sell_slippage_percent": sell_slippage,
        "best_bid": parsed["best_bid"],
        "best_ask": parsed["best_ask"],
    }


# ============================================================
# LIQUIDITY SCORE
# ============================================================

def calculate_liquidity_score(
    quote_volume_24h: float,
    spread_percent: Optional[float],
    minimum_side_depth_usdt: Optional[float],
    slippage_percent: Optional[float],
) -> float:

    score = 0.0

    if quote_volume_24h >= 50_000_000:
        score += 30
    elif quote_volume_24h >= 20_000_000:
        score += 27
    elif quote_volume_24h >= 10_000_000:
        score += 24
    elif quote_volume_24h >= 5_000_000:
        score += 21
    elif quote_volume_24h >= 2_000_000:
        score += 17
    elif quote_volume_24h >= 1_000_000:
        score += 13

    if spread_percent is not None:
        if spread_percent <= 0.03:
            score += 25
        elif spread_percent <= 0.06:
            score += 22
        elif spread_percent <= 0.10:
            score += 18
        elif spread_percent <= 0.15:
            score += 13
        elif spread_percent <= 0.25:
            score += 7

    if minimum_side_depth_usdt is not None:
        if minimum_side_depth_usdt >= 500_000:
            score += 25
        elif minimum_side_depth_usdt >= 250_000:
            score += 22
        elif minimum_side_depth_usdt >= 100_000:
            score += 18
        elif minimum_side_depth_usdt >= 50_000:
            score += 14
        elif minimum_side_depth_usdt >= 10_000:
            score += 8

    if slippage_percent is not None:
        if slippage_percent <= 0.02:
            score += 20
        elif slippage_percent <= 0.05:
            score += 17
        elif slippage_percent <= 0.10:
            score += 13
        elif slippage_percent <= 0.20:
            score += 8

    return round(min(100.0, score), 2)


# ============================================================
# CANDIDATE VALIDATION
# ============================================================

def validate_candidate(
    candidate: Dict[str, Any],
    order_book: Optional[Dict[str, Any]] = None,
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME_24H,
    max_spread_percent: float = DEFAULT_MAX_SPREAD_PERCENT,
    min_depth_usdt: float = DEFAULT_MIN_DEPTH_USDT,
    max_slippage_percent: float = DEFAULT_MAX_SLIPPAGE_PERCENT,
) -> Tuple[bool, str]:

    if not isinstance(candidate, dict):
        return False, "INVALID_CANDIDATE"

    symbol = _ticker_symbol(candidate)

    if not is_eligible_spot_usdt_symbol(symbol):
        return False, "INELIGIBLE_SYMBOL"

    valid_ticker, ticker_reason, _ = validate_ticker(
        candidate,
        min_quote_volume=min_quote_volume,
        min_trades=DEFAULT_MIN_TRADES_24H,
    )

    if not valid_ticker:
        return False, ticker_reason

    if order_book is None:
        return False, "ORDER_BOOK_UNVERIFIED"

    book = analyze_order_book(order_book)

    if not book["valid"]:
        return False, "ORDER_BOOK_INVALID"

    spread = book["spread_percent"]
    depth = book["minimum_side_depth_usdt"]
    slippage = book["buy_slippage_percent"]

    if spread is None or spread > max_spread_percent:
        return False, "SPREAD_TOO_HIGH"

    if depth is None or depth < min_depth_usdt:
        return False, "INSUFFICIENT_ORDER_BOOK_DEPTH"

    if slippage is None or slippage > max_slippage_percent:
        return False, "SLIPPAGE_TOO_HIGH"

    return True, "VALID"


# ============================================================
# CANDIDATE ENRICHMENT
# ============================================================

def build_candidate(
    ticker: Dict[str, Any],
    order_book: Optional[Dict[str, Any]] = None,
    order_value_usdt: float = 100.0,
) -> Dict[str, Any]:

    valid, reason, ticker_metrics = validate_ticker(ticker)

    result: Dict[str, Any] = {
        "symbol": _ticker_symbol(ticker),
        "eligible": valid,
        "ticker_status": reason,
        "liquidity_status": "UNVERIFIED",
        "quote_volume_24h": ticker_metrics.get("quote_volume_24h"),
        "base_volume_24h": ticker_metrics.get("base_volume_24h"),
        "last_price": ticker_metrics.get("last_price"),
        "trade_count_24h": ticker_metrics.get("trade_count_24h"),
        "price_change_percent_24h": ticker_metrics.get(
            "price_change_percent_24h"
        ),
        "spread_percent": None,
        "bid_depth_usdt": None,
        "ask_depth_usdt": None,
        "total_depth_usdt": None,
        "minimum_side_depth_usdt": None,
        "order_book_imbalance": None,
        "buy_slippage_percent": None,
        "sell_slippage_percent": None,
        "liquidity_score": 0.0,
        "selection_status": "REJECTED",
        "rejection_reason": reason,
    }

    if not valid:
        return result

    if order_book is None:
        result["rejection_reason"] = "ORDER_BOOK_UNVERIFIED"
        return result

    book = analyze_order_book(
        order_book,
        order_value_usdt=order_value_usdt,
    )

    result.update({
        "liquidity_status": book["status"],
        "spread_percent": book["spread_percent"],
        "bid_depth_usdt": book["bid_depth_usdt"],
        "ask_depth_usdt": book["ask_depth_usdt"],
        "total_depth_usdt": book["total_depth_usdt"],
        "minimum_side_depth_usdt": book["minimum_side_depth_usdt"],
        "order_book_imbalance": book["imbalance"],
        "buy_slippage_percent": book["buy_slippage_percent"],
        "sell_slippage_percent": book["sell_slippage_percent"],
    })

    score = calculate_liquidity_score(
        quote_volume_24h=result["quote_volume_24h"] or 0.0,
        spread_percent=result["spread_percent"],
        minimum_side_depth_usdt=result["minimum_side_depth_usdt"],
        slippage_percent=result["buy_slippage_percent"],
    )

    result["liquidity_score"] = score

    accepted, validation_reason = validate_candidate(
        ticker,
        order_book=order_book,
    )

    result["selection_status"] = (
        "ACCEPTED" if accepted else "REJECTED"
    )

    result["rejection_reason"] = (
        "NONE" if accepted else validation_reason
    )

    return result


# ============================================================
# SELECT COINS
# ============================================================

def select_coins(
    tickers: Iterable[Dict[str, Any]],
    order_books: Optional[Dict[str, Dict[str, Any]]] = None,
    max_symbols: int = DEFAULT_MAX_CANDIDATES,
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME_24H,
    max_spread_percent: float = DEFAULT_MAX_SPREAD_PERCENT,
    min_depth_usdt: float = DEFAULT_MIN_DEPTH_USDT,
    max_slippage_percent: float = DEFAULT_MAX_SLIPPAGE_PERCENT,
    order_value_usdt: float = 100.0,
) -> List[Dict[str, Any]]:

    order_books = order_books or {}
    selected: List[Dict[str, Any]] = []

    if not isinstance(max_symbols, int) or max_symbols < 1:
        max_symbols = DEFAULT_MAX_CANDIDATES

    for ticker in tickers or []:

        if not isinstance(ticker, dict):
            continue

        symbol = _ticker_symbol(ticker)
        book = order_books.get(symbol)

        candidate = build_candidate(
            ticker,
            order_book=book,
            order_value_usdt=order_value_usdt,
        )

        if not candidate.get("eligible"):
            continue

        accepted, reason = validate_candidate(
            ticker,
            order_book=book,
            min_quote_volume=min_quote_volume,
            max_spread_percent=max_spread_percent,
            min_depth_usdt=min_depth_usdt,
            max_slippage_percent=max_slippage_percent,
        )

        candidate["selection_status"] = (
            "ACCEPTED" if accepted else "REJECTED"
        )

        candidate["rejection_reason"] = (
            "NONE" if accepted else reason
        )

        if accepted:
            selected.append(candidate)

    selected.sort(
        key=lambda item: (
            item.get("liquidity_score", 0.0),
            item.get("quote_volume_24h", 0.0),
        ),
        reverse=True,
    )

    return selected[:max_symbols]


# ============================================================
# SUMMARY / DIAGNOSTICS
# ============================================================

def get_selection_summary(
    candidates: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:

    items = list(candidates or [])

    accepted = [
        item for item in items
        if item.get("selection_status") == "ACCEPTED"
    ]

    rejected = [
        item for item in items
        if item.get("selection_status") != "ACCEPTED"
    ]

    rejection_counts: Dict[str, int] = {}

    for item in rejected:
        reason = str(item.get("rejection_reason", "UNKNOWN"))
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    return {
        "total_candidates": len(items),
        "accepted_candidates": len(accepted),
        "rejected_candidates": len(rejected),
        "rejection_reasons": rejection_counts,
        "top_symbols": [
            item.get("symbol")
            for item in accepted[:10]
        ],
    }


def get_coin_selector_config() -> Dict[str, Any]:
    return {
        "quote_asset": QUOTE_ASSET,
        "min_quote_volume_24h": DEFAULT_MIN_QUOTE_VOLUME_24H,
        "min_trades_24h": DEFAULT_MIN_TRADES_24H,
        "max_spread_percent": DEFAULT_MAX_SPREAD_PERCENT,
        "min_depth_usdt": DEFAULT_MIN_DEPTH_USDT,
        "max_slippage_percent": DEFAULT_MAX_SLIPPAGE_PERCENT,
        "order_book_levels": DEFAULT_ORDER_BOOK_LEVELS,
        "depth_levels": DEFAULT_DEPTH_LEVELS,
        "max_candidates": DEFAULT_MAX_CANDIDATES,
        "spot_only": True,
        "formula_version": "4.0",
    }


# ============================================================
# SELF-CHECK
# ============================================================

def self_check() -> Dict[str, Any]:
    """Run deterministic local checks without network access."""

    tests: Dict[str, bool] = {}
    error = None

    sample_book = {
        "bids": [
            ["100.00", "1000"],
            ["99.90", "1000"],
            ["99.80", "1000"],
            ["99.70", "1000"],
            ["99.60", "1000"],
        ],
        "asks": [
            ["100.10", "1000"],
            ["100.20", "1000"],
            ["100.30", "1000"],
            ["100.40", "1000"],
            ["100.50", "1000"],
        ],
    }

    try:
        tests["btc_spot_symbol"] = (
            is_eligible_spot_usdt_symbol("BTCUSDT")
        )

        tests["eth_spot_symbol"] = (
            is_eligible_spot_usdt_symbol("ETHUSDT")
        )

        tests["non_usdt_rejected"] = (
            not is_eligible_spot_usdt_symbol("BTCBUSD")
        )

        tests["leveraged_token_rejected"] = (
            not is_eligible_spot_usdt_symbol("BTCUPUSDT")
        )

        tests["stablecoin_rejected"] = (
            not is_eligible_spot_usdt_symbol("USDCUSDT")
        )

        tests["tokenized_equity_rejected"] = (
            not is_eligible_spot_usdt_symbol("TSLAUSDT")
        )

        spread = compute_spread_percent(sample_book)

        tests["spread_calculation"] = (
            spread is not None
            and math.isfinite(spread)
            and spread > 0
        )

        depth = compute_top_depth_usdt(sample_book, levels=5)

        tests["order_book_depth"] = (
            isinstance(depth, dict)
            and depth.get("bid_depth_usdt", 0) > 0
            and depth.get("ask_depth_usdt", 0) > 0
        )

        imbalance = compute_order_book_imbalance(sample_book)

        tests["order_book_imbalance"] = (
            imbalance is not None
            and math.isfinite(imbalance)
            and -1.0 <= imbalance <= 1.0
        )

        slippage = estimate_market_order_slippage(
            sample_book,
            order_value_usdt=100.0,
            side="BUY",
        )

        tests["buy_slippage"] = (
            slippage is not None
            and math.isfinite(slippage)
            and slippage >= 0
        )

        tests["invalid_book_rejected"] = (
            compute_spread_percent({
                "bids": [],
                "asks": [],
            }) is None
        )

        tests["candidate_builder_available"] = callable(build_candidate)
        tests["candidate_validator_available"] = callable(validate_candidate)
        tests["coin_selector_available"] = callable(select_coins)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        tests["runtime_exception"] = False

    passed_count = sum(bool(value) for value in tests.values())
    total_count = len(tests)
    passed = passed_count == total_count and error is None

    return {
        "ok": passed,
        "passed": passed,
        "tests": tests,
        "passed_count": passed_count,
        "total_count": total_count,
        "error": error,
    }


if __name__ == "__main__":
    result = self_check()

    print("COIN SELECTOR SELF-CHECK:", "PASS" if result["ok"] else "FAIL")
    print(f"Passed: {result['passed_count']}/{result['total_count']}")
    print("Formula Version: 4.0")
    print("Spot Only: YES")

    if not result["ok"]:
        for name, status in result["tests"].items():
            if not status:
                print("FAILED:", name)

        raise SystemExit(1)
