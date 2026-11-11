
"""
Binance Spot V3 Smart Signal Scanner
Central Configuration Module

Version: 3.0.1
Python: 3.11
Market: Binance Spot Only
Quote Asset: USDT Only

All initial screening thresholds are provisional.
Backtesting and paper trading are required before optimization.
"""

from copy import deepcopy
import math


# ============================================================
# 1. CORE CONFIGURATION
# ============================================================

CONFIG = {
    "VERSION": "3.0.1",
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
    "DEFAULT_DRY_RUN": True,
    "SIMULATION_CAPITAL_USDT": 100.0,
    "ALLOWED_SIGNAL_TYPES": ["STRONG BUY", "EXCELLENT BUY"],
    "EXCLUDED_MARKETS": [
        "FUTURES", "MARGIN", "STOCKS", "SHARES",
        "EQUITIES", "TOKENIZED_STOCKS", "NON_CRYPTO_ASSETS",
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
    "BTC_MARKET": ["15m", "1h", "4h"],
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
        "CONFIRMATION_TIMEFRAMES": ["15m", "30m"],
        "ENTRY_VALIDITY_MINUTES": 15,
    },
    "SWING": {
        "ENABLED": True,
        "MAX_DURATION_HOURS": 48,
        "TRIGGER_TIMEFRAME": "15m",
        "CONFIRMATION_TIMEFRAMES": ["30m", "1h"],
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
    "REQUIRE_BREAKOUT_CONFIRMATION": True,
    "REQUIRE_RETEST": True,
    "REQUIRE_BUYER_CONFIRMATION": True,
    "REJECT_LATE_ENTRY": True,
    "MAX_ENTRY_EXTENSION_PERCENT": 3.0,
    "RETEST_TOLERANCE_PERCENT": 0.5,
    "BREAKOUT_LOOKBACK_CANDLES": 20,
}


# ============================================================
# 4. RISK CONFIGURATION
# ============================================================

RISK_CONFIG = {
    "MAX_RISK_PER_TRADE_PERCENT": 1.0,
    "MIN_RISK_REWARD_RATIO": 2.0,
    "MAX_RISK_PERCENT": 1.0,
    "MIN_RISK_REWARD": 2.0,
    "POSITION_SIZING_METHOD": "STOP_LOSS_DISTANCE",
    "INCLUDE_TRADING_FEES": True,
    "INCLUDE_ESTIMATED_SLIPPAGE": True,
    "FEE_RATE": 0.001,
    "SLIPPAGE_RATE": 0.001,
    "ATR_MULTIPLIER": 1.5,
    "MAX_STOP_LOSS_DISTANCE_PERCENT": 8.0,
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
    "MIN_24H_QUOTE_VOLUME_USDT": 3_000_000,
    "MIN_QUOTE_VOLUME_USDT": 3_000_000,
    "MIN_QUOTE_VOLUME": 3_000_000,
    "MIN_RELATIVE_VOLUME": 1.5,
    "PREFERRED_RELATIVE_VOLUME": 2.0,
    "MAX_SPREAD_PERCENT": 0.15,
    "MIN_24H_TRADE_COUNT": 1000,
    "MIN_24H_TRADES": 1000,
    "MIN_TRADES": 1000,
    "REQUIRE_ORDER_BOOK": True,
    "MIN_ORDER_BOOK_DEPTH": 0,

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
    "EMA": {"FAST": 9, "SLOW": 20},
    "SMA": {"PERIODS": [20, 50, 200]},
    "RSI": {"PERIOD": 14},
    "MACD": {"FAST": 12, "SLOW": 26, "SIGNAL": 9},
    "ADX": {"PERIOD": 14},
    "ATR": {"PERIOD": 14},
    "BOLLINGER": {"PERIOD": 20, "STANDARD_DEVIATION": 2},
    "VWAP": {"METHOD": "SESSION_BASED"},
    "RELATIVE_VOLUME": {"BASELINE_CANDLES": 20},
    "OBV": {"METHOD": "STANDARD"},
    "CMF": {"PERIOD": 20},
    "SUPPORT_RESISTANCE": {
        "METHOD": "RECENT_CONFIRMED_SWING_LEVELS",
        "PIVOT_LOOKBACK": 5,
    },
    "MIN_REQUIRED_CANDLES": 220,
}


# ============================================================
# 7. MARKET FILTER CONFIGURATION
# ============================================================

MARKET_CONFIG = {
    "BTC_SYMBOL": "BTCUSDT",
    "REQUIRED_TIMEFRAMES": ["15m", "1h", "4h"],
    "REQUIRED_INDICATORS": [
        "MA20", "MA50", "MA200", "RSI14",
        "MACD", "ADX14", "ATR14", "VOLUME_TREND",
    ],
    "MARKET_STATUSES": [
        "BULLISH", "NEUTRAL", "BEARISH", "HIGH_RISK", "UNKNOWN",
    ],
    "UNKNOWN_DATA_POLICY": "CONSERVATIVE",
    "REJECT_NEW_SIGNALS_ON": ["HIGH_RISK", "UNKNOWN"],
    "ALLOW_SELECTIVE_SIGNALS_ON_BEARISH": True,
    "REQUIRE_COMPLETE_BTC_DATA": True,
}


# ============================================================
# 8. SIGNAL SCORING CONFIGURATION
# ============================================================

SIGNAL_CONFIG = {
    "SCORE_COMPONENTS": [
        "market_condition",
        "btc_context",
        "multi_timeframe_trend",
        "ema_trend",
        "moving_average_trend",
        "rsi_momentum",
        "macd_momentum",
        "adx_strength",
        "relative_volume",
        "vwap_confirmation",
        "buyer_flow",
        "breakout_retest",
    ],
    "POINTS_PER_COMPONENT": 1,
    "MAX_SCORE": 12,
    "MIN_SCORE": 9,
    "REJECT_MAX_SCORE": 8,
    "STRONG_MIN_SCORE": 9,
    "EXCELLENT_MIN_SCORE": 11,

    # Compatibility aliases used by configuration validation.
    "STRONG_BUY_MIN_SCORE": 9,
    "STRONG_BUY_MAX_SCORE": 10,
    "EXCELLENT_BUY_MIN_SCORE": 11,
    "EXCELLENT_BUY_MAX_SCORE": 12,

    "MISSING_DATA_POLICY": "DO_NOT_AWARD_POINTS",
    "MANDATORY_REJECTION_OVERRIDES_SCORE": True,
    "ALLOWED_SIGNAL_TYPES": ["STRONG BUY", "EXCELLENT BUY"],
}


# ============================================================
# 9. SIGNAL TRACKING CONFIGURATION
# ============================================================

TRACKING_CONFIG = {
    "MAX_TRACKING_HOURS": 48,
    "SCALP_ENTRY_VALIDITY_MINUTES": 15,
    "SWING_ENTRY_VALIDITY_MINUTES": 60,
    "DUPLICATE_PREVENTION": True,
    "COOLDOWN_HOURS": 6,
    "SIGNAL_EXPIRY": True,
    "PERFORMANCE_TRACKING": True,
    "TRACK_PARTIAL_EXITS": True,
    "TRACK_REALIZED_PNL": True,
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
        "REALIZED_PNL",
        "PARTIAL_EXIT_HISTORY",
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
        "5m": 600,
        "15m": 1800,
        "30m": 3600,
        "1h": 7200,
        "4h": 14400,
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
    "MAX_MESSAGE_LENGTH": 4000,
    "REQUEST_TIMEOUT_SECONDS": 15,
    "MAX_RETRIES": 2,
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
    "DEFAULT_DRY_RUN": True,
    "ALLOW_LIVE_WITHOUT_TESTS": False,
    "USE_CONCURRENCY_CONTROL": True,
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
    """Return an independent copy of all configuration sections."""

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


# ============================================================
# 14. CONFIGURATION VALIDATION
# ============================================================

def validate_config():
    """Validate critical configuration relationships."""

    if CONFIG["MARKET_TYPE"] != "SPOT":
        raise ValueError("Only Binance Spot market is allowed.")

    if CONFIG["SPOT_ONLY"] is not True:
        raise ValueError("SPOT_ONLY must be True.")

    if CONFIG["QUOTE_ASSET"] != "USDT" or CONFIG["USDT_ONLY"] is not True:
        raise ValueError("Only USDT Spot pairs are allowed.")

    if CONFIG["SCAN_INTERVAL_SECONDS"] != 300:
        raise ValueError("Scan interval must be 5 minutes.")

    if CONFIG["MAX_TRADE_DURATION_HOURS"] != 48:
        raise ValueError("Maximum trade duration must be 48 hours.")

    if CONFIG["DEFAULT_DRY_RUN"] is not True:
        raise ValueError("Default DRY_RUN must remain enabled.")

    capital = CONFIG["SIMULATION_CAPITAL_USDT"]

    if not isinstance(capital, (int, float)) or not math.isfinite(capital):
        raise ValueError("Simulation capital must be finite.")

    if capital <= 0:
        raise ValueError("Simulation capital must be positive.")

    if TIMEFRAMES["SCALP"]["TRIGGER"] != "5m":
        raise ValueError("Scalp trigger timeframe must be 5m.")

    if TIMEFRAMES["SCALP"]["CONFIRMATION"] != "15m":
        raise ValueError("Scalp confirmation timeframe must be 15m.")

    if TIMEFRAMES["SCALP"]["ADDITIONAL_CONFIRMATION"] != "30m":
        raise ValueError("Scalp additional confirmation must be 30m.")

    if TIMEFRAMES["SWING"]["TRIGGER"] != "15m":
        raise ValueError("Swing trigger timeframe must be 15m.")

    if TIMEFRAMES["SWING"]["CONFIRMATION"] != "30m":
        raise ValueError("Swing confirmation timeframe must be 30m.")

    if TIMEFRAMES["SWING"]["TREND_CONFIRMATION"] != "1h":
        raise ValueError("Swing trend confirmation must be 1h.")

    if TIMEFRAMES["REQUIRE_CLOSED_CANDLES"] is not True:
        raise ValueError("Closed candles must be required.")

    for key in (
        "REQUIRE_BREAKOUT_CONFIRMATION",
        "REQUIRE_RETEST",
        "REQUIRE_BUYER_CONFIRMATION",
        "REJECT_LATE_ENTRY",
    ):
        if STRATEGIES[key] is not True:
            raise ValueError(f"{key} must be True.")

    expected_sequence = [
        "BREAKOUT",
        "CANDLE_CLOSE",
        "RETEST",
        "BUYER_CONFIRMATION",
        "ENTRY",
    ]

    if STRATEGIES["ENTRY_SEQUENCE"] != expected_sequence:
        raise ValueError("Entry sequence configuration mismatch.")

    max_risk = RISK_CONFIG["MAX_RISK_PER_TRADE_PERCENT"]
    min_rr = RISK_CONFIG["MIN_RISK_REWARD_RATIO"]

    if not math.isfinite(max_risk) or not 0 < max_risk <= 1.0:
        raise ValueError("Risk per trade must be above 0 and at most 1%.")

    if not math.isfinite(min_rr) or min_rr < 2.0:
        raise ValueError("Minimum risk/reward must be at least 1:2.")

    if RISK_CONFIG["MAX_RISK_PERCENT"] != max_risk:
        raise ValueError("Risk compatibility alias mismatch.")

    if RISK_CONFIG["MIN_RISK_REWARD"] != min_rr:
        raise ValueError("Risk/reward compatibility alias mismatch.")

    for key in ("FEE_RATE", "SLIPPAGE_RATE", "ATR_MULTIPLIER"):
        value = RISK_CONFIG[key]

        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be finite and non-negative.")

    if RISK_CONFIG["ATR_MULTIPLIER"] <= 0:
        raise ValueError("ATR multiplier must be positive.")

    if FILTER_CONFIG["ALLOWED_QUOTE_ASSET"] != "USDT":
        raise ValueError("Only USDT quote assets are allowed.")

    for key in (
        "MIN_24H_QUOTE_VOLUME_USDT",
        "MIN_24H_TRADE_COUNT",
        "MAX_SPREAD_PERCENT",
        "MIN_RELATIVE_VOLUME",
    ):
        value = FILTER_CONFIG[key]

        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be positive and finite.")

    if FILTER_CONFIG["MIN_ORDER_BOOK_DEPTH"] < 0:
        raise ValueError("Minimum order book depth cannot be negative.")

    rsi = FILTER_CONFIG["RSI"]

    if not (
        0 < rsi["WEAK_BELOW"]
        <= rsi["PREFERRED_MIN"]
        < rsi["PREFERRED_MAX"]
        < rsi["REJECT_ABOVE"]
        <= 100
    ):
        raise ValueError("Invalid RSI threshold ordering.")

    ema = INDICATOR_CONFIG["EMA"]
    macd = INDICATOR_CONFIG["MACD"]

    if ema["FAST"] <= 0 or ema["SLOW"] <= ema["FAST"]:
        raise ValueError("Invalid EMA periods.")

    if macd["FAST"] <= 0 or macd["SLOW"] <= macd["FAST"]:
        raise ValueError("Invalid MACD periods.")

    if macd["SIGNAL"] <= 0:
        raise ValueError("Invalid MACD signal period.")

    if INDICATOR_CONFIG["MIN_REQUIRED_CANDLES"] < 220:
        raise ValueError("Minimum candle history must be at least 220.")

    if INDICATOR_CONFIG["RELATIVE_VOLUME"]["BASELINE_CANDLES"] <= 0:
        raise ValueError("Relative volume baseline must be positive.")

    if MARKET_CONFIG["BTC_SYMBOL"] != "BTCUSDT":
        raise ValueError("BTC market symbol must be BTCUSDT.")

    if MARKET_CONFIG["UNKNOWN_DATA_POLICY"] != "CONSERVATIVE":
        raise ValueError("Unknown data policy must be conservative.")

    if "HIGH_RISK" not in MARKET_CONFIG["REJECT_NEW_SIGNALS_ON"]:
        raise ValueError("HIGH_RISK must reject new signals.")

    if "UNKNOWN" not in MARKET_CONFIG["REJECT_NEW_SIGNALS_ON"]:
        raise ValueError("UNKNOWN market must reject new signals.")

    if SIGNAL_CONFIG["MAX_SCORE"] != len(SIGNAL_CONFIG["SCORE_COMPONENTS"]):
        raise ValueError("Signal scoring configuration mismatch.")

    if SIGNAL_CONFIG["MIN_SCORE"] != 9:
        raise ValueError("Minimum signal score must be 9.")

    if not (
        0 <= SIGNAL_CONFIG["REJECT_MAX_SCORE"]
        < SIGNAL_CONFIG["MIN_SCORE"]
        <= SIGNAL_CONFIG["MAX_SCORE"]
    ):
        raise ValueError("Invalid signal score boundaries.")

    if SIGNAL_CONFIG["STRONG_BUY_MIN_SCORE"] > SIGNAL_CONFIG["STRONG_BUY_MAX_SCORE"]:
        raise ValueError("Invalid STRONG BUY score range.")

    if SIGNAL_CONFIG["EXCELLENT_BUY_MIN_SCORE"] > SIGNAL_CONFIG["EXCELLENT_BUY_MAX_SCORE"]:
        raise ValueError("Invalid EXCELLENT BUY score range.")

    if (
        SIGNAL_CONFIG["STRONG_BUY_MIN_SCORE"] < SIGNAL_CONFIG["MIN_SCORE"]
        or SIGNAL_CONFIG["STRONG_BUY_MAX_SCORE"] > SIGNAL_CONFIG["MAX_SCORE"]
    ):
        raise ValueError("STRONG BUY score range is outside valid boundaries.")

    if (
        SIGNAL_CONFIG["EXCELLENT_BUY_MIN_SCORE"] < SIGNAL_CONFIG["MIN_SCORE"]
        or SIGNAL_CONFIG["EXCELLENT_BUY_MAX_SCORE"] > SIGNAL_CONFIG["MAX_SCORE"]
    ):
        raise ValueError("EXCELLENT BUY score range is outside valid boundaries.")

    if SIGNAL_CONFIG["STRONG_MIN_SCORE"] != SIGNAL_CONFIG["STRONG_BUY_MIN_SCORE"]:
        raise ValueError("STRONG score compatibility mismatch.")

    if SIGNAL_CONFIG["EXCELLENT_MIN_SCORE"] != SIGNAL_CONFIG["EXCELLENT_BUY_MIN_SCORE"]:
        raise ValueError("EXCELLENT score compatibility mismatch.")

    if TELEGRAM_CONFIG["MAX_MESSAGE_LENGTH"] <= 0:
        raise ValueError("Telegram message length must be positive.")

    if TELEGRAM_CONFIG["REQUEST_TIMEOUT_SECONDS"] <= 0:
        raise ValueError("Telegram timeout must be positive.")

    if WORKFLOW_CONFIG["DEFAULT_DRY_RUN"] is not True:
        raise ValueError("Workflow default DRY_RUN must remain enabled.")

    if WORKFLOW_CONFIG["ALLOW_LIVE_WITHOUT_TESTS"] is not False:
        raise ValueError("Live mode without tests is not allowed.")

    return True


# ============================================================
# 15. MODULE EXPORTS
# ============================================================

__all__ = [
    "CONFIG",
    "TIMEFRAMES",
    "STRATEGIES",
    "RISK_CONFIG",
    "FILTER_CONFIG",
    "INDICATOR_CONFIG",
    "MARKET_CONFIG",
    "SIGNAL_CONFIG",
    "TRACKING_CONFIG",
    "API_CONFIG",
    "TELEGRAM_CONFIG",
    "WORKFLOW_CONFIG",
    "REQUIRED_CONFIG_EXPORTS",
    "get_config",
    "validate_config",
]
