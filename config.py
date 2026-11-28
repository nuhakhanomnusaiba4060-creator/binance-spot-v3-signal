
"""
File: config.py
System: Binance Spot V3 Smart Signal Scanner
Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Compatibility: New 7-Layer Signal Architecture
Test Status: NOT RUN

Central configuration for:
- 7-Layer weighted signal intelligence
- BTC market regime
- Multi-timeframe confirmation
- Liquidity and order-flow analysis
- Entry and risk management
- Spot-only position sizing
- Backtesting and paper trading
- Telegram notification
"""

from __future__ import annotations

import copy
import os
from typing import Any


# ============================================================
# 1. SYSTEM INFORMATION
# ============================================================

SYSTEM_NAME = "Binance Spot V3 Smart Signal Scanner"

CODE_VERSION = "4.0.0"
FORMULA_VERSION = "4.0"

PYTHON_MIN_VERSION = (3, 11)

EXCHANGE = "BINANCE"
MARKET_TYPE = "SPOT"
QUOTE_ASSET = "USDT"

BASE_URL = "https://data-api.binance.vision"

TIMEZONE = "Asia/Dhaka"

# Public market data only.
# No API key is required for public Binance Spot endpoints.


# ============================================================
# 2. ENVIRONMENT HELPERS
# ============================================================

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    value = value.strip().lower()

    if value in {"1", "true", "yes", "on"}:
        return True

    if value in {"0", "false", "no", "off"}:
        return False

    return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# 3. RUNTIME CONFIGURATION
# ============================================================

RUNTIME_CONFIG = {
    "environment": os.getenv("ENVIRONMENT", "production").lower(),

    "dry_run": _env_bool("DRY_RUN", False),

    "capital_usdt": _env_float(
        "SCANNER_CAPITAL_USDT",
        100.0
    ),

    "log_level": os.getenv("LOG_LEVEL", "INFO").upper(),

    "max_candidates_per_run": _env_int(
        "MAX_CANDIDATES_PER_RUN",
        30
    ),

    "max_signals_per_run": _env_int(
        "MAX_SIGNALS_PER_RUN",
        3
    ),

    "spot_only": True,

    "allow_futures": False,

    "allow_margin": False,

    "allow_short_signals": False,
}


# ============================================================
# 4. TIMEFRAME CONFIGURATION
# ============================================================

TIMEFRAME_CONFIG = {

    "SCALP": {
        "entry": "5m",
        "confirmation": "15m",
        "structure": "30m",

        "required_timeframes": [
            "5m",
            "15m",
            "30m",
        ],

        "candle_limit": 300,
    },

    "SWING": {
        "entry": "15m",
        "confirmation": "30m",
        "structure": "1h",

        "required_timeframes": [
            "15m",
            "30m",
            "1h",
        ],

        "candle_limit": 300,
    },

    "BTC": {
        "required_timeframes": [
            "15m",
            "1h",
            "4h",
        ],

        "candle_limit": 300,
    },
}


# ============================================================
# 5. FORMULA WEIGHTS — TOTAL 100
# ============================================================

LAYER_WEIGHTS = {

    "btc_market_regime": {
        "total": 15,

        "btc_ema_alignment": 5,
        "btc_rsi_adx": 3,
        "btc_atr_risk": 2,
        "market_breadth": 5,
    },

    "technical_structure": {
        "total": 20,

        "ema_alignment": 5,
        "rsi": 3,
        "macd_momentum": 3,
        "adx": 3,
        "market_structure": 4,
        "bollinger_bands": 2,
    },

    "volume_momentum": {
        "total": 15,

        "relative_volume": 5,
        "obv": 4,
        "volume_expansion": 3,
        "roc": 3,
    },

    "liquidity_order_flow": {
        "total": 15,

        "bid_ask_spread": 3,
        "order_book_imbalance": 4,
        "order_book_depth": 3,
        "trade_flow_cvd": 3,
        "slippage": 2,
    },

    "entry_quality": {
        "total": 15,

        "support_resistance": 4,
        "breakout_confirmation": 3,
        "retest_quality": 3,
        "vwap": 2,
        "atr_entry_distance": 3,
    },

    "risk_reward": {
        "total": 10,

        "atr_stop_loss": 3,
        "net_risk_reward": 4,
        "position_sizing": 2,
        "fees_slippage": 1,
    },

    "fundamental_onchain": {
        "total": 10,

        "token_unlock_supply": 2,
        "market_cap_fdv": 2,
        "exchange_flows": 2,
        "holder_whale_concentration": 2,
        "security_development_health": 2,
    },
}


