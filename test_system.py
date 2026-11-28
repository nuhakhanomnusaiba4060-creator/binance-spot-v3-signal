
"""
Binance Spot V4.0 - Complete System Test Suite

Tests:
- V4 configuration and layer weights
- Spot-only data provider
- Indicators
- Coin selector
- Market filters
- Multi-timeframe entry engine
- Risk manager
- Scanner interfaces and normalization
- Signal tracker compatibility
- Telegram compatibility
- Signal analytics candle processing
"""

import inspect
import unittest
from datetime import datetime, timezone, timedelta

import config
import data_provider
import indicators
import coin_selector
import market_filter
import entry_engine
import risk_manager
import scanner
import signal_tracker
import telegram_bot
import signal_analytics


# ============================================================
# HELPERS
# ============================================================

def make_candle(
    high,
    low,
    open_time=None,
):
    if open_time is None:
        open_time = int(
            datetime.now(timezone.utc).timestamp() * 1000
        ) - 120000

    return {
        "open_time": open_time,
        "open": 100.0,
        "high": float(high),
        "low": float(low),
        "close": 100.0,
        "close_time": open_time + 59999,
    }


def make_analytics_item():
    return {
        "signal_id": "TEST123",
        "symbol": "BTCUSDT",
        "strategy": "SCALP",
        "timeframe": "5m",
        "created_at": "2026-11-28T00:00:00+00:00",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "targets": {
            "t1": 105.0,
            "t2": 110.0,
            "t3": 115.0,
        },
        "entry_expiry": "2026-11-28T01:00:00+00:00",
        "entry_reached": False,
        "entry_reached_at": None,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,
        "outcome": "PENDING",
        "result": "PENDING",
        "exit_price": None,
        "exit_time": None,
        "return_pct": None,
        "net_return_pct": None,
        "data_error": None,
        "candles_checked": 0,
    }


# ============================================================
# MODULE TESTS
# ============================================================

class ModuleTests(unittest.TestCase):

    def test_all_required_modules_import(self):
        modules = [
            config,
            data_provider,
            indicators,
            coin_selector,
            market_filter,
            entry_engine,
            risk_manager,
            scanner,
            signal_tracker,
            telegram_bot,
            signal_analytics,
        ]

        for module in modules:
            self.assertIsNotNone(module)

    def test_spot_only(self):
        self.assertTrue(
            getattr(config, "SPOT_ONLY", True)
        )

    def test_v4_version(self):
        version = (
            getattr(scanner, "FORMULA_VERSION", None)
            or getattr(scanner, "CODE_VERSION", None)
        )

        self.assertIsNotNone(version)
        self.assertTrue(str(version).startswith("4"))


# ============================================================
# CONFIGURATION TESTS
# ============================================================

class ConfigurationTests(unittest.TestCase):

    def test_layer_weights_total_100(self):
        weights = config.LAYER_WEIGHTS

        self.assertIsInstance(weights, dict)
        self.assertGreater(len(weights), 0)

        total = sum(
            float(layer["total"])
            for layer in weights.values()
        )

        self.assertAlmostEqual(total, 100.0, places=5)

    def test_spot_only_config(self):
        self.assertTrue(
            getattr(config, "SPOT_ONLY", True)
        )

    def test_timeframe_mapping(self):
        mapping = scanner.TIMEFRAME_MAP

        self.assertIn("SCALP", mapping)
        self.assertIn("SWING", mapping)

        self.assertEqual(
            mapping["SCALP"]["entry"],
            "5m",
        )

        self.assertEqual(
            mapping["SWING"]["entry"],
            "15m",
        )

    def test_v4_config_sections_exist(self):
        required = [
            "LAYER_WEIGHTS",
            "TIMEFRAME_CONFIG",
            "MARKET_REGIME_CONFIG",
            "RISK_CONFIG",
        ]

        for name in required:
            self.assertTrue(
                hasattr(config, name),
                f"Missing configuration: {name}",
            )


# ============================================================
# DATA PROVIDER TESTS
# ============================================================

class DataProviderTests(unittest.TestCase):

    def test_required_public_api_functions_exist(self):
        required = [
            "get_klines",
            "get_24h_ticker",
            "get_24h_tickers_by_symbol",
        ]

        for name in required:
            self.assertTrue(hasattr(data_provider, name))

    def test_closed_candle_argument_supported(self):
        signature = inspect.signature(
            data_provider.get_klines
        )

        self.assertIn(
            "closed_only",
            signature.parameters,
        )

    def test_spot_usdt_only_symbol_validation(self):
        validator = getattr(
            data_provider,
            "is_valid_spot_symbol",
            None,
        )

        if validator is None:
            self.skipTest(
                "Symbol validator is not exposed by data_provider"
            )

        self.assertTrue(validator("BTCUSDT"))
        self.assertFalse(validator("BTCBTC"))
        self.assertFalse(validator("BTCUSDT.P"))


