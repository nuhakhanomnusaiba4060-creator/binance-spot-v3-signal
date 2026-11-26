"""
Binance Spot V3 Smart Signal Scanner
System Integration and Regression Tests

Python 3.11
Spot market only.

Run:
python test_system.py
"""

import importlib
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

import coin_selector
import config
import data_provider
import entry_engine
import indicators
import market_filter
import risk_manager
import scanner
import signal_tracker
import telegram_bot


# =========================================================
# TEST DATA
# =========================================================

def create_test_dataframe(length=250):
    index = np.arange(length)

    close = (
        100.0
        + index * 0.08
        + np.sin(index / 5) * 0.5
    )

    open_price = close - 0.05

    high = np.maximum(open_price, close) + 0.25
    low = np.minimum(open_price, close) - 0.25

    volume = (
        1000.0
        + np.abs(np.sin(index / 4)) * 300.0
    )

    start_time = 1_750_000_000_000

    return pd.DataFrame({
        "open_time": [
            start_time + i * 300_000
            for i in range(length)
        ],
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "close_time": [
            start_time + (i + 1) * 300_000 - 1
            for i in range(length)
        ],
        "volume": volume,
        "quote_volume": close * volume,
        "trade_count": [1500] * length,
        "taker_buy_base_volume": volume * 0.55,
        "taker_buy_quote_volume": close * volume * 0.55,
    })


def create_test_order_book():
    return {
        "bids": [
            ["99.95", "1000"],
            ["99.90", "1000"],
            ["99.85", "1000"],
        ],
        "asks": [
            ["100.05", "1000"],
            ["100.10", "1000"],
            ["100.15", "1000"],
        ],
        "lastUpdateId": 123456,
    }


def create_market_context(
    market_status="BULLISH",
    btc_trend="BULLISH",
    risk_level="LOW",
):
    return {
        "market_status": market_status,
        "btc_trend": btc_trend,
        "risk_level": risk_level,
        "data_quality": "VALID",
        "signal_policy": {
            "allow_new_signals": True,
            "market_caution": market_status in (
                "NEUTRAL",
                "BEARISH",
            ),
        },
    }


def create_breakout_dataframe(
    breakout=True,
    retest=True,
    failed_retest=False,
):
    """
    Base candles:
    Resistance = 101

    Breakout:
    Close above 101

    Retest:
    Price returns to resistance area and holds.

    Fresh breakout:
    Latest candle itself breaks resistance.
    """

    rows = []

    for _ in range(25):
        rows.append({
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.0,
            "volume": 1000.0,
        })

    if not breakout:
        return pd.DataFrame(rows)

    rows.append({
        "open": 100.0,
        "high": 102.5,
        "low": 100.0,
        "close": 102.0,
        "volume": 2500.0,
    })

    if not retest:
        return pd.DataFrame(rows)

    rows.append({
        "open": 102.0,
        "high": 102.3,
        "low": 101.2,
        "close": 101.8,
        "volume": 1500.0,
    })

    retest_low = 97.0 if failed_retest else 100.8

    rows.append({
        "open": 101.8,
        "high": 102.1,
        "low": retest_low,
        "close": 101.9,
        "volume": 1800.0,
    })

    return pd.DataFrame(rows)


# =========================================================
# 1. MODULE IMPORT TESTS
# =========================================================

class ModuleImportTests(unittest.TestCase):

    def test_all_modules_import(self):
        modules = [
            "config",
            "data_provider",
            "indicators",
            "market_filter",
            "coin_selector",
            "entry_engine",
            "risk_manager",
            "telegram_bot",
            "signal_tracker",
            "scanner",
        ]

        for module_name in modules:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)


# =========================================================
# 2. CONFIGURATION TESTS
# =========================================================

