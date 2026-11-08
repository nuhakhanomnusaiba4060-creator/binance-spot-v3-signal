"""
Binance Spot V3 Smart Signal Scanner
Public market-data provider.

Rules:
- Binance Spot only
- USDT quote pairs only
- No Futures or Margin
- Only closed candles are returned
- No API key required
"""

import time
import logging
from datetime import datetime, timezone

import requests
import pandas as pd

from config import API_CONFIG


logger = logging.getLogger(__name__)

# --------------------------------------------------
# API CONFIGURATION
# --------------------------------------------------

BASE_URL = (
    API_CONFIG.get("BASE_URL")
    or API_CONFIG.get("base_url")
    or "https://data-api.binance.vision"
).rstrip("/")

ENDPOINTS = API_CONFIG.get("ENDPOINTS", {})

EXCHANGE_INFO_ENDPOINT = (
    ENDPOINTS.get("EXCHANGE_INFO")
    or ENDPOINTS.get("exchange_info")
    or "/api/v3/exchangeInfo"
)

KLINES_ENDPOINT = (
    ENDPOINTS.get("KLINES")
    or ENDPOINTS.get("klines")
    or "/api/v3/klines"
)

TICKER_ENDPOINT = (
    ENDPOINTS.get("TICKER_24H")
    or ENDPOINTS.get("ticker_24hr")
    or ENDPOINTS.get("ticker")
    or "/api/v3/ticker/24hr"
)

ORDER_BOOK_ENDPOINT = (
    ENDPOINTS.get("ORDER_BOOK")
    or ENDPOINTS.get("order_book")
    or "/api/v3/depth"
)

TIMEOUT = API_CONFIG.get("REQUEST_TIMEOUT_SECONDS", 10)
MAX_RETRIES = API_CONFIG.get("MAX_RETRIES", 3)
BACKOFF_SECONDS = API_CONFIG.get("RETRY_BACKOFF_SECONDS", 1)

# Exchange information cache
EXCHANGE_INFO_CACHE_SECONDS = 3600

_exchange_info_cache = None
_exchange_info_cache_time = 0


# --------------------------------------------------
# EXPLICIT ASSET EXCLUSIONS
# --------------------------------------------------

# Binance exchange metadata cannot reliably identify every
# tokenized stock or synthetic asset. This list provides
# an additional configurable safety filter.

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

# Common leveraged-token suffixes
LEVERAGED_SUFFIXES = (
    "UPUSDT",
    "DOWNUSDT",
    "BULLUSDT",
    "BEARUSDT",
)


# --------------------------------------------------
# EXCEPTIONS
# --------------------------------------------------

class BinanceDataError(Exception):
    """Base exception for Binance data errors."""


class BinanceAPIError(BinanceDataError):
    """Raised when Binance returns an API or HTTP error."""


class BinanceDataValidationError(BinanceDataError):
    """Raised when returned data has an invalid structure."""


# --------------------------------------------------
# GENERAL HELPERS
# --------------------------------------------------

def _utc_now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _is_valid_usdt_symbol(symbol):
    if not isinstance(symbol, str):
        return False

    symbol = symbol.upper()

    if not symbol.endswith("USDT"):
        return False

    if symbol in EXCLUDED_SYMBOLS:
        return False

    if symbol.endswith(LEVERAGED_SUFFIXES):
        return False

    return True


def _request_json(endpoint, params=None):
    """
    Request JSON data with retry and basic rate-limit handling.
    """

    url = BASE_URL + endpoint

    last_error = None

    for attempt in range(MAX_RETRIES + 1):

        try:
            response = requests.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )

            if response.status_code in (418, 429):
                retry_after = response.headers.get("Retry-After")

                try:
                    wait_time = float(retry_after)
                except (TypeError, ValueError):
                    wait_time = BACKOFF_SECONDS * (2 ** attempt)

                if attempt < MAX_RETRIES:
                    time.sleep(min(wait_time, 60))
                    continue

                raise BinanceAPIError(
                    f"Binance rate limit: HTTP {response.status_code}"
                )

            if response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_SECONDS * (2 ** attempt))
                    continue

                raise BinanceAPIError(
                    f"Binance server error: HTTP {response.status_code}"
                )

            if response.status_code >= 400:
                raise BinanceAPIError(
                    f"Binance HTTP error: {response.status_code}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise BinanceDataValidationError(
                    "Binance returned invalid JSON."
                ) from exc

            if isinstance(data, dict) and "code" in data:
                if data.get("code", 0) < 0:
                    raise BinanceAPIError(
                        f"Binance API error: {data.get('msg', 'Unknown error')}"
                    )

            return data

        except BinanceDataError:
            raise

        except requests.RequestException as exc:
            last_error = exc

            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
                continue

    raise BinanceAPIError(
        f"Binance request failed after retries: {last_error}"
    )