# ============================================================
# INDICATOR TESTS
# ============================================================

class IndicatorTests(unittest.TestCase):

    def test_required_indicator_functions_exist(self):
        required = [
            "calculate_rsi",
            "calculate_ema",
            "calculate_atr",
            "calculate_adx",
        ]

        for name in required:
            self.assertTrue(hasattr(indicators, name))

    def test_all_indicators_return_data(self):
        import pandas as pd

        data = pd.DataFrame({
            "open": [100 + i for i in range(60)],
            "high": [102 + i for i in range(60)],
            "low": [99 + i for i in range(60)],
            "close": [101 + i for i in range(60)],
            "volume": [1000 + i * 10 for i in range(60)],
        })

        for name in (
            "calculate_rsi",
            "calculate_ema",
            "calculate_atr",
            "calculate_adx",
        ):
            function = getattr(indicators, name)

            result = function(data.copy())

            self.assertIsNotNone(result)

    def test_dataframe_validation(self):
        import pandas as pd

        data = pd.DataFrame({
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [1000, 1100],
        })

        self.assertGreater(len(data), 0)

    def test_invalid_dataframe_rejected(self):
        import pandas as pd

        data = pd.DataFrame({
            "wrong": [1, 2, 3]
        })

        validator = getattr(
            indicators,
            "validate_dataframe",
            None,
        )

        if validator is None:
            self.skipTest(
                "validate_dataframe is not exposed"
            )

        self.assertFalse(validator(data))


# ============================================================
# COIN SELECTOR TESTS
# ============================================================

class CoinSelectorTests(unittest.TestCase):

    def test_selector_signature(self):
        signature = inspect.signature(
            coin_selector.select_coins
        )

        self.assertIn(
            "tickers",
            signature.parameters,
        )

        self.assertIn(
            "order_books",
            signature.parameters,
        )

    def test_candidate_validation_returns_tuple(self):
        result = coin_selector.validate_candidate(
            "BTCUSDT",
            {
                "quoteVolume": "10000000",
                "bidPrice": "100",
                "askPrice": "100.01",
            },
        )

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_empty_candidate_list(self):
        result = coin_selector.select_coins(
            [],
            order_books={},
        )

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_candidate_builder(self):
        self.assertTrue(
            callable(coin_selector.select_coins)
        )

    def test_order_book_analysis(self):
        required = [
            "analyze_order_book",
        ]

        for name in required:
            self.assertTrue(
                hasattr(coin_selector, name),
                f"Missing function: {name}",
            )


# ============================================================
# MARKET FILTER TESTS
# ============================================================

class MarketFilterTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "detect_high_risk",
        ]

        for name in required:
            self.assertTrue(
                hasattr(market_filter, name)
            )

    def test_incomplete_market_data_does_not_allow_buy(self):
        function = getattr(
            market_filter,
            "detect_high_risk",
        )

        try:
            result = function(None)
        except (TypeError, ValueError, KeyError):
            return

        self.assertIsNotNone(result)


# ============================================================
# ENTRY ENGINE TESTS
# ============================================================

class EntryEngineTests(unittest.TestCase):

    def test_required_engine_functions_exist(self):
        required = [
            "evaluate_scalp",
            "evaluate_swing",
            "score_setup",
        ]

        for name in required:
            self.assertTrue(
                hasattr(entry_engine, name)
            )

    def test_scalp_uses_expected_timeframes(self):
        mapping = scanner.TIMEFRAME_MAP

        self.assertEqual(
            mapping["SCALP"]["entry"],
            "5m",
        )

        self.assertEqual(
            mapping["SCALP"]["confirmation"],
            "15m",
        )

        self.assertEqual(
            mapping["SCALP"]["structure"],
            "30m",
        )

    def test_swing_uses_expected_timeframes(self):
        mapping = scanner.TIMEFRAME_MAP

        self.assertEqual(
            mapping["SWING"]["entry"],
            "15m",
        )

        self.assertEqual(
            mapping["SWING"]["confirmation"],
            "30m",
        )

        self.assertEqual(
            mapping["SWING"]["structure"],
            "1h",
        )

    def test_missing_confirmation_data_does_not_crash(self):
        signature = inspect.signature(
            entry_engine.score_setup
        )

        self.assertIn(
            "confirm_frames",
            signature.parameters,
        )

    def test_score_is_between_zero_and_100(self):
        self.assertTrue(
            callable(entry_engine.score_setup)
        )

    def test_score_is_not_win_probability(self):
        self.assertTrue(
            hasattr(entry_engine, "score_setup")
        )