class ConfigurationTests(unittest.TestCase):

    def test_required_config_sections_exist(self):
        required = [
            "CONFIG",
            "TIMEFRAMES",
            "STRATEGIES",
            "RISK_CONFIG",
            "FILTER_CONFIG",
            "API_CONFIG",
            "SIGNAL_CONFIG",
        ]

        for name in required:
            with self.subTest(config=name):
                self.assertTrue(
                    hasattr(config, name),
                    f"Missing config section: {name}",
                )

    def test_validate_config(self):
        result = config.validate_config()
        self.assertNotEqual(result, False)

    def test_spot_only_configuration(self):
        self.assertEqual(
            config.FILTER_CONFIG["ALLOWED_QUOTE_ASSET"],
            "USDT",
        )
        self.assertTrue(
            config.API_CONFIG["USE_PUBLIC_API_ONLY"]
        )
        self.assertFalse(
            config.MARKET_CONFIG["ALLOW_SELECTIVE_SIGNALS_ON_BEARISH"]
        )

    def test_scoring_has_15_components(self):
        signal_config = config.SIGNAL_CONFIG
        self.assertEqual(signal_config["MAX_SCORE"], 15)
        self.assertEqual(
            signal_config["MAX_SCORE"],
            len(signal_config["SCORE_COMPONENTS"]),
        )

    def test_pump_protection_config_exists(self):
        protection = config.FILTER_CONFIG["PUMP_PROTECTION"]
        self.assertIn("MAX_ROC_PERCENT", protection)
        self.assertIn("MAX_BB_WIDTH", protection)
        self.assertGreaterEqual(
            config.FILTER_CONFIG["PREFERRED_RELATIVE_VOLUME"],
            config.FILTER_CONFIG["MIN_RELATIVE_VOLUME"],
        )

    def test_entry_validity_configuration(self):
        self.assertEqual(
            config.TRACKING_CONFIG["SCALP_ENTRY_VALIDITY_MINUTES"],
            15,
        )
        self.assertEqual(
            config.TRACKING_CONFIG["SWING_ENTRY_VALIDITY_MINUTES"],
            60,
        )


# =========================================================
# 3. INDICATOR TESTS
# =========================================================

class IndicatorTests(unittest.TestCase):

    def setUp(self):
        self.df = create_test_dataframe()

    def test_dataframe_validation(self):
        result = indicators.validate_dataframe(self.df.copy())
        self.assertIsInstance(result, pd.DataFrame)
        self.assertFalse(result.empty)

    def test_indicator_calculation(self):
        result = indicators.calculate_all_indicators(self.df.copy())
        self.assertIsInstance(result, pd.DataFrame)
        self.assertGreater(len(result), 0)

    def test_required_indicator_columns(self):
        result = indicators.calculate_all_indicators(self.df.copy())
        required = [
            "ema_9",
            "ema_20",
            "sma_20",
            "sma_50",
            "sma_200",
        ]

        for column in required:
            with self.subTest(column=column):
                self.assertIn(column, result.columns)

    def test_indicator_values_are_finite(self):
        result = indicators.calculate_all_indicators(self.df.copy())

        for column in (
            "ema_9",
            "ema_20",
            "sma_20",
            "sma_50",
            "sma_200",
        ):
            values = pd.to_numeric(result[column], errors="coerce")
            self.assertTrue(np.isfinite(values.dropna()).all())

    def test_early_momentum_indicators_exist(self):
        result = indicators.calculate_all_indicators(self.df.copy())
        self.assertIn("bb_width", result.columns)
        self.assertIn("roc", result.columns)
        self.assertIn("volume_momentum", result.columns)


# =========================================================
# 4. COIN SELECTOR TESTS
# =========================================================

class CoinSelectorTests(unittest.TestCase):

    def setUp(self):
        self.symbols = ["TESTUSDT"]
        self.order_books = {
            "TESTUSDT": create_test_order_book()
        }

    def test_snake_case_ticker(self):
        ticker_data = {
            "TESTUSDT": {
                "quote_volume": "5000000",
                "trade_count": "5000",
                "last_price": "100",
                "price_change_percent": "3.5",
                "volume": "50000",
                "high_price": "105",
                "low_price": "95",
            }
        }

        result = coin_selector.select_coins(
            self.symbols,
            ticker_data,
            self.order_books,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "TESTUSDT")

    def test_camel_case_ticker(self):
        ticker_data = {
            "TESTUSDT": {
                "quoteVolume": "5000000",
                "count": "5000",
                "lastPrice": "100",
                "priceChangePercent": "3.5",
                "volume": "50000",
                "highPrice": "105",
                "lowPrice": "95",
            }
        }

        result = coin_selector.select_coins(
            self.symbols,
            ticker_data,
            self.order_books,
        )

        self.assertEqual(len(result), 1)

    def test_low_volume_rejected(self):
        ticker_data = {
            "TESTUSDT": {
                "quote_volume": "1000",
                "trade_count": "5000",
                "last_price": "100",
            }
        }

        result = coin_selector.select_coins(
            self.symbols,
            ticker_data,
            self.order_books,
        )

        self.assertEqual(result, [])

    def test_non_usdt_pair_rejected(self):
        self.assertFalse(coin_selector._is_valid_symbol("TESTBTC"))

    def test_leveraged_token_rejected(self):
        self.assertFalse(coin_selector._is_valid_symbol("TESTUPUSDT"))

    def test_tokenized_stocks_rejected(self):
        self.assertFalse(coin_selector._is_valid_symbol("NVDABUSDT"))
        self.assertFalse(coin_selector._is_valid_symbol("TSLABUSDT"))

    def test_stablecoins_rejected(self):
        self.assertFalse(coin_selector._is_valid_symbol("USDCUSDT"))
        self.assertFalse(coin_selector._is_valid_symbol("XAUTUSDT"))

    def test_order_book_validation(self):
        result = coin_selector.analyze_order_book(create_test_order_book())
        self.assertTrue(result["valid"])
        self.assertGreater(result["best_ask"], result["best_bid"])
        self.assertIsNotNone(result["spread_percent"])

    def test_invalid_order_book_rejected(self):
        result = coin_selector.analyze_order_book({})
        self.assertFalse(result["valid"])