# --------------------------------------------------
# 1. EXCHANGE INFORMATION
# --------------------------------------------------

def get_exchange_info(force_refresh=False):
    """
    Return Binance Spot exchange information.

    Cached for one hour unless force_refresh=True.
    """

    global _exchange_info_cache
    global _exchange_info_cache_time

    now = time.time()

    cache_valid = (
        _exchange_info_cache is not None
        and now - _exchange_info_cache_time
        < EXCHANGE_INFO_CACHE_SECONDS
    )

    if cache_valid and not force_refresh:
        return _exchange_info_cache

    data = _request_json(EXCHANGE_INFO_ENDPOINT)

    if not isinstance(data, dict):
        raise BinanceDataValidationError(
            "Invalid exchange information response."
        )

    if not isinstance(data.get("symbols"), list):
        raise BinanceDataValidationError(
            "Exchange information has no valid symbols list."
        )

    _exchange_info_cache = data
    _exchange_info_cache_time = now

    return data


# --------------------------------------------------
# 2. GET ELIGIBLE SPOT USDT SYMBOLS
# --------------------------------------------------

def get_usdt_symbols(force_refresh=False):
    """
    Return eligible Binance Spot USDT trading symbols.

    Filters:
    - TRADING status
    - USDT quote asset
    - Spot trading enabled
    - Explicitly excluded assets
    - Common leveraged tokens excluded
    """

    exchange_info = get_exchange_info(
        force_refresh=force_refresh
    )

    eligible_symbols = []

    for item in exchange_info["symbols"]:

        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol", "").upper()

        if not _is_valid_usdt_symbol(symbol):
            continue

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("isSpotTradingAllowed") is not True:
            continue

        eligible_symbols.append(symbol)

    return sorted(set(eligible_symbols))


# --------------------------------------------------
# 3. KLINE DATA
# --------------------------------------------------

VALID_INTERVALS = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}


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
]