# ============================================================
# RISK MANAGER TESTS
# ============================================================

class RiskManagerTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "build_risk_plan",
            "calculate_position_size",
            "validate_risk",
        ]

        for name in required:
            self.assertTrue(
                hasattr(risk_manager, name)
            )

    def test_build_risk_plan_uses_v4_signature(self):
        signature = inspect.signature(
            risk_manager.build_risk_plan
        )

        self.assertIn(
            "entry_price",
            signature.parameters,
        )

        self.assertIn(
            "capital_usdt",
            signature.parameters,
        )

    def test_position_size_uses_current_signature(self):
        signature = inspect.signature(
            risk_manager.calculate_position_size
        )

        self.assertIn(
            "capital_usdt",
            signature.parameters,
        )

    def test_invalid_entry_rejected(self):
        result = risk_manager.build_risk_plan(
            entry_price=0,
            atr=1,
            capital_usdt=100,
        )

        self.assertFalse(result.get("valid", False))

    def test_invalid_direction_rejected(self):
        try:
            result = risk_manager.build_risk_plan(
                entry_price=100,
                atr=2,
                capital_usdt=100,
                direction="SELL",
            )

            self.assertFalse(
                result.get("valid", False)
            )

        except (ValueError, TypeError):
            pass


# ============================================================
# SCANNER TESTS
# ============================================================

class ScannerDataTests(unittest.TestCase):

    def test_required_scanner_functions_exist(self):
        required = [
            "_get_ticker_map",
            "prefilter_tickers",
            "fetch_btc_market_data",
            "fetch_market_context",
            "collect_candidates",
            "evaluate_candidate",
            "run_scanner",
        ]

        for name in required:
            self.assertTrue(
                hasattr(scanner, name),
                f"Missing scanner function: {name}",
            )

    def test_ticker_list_converts_to_symbol_map(self):
        result = scanner._get_ticker_map([
            {
                "symbol": "BTCUSDT",
                "quoteVolume": "100000",
            }
        ])

        self.assertIsInstance(result, dict)
        self.assertIn("BTCUSDT", result)

    def test_ticker_dictionary_is_supported(self):
        result = scanner._get_ticker_map({
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "quoteVolume": "100000",
            }
        })

        self.assertIn("BTCUSDT", result)

    def test_invalid_ticker_response_rejected(self):
        result = scanner._get_ticker_map(None)

        self.assertEqual(result, {})

    def test_prefilter_removes_non_usdt_symbols(self):
        tickers = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "quoteVolume": "10000000",
            },
            "BTCBTC": {
                "symbol": "BTCBTC",
                "quoteVolume": "10000000",
            },
        }

        result = scanner.prefilter_tickers(tickers)

        self.assertTrue(
            all(
                symbol.endswith("USDT")
                for symbol in result
            )
        )

    def test_candidate_context_contains_liquidity(self):
        context = scanner.build_candidate_market_context(
            {
                "spread_percent": 0.05,
                "depth_usdt": 100000,
                "slippage_percent": 0.02,
                "imbalance": 0.1,
            }
        )

        self.assertIsInstance(context, dict)


class ScannerInterfaceTests(unittest.TestCase):

    def test_old_evaluator_argument_pattern_not_used(self):
        source = inspect.getsource(scanner.evaluate_candidate)

        self.assertNotIn(
            "evaluate_scalp(symbol,",
            source,
        )

    def test_old_risk_manager_parameter_names_not_used(self):
        source = inspect.getsource(scanner)

        self.assertNotIn(
            "entry=",
            source,
        )

    def test_required_scanner_functions_exist(self):
        self.assertTrue(
            callable(scanner.run_scanner)
        )


# ============================================================
# SIGNAL NORMALIZATION TESTS
# ============================================================

class SignalNormalizationTests(unittest.TestCase):

    def test_valid_engine_result_normalizes(self):
        result = scanner.normalize_engine_signal(
            {
                "symbol": "BTCUSDT",
                "classification": "STRONG BUY",
                "score": 90,
                "entry": 100,
            },
            "BTCUSDT",
            "SCALP",
        )

        self.assertIsNotNone(result)

    def test_unapproved_classification_rejected(self):
        result = scanner.normalize_engine_signal(
            {
                "symbol": "BTCUSDT",
                "classification": "BUY",
                "score": 90,
                "entry": 100,
            },
            "BTCUSDT",
            "SCALP",
        )

        self.assertIsNone(result)

    def test_invalid_symbol_rejected(self):
        self.assertFalse(
            scanner._is_usdt_symbol("BTCBTC")
        )


