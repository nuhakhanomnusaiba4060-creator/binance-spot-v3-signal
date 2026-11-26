"""
Binance Spot V3 Smart Signal Scanner
Coin Selection & Liquidity Validator

Design principles:
- Reject clearly ineligible/non-ASCII/pegged symbols early
- Keep liquidity & spread checks balanced so valid scalping/short-term
  breakout and retest candidates are not over-filtered
"""

from __future__ import annotations

import logging
import math
from typing import Any

import config as cfg
from data_provider import is_eligible_spot_usdt_symbol


logger = logging.getLogger(__name__)


COIN_SELECTION_CONFIG = getattr(
    cfg,
    "COIN_SELECTION_CONFIG",
    getattr(cfg, "FILTER_CONFIG", {}),
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _get_threshold(names: tuple[str, ...], default: float) -> float:
    if not isinstance(COIN_SELECTION_CONFIG, dict):
        return default
    for key in names:
        if key in COIN_SELECTION_CONFIG and COIN_SELECTION_CONFIG[key] is not None:
            return _safe_float(COIN_SELECTION_CONFIG[key], default)
    return default


def compute_spread_percent(order_book: dict[str, Any] | None, fallback_price: float = 0.0) -> float:
    if not isinstance(order_book, dict):
        return 0.0

    bids = order_book.get("bids") or []
    asks = order_book.get("asks") or []

    if not bids or not asks:
        return 0.0

    best_bid = _safe_float(bids[0][0]) if len(bids[0]) >= 1 else 0.0
    best_ask = _safe_float(asks[0][0]) if len(asks[0]) >= 1 else 0.0

    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        return 0.0

    mid = (best_bid + best_ask) / 2.0
    reference = mid if mid > 0 else fallback_price
    if reference <= 0:
        return 0.0

    return ((best_ask - best_bid) / reference) * 100.0


def compute_top_depth_usdt(order_book: dict[str, Any] | None, levels: int = 10) -> tuple[float, float]:
    if not isinstance(order_book, dict):
        return 0.0, 0.0

    bids = (order_book.get("bids") or [])[:levels]
    asks = (order_book.get("asks") or [])[:levels]

    bid_usdt = sum(
        _safe_float(row[0]) * _safe_float(row[1])
        for row in bids
        if isinstance(row, (list, tuple)) and len(row) >= 2
    )
    ask_usdt = sum(
        _safe_float(row[0]) * _safe_float(row[1])
        for row in asks
        if isinstance(row, (list, tuple)) and len(row) >= 2
    )
    return bid_usdt, ask_usdt


def select_coins(
    symbols: list[str],
    ticker_data: dict[str, Any],
    order_books: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    min_quote_volume = _get_threshold(
        ("MIN_24H_QUOTE_VOLUME_USDT", "MIN_QUOTE_VOLUME_USDT"),
        3_000_000.0,
    )
    min_trades = int(
        _get_threshold(
            ("MIN_TRADE_COUNT_24H", "MIN_24H_TRADES", "MIN_TRADES"),
            1000.0,
        )
    )
    max_spread_pct = _get_threshold(
        ("MAX_SPREAD_PERCENT",),
        0.25,
    )

    if not isinstance(symbols, list) or not isinstance(ticker_data, dict):
        return []

    order_books = order_books if isinstance(order_books, dict) else {}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip().upper()
        if not symbol or symbol in seen:
            continue

        if not is_eligible_spot_usdt_symbol(symbol):
            logger.debug("Skipping ineligible symbol in coin_selector: %s", symbol)
            continue

        ticker = ticker_data.get(symbol)
        if not isinstance(ticker, dict):
            continue

        last_price = _safe_float(ticker.get("last_price") or ticker.get("lastPrice"))
        quote_volume = _safe_float(ticker.get("quote_volume") or ticker.get("quoteVolume"))
        trade_count = int(_safe_float(ticker.get("trade_count") or ticker.get("count")))

        if last_price <= 0:
            continue
        if quote_volume < min_quote_volume or trade_count < min_trades:
            continue

        ob = order_books.get(symbol)
        spread_pct = compute_spread_percent(ob, fallback_price=last_price)
        if spread_pct > max_spread_pct:
            logger.debug(
                "Skipping %s due to wide spread: %.4f%% > %.4f%%",
                symbol,
                spread_pct,
                max_spread_pct,
            )
            continue

        bid_depth_usdt, ask_depth_usdt = compute_top_depth_usdt(ob, levels=10)
        total_depth_usdt = bid_depth_usdt + ask_depth_usdt

        seen.add(symbol)
        selected.append(
            {
                "symbol": symbol,
                "last_price": last_price,
                "quote_volume_24h": quote_volume,
                "trade_count_24h": trade_count,
                "spread_percent": round(spread_pct, 5),
                "bid_depth_usdt": round(bid_depth_usdt, 2),
                "ask_depth_usdt": round(ask_depth_usdt, 2),
                "top_depth_usdt": round(total_depth_usdt, 2),
            }
        )

    selected.sort(key=lambda item: item["quote_volume_24h"], reverse=True)
    return selected


def validate_candidate(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False

    symbol = str(candidate.get("symbol", "")).strip().upper()
    if not is_eligible_spot_usdt_symbol(symbol):
        return False

    last_price = _safe_float(candidate.get("last_price"))
    quote_volume = _safe_float(candidate.get("quote_volume_24h"))
    spread_pct = _safe_float(candidate.get("spread_percent"))

    min_quote_volume = _get_threshold(
        ("MIN_24H_QUOTE_VOLUME_USDT", "MIN_QUOTE_VOLUME_USDT"),
        3_000_000.0,
    )
    max_spread_pct = _get_threshold(
        ("MAX_SPREAD_PERCENT",),
        0.25,
    )

    if last_price <= 0 or quote_volume < min_quote_volume:
        return False

    if spread_pct > max_spread_pct:
        return False

    return True
