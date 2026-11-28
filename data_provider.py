"""
File: data_provider.py
System: Binance Spot V3 Smart Signal Scanner
Code Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Compatibility: New internal architecture
Test Status: NOT RUN

Purpose:
- Fetch public Binance Spot market data.
- Fetch exchange trading rules and eligible USDT symbols.
- Fetch 24h tickers, OHLCV klines and order books.
- Exclude the currently open candle.
- Validate timestamps, OHLCV values and data integrity.
- Fail safely when market data is invalid or unavailable.

Security:
- Public endpoints only.
- No API key required.
- No Futures or Margin endpoints.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = os.getenv(
    "BINANCE_SPOT_BASE_URL",
    "https://data-api.binance.vision",
).rstrip("/")

API_TIMEOUT_SECONDS = 12
API_RETRIES = 3
RETRY_DELAY_SECONDS = 0.8
USER_AGENT = "Binance-Spot-V3-Signal-Scanner/4.0.0"

DEFAULT_KLINE_LIMIT = 300
MAX_KLINE_LIMIT = 1000
DEFAULT_ORDER_BOOK_LIMIT = 100

QUOTE_ASSET = "USDT"

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]

OHLCV_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
]

SUPPORTED_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
}

logger = logging.getLogger(__name__)


# ============================================================
# API EXCEPTIONS
# ============================================================

class BinanceDataError(RuntimeError):
    """Base exception for Binance data errors."""


class BinanceAPIError(BinanceDataError):
    """Raised when Binance returns an API error."""


class BinanceNetworkError(BinanceDataError):
    """Raised when a network request fails."""


class BinanceDataValidationError(BinanceDataError):
    """Raised when returned market data is invalid."""


# ============================================================
# HTTP REQUEST ENGINE
# ============================================================

def _build_url(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    endpoint = "/" + endpoint.lstrip("/")
    query = urllib.parse.urlencode(params or {})
    return f"{BASE_URL}{endpoint}" + (f"?{query}" if query else "")


def _request_json(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Perform a public Binance GET request.

    Retries transient network/server errors.
    Does not retry permanent client-side API errors.
    """
    url = _build_url(endpoint, params)

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }

    last_error: Optional[Exception] = None

    for attempt in range(API_RETRIES):
        request = urllib.request.Request(
            url,
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=API_TIMEOUT_SECONDS,
            ) as response:
                status = response.getcode()
                body = response.read().decode("utf-8")

            if status != 200:
                raise BinanceAPIError(
                    f"HTTP {status} from Binance"
                )

            try:
                data = json.loads(body)
            except json.JSONDecodeError as exc:
                raise BinanceDataValidationError(
                    "Binance returned invalid JSON"
                ) from exc

            if isinstance(data, dict) and "code" in data:
                code = data.get("code")
                message = data.get("msg", "Unknown Binance API error")
                raise BinanceAPIError(
                    f"Binance API error {code}: {message}"
                )

            return data

        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            # Retry rate-limit and server errors.
            if exc.code == 429 or exc.code >= 500:
                last_error = BinanceNetworkError(
                    f"Binance HTTP {exc.code}: {body[:300]}"
                )
            else:
                raise BinanceAPIError(
                    f"Binance HTTP {exc.code}: {body[:300]}"
                ) from exc

        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            last_error = BinanceNetworkError(str(exc))

        except BinanceDataError:
            raise

        except Exception as exc:
            last_error = BinanceNetworkError(str(exc))

        if attempt < API_RETRIES - 1:
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))

    raise BinanceNetworkError(
        f"Binance request failed after {API_RETRIES} attempts: "
        f"{last_error}"
    )


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time() -> int:
    """Return Binance server time in milliseconds."""
    data = _request_json("/api/v3/time")

    if not isinstance(data, dict):
        raise BinanceDataValidationError(
            "Invalid Binance server-time response"
        )

    server_time = data.get("serverTime")

    try:
        server_time = int(server_time)
    except (TypeError, ValueError):
        raise BinanceDataValidationError(
            "Missing or invalid Binance serverTime"
        )

    if server_time <= 0:
        raise BinanceDataValidationError(
            "Invalid Binance server timestamp"
        )

    return server_time