TOTAL_FORMULA_SCORE = 100


# ============================================================
# 6. SIGNAL CLASSIFICATION
# ============================================================

CLASSIFICATION_CONFIG = {

    "EXCELLENT BUY": {
        "minimum_score": 90,
        "maximum_score": 100,
        "telegram_enabled": True,
    },

    "STRONG BUY": {
        "minimum_score": 85,
        "maximum_score": 89,
        "telegram_enabled": True,
    },

    "WATCHLIST": {
        "minimum_score": 75,
        "maximum_score": 84,
        "telegram_enabled": False,
    },

    "WAIT": {
        "minimum_score": 60,
        "maximum_score": 74,
        "telegram_enabled": False,
    },

    "REJECT": {
        "minimum_score": 0,
        "maximum_score": 59,
        "telegram_enabled": False,
    },
}

# Score is a weighted assessment, NOT a probability of profit.
# Hard gates always override the score.


# ============================================================
# 7. BTC MARKET REGIME
# ============================================================

BTC_REGIME_CONFIG = {

    "regimes": [
        "STRONG_BULLISH",
        "BULLISH",
        "NEUTRAL",
        "BEARISH",
        "HIGH_RISK",
    ],

    "ema_periods": [
        20,
        50,
        200,
    ],

    "rsi_period": 14,

    "adx_period": 14,

    "atr_period": 14,

    "high_risk_blocks_new_buy": True,

    "bearish_requires_stronger_confirmation": True,

    "use_market_breadth": True,

    "breadth_sample_size": 50,

    "avoid_duplicate_btc_penalty": True,
}


# ============================================================
# 8. TECHNICAL INDICATORS
# ============================================================

INDICATOR_CONFIG = {

    "ema_periods": [
        20,
        50,
        200,
    ],

    "rsi": {
        "period": 14,
        "oversold": 30,
        "neutral_low": 45,
        "neutral_high": 55,
        "overbought": 70,
    },

    "macd": {
        "fast": 12,
        "slow": 26,
        "signal": 9,
    },

    "adx": {
        "period": 14,
        "trend_threshold": 20,
        "strong_trend_threshold": 25,
    },

    "atr": {
        "period": 14,
    },

    "bollinger": {
        "period": 20,
        "standard_deviation": 2.0,
    },

    "rvol": {
        "period": 20,
        "minimum_reference": 1.0,
    },

    "obv": {
        "enabled": True,
    },

    "roc": {
        "period": 12,
    },

    "vwap": {
        "enabled": True,
    },

    "support_resistance": {
        "lookback": 50,
        "pivot_left": 3,
        "pivot_right": 3,
    },
}


# ============================================================
# 9. MARKET STRUCTURE
# ============================================================

MARKET_STRUCTURE_CONFIG = {

    "enabled": True,

    "detect_higher_high": True,

    "detect_higher_low": True,

    "detect_lower_high": True,

    "detect_lower_low": True,

    "detect_bos": True,

    "detect_choch": True,

    "structure_lookback": 50,

    # Closed candle confirmation only.
    "use_closed_candles": True,
}


# ============================================================
# 10. LIQUIDITY AND ORDER FLOW
# ============================================================