def get_klines(symbol, interval, limit=300):
    """
    Return closed Binance Spot candles as a pandas DataFrame.

    Current/unclosed candles are always removed.

    Numeric price and volume columns are converted to float.
    Timestamp and trade-count columns are integers.
    """

    symbol = str(symbol).upper()

    if not _is_valid_usdt_symbol(symbol):
        raise BinanceDataValidationError(
            f"Symbol is not an eligible USDT asset: {symbol}"
        )

    if interval not in VALID_INTERVALS:
        raise BinanceDataValidationError(
            f"Unsupported candle interval: {interval}"
        )

    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise BinanceDataValidationError(
            "Kline limit must be an integer between 1 and 1000."
        )

    data = _request_json(
        KLINES_ENDPOINT,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )

    if not isinstance(data, list):
        raise BinanceDataValidationError(
            "Invalid kline response."
        )

    if not data:
        return pd.DataFrame(columns=KLINE_COLUMNS)

    rows = []

    for candle in data:

        if not isinstance(candle, list) or len(candle) < 11:
            continue

        rows.append(candle[:11])

    if not rows:
        return pd.DataFrame(columns=KLINE_COLUMNS)

    df = pd.DataFrame(
        rows,
        columns=KLINE_COLUMNS,
    )

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    integer_columns = [
        "open_time",
        "close_time",
        "trade_count",
    ]

    for column in integer_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df.dropna(
        subset=[
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    for column in integer_columns:
        df[column] = df[column].astype("int64")

    # Keep only candles whose close time has passed.
    now_ms = _utc_now_ms()

    df = df[
        df["close_time"] < now_ms
    ].copy()

    df = df.sort_values("open_time")

    df = df.drop_duplicates(
        subset=["open_time"],
        keep="last",
    )

    df = df.reset_index(drop=True)

    return df


# --------------------------------------------------
# 4. 24-HOUR TICKER DATA
# --------------------------------------------------

def get_24h_ticker(symbols=None):
    """
    Fetch 24-hour ticker data in one API request.

    Returns:
        {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "last_price": float,
                "price_change_percent": float,
                "quote_volume": float,
                "volume": float,
                "trade_count": int,
                "high_price": float,
                "low_price": float,
                "weighted_avg_price": float
            }
        }

    If symbols is provided, only those symbols are returned.
    """

    data = _request_json(TICKER_ENDPOINT)

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        raise BinanceDataValidationError(
            "Invalid 24-hour ticker response."
        )

    requested = None

    if symbols is not None:
        requested = {
            str(symbol).upper()
            for symbol in symbols
        }

    result = {}

    for item in data:

        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol", "").upper()

        if not _is_valid_usdt_symbol(symbol):
            continue

        if requested is not None and symbol not in requested:
            continue

        try:
            result[symbol] = {
                "symbol": symbol,
                "last_price": float(item["lastPrice"]),
                "price_change_percent": float(
                    item["priceChangePercent"]
                ),
                "quote_volume": float(item["quoteVolume"]),
                "volume": float(item["volume"]),
                "trade_count": int(item["count"]),
                "high_price": float(item["highPrice"]),
                "low_price": float(item["lowPrice"]),
                "weighted_avg_price": float(
                    item["weightedAvgPrice"]
                ),
                "open_price": float(item["openPrice"]),
                "open_time": int(item["openTime"]),
                "close_time": int(item["closeTime"]),
            }

        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Skipping invalid ticker data for %s",
                symbol,
            )

    return result


# --------------------------------------------------
# 5. ORDER BOOK DATA
# --------------------------------------------------

def get_order_book(symbol, limit=100):
    """
    Return Binance Spot order book data.

    Output:
        {
            "symbol": str,
            "bids": [[price, quantity], ...],
            "asks": [[price, quantity], ...],
            "last_update_id": int,
            "received_at": int
        }
    """

    symbol = str(symbol).upper()

    if not _is_valid_usdt_symbol(symbol):
        raise BinanceDataValidationError(
            f"Symbol is not an eligible USDT asset: {symbol}"
        )

    valid_limits = {
        5,
        10,
        20,
        50,
        100,
        500,
        1000,
    }

    if limit not in valid_limits:
        raise BinanceDataValidationError(
            "Invalid order book limit."
        )

    data = _request_json(
        ORDER_BOOK_ENDPOINT,
        params={
            "symbol": symbol,
            "limit": limit,
        },
    )

    if not isinstance(data, dict):
        raise BinanceDataValidationError(
            "Invalid order book response."
        )

    bids = data.get("bids")
    asks = data.get("asks")

    if not isinstance(bids, list) or not isinstance(asks, list):
        raise BinanceDataValidationError(
            "Order book bids or asks are missing."
        )

    try:
        normalized_bids = [
            [float(level[0]), float(level[1])]
            for level in bids
            if len(level) >= 2
        ]

        normalized_asks = [
            [float(level[0]), float(level[1])]
            for level in asks
            if len(level) >= 2
        ]

    except (TypeError, ValueError, IndexError) as exc:
        raise BinanceDataValidationError(
            "Invalid order book price or quantity."
        ) from exc

    if not normalized_bids or not normalized_asks:
        raise BinanceDataValidationError(
            "Order book has empty bids or asks."
        )

    return {
        "symbol": symbol,
        "bids": normalized_bids,
        "asks": normalized_asks,
        "last_update_id": int(data.get("lastUpdateId", 0)),
        "received_at": _utc_now_ms(),
    }


# --------------------------------------------------
# MODULE CHECK
# --------------------------------------------------

if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    print("Binance Spot V3 Data Provider")
    print("API:", BASE_URL)

    try:
        symbols = get_usdt_symbols()

        print("Eligible Spot USDT pairs:", len(symbols))
        print("Sample:", symbols[:10])

        ticker = get_24h_ticker(symbols[:10])

        print("Ticker records:", len(ticker))

        if symbols:
            sample_symbol = symbols[0]

            candles = get_klines(
                sample_symbol,
                "5m",
                limit=250,
            )

            print(
                f"{sample_symbol} closed 5m candles:",
                len(candles),
            )

    except BinanceDataError as error:
        print("DATA PROVIDER ERROR:", error)