def _current_time_ms() -> int:
    """
    Use Binance server time for candle-close validation.
    Fall back to UTC system time only if the time endpoint fails.
    """
    try:
        return get_server_time()
    except BinanceDataError:
        logger.warning(
            "Binance server time unavailable; using local UTC clock"
        )
        return int(time.time() * 1000)


# ============================================================
# EXCHANGE INFORMATION
# ============================================================

def get_exchange_info() -> Dict[str, Any]:
    data = _request_json("/api/v3/exchangeInfo")

    if not isinstance(data, dict):
        raise BinanceDataValidationError(
            "Invalid exchangeInfo response"
        )

    symbols = data.get("symbols")
    if not isinstance(symbols, list):
        raise BinanceDataValidationError(
            "exchangeInfo symbols field is invalid"
        )

    return data


def _symbol_is_spot_usdt_eligible(
    item: Dict[str, Any],
) -> bool:
    if not isinstance(item, dict):
        return False

    symbol = str(item.get("symbol", "")).upper()
    status = str(item.get("status", "")).upper()
    quote_asset = str(item.get("quoteAsset", "")).upper()

    if status != "TRADING":
        return False

    if quote_asset != QUOTE_ASSET:
        return False

    if not bool(item.get("isSpotTradingAllowed", False)):
        return False

    if not symbol.endswith(QUOTE_ASSET):
        return False

    base_asset = str(item.get("baseAsset", "")).upper()

    if not base_asset:
        return False

    if base_asset in {
        "USDT", "USDC", "BUSD", "FDUSD", "TUSD",
        "USDP", "DAI", "USDE", "USDS", "UST",
        "USTC", "USDD", "EUR", "GBP", "AUD",
        "TRY", "BRL", "BIDR", "IDRT", "UAH",
        "RUB", "NGN", "JPY", "ARS", "PAXG",
    }:
        return False

    if base_asset.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return False

    return True


def get_usdt_symbols() -> List[str]:
    """
    Return Binance Spot USDT symbols that are currently tradable.

    This function uses exchangeInfo as the source of truth.
    """
    info = get_exchange_info()

    result = []

    for item in info["symbols"]:
        if _symbol_is_spot_usdt_eligible(item):
            result.append(str(item["symbol"]).upper())

    return sorted(set(result))


def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
    symbol = str(symbol or "").upper().strip()

    if not symbol:
        return None

    info = get_exchange_info()

    for item in info["symbols"]:
        if str(item.get("symbol", "")).upper() == symbol:
            if _symbol_is_spot_usdt_eligible(item):
                return item
            return None

    return None


# ============================================================
# SYMBOL VALIDATION
# ============================================================

def is_eligible_spot_usdt_symbol(
    symbol: str,
    exchange_info: Optional[Dict[str, Any]] = None,
) -> bool:
    symbol = str(symbol or "").upper().strip()

    if not symbol.endswith(QUOTE_ASSET):
        return False

    if exchange_info is None:
        try:
            exchange_info = get_exchange_info()
        except BinanceDataError:
            return False

    for item in exchange_info.get("symbols", []):
        if str(item.get("symbol", "")).upper() == symbol:
            return _symbol_is_spot_usdt_eligible(item)

    return False


# ============================================================
# 24H TICKER
# ============================================================

def get_24h_ticker(
    symbol: Optional[str] = None,
) -> Any:
    """
    Fetch 24h ticker statistics.

    Without symbol: returns a list of ticker dictionaries.
    With symbol: returns one ticker dictionary.
    """
    params = {}

    if symbol:
        symbol = str(symbol).upper().strip()
        if not symbol.endswith(QUOTE_ASSET):
            raise ValueError("Only USDT Spot symbols are supported")
        params["symbol"] = symbol

    data = _request_json("/api/v3/ticker/24hr", params)

    if symbol:
        if not isinstance(data, dict):
            raise BinanceDataValidationError(
                "Invalid single ticker response"
            )
        return data

    if not isinstance(data, list):
        raise BinanceDataValidationError(
            "Invalid 24h ticker list response"
        )

    return data


def get_24h_tickers_by_symbol() -> Dict[str, Dict[str, Any]]:
    """Return 24h ticker data indexed by symbol."""
    tickers = get_24h_ticker()

    result = {}

    for ticker in tickers:
        if not isinstance(ticker, dict):
            continue

        symbol = str(ticker.get("symbol", "")).upper()

        if symbol:
            result[symbol] = ticker

    return result