LIQUIDITY_CONFIG = {

    "order_book_limit": 100,

    "depth_levels": 10,

    "maximum_spread_percent": 0.15,

    "minimum_top_depth_usdt": 5000.0,

    "maximum_estimated_slippage_percent": 0.15,

    "maximum_imbalance_ratio": 5.0,

    "minimum_order_book_levels": 5,

    "use_trade_flow_proxy": True,

    "use_cvd_proxy": True,

    "reject_invalid_order_book": True,
}


# ============================================================
# 11. ENTRY QUALITY
# ============================================================

ENTRY_CONFIG = {

    "use_support_resistance": True,

    "use_breakout_confirmation": True,

    "use_retest_confirmation": True,

    "use_vwap": True,

    "use_atr_entry_distance": True,

    "maximum_entry_extension_atr": 1.5,

    "maximum_entry_distance_from_ema20_percent": 3.0,

    "require_closed_candle_breakout": True,

    "reject_chasing_price": True,

    "entry_validity_minutes": {
        "SCALP": 15,
        "SWING": 60,
    },
}


# ============================================================
# 12. RISK MANAGEMENT
# ============================================================

RISK_CONFIG = {

    # Maximum planned capital risk per trade.
    "risk_percent": 1.0,

    "maximum_risk_percent": 1.0,

    "maximum_open_positions": 3,

    "maximum_signals_per_run": 3,

    "minimum_net_risk_reward": 1.5,

    "atr_stop_loss": {
        "period": 14,

        "SCALP": {
            "multiplier": 1.5,
            "minimum_distance_percent": 0.30,
            "maximum_distance_percent": 3.0,
        },

        "SWING": {
            "multiplier": 2.0,
            "minimum_distance_percent": 0.50,
            "maximum_distance_percent": 5.0,
        },
    },

    "position_sizing": {
        "method": "FIXED_RISK",

        "risk_based": True,

        "include_entry_fee": True,

        "include_exit_fee": True,

        "include_slippage": True,

        "minimum_order_value_usdt": 10.0,
    },

    "targets": {
        "minimum_targets": 1,
        "maximum_targets": 3,

        "allow_partial_targets": True,

        "use_resistance_levels": True,

        "use_atr_fallback": True,
    },

    "cooldown_hours": 6,

    "maximum_tracking_hours": 48,
}


# ============================================================
# 13. FEES AND EXECUTION COST
# ============================================================

EXECUTION_COST_CONFIG = {

    # Initial estimate. Actual account fee may differ.
    "entry_fee_percent": 0.10,

    "exit_fee_percent": 0.10,

    "round_trip_fee_percent": 0.20,

    "estimated_slippage_percent": 0.05,

    "include_fees_in_net_rr": True,

    "include_slippage_in_net_rr": True,

    "include_costs_in_position_size": True,

    "assume_market_order": True,

    "fee_note": (
        "Estimated fee configuration. "
        "Actual Binance account fee must be verified."
    ),
}


# ============================================================
# 14. FUNDAMENTAL AND ON-CHAIN DATA
# ============================================================

FUNDAMENTAL_CONFIG = {

    "enabled": True,

    "missing_data_policy": "UNVERIFIED_ZERO_SCORE",

    "never_fabricate_data": True,

    "token_unlock": {
        "enabled": True,
        "weight": 2,
    },

    "market_cap_fdv": {
        "enabled": True,
        "weight": 2,
    },

    "exchange_flows": {
        "enabled": True,
        "weight": 2,
    },

    "holder_whale_concentration": {
        "enabled": True,
        "weight": 2,
    },

    "security_development_health": {
        "enabled": True,
        "weight": 2,
    },

    "critical_security_incident_blocks_buy": True,

    "severe_liquidity_problem_blocks_buy": True,

    # Missing optional data alone does not block every signal.
    "missing_data_blocks_buy": False,
}


# ============================================================
# 15. HARD GATES
# ============================================================

