
"""
Binance Spot V3 Smart Signal Scanner
Validated public market-data provider.

Rules:
- Binance Spot public endpoints only
- USDT quote symbols only
- No Futures or Margin
- Closed candles only
- Strict OHLCV, ticker and order-book validation
- Config-driven data freshness
- No API key required
"""

import copy
import logging
import math
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from config import API_CONFIG


logger = logging.getLogger(__name__)


# ==================================================
# 1. API CONFIGURATION
# ==================================================

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

FRESHNESS_CONFIG = API_CONFIG.get(
    "DATA_FRESHNESS_SECONDS", {}
)

EXCHANGE_INFO_CACHE_SECONDS = 3600

_exchange_info_cache = None
_exchange_info_cache_time = 0


# ==================================================
# 2. SYMBOL FILTERS
# ==================================================

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

LEVERAGED_SUFFIXES = (
    "UPUSDT",
    "DOWNUSDT",
    "BULLUSDT",
    "BEARUSDT",
)


# ==================================================
# 3. EXCEPTIONS
# ==================================================

class BinanceDataError(Exception):
    """Base exception for Binance data errors."""


class BinanceAPIError(BinanceDataError):
    """Binance HTTP or API error."""


class BinanceDataValidationError(BinanceDataError):
    """Invalid or unreliable market data."""


# ==================================================
# 4. GENERAL HELPERS
# ==================================================

def _utc_now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _is_finite_number(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _safe_float(value, field_name):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BinanceDataValidationError(
            f"Invalid numeric field: {field_name}"
        ) from exc

    if not math.isfinite(number):
        raise BinanceDataValidationError(
            f"Non-finite numeric field: {field_name}"
        )

    return number


def _safe_int(value, field_name):
    number = _safe_float(value, field_name)

    if not number.is_integer():
        raise BinanceDataValidationError(
            f"Invalid integer field: {field_name}"
        )

    return int(number)


def _is_valid_usdt_symbol(symbol):
    if not isinstance(symbol, str):
        return False

    symbol = symbol.upper().strip()

    if not symbol.endswith("USDT"):
        return False

    if symbol in EXCLUDED_SYMBOLS:
        return False

    if symbol.endswith(LEVERAGED_SUFFIXES):
        return False

    if len(symbol) <= 4:
        return False

    return True


def _get_freshness_seconds(key, default):
    value = FRESHNESS_CONFIG.get(key, default)

    try:
        value = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(value) or value <= 0:
        return default

    return value


# ==================================================
# 5. HTTP REQUEST ENGINE
# ==================================================

def _request_json(endpoint, params=None):
    """
    Request public Binance JSON data.

    Retries:
    - Network errors
    - HTTP 418 / 429
    - HTTP 5xx

    Does not retry ordinary HTTP 4xx errors.
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
                retry_after = response.headers.get(
                    "Retry-After"
                )

                try:
                    wait_time = float(retry_after)
                except (TypeError, ValueError):
                    wait_time = (
                        BACKOFF_SECONDS * (2 ** attempt)
                    )

                if attempt < MAX_RETRIES:
                    time.sleep(min(max(wait_time, 1), 60))
                    continue

                raise BinanceAPIError(
                    f"Binance rate limit: HTTP "
                    f"{response.status_code}"
                )

            if response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    time.sleep(
                        BACKOFF_SECONDS * (2 ** attempt)
                    )
                    continue

                raise BinanceAPIError(
                    f"Binance server error: HTTP "
                    f"{response.status_code}"
                )

            if response.status_code >= 400:
                raise BinanceAPIError(
                    f"Binance HTTP error: "
                    f"{response.status_code}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise BinanceDataValidationError(
                    "Binance returned invalid JSON."
                ) from exc

            if isinstance(data, dict) and "code" in data:
                code = data.get("code")

                if isinstance(code, (int, float)) and code < 0:
                    raise BinanceAPIError(
                        "Binance returned an API error."
                    )

            return data

        except BinanceDataError:
            raise

        except requests.RequestException as exc:
            last_error = exc

            if attempt < MAX_RETRIES:
                time.sleep(
                    BACKOFF_SECONDS * (2 ** attempt)
                )
                continue

    raise BinanceAPIError(
        f"Binance request failed after retries: "
        f"{type(last_error).__name__ if last_error else 'Unknown'}"
    )


# ==================================================
# 6. EXCHANGE INFORMATION
# ==================================================

def get_exchange_info(force_refresh=False):
    """
    Return cached Binance Spot exchange information.

    Returned data is a deep copy so callers cannot
    accidentally modify the internal cache.
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
        return copy.deepcopy(_exchange_info_cache)

    data = _request_json(EXCHANGE_INFO_ENDPOINT)

    if not isinstance(data, dict):
        raise BinanceDataValidationError(
            "Invalid exchange information response."
        )

    if not isinstance(data.get("symbols"), list):
        raise BinanceDataValidationError(
            "Exchange information has no valid symbols list."
        )

    _exchange_info_cache = copy.deepcopy(data)
    _exchange_info_cache_time = now

    return copy.deepcopy(_exchange_info_cache)


# ==================================================
# 7. ELIGIBLE SPOT USDT SYMBOLS
# ==================================================

def get_usdt_symbols(force_refresh=False):
    """
    Return eligible Binance Spot USDT symbols.
    """

    exchange_info = get_exchange_info(
        force_refresh=force_refresh
    )

    eligible_symbols = []

    for item in exchange_info["symbols"]:

        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol", "")

        if not _is_valid_usdt_symbol(symbol):
            continue

        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("isSpotTradingAllowed") is not True:
            continue

        eligible_symbols.append(symbol.upper())

    return sorted(set(eligible_symbols))


# ==================================================
# 8. KLINE CONFIGURATION
# ==================================================

VALID_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h",
    "12h", "1d", "3d", "1w", "1M",
}

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
    "3d": 259_200_000,
    "1w": 604_800_000,
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

NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
]

INTEGER_COLUMNS = [
    "open_time",
    "close_time",
    "trade_count",
]


def _validate_candle_rows(df):
    """
    Reject invalid OHLCV rows instead of silently
    passing corrupted market data to indicators.
    """

    if df.empty:
        return df

    for column in NUMERIC_COLUMNS + INTEGER_COLUMNS:
        if df[column].isna().any():
            raise BinanceDataValidationError(
                f"Kline contains missing values: {column}"
            )

    for column in NUMERIC_COLUMNS:
        values = df[column].astype(float)

        if not values.map(math.isfinite).all():
            raise BinanceDataValidationError(
                f"Kline contains non-finite values: {column}"
            )

    for column in INTEGER_COLUMNS:
        values = df[column].astype(float)

        if not values.map(
            lambda x: math.isfinite(x) and x >= 0 and x.is_integer()
        ).all():
            raise BinanceDataValidationError(
                f"Kline contains invalid integer values: {column}"
            )

    prices = df[["open", "high", "low", "close"]]

    if (prices <= 0).any().any():
        raise BinanceDataValidationError(
            "Kline contains non-positive prices."
        )

    if (df[["volume", "quote_volume"]] < 0).any().any():
        raise BinanceDataValidationError(
            "Kline contains negative volume."
        )

    if (df["trade_count"] < 0).any():
        raise BinanceDataValidationError(
            "Kline contains negative trade count."
        )

    invalid_ohlc = (
        (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
        | (df["high"] < df["low"])
    )

    if invalid_ohlc.any():
        raise BinanceDataValidationError(
            "Kline contains inconsistent OHLC prices."
        )

    if (
        df["taker_buy_base_volume"] > df["volume"] * 1.001
    ).any():
        raise BinanceDataValidationError(
            "Taker-buy base volume exceeds total volume."
        )

    return df


def _validate_candle_continuity(df, interval):
    """
    Detect missing candles for fixed-duration intervals.

    Monthly candles are excluded because their duration
    is variable.
    """

    interval_ms = INTERVAL_MS.get(interval)

    if interval_ms is None or len(df) < 2:
        return

    differences = df["open_time"].diff().dropna()

    if (differences != interval_ms).any():
        raise BinanceDataValidationError(
            f"Candle gap detected for interval {interval}."
        )


def _validate_candle_freshness(df, interval):
    if df.empty:
        raise BinanceDataValidationError(
            "No closed candles available."
        )

    defaults = {
        "5m": 600,
        "15m": 1800,
        "30m": 3600,
        "1h": 7200,
    }

    default_age = defaults.get(
        interval,
        2 * INTERVAL_MS.get(interval, 3_600_000) / 1000,
    )

    max_age = _get_freshness_seconds(
        interval,
        default_age,
    )

    latest_close = int(df.iloc[-1]["close_time"])
    age_seconds = (_utc_now_ms() - latest_close) / 1000

    if age_seconds < 0:
        raise BinanceDataValidationError(
            "Latest candle has a future close timestamp."
        )

    if age_seconds > max_age:
        raise BinanceDataValidationError(
            f"Stale {interval} candle data: "
            f"{age_seconds:.0f}s old."
        )


# ==================================================
# 9. GET CLOSED KLINES
# ==================================================

def get_klines(symbol, interval, limit=300):
    """
    Return validated, closed Binance Spot candles.
    """

    symbol = str(symbol).upper().strip()

    if not _is_valid_usdt_symbol(symbol):
        raise BinanceDataValidationError(
            f"Invalid USDT symbol: {symbol}"
        )

    if interval not in VALID_INTERVALS:
        raise BinanceDataValidationError(
            f"Unsupported candle interval: {interval}"
        )

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 1000
    ):
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
            raise BinanceDataValidationError(
                "Malformed kline row received."
            )

        rows.append(candle[:11])

    df = pd.DataFrame(
        rows,
        columns=KLINE_COLUMNS,
    )

    for column in NUMERIC_COLUMNS + INTEGER_COLUMNS:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    if df.isna().any().any():
        raise BinanceDataValidationError(
            "Kline response contains invalid numeric values."
        )

    for column in INTEGER_COLUMNS:
        values = df[column].astype(float)

        if not values.map(
            lambda x: math.isfinite(x) and x.is_integer()
        ).all():
            raise BinanceDataValidationError(
                f"Invalid integer values in {column}."
            )

        df[column] = values.astype("int64")

    # Keep only closed candles.
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

    if df.empty:
        raise BinanceDataValidationError(
            "No closed candles returned."
        )

    _validate_candle_rows(df)
    _validate_candle_continuity(df, interval)
    _validate_candle_freshness(df, interval)

    return df


