"""
Binance Spot V3 Smart Signal Scanner
System and Integration Contract Tests

Python: 3.11

Tests:
- Module imports
- Configuration validation
- Indicator calculations
- Coin selector ticker compatibility
- Order-book validation
- Market filter interface
- Entry engine interface (SCALP/SWING split + pump protection)
- Risk manager interface (SL bounds + ATR fallback targets)
- Telegram interface
- Signal tracker persistence + entry expiry

No Binance API requests.
No Telegram messages.
No live trading.
"""

import unittest
import tempfile
import os
import importlib

import numpy as np
import pandas as pd


# =========================================================
# MODULE IMPORTS
# =========================================================

import config
import data_provider
import indicators
import market_filter
import coin_selector
import entry_engine
import risk_manager
import telegram_bot
import signal_tracker
import scanner


# =========================================================
# TEST DATA
# =========================================================

def create_test_dataframe(length=250):
    index = np.arange(length)
    close = 100 + index * 0.08 + np.sin(index / 5) * 0.5
    open_price = close - 0.05
    high = np.maximum(open_price, close) + 0.25
    low = np.minimum(open_price, close) - 0.25
    volume = 1000 + np.abs(np.sin(index / 4)) * 300
    start_time = 1_750_000_000_000

    return pd.DataFrame({
        "open_time": [start_time + i * 300_000 for i in range(length)],
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "close_time": [start_time + (i + 1) * 300_000 - 1 for i in range(length)],
        "quote_volume": close * volume,
        "trade_count": [1500] * length,
        "taker_buy_base_volume": volume * 0.55,
        "taker_buy_quote_volume": close * volume * 0.55,
    })


def create_test_order_book():
    return {
        "bids": [["99.95", "1000"], ["99.90", "1000"], ["99.85", "1000"]],
        "asks": [["100.05", "1000"], ["100.10", "1000"], ["100.15", "1000"]],
        "lastUpdateId": 123456,
    }


# =========================================================
# 1. MODULE IMPORT TESTS
# =========================================================

class ModuleImportTests(unittest.TestCase):

    def test_all_modules_import(self):
        modules = [
            "config", "data_provider", "indicators", "market_filter",
            "coin_selector", "entry_engine", "risk_manager",
            "telegram_bot", "signal_tracker", "scanner",
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
            "CONFIG", "TIMEFRAMES", "STRATEGIES",
            "RISK_CONFIG", "FILTER_CONFIG", "API_CONFIG",
        ]
        for name in required:
            with self.subTest(config=name):
                self.assertTrue(hasattr(config, name), f"Missing config export: {name}")

    def test_validate_config(self):
        result = config.validate_config()
        self.assertNotEqual(result, False, "Configuration validation returned False.")

    def test_spot_only_configuration(self):
        result = config.validate_config()
        self.assertNotEqual(result, False)
        self.assertEqual(config.FILTER_CONFIG["ALLOWED_QUOTE_ASSET"], "USDT")
        self.assertTrue(config.API_CONFIG["USE_PUBLIC_API_ONLY"])

    def test_15_point_scoring_matches_components(self):
        """🔥 NEW: Verify 15-point scoring sync with components."""
        self.assertEqual(
            config.SIGNAL_CONFIG["MAX_SCORE"],
            len(config.SIGNAL_CONFIG["SCORE_COMPONENTS"])
        )
        self.assertEqual(config.SIGNAL_CONFIG["MAX_SCORE"], 15)

    def test_early_pump_components_present(self):
        """🔥 NEW: Ensure early-pump components are in the scoring model."""
        components = config.SIGNAL_CONFIG["SCORE_COMPONENTS"]
        self.assertIn("bb_squeeze", components)
        self.assertIn("early_momentum", components)
        self.assertIn("volume_acceleration", components)

    def test_pump_protection_config_present(self):
        """🔥 NEW: Pump protection thresholds must be configured."""
        protection = config.FILTER_CONFIG["PUMP_PROTECTION"]
        self.assertIn("MAX_ROC_PERCENT", protection)
        self.assertIn("MAX_BB_WIDTH", protection)

    def test_entry_validity_minutes_configured(self):
        """🔥 NEW: Entry window validity must be set."""
        self.assertEqual(
            config.TRACKING_CONFIG["SCALP_ENTRY_VALIDITY_MINUTES"], 15
        )
        self.assertEqual(
            config.TRACKING_CONFIG["SWING_ENTRY_VALIDITY_MINUTES"], 60
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
        self.assertGreaterEqual(len(result), 220)

    def test_required_indicator_columns(self):
        result = indicators.calculate_all_indicators(self.df.copy())
        required_columns = ["ema_9", "ema_20", "sma_20", "sma_50", "sma_200"]
        for column in required_columns:
            with self.subTest(column=column):
                self.assertIn(column, result.columns)

    def test_indicator_values_are_numeric(self):
        result = indicators.calculate_all_indicators(self.df.copy())
        for column in ("ema_9", "ema_20", "sma_20", "sma_50", "sma_200"):
            values = pd.to_numeric(result[column], errors="coerce")
            self.assertTrue(np.isfinite(values.dropna()).all())

    def test_new_early_pump_indicators_present(self):
        """🔥 NEW: Verify BB width, ROC, volume momentum are calculated."""
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
        self.order_books = {"TESTUSDT": create_test_order_book()}

    def test_snake_case_ticker(self):
        ticker_data = {
            "TESTUSDT": {
                "quote_volume": "5000000", "trade_count": "5000",
                "last_price": "100", "price_change_percent": "3.5",
                "volume": "50000", "high_price": "105", "low_price": "95",
            }
        }
        result = coin_selector.select_coins(self.symbols, ticker_data, self.order_books)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "TESTUSDT")

    def test_camel_case_ticker(self):
        ticker_data = {
            "TESTUSDT": {
                "quoteVolume": "5000000", "count": "5000",
                "lastPrice": "100", "priceChangePercent": "3.5",
                "volume": "50000", "highPrice": "105", "lowPrice": "95",
            }
        }
        result = coin_selector.select_coins(self.symbols, ticker_data, self.order_books)
        self.assertEqual(len(result), 1)

    def test_low_volume_rejected(self):
        ticker_data = {
            "TESTUSDT": {"quote_volume": "1000", "trade_count": "5000", "last_price": "100"}
        }
        result = coin_selector.select_coins(self.symbols, ticker_data, self.order_books)
        self.assertEqual(result, [])

    def test_non_usdt_pair_rejected(self):
        self.assertFalse(coin_selector._is_valid_symbol("TESTBTC"))

    def test_leveraged_token_rejected(self):
        self.assertFalse(coin_selector._is_valid_symbol("TESTUPUSDT"))

    def test_tokenized_stock_rejected(self):
        """🔥 NEW: Binance xStocks must be rejected."""
        self.assertFalse(coin_selector._is_valid_symbol("NVDABUSDT"))
        self.assertFalse(coin_selector._is_valid_symbol("TSLABUSDT"))

    def test_stablecoin_rejected(self):
        """🔥 NEW: Stablecoins must be rejected."""
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
# 5. MARKET FILTER INTERFACE TESTS
# =========================================================