# ============================================================
# KLINE DATA VALIDATION
# ============================================================

def validate_klines_dataframe(
    df: pd.DataFrame,
    min_rows: int = 50,
    require_closed: bool = False,
    server_time_ms: Optional[int] = None,
) -> bool:
    """
    Validate OHLCV DataFrame.

    When require_closed=True, rejects any candle whose close_time
    is not earlier than the supplied Binance server time.
    """
    if not isinstance(df, pd.DataFrame):
        return False

    if df.empty or len(df) < min_rows:
        return False

    required = set(OHLCV_COLUMNS + ["open_time", "close_time"])

    if not required.issubset(df.columns):
        return False

    numeric_columns = OHLCV_COLUMNS + [
        "open_time",
        "close_time",
    ]

    for column in numeric_columns:
        values = pd.to_numeric(df[column], errors="coerce")

        if values.isna().any():
            return False

        if not values.map(math.isfinite).all():
            return False

    if (df["open"] <= 0).any():
        return False

    if (df["high"] <= 0).any():
        return False

    if (df["low"] <= 0).any():
        return False

    if (df["close"] <= 0).any():
        return False

    if (df["volume"] < 0).any():
        return False

    if (df["high"] < df["low"]).any():
        return False

    if (df["high"] < df[["open", "close"]].max(axis=1)).any():
        return False

    if (df["low"] > df[["open", "close"]].min(axis=1)).any():
        return False

    if df["open_time"].duplicated().any():
        return False

    if not df["open_time"].is_monotonic_increasing:
        return False

    if (df["close_time"] <= df["open_time"]).any():
        return False

    if require_closed:
        if server_time_ms is None:
            server_time_ms = _current_time_ms()

        if (df["close_time"] >= server_time_ms).any():
            return False

    return True


# ============================================================
# KLINE FETCHING
# ============================================================

def _parse_klines(
    raw_klines: Any,
) -> pd.DataFrame:
    if not isinstance(raw_klines, list):
        raise BinanceDataValidationError(
            "Kline response is not a list"
        )

    rows = []

    for candle in raw_klines:
        if not isinstance(candle, (list, tuple)):
            continue

        if len(candle) < 12:
            continue

        rows.append(candle[:12])

    if not rows:
        raise BinanceDataValidationError(
            "Binance returned no valid kline rows"
        )

    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)

    integer_columns = [
        "open_time",
        "close_time",
        "number_of_trades",
    ]

    float_columns = [
        "open", "high", "low", "close", "volume",
        "quote_volume", "taker_buy_base_volume",
        "taker_buy_quote_volume", "ignore",
    ]

    for column in integer_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    for column in float_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    if df[integer_columns + float_columns].isna().any().any():
        raise BinanceDataValidationError(
            "Kline response contains invalid numeric values"
        )

    df["open_time"] = df["open_time"].astype("int64")
    df["close_time"] = df["close_time"].astype("int64")
    df["number_of_trades"] = (
        df["number_of_trades"].astype("int64")
    )

    df = df.sort_values("open_time")
    df = df.drop_duplicates(subset=["open_time"], keep="last")
    df = df.reset_index(drop=True)

    df["open_datetime"] = pd.to_datetime(
        df["open_time"],
        unit="ms",
        utc=True,
    )

    df["close_datetime"] = pd.to_datetime(
        df["close_time"],
        unit="ms",
        utc=True,
    )

    return df