# ==================================================
# 10. 24-HOUR TICKER
# ==================================================

def get_24h_ticker(symbols=None):
    """
    Return validated 24-hour ticker records.

    Ticker freshness is checked using Binance closeTime.
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
            if _is_valid_usdt_symbol(str(symbol))
        }

    result = {}

    max_age = _get_freshness_seconds(
        "ticker",
        120,
    )

    now_ms = _utc_now_ms()

    for item in data:

        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()

        if not _is_valid_usdt_symbol(symbol):
            continue

        if requested is not None and symbol not in requested:
            continue

        try:
            record = {
                "symbol": symbol,
                "last_price": _safe_float(
                    item["lastPrice"], "lastPrice"
                ),
                "price_change_percent": _safe_float(
                    item["priceChangePercent"],
                    "priceChangePercent",
                ),
                "quote_volume": _safe_float(
                    item["quoteVolume"], "quoteVolume"
                ),
                "volume": _safe_float(
                    item["volume"], "volume"
                ),
                "trade_count": _safe_int(
                    item["count"], "count"
                ),
                "high_price": _safe_float(
                    item["highPrice"], "highPrice"
                ),
                "low_price": _safe_float(
                    item["lowPrice"], "lowPrice"
                ),
                "weighted_avg_price": _safe_float(
                    item["weightedAvgPrice"],
                    "weightedAvgPrice",
                ),
                "open_price": _safe_float(
                    item["openPrice"], "openPrice"
                ),
                "open_time": _safe_int(
                    item["openTime"], "openTime"
                ),
                "close_time": _safe_int(
                    item["closeTime"], "closeTime"
                ),
            }

            if record["last_price"] <= 0:
                continue

            if record["open_price"] <= 0:
                continue

            if record["weighted_avg_price"] <= 0:
                continue

            if record["low_price"] <= 0:
                continue

            if record["high_price"] < record["low_price"]:
                continue

            if record["volume"] < 0:
                continue

            if record["quote_volume"] < 0:
                continue

            if record["trade_count"] < 0:
                continue

            age_seconds = (
                now_ms - record["close_time"]
            ) / 1000

            if age_seconds < 0 or age_seconds > max_age:
                logger.warning(
                    "Skipping stale ticker for %s",
                    symbol,
                )
                continue

            result[symbol] = record

        except (
            KeyError,
            TypeError,
            ValueError,
            BinanceDataValidationError,
        ):
            logger.warning(
                "Skipping invalid ticker data for %s",
                symbol,
            )

    return result


# ==================================================
# 11. ORDER BOOK VALIDATION
# ==================================================

def _normalize_order_book_side(levels, side_name):
    if not isinstance(levels, list):
        ra