class MarketFilterTests(unittest.TestCase):

    def test_market_filter_function_exists(self):
        self.assertTrue(callable(market_filter.analyze_market))

    def test_market_context_validator_exists(self):
        self.assertTrue(callable(market_filter.validate_market_context))


# =========================================================
# 6. ENTRY ENGINE TESTS
# =========================================================

class EntryEngineTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = ["evaluate_scalp", "evaluate_swing", "score_setup", "validate_entry"]
        for name in required:
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(entry_engine, name, None)))

    def test_only_approved_signal_classes(self):
        self.assertIn(
            "STRONG BUY",
            entry_engine.__dict__.get(
                "APPROVED_CLASSIFICATIONS", ["STRONG BUY", "EXCELLENT BUY"]
            ),
        )

    def test_scalp_swing_configs_differ(self):
        """🔥 NEW: SCALP and SWING must have different thresholds."""
        self.assertNotEqual(
            entry_engine.SCALP_CONFIG["MIN_RVOL"],
            entry_engine.SWING_CONFIG["MIN_RVOL"],
        )
        self.assertNotEqual(
            entry_engine.SCALP_CONFIG["MIN_ADX"],
            entry_engine.SWING_CONFIG["MIN_ADX"],
        )

    def test_pump_protection_functions_exist(self):
        """🔥 NEW: Pump protection functions must exist."""
        required = [
            "_has_consecutive_bullish_candles",
            "_has_rvol_collapse",
            "_has_insufficient_upside",
        ]
        for name in required:
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(entry_engine, name, None)))


# =========================================================
# 7. RISK MANAGER TESTS
# =========================================================

class RiskManagerTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "calculate_stop_loss", "calculate_targets",
            "calculate_position_size", "validate_risk", "build_risk_plan",
        ]
        for name in required:
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(risk_manager, name, None)))

    def test_position_size_function(self):
        result = risk_manager.calculate_position_size(
            capital=100, entry=10, stop_loss=9,
            risk_percent=1, fee_rate=0.001, slippage_rate=0.001,
        )
        self.assertIsInstance(result, dict)
        self.assertGreater(result.get("quantity", 0), 0)

    def test_stop_loss_rejects_too_wide(self):
        """🔥 NEW: SL wider than 8% must be rejected."""
        with self.assertRaises(ValueError):
            risk_manager.calculate_stop_loss(
                entry_price=100, support_level=85, atr=None,
            )

    def test_stop_loss_bounds_configured(self):
        """🔥 NEW: SL distance bounds must be configured."""
        self.assertGreater(risk_manager.MAX_STOP_LOSS_DISTANCE_PERCENT, 0)
        self.assertLessEqual(risk_manager.MAX_STOP_LOSS_DISTANCE_PERCENT, 20)
        self.assertGreater(risk_manager.MIN_STOP_LOSS_DISTANCE_PERCENT, 0)