HARD_GATE_CONFIG = {

    "block_high_risk_btc_regime": True,

    "require_closed_candles": True,

    "reject_stale_data": True,

    "reject_invalid_ohlcv": True,

    "reject_insufficient_history": True,

    "reject_excessive_spread": True,

    "reject_insufficient_depth": True,

    "reject_excessive_slippage": True,

    "reject_overextended_entry": True,

    "reject_invalid_stop_loss": True,

    "reject_invalid_net_risk_reward": True,

    "reject_position_risk_violation": True,

    "reject_duplicate_signal": True,

    "reject_cooldown_violation": True,

    "reject_non_spot_symbols": True,

    "reject_stablecoin_pairs": True,

    "reject_leveraged_tokens": True,
}


# ============================================================
# 16. MARKET DATA
# ============================================================

DATA_CONFIG = {

    "base_url": BASE_URL,

    "timeout_seconds": 15,

    "max_retries": 3,

    "retry_delay_seconds": 1.0,

    "klines_limit": 300,

    "ticker_endpoint": "/api/v3/ticker/24hr",

    "klines_endpoint": "/api/v3/klines",

    "exchange_info_endpoint": "/api/v3/exchangeInfo",

    "depth_endpoint": "/api/v3/depth",

    "ticker_price_endpoint": "/api/v3/ticker/price",

    "use_closed_candles_only": True,

    "drop_current_open_candle": True,

    "maximum_data_age_seconds": 180,

    "require_positive_prices": True,

    "require_valid_volume": True,

    "cache_exchange_info_minutes": 60,

    "cache_ticker_seconds": 30,
}


# ============================================================
# 17. SYMBOL FILTER
# ============================================================

SYMBOL_CONFIG = {

    "quote_asset": "USDT",

    "spot_only": True,

    "exclude_stablecoins": True,

    "exclude_tokenized_stocks": True,

    "exclude_leveraged_tokens": True,

    "exclude_low_liquidity": True,

    "exclude_symbols": [
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "USDPUSDT",
        "DAIUSDT",
    ],

    "excluded_suffixes": [
        "UPUSDT",
        "DOWNUSDT",
        "BULLUSDT",
        "BEARUSDT",
    ],

    "minimum_24h_quote_volume_usdt": 1_000_000.0,

    "maximum_symbols_to_analyze": 100,
}


# ============================================================
# 18. SIGNAL MANAGEMENT
# ============================================================

SIGNAL_CONFIG = {

    "allowed_classifications": [
        "STRONG BUY",
        "EXCELLENT BUY",
    ],

    "send_watchlist_to_telegram": False,

    "send_wait_to_telegram": False,

    "send_rejected_to_telegram": False,

    "prevent_duplicate_signals": True,

    "duplicate_window_hours": 6,

    "signal_id_required": True,

    "store_formula_version": True,

    "store_layer_scores": True,

    "store_market_regime": True,

    "store_entry_snapshot": True,

    "store_risk_plan": True,
}


# ============================================================
# 19. PAPER TRADING
# ============================================================

PAPER_TRADING_CONFIG = {

    "enabled": True,

    "mode": "SIMULATED",

    "track_scalp_and_swing_separately": True,

    "simulate_entry_fee": True,

    "simulate_exit_fee": True,

    "simulate_spread": True,

    "simulate_slippage": True,

    "simulate_execution_delay": True,

    "use_closed_candle_data": True,

    "entry_hit_is_not_guaranteed_fill": True,

    "record_mfe": True,

    "record_mae": True,

    "record_gross_pnl": True,

    "record_net_pnl": True,

    "record_holding_time": True,

    "record_exit_reason": True,

    "minimum_observation_days": 30,

    "preferred_observation_days": 60,
}


# ============================================================
# 20. BACKTESTING
# ============================================================

