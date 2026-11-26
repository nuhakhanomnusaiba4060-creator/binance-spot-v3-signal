"""
Binance Spot V3 Smart Signal Scanner
Market Data Provider (Spot USDT Only)

Design principles:
- Use Binance Spot public endpoints only
- Drop unclosed live candles so indicators rely strictly on closed bars
- Filter out non-ASCII and clearly pegged/stable symbols without over-filtering
- Retry transient failures with exponential backoff
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

import pandas as pd
import requests

import config as cfg


logger = logging.getLogger(__name__)


API_CONFIG = getattr(cfg, "API_CONFIG", {})
COIN_SELECTION_CONFIG = getattr(
    cfg,
    "COIN_SELECTION_CONFIG",
    getattr(cfg, "FILTER_CONFIG", {}),
)

DEFAULT_BASE_URL = "https://data-api.binance.vision"
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

# Only reject clearly pegged/stable/wrapped non-momentum instruments
EXCLUDED_BASE_ASSETS = {
    "USDC",
    "BUSD",
    "TUSD",
    "USDP",
    "FDUSD",
    "DAI",
    "EUR",
    "GBP",
    "AEUR",
    "RWUSD",
    "USD1",
    "USDE",
    "BFUSD",
    "WBTC",
    "WETH",
    "STETH",
    "CBBTC",
    "WBETH",
    "PAXG",
    "XAUT",
}

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,15}USDT$")
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

_EXCHANGE_INFO_CACHE: dict[str, Any] = {
    "fetched_at": 0.0,
    "symbols": [],
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError, OverflowError):
        return default


def is_eligible_spot_usdt_symbol(symbol: Any) -> bool:
    """
    Allow active ASCII Spot USDT pairs while filtering out non-ASCII symbols,
    leveraged tokens, and known pegged/stable/wrapped tokens.
    """
    if not isinstance(symbol, str):
        return False

    sym = symbol.strip().upper()
    if not sym or not sym.isascii():
        return False

    if not SYMBOL_PATTERN.fullmatch(sym):
        return False

    if sym.endswith(LEVERAGED_SUFFIXES):
        return False

    base_asset = sym[: -len("USDT")]
    if not base_asset or base_asset in EXCLUDED_BASE_ASSETS:
        return False

    return True


def _get_base_url() -> str:
    url = str(API_CONFIG.get("BASE_URL") or DEFAULT_BASE_URL).strip()
    return (url or DEFAULT_BASE_URL).rstrip("/")


def _get_endpoint(key: str, default_path: str) -> str:
    endpoints = API_CONFIG.get("ENDPOINTS", {})
    if isinstance(endpoints, dict) and endpoints.get(key):
        return str(endpoints[key])
    return default_path


def _request_json(path: str, params: dict[str, Any] | None = None) -> Any:
    timeout = _safe_float(API_CONFIG.get("REQUEST_TIMEOUT_SECONDS"), 10.0)
    max_retries = max(1, int(_safe_float(API_CONFIG.get("MAX_RETRIES"), 3)))
    backoff_base = max(0.2, _safe_float(API_CONFIG.get("RETRY_BACKOFF_SECONDS"), 1.0))

    url = f"{_get_base_url()}{path}"
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code in (418, 429):
                sleep_for = backoff_base * (2**attempt)
                logger.warning(
                    "Binance rate limit/ban status %s on %s; retrying in %.1fs",
                    response.status_code,
                    path,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue

            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                sleep_for = backoff_base * (2**attempt)
                time.sleep(sleep_for)

    raise RuntimeError(f"Request failed for {path}: {last_error}")


def get_usdt_symbols(force_refresh: bool = False) -> list[str]:
    cache_ttl = _safe_float(API_CONFIG.get("EXCHANGE_INFO_CACHE_SECONDS"), 3600.0)
    now = time.time()

    if (
        not force_refresh
        and _EXCHANGE_INFO_CACHE["symbols"]
        and (now - _EXCHANGE_INFO_CACHE["fetched_at"]) < cache_ttl
    ):
        return list(_EXCHANGE_INFO_CACHE["symbols"])

    endpoint = _get_endpoint("EXCHANGE_INFO", "/api/v3/exchangeInfo")
    payload = _request_json(endpoint)

    raw_symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
    eligible: list[str] = []
    seen: set[str] = set()

    for item in raw_symbols:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()
        quote_asset = str(item.get("quoteAsset", "")).upper()
        status = str(item.get("status", "")).upper()
        spot_allowed = item.get("isSpotTradingAllowed", True) is not False

        if quote_asset != "USDT" or status != "TRADING" or not spot_allowed:
            continue

        if not is_eligible_spot_usdt_symbol(symbol):
            continue

        if symbol not in seen:
            seen.add(symbol)
            eligible.append(symbol)

    _EXCHANGE_INFO_CACHE["fetched_at"] = now
    _EXCHANGE_INFO_CACHE["symbols"] = list(eligible)
    return eligible


def _drop_unclosed_klines(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if df.empty or interval not in INTERVAL_MS:
        return df

    step_ms = INTERVAL_MS[interval]
    now_ms = int(time.time() * 1000)
    # A candle with close_time >= now_ms (or open_time + step_ms > now_ms) is still forming
    closed_mask = (df["close_time"] < now_ms) & ((df["open_time"] + step_ms) <= now_ms)
    return df.loc[closed_mask].reset_index(drop=True)


def get_klines(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    sym = str(symbol).upper().strip()
    if not is_eligible_spot_usdt_symbol(sym):
        raise ValueError(f"Ineligible symbol for spot klines: {symbol!r}")

    endpoint = _get_endpoint("KLINES", "/api/v3/klines")
    safe_limit = max(1, min(int(limit), 1000))
    raw = _request_json(
        endpoint,
        params={"symbol": sym, "interval": interval, "limit": safe_limit},
    )

    if not isinstance(raw, list) or not raw:
        return pd.DataFrame(columns=KLINE_COLUMNS)

    df = pd.DataFrame(raw, columns=KLINE_COLUMNS)
    numeric_cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trade_count",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open_time", "open", "high", "low", "close", "volume", "close_time"])
    df = df.sort_values("open_time", kind="stable").drop_duplicates(subset=["open_time"], keep="last")
    df = _drop_unclosed_klines(df, interval)
    return df.reset_index(drop=True)


def get_24h_ticker() -> dict[str, dict[str, Any]]:
    endpoint = _get_endpoint("TICKER_24H", "/api/v3/ticker/24hr")
    raw = _request_json(endpoint)

    if not isinstance(raw, list):
        return {}

    now_ms = int(time.time() * 1000)
    max_age_sec = _safe_float(
        API_CONFIG.get("DATA_FRESHNESS_SECONDS", {}).get("TICKER_24H")
        if isinstance(API_CONFIG.get("DATA_FRESHNESS_SECONDS"), dict)
        else 120.0,
        120.0,
    )
    max_age_ms = max(10_000.0, max_age_sec * 1000.0)

    result: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue

        symbol = str(row.get("symbol", "")).upper()
        if not is_eligible_spot_usdt_symbol(symbol):
            continue

        close_time = _safe_float(row.get("closeTime"), 0.0)
        if close_time > 0 and (now_ms - close_time) > (max_age_ms * 10):
            continue

        last_price = _safe_float(row.get("lastPrice"))
        quote_volume = _safe_float(row.get("quoteVolume"))
        trade_count = int(_safe_float(row.get("count")))

        if last_price <= 0:
            continue

        result[symbol] = {
            "symbol": symbol,
            "last_price": last_price,
            "lastPrice": last_price,
            "quote_volume": quote_volume,
            "quoteVolume": quote_volume,
            "trade_count": trade_count,
            "count": trade_count,
            "price_change_percent": _safe_float(row.get("priceChangePercent")),
            "high_price": _safe_float(row.get("highPrice")),
            "low_price": _safe_float(row.get("lowPrice")),
            "bid_price": _safe_float(row.get("bidPrice")),
            "ask_price": _safe_float(row.get("askPrice")),
        }

    return result


def get_order_book(symbol: str, limit: int = 100) -> dict[str, Any]:
    sym = str(symbol).upper().strip()
    if not is_eligible_spot_usdt_symbol(sym):
        raise ValueError(f"Ineligible symbol for order book: {symbol!r}")

    endpoint = _get_endpoint("ORDER_BOOK", "/api/v3/depth")
    safe_limit = max(5, min(int(limit), 500))
    raw = _request_json(endpoint, params={"symbol": sym, "limit": safe_limit})

    bids: list[list[float]] = []
    asks: list[list[float]] = []

    if isinstance(raw, dict):
        for pair in raw.get("bids", []):
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                p, q = _safe_float(pair[0]), _safe_float(pair[1])
                if p > 0 and q > 0:
                    bids.append([p, q])

        for pair in raw.get("asks", []):
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                p, q = _safe_float(pair[0]), _safe_float(pair[1])
                if p > 0 and q > 0:
                    asks.append([p, q])

    return {
        "symbol": sym,
        "bids": bids,
        "asks": asks,
    }