# =========================================================
# 8. TELEGRAM INTERFACE TESTS
# =========================================================

class TelegramTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "credentials_available", "send_message",
            "send_connection_test", "format_signal", "send_signal",
        ]
        for name in required:
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(telegram_bot, name, None)))

    def test_missing_credentials_do_not_expose_secrets(self):
        status = telegram_bot.get_telegram_status()
        self.assertIsInstance(status, dict)
        self.assertNotIn("TELEGRAM_BOT_TOKEN_VALUE", status)


# =========================================================
# 9. SIGNAL TRACKER TESTS
# =========================================================

class SignalTrackerTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "load_history", "save_history", "register_signal",
            "check_duplicate", "update_signal_status",
            "expire_old_signals", "calculate_performance",
        ]
        for name in required:
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(signal_tracker, name, None)))

    def test_entry_expiry_function_exists(self):
        """🔥 NEW: expire_unfilled_entries must exist."""
        self.assertTrue(callable(getattr(signal_tracker, "expire_unfilled_entries", None)))

    def test_entry_validity_constants_present(self):
        """🔥 NEW: Entry window constants must be loaded."""
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
# 10. SCANNER INTERFACE TESTS
# =========================================================

class ScannerTests(unittest.TestCase):

    def test_scanner_functions_exist(self):
        required = [
            "run_scanner", "fetch_market_context", "collect_candidates",
            "evaluate_candidate", "attach_risk_plan", "deliver_signal",
        ]
        for name in required:
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(scanner, name, None)))

    def test_non_usdt_signal_rejected(self):
        signal = {"symbol": "BTCBTC", "classification": "STRONG BUY", "entry_price": 100}
        self.assertFalse(scanner.is_eligible_signal(signal))

    def test_unapproved_signal_rejected(self):
        signal = {"symbol": "BTCUSDT", "classification": "WEAK BUY", "entry_price": 100}
        self.assertFalse(scanner.is_eligible_signal(signal))


# =========================================================
# 11. BREAKOUT + RETEST LOGIC TESTS
# =========================================================

class EntryEngineBreakoutRetestTests(unittest.TestCase):

    def make_breakout_dataframe(self, retest_low=100.80):
        rows = []
        for _ in range(23):
            rows.append({
                "open": 100.0, "high": 101.0, "low": 99.5,
                "close": 100.0, "volume": 1000.0,
            })
        rows.append({
            "open": 100.0, "high": 103.0, "low": 100.0,
            "close": 102.5, "volume": 2500.0,
        })
        rows.append({
            "open": 101.0, "high": 102.0, "low": retest_low,
            "close": 101.5, "volume": 1800.0,
        })
        return pd.DataFrame(rows)

    def test_separate_candle_breakout_and_retest(self):
        df = self.make_breakout_dataframe()
        result = entry_engine._get_breakout_data(df)
        self.assertTrue(result.get("breakout"))
        self.assertTrue(result.get("retest"))
        self.assertTrue(result.get("above_resistance"))

    def test_failed_retest_is_rejected(self):
        df = self.make_breakout_dataframe(retest_low=99.0)
        result = entry_engine._get_breakout_data(df)
        self.assertFalse(result.get("retest", False))

    def test_breakout_without_separate_retest_is_rejected(self):
        df = self.make_breakout_dataframe()
        df.loc[df.index[-1], "open"] = 100.0
        df.loc[df.index[-1], "high"] = 103.0
        df.loc[df.index[-1], "low"] = 100.0
        df.loc[df.index[-1], "close"] = 102.5

        result = entry_engine._get_breakout_data(df)

        self.assertFalse(result.get("breakout", False))
        self.assertFalse(result.get("retest", False))

    def test_unknown_market_context_is_rejected(self):
        result = entry_engine._validate_market_context({
            "market_status": "UNKNOWN",
            "btc_trend": "UNKNOWN",
            "risk_level": "UNKNOWN",
        })
        self.assertFalse(result[0])

    def test_high_risk_market_is_rejected(self):
        result = entry_engine._validate_market_context({
            "market_status": "HIGH_RISK",
            "btc_trend": "BEARISH",
            "risk_level": "HIGH",
        })
        self.assertFalse(result[0])


# =========================================================
# TEST RUNNER
# =========================================================

if __name__ == "__main__":
    print("=" * 60)
    print("BINANCE SPOT V3 SYSTEM TESTS")
    print("=" * 60)
    unittest.main(verbosity=2)
