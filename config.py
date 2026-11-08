
"""
Binance Spot V3 Smart Signal Scanner
Central Configuration Module

Version: 3.0
Python: 3.11
Market: Binance Spot Only
Quote Asset: USDT Only

All initial screening thresholds are provisional.
Backtesting and paper trading are required before optimization.
"""

from copy import deepcopy


# ============================================================
# 1. CORE CONFIGURATION
# ============================================================

CONFIG = {
    "VERSION": "3.0",
    "EXCHANGE": "BINANCE",
    "MARKET_TYPE": "SPOT",
    "QUOTE_ASSET": "USDT",

    "SCAN_INTERVAL_SECONDS": 300,
    "TARGET_SIGNALS_PER_DAY": (5, 7),
    "TARGET_SIGNALS_MANDATORY": False,

    "MAX_TRADE_DURATION_HOURS": 48,
    "SIGNAL_TRACKING_HOURS": 48,

    "TIMEZONE": "UTC",
    "PYTHON_VERSION": "3.11",

    "SPOT_ONLY": True,
    "USDT_ONLY": True,

    "ALLOWED_SIGNAL_TYPES": [
        "STRONG BUY",
        "EXCELLENT BUY",
    ],

    "EXCLUDED_MARKETS": [
        "FUTURES",
        "MARGIN",
        "STOCKS",
        "SHARES",
        "EQUITIES",
        "TOKENIZED_STOCKS",
        "NON_CRYPTO_ASSETS",
    ],
}


# ============================================================
# 2. TIMEFRAME CONFIGURATION
# ============================================================

TIMEFRAMES = {
    "SCALP": {
        "TRIGGER": "5m",
        "CONFIRMATION": "15m",
        "ADDITIONAL_CONFIRMATION": "30m",
        "ENTRY_VALIDITY_MINUTES": 15,
    },

    "SWING": {
        "TRIGGER": "15m",
        "CONFIRMATION": "30m",
        "TREND_CONFIRMATION": "1h",
        "ENTRY_VALIDITY_MINUTES": 60,
    },

    "BTC_MARKET": [
        "15m",
        "1h",
        "4h",
    ],

    "REQUIRE_CLOSED_CANDLES": True,
}


# ============================================================
# 3. STRATEGY CONFIGURATION
# ============================================================

STRATEGIES = {
    "SCALP": {
        "ENABLED": True,
        "MAX_DURATION": "SEVERAL_HOURS",
        "TRIGGER_TIMEFRAME": "5m",
        "CONFIRMATION_TIMEFRAMES": [
            "15m",
            "30m",
        ],
        "ENTRY_VALIDITY_MINUTES": 15,
    },

    "SWING": {
        "ENABLED": True,
        "MAX_DURATION_HOURS": 48,
        "TRIGGER_TIMEFRAME": "15m",
        "CONFIRMATION_TIMEFRAMES": [
            "30m",
            "1h",
        ],
        "ENTRY_VALIDITY_MINUTES": 60,
    },

    "ENTRY_SEQUENCE": [
        "BREAKOUT",
        "CANDLE_CLOSE",
        "RETEST",
        "BUYER_CONFIRMATION",
        "ENTRY",
    ],

    "PREFER_RETEST": True,
    "REJECT_LATE_ENTRY": True,
}


# ============================================================
# 4. RISK CONFIGURATION
# ============================================================

RISK_CONFIG = {
    "MAX_RISK_PER_TRADE_PERCENT": 1.0,
    "MIN_RISK_REWARD_RATIO": 2.0,

    "POSITION_SIZING_METHOD": "STOP_LOSS_DISTANCE",

    "INCLUDE_TRADING_FEES": True,
    "INCLUDE_ESTIMATED_SLIPPAGE": True,

    "STOP_LOSS_METHOD": [
        "TECHNICAL_INVALIDATION",
        "CONFIRMED_SUPPORT",
        "ATR14",
        "MARKET_VOLATILITY",
    ],

    "TARGET_METHOD": {
        "T1": "FIRST_MEANINGFUL_RESISTANCE",
        "T2": "NEXT_RESISTANCE",
        "T3": "EXTENDED_RESISTANCE",
    },

    "REQUIRE_MINIMUM_RR_AT_T1": True,
}