BACKTEST_CONFIG = {

    "enabled": True,

    "timeframes": [
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
    ],

    "initial_capital_usdt": 100.0,

    "use_realistic_fees": True,

    "use_realistic_slippage": True,

    "avoid_lookahead_bias": True,

    "avoid_survivorship_bias": True,

    "same_candle_sl_tp_policy": "CONSERVATIVE_STOP_FIRST",

    "use_intrabar_data_when_available": True,

    "use_walk_forward_validation": True,

    "use_out_of_sample_testing": True,

    "separate_scalp_and_swing_results": True,

    "metrics": [
        "win_rate",
        "profit_factor",
        "expectancy",
        "maximum_drawdown",
        "average_risk_reward",
        "fee_adjusted_return",
        "maximum_favorable_excursion",
        "maximum_adverse_excursion",
        "signal_frequency",
    ],
}


# ============================================================
# 21. TRACKING AND HISTORY
# ============================================================

TRACKING_CONFIG = {

    "history_file": "signal_history.json",

    "paper_ledger_file": "paper_trading_ledger.json",

    "analytics_file": "signal_analytics.json",

    "backup_directory": "backups",

    "retention_days": 30,

    "maximum_tracking_hours": 48,

    "record_every_signal": True,

    "record_rejected_signals": False,

    "preserve_legacy_history": True,

    "atomic_file_writes": True,

    "backup_before_migration": True,
}


# ============================================================
# 22. ANALYTICS
# ============================================================

ANALYTICS_CONFIG = {

    "enabled": True,

    "update_interval_minutes": 5,

    "report_window_hours": 24,

    "use_snapshot_timestamp": True,

    "timezone": TIMEZONE,

    "separate_scalp_swing": True,

    "calculate_net_pnl": True,

    "calculate_win_rate": True,

    "calculate_profit_factor": True,

    "calculate_expectancy": True,

    "calculate_max_drawdown": True,

    "do_not_assume_entry_fill": True,
}


# ============================================================
# 23. TELEGRAM
# ============================================================

TELEGRAM_CONFIG = {

    "enabled": True,

    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),

    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),

    "parse_mode": "HTML",

    "disable_notification": False,

    "send_only_approved_signals": True,

    "allowed_classifications": [
        "STRONG BUY",
        "EXCELLENT BUY",
    ],

    "include_bengali_explanation": True,

    "include_formula_version": True,

    "include_layer_scores": True,

    "include_btc_regime": True,

    "include_entry": True,

    "include_stop_loss": True,

    "include_targets": True,

    "include_net_profit_estimate": True,

    "include_risk_reward": True,

    "include_position_size": True,

    "include_fees_slippage": True,

    "message_limit": 4000,

    "request_timeout_seconds": 15,
}


# ============================================================
# 24. WORKFLOW
# ============================================================

WORKFLOW_CONFIG = {

    "scanner_schedule": "*/5 * * * *",

    "analytics_schedule": "*/5 * * * *",

    # 18:05 UTC = 00:05 Bangladesh time.
    "daily_report_schedule": "5 18 * * *",

    "python_version": "3.11",

    "scanner_script": "scanner.py",

    "test_script": "test_system.py",

    "analytics_script": "signal_analytics.py",

    "report_script": "signal_24h_report.py",

    "preserve_scanner_schedule": True,

    "non_blocking_analytics": True,
}


# ============================================================
# 25. COMPLETE CONFIGURATION
# ============================================================