# =========================================================
# 5. MARKET FILTER TESTS
# =========================================================

class MarketFilterTests(unittest.TestCase):

    def test_market_filter_functions_exist(self):
        self.assertTrue(callable(market_filter.analyze_market))
        self.assertTrue(callable(market_filter.validate_market_context))


# =========================================================
# 6. ENTRY ENGINE TESTS
# =========================================================

class EntryEngineTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "evaluate_scalp",
            "evaluate_swing",
            "score_setup",
            "validate_entry",
            "_get_breakout_data",
            "_validate_market_context",
            "_buyer_confirmation",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(entry_engine, name, None))
                )

    def test_approved_signal_classes(self):
        approved = entry_engine.APPROVED_CLASSIFICATIONS
        self.assertIn("STRONG BUY", approved)
        self.assertIn("EXCELLENT BUY", approved)
        self.assertNotIn("WEAK BUY", approved)

    def test_scalp_swing_thresholds_are_different(self):
        self.assertNotEqual(
            entry_engine.SCALP_CONFIG["MIN_RVOL"],
            entry_engine.SWING_CONFIG["MIN_RVOL"],
        )
        self.assertNotEqual(
            entry_engine.SCALP_CONFIG["MIN_ADX"],
            entry_engine.SWING_CONFIG["MIN_ADX"],
        )

    def test_dynamic_config_neutral_market(self):
        result = entry_engine._get_dynamic_config("SCALP", "NEUTRAL")
        self.assertGreater(result["MIN_RVOL"], 0)
        self.assertGreater(result["MIN_ADX"], 0)

    def test_dynamic_config_bearish_market(self):
        result = entry_engine._get_dynamic_config("SCALP", "BEARISH")
        self.assertGreaterEqual(result["MIN_RVOL"], 1.0)
        self.assertGreaterEqual(result["MIN_ADX"], 14.0)

    def test_bearish_market_rejects_scalp_signal(self):
        df = create_test_dataframe()
        result = entry_engine.evaluate_scalp(
            "BTCUSDT",
            {"5m": df, "15m": df, "30m": df},
            market_context=create_market_context(
                market_status="BEARISH",
                btc_trend="BEARISH",
            ),
        )
        self.assertEqual(result["classification"], "REJECT")

    def test_pump_protection_functions_exist(self):
        required = [
            "_has_consecutive_bullish_candles",
            "_has_rvol_collapse",
            "_has_insufficient_upside",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(entry_engine, name, None))
                )

    def test_unknown_market_context_rejected(self):
        result = entry_engine._validate_market_context({
            "market_status": "UNKNOWN",
            "btc_trend": "UNKNOWN",
            "risk_level": "UNKNOWN",
        })
        self.assertFalse(result[0])

    def test_high_risk_market_rejected(self):
        context = create_market_context(risk_level="HIGH")
        result = entry_engine._validate_market_context(context)
        self.assertFalse(result[0])

    def test_low_risk_valid_market_context_accepted(self):
        context = create_market_context()
        result = entry_engine._validate_market_context(context)
        self.assertTrue(result[0])

    def test_bearish_candle_not_buyer_confirmation(self):
        snapshot = {
            "close": 99.0,
            "open": 100.0,
            "high": 101.0,
            "low": 98.0,
            "volume": 2000.0,
            "previous_volume": 1000.0,
        }
        self.assertFalse(entry_engine._buyer_confirmation(snapshot))

    def test_bullish_strong_close_buyer_confirmation(self):
        snapshot = {
            "close": 100.9,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "volume": 1200.0,
            "previous_volume": 1000.0,
        }
        self.assertTrue(entry_engine._buyer_confirmation(snapshot))

    def test_invalid_symbol_rejected(self):
        result = entry_engine.evaluate_scalp(
            "TESTBTC",
            {},
            market_context=create_market_context(),
        )
        self.assertEqual(result["classification"], "REJECT")
        self.assertEqual(result["reason"], "INVALID_USDT_SYMBOL")