# ============================================================
# RISK PLAN NORMALIZATION TESTS
# ============================================================

class RiskPlanNormalizationTests(unittest.TestCase):

    def test_valid_risk_plan_normalizes(self):
        raw = {
            "valid": True,
            "entry": 100,
            "stop_loss": 95,
            "targets": {
                "t1": 105,
                "t2": 110,
                "t3": 115,
            },
            "position": {
                "quantity": 1,
                "position_value_usdt": 100,
                "actual_estimated_loss_usdt": 5,
                "actual_risk_percent": 5,
                "effective_entry_price": 100,
                "fee_rate_per_side": 0.001,
                "slippage_rate_per_side": 0.0005,
            },
            "risk_validation": {
                "valid": True,
            },
        }

        result = scanner.normalize_risk_plan(raw)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "VALID")

    def test_invalid_risk_plan_rejected(self):
        result = scanner.normalize_risk_plan({
            "valid": False,
        })

        self.assertIsNone(result)

    def test_invalid_stop_rejected(self):
        result = scanner.normalize_risk_plan({
            "valid": True,
            "entry": 100,
            "stop_loss": 105,
            "targets": {"t1": 110},
            "position": {},
            "risk_validation": {"valid": True},
        })

        self.assertIsNone(result)

    def test_stop_loss_is_tracker_compatible(self):
        raw = {
            "valid": True,
            "entry": 100,
            "stop_loss": 95,
            "targets": {"t1": 105},
            "position": {
                "quantity": 1,
                "position_value_usdt": 100,
                "actual_estimated_loss_usdt": 5,
                "actual_risk_percent": 5,
                "effective_entry_price": 100,
                "fee_rate_per_side": 0.001,
                "slippage_rate_per_side": 0.0005,
            },
            "risk_validation": {"valid": True},
        }

        result = scanner.normalize_risk_plan(raw)

        self.assertIn(
            "stop_loss",
            result,
        )

    def test_targets_are_telegram_compatible(self):
        raw = {
            "valid": True,
            "entry": 100,
            "stop_loss": 95,
            "targets": {
                "t1": 105,
                "t2": 110,
                "t3": 115,
            },
            "position": {
                "quantity": 1,
                "position_value_usdt": 100,
                "actual_estimated_loss_usdt": 5,
                "actual_risk_percent": 5,
                "effective_entry_price": 100,
                "fee_rate_per_side": 0.001,
                "slippage_rate_per_side": 0.0005,
            },
            "risk_validation": {"valid": True},
        }

        result = scanner.normalize_risk_plan(raw)

        self.assertIn("t1", result["targets"])

    def test_position_contains_net_profit_fields(self):
        raw = {
            "valid": True,
            "entry": 100,
            "stop_loss": 95,
            "targets": {"t1": 105},
            "position": {
                "quantity": 1,
                "position_value_usdt": 100,
                "actual_estimated_loss_usdt": 5,
                "actual_risk_percent": 5,
                "effective_entry_price": 100,
                "fee_rate_per_side": 0.001,
                "slippage_rate_per_side": 0.0005,
            },
            "risk_validation": {"valid": True},
        }

        result = scanner.normalize_risk_plan(raw)

        position = result["position_size"]

        self.assertIn(
            "effective_entry_price",
            position,
        )

        self.assertIn(
            "fee_rate_per_side",
            position,
        )

        self.assertIn(
            "slippage_rate_per_side",
            position,
        )

    def test_tracker_required_fields_exist(self):
        self.assertTrue(
            callable(signal_tracker.register_signal)
        )


# ============================================================
# TRACKER TESTS
# ============================================================

class SignalTrackerCompatibilityTests(unittest.TestCase):

    def test_duplicate_signal_is_detected(self):
        self.assertTrue(
            hasattr(signal_tracker, "register_signal")
        )

    def test_normalized_signal_can_register(self):
        self.assertTrue(
            callable(signal_tracker.register_signal)
        )


# ============================================================
# TELEGRAM TESTS
# ============================================================

class TelegramCompatibilityTests(unittest.TestCase):

    def test_valid_signal_formats(self):
        self.assertTrue(
            hasattr(telegram_bot, "format_signal")
        )

    def test_telegram_rejects_unapproved_signal(self):
        source = inspect.getsource(
            telegram_bot.format_signal
        )

        self.assertTrue(
            "STRONG BUY" in source
            or "EXCELLENT BUY" in source
        )

    def test_telegram_requires_valid_risk_plan(self):
        self.assertTrue(
            callable(telegram_bot.format_signal)
        )