# ============================================================
# 5. FILTER CONFIGURATION
# ============================================================

FILTER_CONFIG = {
    "ALLOWED_QUOTE_ASSET": "USDT",

    # Initial thresholds: pending backtesting.
    "MIN_24H_QUOTE_VOLUME_USDT": 3_000_000,
    "MIN_RELATIVE_VOLUME": 1.5,
    "PREFERRED_RELATIVE_VOLUME": 2.0,

    "MAX_SPREAD_PERCENT": 0.15,
    "MIN_24H_TRADE_COUNT": 1000,

    "RSI": {
        "PERIOD": 14,

        "WEAK_BELOW": 45,
        "CAUTION_MIN": 45,

        "PREFERRED_MIN": 50,
        "PREFERRED_MAX": 68,

        "OVEREXTENSION_MIN": 69,
        "OVEREXTENSION_MAX": 74,

        "REJECT_ABOVE": 74,
    },

    "ORDER_BOOK": {
        "VALIDATE_SPREAD": True,
        "VALIDATE_DEPTH": True,
        "VALIDATE_BUY_LIQUIDITY": True,
        "VALIDATE_SELL_LIQUIDITY": True,
        "ESTIMATE_SLIPPAGE": True,
        "CHECK_IMBALANCE": True,
    },

    "PUMP_PROTECTION": {
        "ENABLED": True,
        "CHECK_PRICE_SPIKES": True,
        "CHECK_VOLUME_SPIKES": True,
        "CHECK_RAPID_REVERSALS": True,
        "CHECK_THIN_ORDER_BOOK": True,
        "CHECK_ABNORMAL_VOLATILITY": True,
        "REJECT_STALE_DATA": True,
    },
}


# ============================================================
# 6. INDICATOR CONFIGURATION
# ============================================================

INDICATOR_CONFIG = {
    "EMA": {
        "FAST": 9,
        "SLOW": 20,
    },

    "SMA": {
        "PERIODS": [
            20,
            50,
            200,
        ],
    },

    "RSI": {
        "PERIOD": 14,
    },

    "MACD": {
        "FAST": 12,
        "SLOW": 26,
        "SIGNAL": 9,
    },

    "ADX": {
        "PERIOD": 14,
    },

    "ATR": {
        "PERIOD": 14,
    },

    "BOLLINGER": {
        "PERIOD": 20,
        "STANDARD_DEVIATION": 2,
    },

    "VWAP": {
        "METHOD": "SESSION_BASED",
    },

    "RELATIVE_VOLUME": {
        "BASELINE_CANDLES": 20,
    },

    "OBV": {
        "METHOD": "STANDARD",
    },

    "CMF": {
        "PERIOD": 20,
    },

    "SUPPORT_RESISTANCE": {
        "METHOD": "RECENT_CONFIRMED_SWING_LEVELS",
    },

    "MIN_REQUIRED_CANDLES": 220,
}


# ============================================================
# 7. MARKET FILTER CONFIGURATION
# ============================================================

MARKET_CONFIG = {
    "BTC_SYMBOL": "BTCUSDT",

    "REQUIRED_TIMEFRAMES": [
        "15m",
        "1h",
        "4h",
    ],

    "REQUIRED_INDICATORS": [
        "MA20",
        "MA50",
        "MA200",
        "RSI14",
        "MACD",
        "ADX14",
        "ATR14",
        "VOLUME_TREND",
    ],

    "MARKET_STATUSES": [
        "BULLISH",
        "NEUTRAL",
        "BEARISH",
        "HIGH_RISK",
        "UNKNOWN",
    ],

    "UNKNOWN_DATA_POLICY": "CONSERVATIVE",

    "REJECT_NEW_SIGNALS_ON": [
        "HIGH_RISK",
    ],

    "ALLOW_SELECTIVE_SIGNALS_ON_BEARISH": True,
}