def get_klines(
    symbol: str,
    interval: str = "15m",
    limit: int = DEFAULT_KLINE_LIMIT,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    closed_only: bool = True,
    min_rows: int = 50,
) -> pd.DataFrame:
    """
    Fetch Binance Spot klines.

    Returns a DataFrame with numeric OHLCV columns and timestamps.

    closed_only=True:
        Removes the currently open candle.

    Timestamps:
        open_time and close_time are Unix milliseconds.
        open_datetime and close_datetime are UTC timestamps.
    """
    symbol = str(symbol or "").upper().strip()
    interval = str(interval or "").strip()

    if not symbol.endswith(QUOTE_ASSET):
        raise ValueError("Only Binance Spot USDT symbols are supported")

    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"Unsupported Binance interval: {interval}")

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("Kline limit must be an integer")

    limit = max(1, min(limit, MAX_KLINE_LIMIT))

    params: Dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    if start_time is not None:
        params["startTime"] = int(start_time)

    if end_time is not None:
        params["endTime"] = int(end_time)

    raw = _request_json("/api/v3/klines", params)
    df = _parse_klines(raw)

    if closed_only:
        server_time = _current_time_ms()

        # Binance candle closeTime is inclusive.
        # A candle is closed only when closeTime < serverTime.
        df = df[df["close_time"] < server_time].copy()
        df = df.reset_index(drop=True)

    if len(df) < min_rows:
        raise BinanceDataValidationError(
            f"Insufficient closed candles for {symbol} {interval}: "
            f"{len(df)} available, {min_rows} required"
        )

    if not validate_klines_dataframe(
        df,
        min_rows=min_rows,
        require_closed=closed_only,
    ):
        raise BinanceDataValidationError(
            f"Invalid OHLCV data for {symbol} {interval}"
        )

    return df


# ============================================================
# ORDER BOOK
# ============================================================