CONFIG = {

    "system": {
        "name": SYSTEM_NAME,
        "code_version": CODE_VERSION,
        "formula_version": FORMULA_VERSION,
        "python_min_version": PYTHON_MIN_VERSION,
        "exchange": EXCHANGE,
        "market_type": MARKET_TYPE,
        "quote_asset": QUOTE_ASSET,
        "timezone": TIMEZONE,
    },

    "runtime": RUNTIME_CONFIG,

    "timeframes": TIMEFRAME_CONFIG,

    "layer_weights": LAYER_WEIGHTS,

    "total_formula_score": TOTAL_FORMULA_SCORE,

    "classification": CLASSIFICATION_CONFIG,

    "btc_regime": BTC_REGIME_CONFIG,

    "indicators": INDICATOR_CONFIG,

    "market_structure": MARKET_STRUCTURE_CONFIG,

    "liquidity": LIQUIDITY_CONFIG,

    "entry": ENTRY_CONFIG,

    "risk": RISK_CONFIG,

    "execution_cost": EXECUTION_COST_CONFIG,

    "fundamental": FUNDAMENTAL_CONFIG,

    "hard_gates": HARD_GATE_CONFIG,

    "data": DATA_CONFIG,

    "symbols": SYMBOL_CONFIG,

    "signals": SIGNAL_CONFIG,

    "paper_trading": PAPER_TRADING_CONFIG,

    "backtesting": BACKTEST_CONFIG,

    "tracking": TRACKING_CONFIG,

    "analytics": ANALYTICS_CONFIG,

    "telegram": TELEGRAM_CONFIG,

    "workflow": WORKFLOW_CONFIG,
}


# ============================================================
# 26. CONFIGURATION ACCESS
# ============================================================

def get_config() -> dict[str, Any]:
    """
    Return a deep copy of the complete configuration.
    Prevent accidental modification of global settings.
    """
    return copy.deepcopy(CONFIG)


def get_layer_weights() -> dict[str, dict[str, int]]:
    return copy.deepcopy(LAYER_WEIGHTS)


def get_strategy_config(strategy: str) -> dict[str, Any]:
    strategy = strategy.upper()

    if strategy not in TIMEFRAME_CONFIG:
        raise ValueError(
            f"Unsupported strategy: {strategy}"
        )

    if strategy == "BTC":
        raise ValueError(
            "BTC is a market-context configuration, not a trade strategy."
        )

    return copy.deepcopy(TIMEFRAME_CONFIG[strategy])


def get_telegram_credentials() -> tuple[str, str]:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", ""),
        os.getenv("TELEGRAM_CHAT_ID", ""),
    )


def is_dry_run() -> bool:
    return _env_bool("DRY_RUN", False)


def get_capital_usdt() -> float:
    return _env_float(
        "SCANNER_CAPITAL_USDT",
        RUNTIME_CONFIG["capital_usdt"]
    )


# ============================================================
# 27. CONFIGURATION VALIDATION
# ============================================================