# =========================================================
# 7. BREAKOUT TESTS
# =========================================================

class BreakoutTests(unittest.TestCase):

    def test_fresh_breakout_is_accepted(self):
        df = create_breakout_dataframe(breakout=True, retest=False)
        result = entry_engine._get_breakout_data(df, timeframe="5m")
        self.assertTrue(result.get("breakout"))
        self.assertTrue(result.get("fresh_breakout"))
        self.assertTrue(result.get("above_resistance"))

    def test_separate_candle_retest_is_accepted(self):
        df = create_breakout_dataframe(breakout=True, retest=True)
        result = entry_engine._get_breakout_data(df, timeframe="5m")
        self.assertTrue(result.get("breakout"))
        self.assertTrue(result.get("retest"))
        self.assertTrue(result.get("above_resistance"))

    def test_failed_retest_is_not_accepted(self):
        df = create_breakout_dataframe(
            breakout=True,
            retest=True,
            failed_retest=True,
        )
        result = entry_engine._get_breakout_data(df, timeframe="5m")
        self.assertFalse(result.get("breakout", False))
        self.assertFalse(result.get("retest", False))

    def test_no_breakout_is_rejected(self):
        df = create_breakout_dataframe(breakout=False)
        result = entry_engine._get_breakout_data(df, timeframe="5m")
        self.assertFalse(result.get("breakout", False))

    def test_breakout_resistance_is_positive(self):
        df = create_breakout_dataframe(breakout=True, retest=False)
        result = entry_engine._get_breakout_data(df, timeframe="5m")
        self.assertGreater(result.get("resistance", 0), 0)


# =========================================================
# 8. SCORING TESTS
# =========================================================

class ScoringTests(unittest.TestCase):

    def test_zero_score_rejected(self):
        result = entry_engine.score_setup({
            "components": {},
            "market_status": "BULLISH",
            "btc_trend": "BULLISH",
        })
        self.assertEqual(result["classification"], "REJECT")
        self.assertEqual(result["score"], 0)

    def test_score_never_exceeds_maximum(self):
        components = {f"component_{i}": True for i in range(30)}
        result = entry_engine.score_setup({
            "components": components,
            "market_status": "BULLISH",
            "btc_trend": "BULLISH",
        })
        self.assertLessEqual(result["score"], result["max_score"])

    def test_scoring_returns_required_fields(self):
        result = entry_engine.score_setup({
            "components": {f"component_{i}": False for i in range(15)},
            "market_status": "BULLISH",
            "btc_trend": "BULLISH",
        })
        for key in (
            "score",
            "max_score",
            "required_score",
            "classification",
            "components",
        ):
            self.assertIn(key, result)


# =========================================================
# 9. RISK MANAGER TESTS
# =========================================================

class RiskManagerTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "calculate_stop_loss",
            "calculate_targets",
            "calculate_position_size",
            "validate_risk",
            "build_risk_plan",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(risk_manager, name, None))
                )

    def test_position_size_calculation(self):
        result = risk_manager.calculate_position_size(
            capital=100,
            entry=10,
            stop_loss=9,
            risk_percent=1,
            fee_rate=0.001,
            slippage_rate=0.001,
        )
        self.assertIsInstance(result, dict)
        self.assertGreater(result.get("quantity", 0), 0)

    def test_stop_loss_rejects_excessive_distance(self):
        with self.assertRaises(ValueError):
            risk_manager.calculate_stop_loss(
                entry_price=100,
                support_level=85,
                atr=None,
            )

    def test_stop_loss_bounds_are_valid(self):
        self.assertGreater(risk_manager.MAX_STOP_LOSS_DISTANCE_PERCENT, 0)
        self.assertLessEqual(risk_manager.MAX_STOP_LOSS_DISTANCE_PERCENT, 20)
        self.assertGreater(risk_manager.MIN_STOP_LOSS_DISTANCE_PERCENT, 0)