# ============================================================
# 8. SIGNAL SCORING CONFIGURATION
# ============================================================

SIGNAL_CONFIG = {
    "MAX_SCORE": 12,
    "MIN_SCORE": 9,

    "STRONG_BUY_MIN_SCORE": 9,
    "STRONG_BUY_MAX_SCORE": 10,

    "EXCELLENT_BUY_MIN_SCORE": 11,
    "EXCELLENT_BUY_MAX_SCORE": 12,

    "REJECT_MAX_SCORE": 8,

    "SCORE_COMPONENTS": [
        "MARKET_CONDITION",
        "BTC_CONTEXT",
        "TREND_STRUCTURE",
        "EMA_CONFIRMATION",
        "MA_CONFIRMATION",
        "RSI_MOMENTUM",
        "MACD_CONFIRMATION",
        "ADX_STRENGTH",
        "RELATIVE_VOLUME",
        "VWAP_CONFIRMATION",
        "OBV_CMF_CONFIRMATION",
        "BREAKOUT_RETEST_QUALITY",
    ],

    "POINTS_PER_COMPONENT": 1,

    "MISSING_DATA_POLICY": "DO_NOT_AWARD_POINTS",

    "MANDATORY_REJECTION_OVERRIDES_SCORE": True,

    "ALLOWED_SIGNAL_TYPES": [
        "STRONG BUY",
        "EXCELLENT BUY",
    ],
}


# ============================================================
# 9. SIGNAL TRACKING CONFIGURATION
# ============================================================

TRACKING_CONFIG = {
    "MAX_TRACKING_HOURS": 48,

    "SCALP_ENTRY_VALIDITY_MINUTES": 15,
    "SWING_ENTRY_VALIDITY_MINUTES": 60,

    "DUPLICATE_PREVENTION": True,

    # Initial value: pending backtesting.
    "COOLDOWN_HOURS": 6,

    "SIGNAL_EXPIRY": True,
    "PERFORMANCE_TRACKING": True,

    "TRACK_FIELDS": [
        "SIGNAL_TIMESTAMP",
        "ENTRY_PRICE",
        "ACTUAL_ENTRY_STATUS",
        "STOP_LOSS",
        "T1",
        "T2",
        "T3",
        "MAX_FAVORABLE_MOVEMENT",
        "MAX_ADVERSE_MOVEMENT",
        "TARGET_REACHED",
        "STOP_LOSS_REACHED",
        "EXPIRED_STATUS",
        "FINAL_RESULT",
    ],

    "EXPIRED_BEFORE_ENTRY_COUNTS_AS_TRADE": False,
}


# ============================================================
# 10. API CONFIGURATION
# ============================================================

API_CONFIG = {
    "BASE_URL": "https://data-api.binance.vision",

    "ENDPOINTS": {
        "EXCHANGE_INFO": "/api/v3/exchangeInfo",
        "KLINES": "/api/v3/klines",
        "TICKER_24H": "/api/v3/ticker/24hr",
        "ORDER_BOOK": "/api/v3/depth",
    },

    "DATA_FRESHNESS_SECONDS": {
        "5m": None,
        "15m": None,
        "30m": None,
        "1h": None,
        "TICKER_24H": 120,
        "ORDER_BOOK": 10,
    },

    "REQUIRE_CLOSED_CANDLES": True,

    "MAX_RETRIES": 3,
    "REQUEST_TIMEOUT_SECONDS": 10,
    "RETRY_BACKOFF_SECONDS": 1,

    "USE_PUBLIC_API_ONLY": True,

    "MISSING_DATA_POLICY": "REJECT_OR_MARK_UNKNOWN",
}


# ============================================================
# 11. TELEGRAM CONFIGURATION
# ============================================================