def validate_config(
    config: dict[str, Any] | None = None,
) -> list[str]:
    """
    Validate configuration consistency.

    Returns:
        Empty list: configuration passed validation.
        Non-empty list: validation errors.

    This function does not claim that market data,
    exchange connectivity or trading performance is valid.
    """

    cfg = config if config is not None else CONFIG

    errors: list[str] = []

    weights = cfg.get("layer_weights", {})

    if not weights:
        errors.append("Layer weights are missing.")

    calculated_total = 0

    for layer_name, layer in weights.items():

        if not isinstance(layer, dict):
            errors.append(
                f"Invalid layer configuration: {layer_name}"
            )
            continue

        declared_total = layer.get("total")

        component_total = sum(
            value
            for key, value in layer.items()
            if key != "total" and isinstance(value, (int, float))
        )

        if declared_total != component_total:
            errors.append(
                f"{layer_name}: component weights "
                f"({component_total}) do not equal "
                f"declared total ({declared_total})."
            )

        calculated_total += component_total

    expected_total = cfg.get("total_formula_score", 100)

    if calculated_total != expected_total:
        errors.append(
            f"Formula weight total is {calculated_total}; "
            f"expected {expected_total}."
        )

    if cfg.get("system", {}).get("market_type") != "SPOT":
        errors.append("Only Binance Spot is supported.")

    if cfg.get("runtime", {}).get("allow_futures") is not False:
        errors.append("Futures must remain disabled.")

    if cfg.get("runtime", {}).get("allow_margin") is not False:
        errors.append("Margin must remain disabled.")

    if cfg.get("runtime", {}).get("spot_only") is not True:
        errors.append("Spot-only mode must be enabled.")

    capital = cfg.get("runtime", {}).get("capital_usdt", 0)

    if not isinstance(capital, (int, float)) or capital <= 0:
        errors.append("Capital must be greater than zero.")

    risk = cfg.get("risk", {})

    risk_percent = risk.get("risk_percent", 0)
    max_risk = risk.get("maximum_risk_percent", 0)

    if risk_percent <= 0:
        errors.append("Risk percentage must be positive.")

    if risk_percent > max_risk:
        errors.append(
            "Risk percentage exceeds maximum risk percentage."
        )

    if max_risk > 1.0:
        errors.append(
            "Maximum risk percentage cannot exceed 1% "
            "under the current system policy."
        )

    min_rr = risk.get("minimum_net_risk_reward", 0)

    if min_rr < 1.0:
        errors.append(
            "Minimum net risk/reward must be at least 1.0."
        )

    classification = cfg.get("classification", {})

    expected_bands = {
        "EXCELLENT BUY": (90, 100),
        "STRONG BUY": (85, 89),
        "WATCHLIST": (75, 84),
        "WAIT": (60, 74),
        "REJECT": (0, 59),
    }

    for name, expected in expected_bands.items():

        item = classification.get(name)

        if not item:
            errors.append(
                f"Missing classification: {name}"
            )
            continue

        actual = (
            item.get("minimum_score"),
            item.get("maximum_score"),
        )

        if actual != expected:
            errors.append(
                f"Incorrect score range for {name}: {actual}"
            )

    timeframe = cfg.get("timeframes", {})

    for strategy in ("SCALP", "SWING"):

        item = timeframe.get(strategy)

        if not item:
            errors.append(
                f"Missing timeframe strategy: {strategy}"
            )
            continue

        required = item.get("required_timeframes", [])

        if len(required) != 3:
            errors.append(
                f"{strategy} must have three timeframes."
            )

    telegram_allowed = set(
        cfg.get("telegram", {}).get(
            "allowed_classifications", []
        )
    )

    if telegram_allowed != {
        "STRONG BUY",
        "EXCELLENT BUY",
    }:
        errors.append(
            "Telegram must only send STRONG BUY "
            "and EXCELLENT BUY."
        )

    if cfg.get("fundamental", {}).get(
        "missing_data_blocks_buy"
    ) is not False:
        errors.append(
            "Missing optional fundamental data "
            "must not block all BUY signals."
        )

    if cfg.get("hard_gates", {}).get(
        "require_closed_candles"
    ) is not True:
        errors.append(
            "Closed-candle validation must be enabled."
        )

    if cfg.get("paper_trading", {}).get(
        "entry_hit_is_not_guaranteed_fill"
    ) is not True:
        errors.append(
            "Paper trading must not treat entry hit "
            "as guaranteed execution."
        )

    if cfg.get("tracking", {}).get(
        "preserve_legacy_history"
    ) is not True:
        errors.append(
            "Legacy signal history preservation must remain enabled."
        )

    return errors


def validate_config_or_raise() -> bool:
    """
    Raise ValueError if any configuration check fails.
    """
    errors = validate_config()

    if errors:
        raise ValueError(
            "Configuration validation failed:\n- "
            + "\n- ".join(errors)
        )

    return True


# ============================================================
# 28. MODULE SELF-CHECK
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print(SYSTEM_NAME)
    print(f"Code Version: {CODE_VERSION}")
    print(f"Formula Version: {FORMULA_VERSION}")
    print("=" * 60)

    validation_errors = validate_config()

    if validation_errors:

        print("CONFIGURATION: FAIL")

        for error in validation_errors:
            print(f"- {error}")

        raise SystemExit(1)

    print("CONFIGURATION: PASS")
    print(f"Formula Score: {TOTAL_FORMULA_SCORE}")
    print(f"Market: {MARKET_TYPE}")
    print(f"Quote Asset: {QUOTE_ASSET}")
    print(f"Capital: {get_capital_usdt():.2f} USDT")
    print(f"Dry Run: {is_dry_run()}")

    print("=" * 60)