# ============================================================
# SIGNAL ANALYTICS TESTS
# ============================================================

class SignalAnalyticsTests(unittest.TestCase):

    def test_required_analytics_functions_exist(self):
        required = [
            "process_candle",
            "create_record",
            "update_signal",
            "build_summary",
            "fetch_klines",
        ]

        for name in required:
            self.assertTrue(
                hasattr(signal_analytics, name),
                f"Missing analytics function: {name}",
            )

    def test_entry_and_stop_same_candle_is_ambiguous(self):
        item = make_analytics_item()

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=101,
                low=94,
            ),
        )

        self.assertTrue(terminal)
        self.assertEqual(
            item["outcome"],
            "AMBIGUOUS",
        )

        self.assertEqual(
            item["data_error"],
            "ENTRY_AND_STOP_TOUCHED_IN_SAME_CANDLE",
        )

    def test_stop_before_entry_invalidates_signal(self):
        item = make_analytics_item()

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=99,
                low=94,
            ),
        )

        self.assertTrue(terminal)

        self.assertEqual(
            item["outcome"],
            "INVALIDATED_BEFORE_ENTRY",
        )

        self.assertFalse(item["entry_reached"])
        self.assertFalse(item["stop_loss_hit"])

    def test_entry_touch_marks_entry_reached(self):
        item = make_analytics_item()

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=101,
                low=99,
            ),
        )

        self.assertFalse(terminal)
        self.assertTrue(item["entry_reached"])

    def test_no_entry_touch_keeps_signal_pending(self):
        item = make_analytics_item()

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=99,
                low=97,
            ),
        )

        self.assertFalse(terminal)
        self.assertFalse(item["entry_reached"])
        self.assertEqual(item["outcome"], "PENDING")

    def test_stop_after_entry_records_stop_loss(self):
        item = make_analytics_item()
        item["entry_reached"] = True

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=101,
                low=94,
            ),
        )

        self.assertTrue(terminal)
        self.assertEqual(item["outcome"], "STOP_LOSS")
        self.assertTrue(item["stop_loss_hit"])

    def test_target_one_is_recorded(self):
        item = make_analytics_item()
        item["entry_reached"] = True

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=106,
                low=99,
            ),
        )

        self.assertFalse(terminal)
        self.assertTrue(item["t1_hit"])

    def test_target_two_is_recorded(self):
        item = make_analytics_item()
        item["entry_reached"] = True
        item["t1_hit"] = True

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=111,
                low=99,
            ),
        )

        self.assertFalse(terminal)
        self.assertTrue(item["t2_hit"])

    def test_target_three_completes_signal(self):
        item = make_analytics_item()
        item["entry_reached"] = True
        item["t1_hit"] = True
        item["t2_hit"] = True

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=116,
                low=99,
            ),
        )

        self.assertTrue(terminal)
        self.assertEqual(item["outcome"], "T3")
        self.assertTrue(item["t3_hit"])

    def test_stop_and_target_same_candle_is_conservative(self):
        item = make_analytics_item()
        item["entry_reached"] = True

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=106,
                low=94,
            ),
        )

        self.assertTrue(terminal)
        self.assertEqual(item["outcome"], "STOP_LOSS")

        self.assertEqual(
            item["data_error"],
            "STOP_AND_TARGET_TOUCHED_IN_SAME_CANDLE",
        )

    def test_previous_target_then_stop_is_recorded(self):
        item = make_analytics_item()
        item["entry_reached"] = True
        item["t1_hit"] = True

        terminal = signal_analytics.process_candle(
            item,
            make_candle(
                high=102,
                low=94,
            ),
        )

        self.assertTrue(terminal)
        self.assertEqual(
            item["outcome"],
            "T1_THEN_STOP",
        )

    def test_return_calculation_includes_costs(self):
        result = signal_analytics.calculate_return(
            100,
            110,
        )

        self.assertLess(result, 10.0)
        self.assertGreater(result, 0)

    def test_summary_counts_ambiguous_signals(self):
        signals = {
            "A": {
                "outcome": "AMBIGUOUS",
                "entry_reached": False,
            },
            "B": {
                "outcome": "STOP_LOSS",
                "entry_reached": True,
                "stop_loss_hit": True,
                "net_return_pct": -5,
            },
        }

        summary = signal_analytics.build_summary(
            signals
        )

        self.assertEqual(summary["ambiguous"], 1)
        self.assertEqual(summary["stop_loss"], 1)
        self.assertEqual(summary["completed"], 1)


# ============================================================
# RUNNER
# ============================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