TELEGRAM_CONFIG = {
    "BOT_TOKEN_ENV": "TELEGRAM_BOT_TOKEN",
    "CHAT_ID_ENV": "TELEGRAM_CHAT_ID",

    "REQUIRE_BOTH_CREDENTIALS": True,

    "TEST_MESSAGE_SEPARATE_FROM_SIGNALS": True,

    "REQUIRED_SIGNAL_FIELDS": [
        "SYMBOL",
        "SIGNAL_CLASSIFICATION",
        "STRATEGY",
        "SCORE",
        "MARKET_CONDITION",
        "ENTRY_ZONE",
        "STOP_LOSS",
        "T1",
        "T2",
        "T3",
        "RISK_REWARD",
        "ENTRY_EXPIRY",
        "TIMESTAMP_UTC",
        "WARNINGS",
    ],
}


# ============================================================
# 12. GITHUB ACTIONS CONFIGURATION
# ============================================================

WORKFLOW_CONFIG = {
    "RUNTIME": "Python 3.11",
    "SCHEDULE_INTERVAL_MINUTES": 5,
    "MANUAL_TESTING": True,
    "RUN_AUTOMATED_TESTS_BEFORE_SIGNALS": True,
    "CREDENTIAL_STORAGE": "GITHUB_SECRETS",
}


# ============================================================
# 13. CONFIGURATION EXPORTS
# ============================================================

REQUIRED_CONFIG_EXPORTS = [
    "CONFIG",
    "TIMEFRAMES",
    "STRATEGIES",
    "RISK_CONFIG",
    "FILTER_CONFIG",
    "API_CONFIG",
]


def get_config():
    """
    Return an independent copy of all configuration sections.
    """

    return {
        "CONFIG": deepcopy(CONFIG),
        "TIMEFRAMES": deepcopy(TIMEFRAMES),
        "STRATEGIES": deepcopy(STRATEGIES),
        "RISK_CONFIG": deepcopy(RISK_CONFIG),
        "FILTER_CONFIG": deepcopy(FILTER_CONFIG),
        "INDICATOR_CONFIG": deepcopy(INDICATOR_CONFIG),
        "MARKET_CONFIG": deepcopy(MARKET_CONFIG),
        "SIGNAL_CONFIG": deepcopy(SIGNAL_CONFIG),
        "TRACKING_CONFIG": deepcopy(TRACKING_CONFIG),
        "API_CONFIG": deepcopy(API_CONFIG),
        "TELEGRAM_CONFIG": deepcopy(TELEGRAM_CONFIG),
        "WORKFLOW_CONFIG": deepcopy(WORKFLOW_CONFIG),
    }


def validate_config():
    """
    Validate critical configuration relationships.
    Raises ValueError if any mandatory rule is violated.
    """

    if CONFIG["MARKET_TYPE"] != "SPOT":
        raise ValueError("Only Binance Spot market is allowed.")

    if CONFIG["QUOTE_ASSET"] != "USDT":
        raise ValueError("Only USDT quote pairs are allowed.")

    if CONFIG["SCAN_INTERVAL_SECONDS"] != 300:
        raise ValueError("Scan interval must be 5 minutes.")

    if RISK_CONFIG["MAX_RISK_PER_TRADE_PERCENT"] > 1.0:
        raise ValueError("Risk per trade cannot exceed 1%.")

    if RISK_CONFIG["MIN_RISK_REWARD_RATIO"] < 2.0:
        raise ValueError("Minimum risk/reward must be at least 1:2.")

    if SIGNAL_CONFIG["MAX_SCORE"] != len(
        SIGNAL_CONFIG["SCORE_COMPONENTS"]
    ):
        raise ValueError("Signal scoring configuration mismatch.")

    if SIGNAL_CONFIG["MIN_SCORE"] != 9:
        raise ValueError("Minimum signal score must be 9.")

    if TRACKING_CONFIG["MAX_TRACKING_HOURS"] != 48:
        raise ValueError("Signal tracking must be 48 hours.")

    if INDICATOR_CONFIG["MIN_REQUIRED_CANDLES"] < 220:
        raise ValueError("Minimum candle history must be at least 220.")

    if API_CONFIG["USE_PUBLIC_API_ONLY"] is not True:
        raise ValueError("Public API mode is required.")

    if FILTER_CONFIG["ALLOWED_QUOTE_ASSET"] != "USDT":
        raise ValueError("Only USDT quote assets are allowed.")

    return True