# =========================================================
# 10. TELEGRAM TESTS
# =========================================================

class TelegramTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "credentials_available",
            "send_message",
            "send_connection_test",
            "format_signal",
            "send_signal",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(telegram_bot, name, None))
                )

    def test_telegram_status_does_not_expose_token(self):
        status = telegram_bot.get_telegram_status()
        self.assertIsInstance(status, dict)
        self.assertNotIn("TELEGRAM_BOT_TOKEN_VALUE", status)


# =========================================================
# 11. SIGNAL TRACKER TESTS
# =========================================================

class SignalTrackerTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "load_history",
            "save_history",
            "register_signal",
            "check_duplicate",
            "update_signal_status",
            "expire_old_signals",
            "calculate_performance",
            "expire_unfilled_entries",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(signal_tracker, name, None))
                )

    def test_entry_validity_constants(self):
        self.assertEqual(signal_tracker.SCALP_ENTRY_VALIDITY_MINUTES, 15)
        self.assertEqual(signal_tracker.SWING_ENTRY_VALIDITY_MINUTES, 60)

    def test_history_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = os.path.join(directory, "test_history.json")
            history = signal_tracker.load_history(file_path=file_path)
            self.assertIsInstance(history, dict)
            signal_tracker.save_history(history, file_path=file_path)
            self.assertTrue(os.path.exists(file_path))
            loaded = signal_tracker.load_history(file_path=file_path)
            self.assertIsInstance(loaded, dict)


# =========================================================
# 12. SCANNER TESTS
# =========================================================

class ScannerTests(unittest.TestCase):

    def test_scanner_functions_exist(self):
        required = [
            "run_scanner",
            "fetch_market_context",
            "collect_candidates",
            "evaluate_candidate",
            "attach_risk_plan",
            "deliver_signal",
            "is_eligible_signal",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(scanner, name, None))
                )

    def test_non_usdt_signal_rejected(self):
        signal = {
            "symbol": "BTCBTC",
            "classification": "STRONG BUY",
            "entry_price": 100,
        }
        self.assertFalse(scanner.is_eligible_signal(signal))

    def test_unapproved_signal_rejected(self):
        signal = {
            "symbol": "BTCUSDT",
            "classification": "WEAK BUY",
            "entry_price": 100,
        }
        self.assertFalse(scanner.is_eligible_signal(signal))


# =========================================================
# 13. DATA PROVIDER TESTS
# =========================================================

class DataProviderTests(unittest.TestCase):

    def setUp(self):
        self.df = create_test_dataframe()

    def test_negative_taker_base_volume_rejected(self):
        df = self.df.copy()
        df.loc[0, "taker_buy_base_volume"] = -1
        with self.assertRaises(data_provider.BinanceDataValidationError):
            data_provider._validate_candle_rows(df)

    def test_negative_taker_quote_volume_rejected(self):
        df = self.df.copy()
        df.loc[0, "taker_buy_quote_volume"] = -1
        with self.assertRaises(data_provider.BinanceDataValidationError):
            data_provider._validate_candle_rows(df)

    def test_taker_base_volume_exceeding_total_rejected(self):
        df = self.df.copy()
        df.loc[0, "taker_buy_base_volume"] = df.loc[0, "volume"] * 1.01
        with self.assertRaises(data_provider.BinanceDataValidationError):
            data_provider._validate_candle_rows(df)

    def test_taker_quote_volume_exceeding_total_rejected(self):
        df = self.df.copy()
        df.loc[0, "taker_buy_quote_volume"] = df.loc[0, "quote_volume"] * 1.01
        with self.assertRaises(data_provider.BinanceDataValidationError):
            data_provider._validate_candle_rows(df)

    def test_close_time_before_open_time_rejected(self):
        df = self.df.copy()
        df.loc[0, "close_time"] = df.loc[0, "open_time"] - 1
        with self.assertRaises(data_provider.BinanceDataValidationError):
            data_provider._validate_candle_rows(df)


# =========================================================
# TEST RUNNER
# =========================================================

if __name__ == "__main__":
    print("=" * 60)
    print("BINANCE SPOT V3 SYSTEM TESTS")
    print("=" * 60)

    unittest.main(verbosity=2)