def get_order_book(
    symbol: str,
    limit: int = DEFAULT_ORDER_BOOK_LIMIT,
) -> Dict[str, Any]:
    """
    Fetch Binance Spot order book.

    The returned bids and asks are raw Binance levels.
    """
    symbol = str(symbol or "").upper().strip()

    if not symbol.endswith(QUOTE_ASSET):
        raise ValueError("Only USDT Spot order books are supported")

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("Order book limit must be an integer")

    allowed_limits = {
        5, 10, 20, 50, 100, 500, 1000,
    }

    if limit not in allowed_limits:
        raise ValueError(
            f"Unsupported order book limit: {limit}"
        )

    data = _request_json(
        "/api/v3/depth",
        {
            "symbol": symbol,
            "limit": limit,
        },
    )

    if not isinstance(data, dict):
        raise BinanceDataValidationError(
            "Invalid order book response"
        )

    bids = data.get("bids")
    asks = data.get("asks")

    if not isinstance(bids, list) or not isinstance(asks, list):
        raise BinanceDataValidationError(
            "Order book bids/asks are invalid"
        )

    if not bids or not asks:
        raise BinanceDataValidationError(
            "Order book is empty"
        )

    parsed_bids = []
    parsed_asks = []

    for side, target in ((bids, parsed_bids), (asks, parsed_asks)):
        for level in side:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue

            try:
                price = float(level[0])
                quantity = float(level[1])
            except (TypeError, ValueError):
                continue

            if (
                not math.isfinite(price)
                or not math.isfinite(quantity)
                or price <= 0
                or quantity <= 0
            ):
                continue

            target.append([str(price), str(quantity)])

    if not parsed_bids or not parsed_asks:
        raise BinanceDataValidationError(
            "Order book has no valid price levels"
        )

    best_bid = max(float(level[0]) for level in parsed_bids)
    best_ask = min(float(level[0]) for level in parsed_asks)

    if best_ask <= best_bid:
        raise BinanceDataValidationError(
            "Order book is crossed or invalid"
        )

    return {
        "lastUpdateId": data.get("lastUpdateId"),
        "bids": parsed_bids,
        "asks": parsed_asks,
        "symbol": symbol,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# BULK DATA HELPERS
# ============================================================

def fetch_market_snapshot() -> Dict[str, Any]:
    """
    Fetch all 24h tickers and current exchange symbol information.

    This does not fetch individual order books or klines.
    """
    exchange_info = get_exchange_info()
    tickers = get_24h_ticker()

    eligible_symbols = {
        str(item["symbol"]).upper()
        for item in exchange_info.get("symbols", [])
        if _symbol_is_spot_usdt_eligible(item)
    }

    filtered_tickers = [
        ticker
        for ticker in tickers
        if (
            isinstance(ticker, dict)
            and str(ticker.get("symbol", "")).upper()
            in eligible_symbols
        )
    ]

    return {
        "exchange_info": exchange_info,
        "tickers": filtered_tickers,
        "eligible_symbol_count": len(eligible_symbols),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_symbol_market_data(
    symbol: str,
    intervals: Optional[List[str]] = None,
    kline_limit: int = DEFAULT_KLINE_LIMIT,
    order_book_limit: int = DEFAULT_ORDER_BOOK_LIMIT,
) -> Dict[str, Any]:
    """
    Fetch a symbol's 24h ticker, requested closed candles,
    and current order book.

    Any failed required data request raises an exception.
    Partial data is not silently labelled complete.
    """
    symbol = str(symbol or "").upper().strip()

    intervals = intervals or ["5m", "15m", "30m", "1h"]

    if not symbol.endswith(QUOTE_ASSET):
        raise ValueError("Only USDT Spot symbols are supported")

    ticker = get_24h_ticker(symbol)
    order_book = get_order_book(symbol, order_book_limit)

    frames: Dict[str, pd.DataFrame] = {}

    for interval in intervals:
        frames[interval] = get_klines(
            symbol=symbol,
            interval=interval,
            limit=kline_limit,
            closed_only=True,
        )

    return {
        "symbol": symbol,
        "ticker": ticker,
        "order_book": order_book,
        "klines": frames,
        "data_status": "COMPLETE",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "spot_only": True,
    }


# ============================================================
# DATA QUALITY DIAGNOSTICS
# ============================================================

def get_data_quality_report(
    df: pd.DataFrame,
    interval: str,
) -> Dict[str, Any]:
    """
    Return a diagnostic report for a candle DataFrame.

    Does not repair or fabricate missing candles.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {
            "valid": False,
            "reason": "EMPTY_DATAFRAME",
            "rows": 0,
            "interval": interval,
        }

    valid = validate_klines_dataframe(
        df,
        min_rows=1,
        require_closed=False,
    )

    gaps = 0

    if "open_time" in df.columns and len(df) > 1:
        differences = df["open_time"].diff().dropna()
        gaps = int((differences <= 0).sum())

    return {
        "valid": valid,
        "reason": "VALID" if valid else "DATA_VALIDATION_FAILED",
        "rows": len(df),
        "interval": interval,
        "first_open_time": int(df["open_time"].iloc[0]),
        "last_open_time": int(df["open_time"].iloc[-1]),
        "last_close_time": int(df["close_time"].iloc[-1]),
        "duplicate_or_reverse_timestamps": gaps,
        "missing_values": int(df.isna().sum().sum()),
    }


# ============================================================
# CONFIGURATION SNAPSHOT
# ============================================================

def get_data_provider_config() -> Dict[str, Any]:
    return {
        "base_url": BASE_URL,
        "quote_asset": QUOTE_ASSET,
        "timeout_seconds": API_TIMEOUT_SECONDS,
        "retries": API_RETRIES,
        "default_kline_limit": DEFAULT_KLINE_LIMIT,
        "max_kline_limit": MAX_KLINE_LIMIT,
        "default_order_book_limit": DEFAULT_ORDER_BOOK_LIMIT,
        "closed_candles_only": True,
        "spot_only": True,
        "api_key_required": False,
        "formula_version": "4.0",
    }


# ============================================================
# LOCAL SELF-CHECK
# ============================================================

def self_check() -> bool:
    """Offline checks; no Binance network request is performed."""

    raw = [[
        1_700_000_000_000,
        "100",
        "105",
        "99",
        "103",
        "500",
        1_700_000_899_999,
        "51000",
        1000,
        "250",
        "25500",
        "0",
    ]]

    df = _parse_klines(raw)

    assert len(df) == 1
    assert float(df.iloc[0]["open"]) == 100.0
    assert float(df.iloc[0]["close"]) == 103.0

    assert validate_klines_dataframe(
        df,
        min_rows=1,
        require_closed=False,
    )

    assert not validate_klines_dataframe(
        pd.DataFrame(),
        min_rows=1,
    )

    assert "5m" in SUPPORTED_INTERVALS
    assert "15m" in SUPPORTED_INTERVALS
    assert "1h" in SUPPORTED_INTERVALS

    return True


if __name__ == "__main__":
    try:
        self_check()
        print("DATA PROVIDER SELF-CHECK: PASS")
        print("Closed Candle Validation: ENABLED")
        print("Binance Spot Only: YES")
        print("API Key Required: NO")
    except Exception as exc:
        print(f"DATA PROVIDER SELF-CHECK: FAIL - {exc}")
        raise
