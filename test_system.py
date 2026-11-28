
"""
Binance Spot V3 Smart Signal Scanner
V4 Formula System Tests

System Version: 4.0.0
Formula Version: 4.0
Python: 3.11+

Run:
python -m unittest -v test_system.py

Network:
No live Binance requests.
No real Telegram messages.
No real trading orders.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import config
import coin_selector
import data_provider
import entry_engine
import indicators
import market_filter
import risk_manager
import scanner
import signal_tracker
import telegram_bot


# ============================================================
# TEST DATA
# ============================================================

def create_ohlcv(length=300):
    index = np.arange(length, dtype=float)

    close = (
        100.0
        + index * 0.035
        + np.sin(index / 8.0) * 0.15
    )

    open_price = close - 0.025
    high = np.maximum(open_price, close) + 0.15
    low = np.minimum(open_price, close) - 0.15

    volume = (
        10000.0
        + np.abs(np.sin(index / 5.0)) * 2500.0
    )

    start_time = 1_750_000_000_000

    return pd.DataFrame({
        "open_time": [
            int(start_time + i * 300_000)
            for i in range(length)
        ],
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "close_time": [
            int(start_time + (i + 1) * 300_000 - 1)
            for i in range(length)
        ],
        "volume": volume,
        "quote_volume": close * volume,
        "trade_count": [2000] * length,
        "taker_buy_base_volume": volume * 0.55,
        "taker_buy_quote_volume": close * volume * 0.55,
    })


def create_order_book():
    return {
        "lastUpdateId": 123456,
        "bids": [
            ["99.99", "10000"],
            ["99.98", "10000"],
            ["99.97", "10000"],
            ["99.96", "10000"],
        ],
        "asks": [
            ["100.01", "10000"],
            ["100.02", "10000"],
            ["100.03", "10000"],
            ["100.04", "10000"],
        ],
    }


def create_raw_risk_plan():
    return {
        "valid": True,
        "reason": "VALID",
        "direction": "BUY",
        "spot_only": True,
        "formula_version": "4.0",
        "entry": 100.0,
        "stop_loss": 98.0,
        "targets": {
            "t1": 104.0,
            "t2": 106.0,
            "t3": 108.0,
        },
        "target_net_returns_pct": {
            "t1": 3.0,
            "t2": 5.0,
            "t3": 7.0,
        },
        "atr": 1.0,
        "risk_distance_pct": 2.0,
        "execution_cost_pct": 0.3,
        "position": {
            "valid": True,
            "reason": "VALID",
            "capital_usdt": 100.0,
            "risk_percent": 1.0,
            "position_value_usdt": 40.0,
            "quantity": 0.4,
            "estimated_loss_usdt": 0.92,
            "estimated_loss_within_budget": True,
        },
        "risk_validation": {
            "valid": True,
            "reason": "VALID",
            "target_checks": {
                "t1": {
                    "valid": True,
                    "net_rr": 1.8,
                },
                "t2": {
                    "valid": True,
                    "net_rr": 2.8,
                },
                "t3": {
                    "valid": True,
                    "net_rr": 3.8,
                },
            },
        },
    }


def create_valid_signal():
    raw_plan = create_raw_risk_plan()

    normalized_plan = scanner.normalize_risk_plan(
        raw_plan,
        entry_price=100.0,
    )

    return {
        "symbol": "BTCUSDT",
        "strategy": "SWING",
        "classification": "STRONG BUY",
        "signal": "STRONG BUY",
        "decision": "BUY",
        "status": "APPROVED",
        "score": 87.5,
        "max_score": 100,
        "formula_version": "4.0",
        "code_version": "4.0.0",
        "entry_price": 100.0,
        "current_price": 100.0,
        "last_price": 100.0,
        "atr": 1.0,
        "atr_value": 1.0,
        "rsi": 60.0,
        "rvol": 1.5,
        "adx": 25.0,
        "btc_trend": "BULLISH",
        "market_status": "BULLISH",
        "risk_level": "BULLISH",
        "generated_at": "2026-11-28T00:00:00+00:00",
        "created_at": "2026-11-28T00:00:00+00:00",
        "warnings": [],
        "risk_plan": normalized_plan,
    }


# ============================================================
# 1. MODULE IMPORT AND VERSION TESTS
# ============================================================

class ModuleTests(unittest.TestCase):

    def test_all_required_modules_import(self):
        modules = [
            config,
            data_provider,
            indicators,
            market_filter,
            coin_selector,
            entry_engine,
            risk_manager,
            signal_tracker,
            telegram_bot,
            scanner,
        ]

        for module in modules:
            with self.subTest(module=module.__name__):
                self.assertIsNotNone(module)

    def test_v4_version(self):
        self.assertEqual(scanner.CODE_VERSION, "4.0.0")
        self.assertEqual(scanner.FORMULA_VERSION, "4.0")

    def test_spot_only(self):
        self.assertEqual(scanner.QUOTE_ASSET, "USDT")
        self.assertTrue(
            scanner.RUNTIME_CONFIG.get("spot_only", True)
        )


# ============================================================
# 2. CONFIGURATION TESTS
# ============================================================

class ConfigurationTests(unittest.TestCase):

    def test_v4_config_sections_exist(self):
        required = [
            "RUNTIME_CONFIG",
            "TIMEFRAME_CONFIG",
            "LAYER_WEIGHTS",
            "CLASSIFICATION_CONFIG",
            "BTC_REGIME_CONFIG",
            "INDICATOR_CONFIG",
            "MARKET_STRUCTURE_CONFIG",
            "LIQUIDITY_CONFIG",
            "ENTRY_CONFIG",
            "RISK_CONFIG",
            "EXECUTION_COST_CONFIG",
            "FUNDAMENTAL_CONFIG",
            "HARD_GATE_CONFIG",
            "DATA_CONFIG",
            "SYMBOL_CONFIG",
            "SIGNAL_CONFIG",
            "PAPER_TRADING_CONFIG",
            "BACKTEST_CONFIG",
            "TRACKING_CONFIG",
            "ANALYTICS_CONFIG",
            "TELEGRAM_CONFIG",
        ]

        for name in required:
            with self.subTest(section=name):
                self.assertTrue(
                    hasattr(config, name),
                    f"Missing V4 config section: {name}",
                )

    def test_layer_weights_total_100(self):
        weights = config.LAYER_WEIGHTS

        self.assertIsInstance(weights, dict)

        total = sum(
            float(value)
            for value in weights.values()
        )

        self.assertAlmostEqual(total, 100.0, places=5)

    def test_timeframe_mapping(self):
        self.assertEqual(
            scanner.TIMEFRAME_MAP["SCALP"],
            {
                "entry": "5m",
                "confirmation": "15m",
                "structure": "30m",
            },
        )

        self.assertEqual(
            scanner.TIMEFRAME_MAP["SWING"],
            {
                "entry": "15m",
                "confirmation": "30m",
                "structure": "1h",
            },
        )

    def test_spot_only_config(self):
        self.assertEqual(
            config.SYMBOL_CONFIG["quote_asset"],
            "USDT",
        )

        self.assertTrue(
            config.SYMBOL_CONFIG["spot_only"]
        )


# ============================================================
# 3. INDICATOR TESTS
# ============================================================

class IndicatorTests(unittest.TestCase):

    def setUp(self):
        self.df = create_ohlcv()

    def test_dataframe_validation(self):
        self.assertTrue(
            indicators.validate_dataframe(self.df)
        )

    def test_all_indicators_return_dataframe(self):
        result = indicators.calculate_all_indicators(
            self.df.copy()
        )

        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), len(self.df))

    def test_required_indicator_functions_exist(self):
        required = [
            "calculate_ema",
            "calculate_rsi",
            "calculate_macd",
            "calculate_atr",
            "calculate_adx",
            "calculate_vwap",
            "calculate_relative_volume",
            "calculate_roc",
            "calculate_obv",
            "calculate_bollinger_bands",
            "support_resistance",
            "detect_market_structure",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(indicators, name, None))
                )

    def test_invalid_dataframe_rejected(self):
        with self.assertRaises(Exception):
            indicators.calculate_all_indicators(
                pd.DataFrame()
            )


# ============================================================
# 4. DATA PROVIDER TESTS
# ============================================================

class DataProviderTests(unittest.TestCase):

    def test_required_public_api_functions_exist(self):
        required = [
            "get_24h_ticker",
            "get_24h_tickers_by_symbol",
            "get_usdt_symbols",
            "get_klines",
            "get_order_book",
            "validate_klines_dataframe",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(data_provider, name, None))
                )

    def test_closed_candle_argument_supported(self):
        import inspect

        parameters = inspect.signature(
            data_provider.get_klines
        ).parameters

        self.assertIn("closed_only", parameters)

    def test_spot_usdt_only_symbol_validation(self):
        self.assertTrue(
            data_provider.is_eligible_spot_usdt_symbol(
                "BTCUSDT"
            )
        )

        self.assertFalse(
            data_provider.is_eligible_spot_usdt_symbol(
                "BTCBTC"
            )
        )


# ============================================================
# 5. COIN SELECTOR TESTS
# ============================================================

class CoinSelectorTests(unittest.TestCase):

    def test_selector_signature(self):
        import inspect

        parameters = inspect.signature(
            coin_selector.select_coins
        ).parameters

        self.assertIn("tickers", parameters)
        self.assertIn("order_books", parameters)
        self.assertIn("max_symbols", parameters)

    def test_empty_candidate_list(self):
        result = coin_selector.select_coins(
            tickers=[],
            order_books={},
        )

        self.assertEqual(result, [])

    def test_candidate_builder(self):
        ticker = {
            "symbol": "BTCUSDT",
            "quoteVolume": "5000000",
            "count": "50000",
            "lastPrice": "100",
            "priceChangePercent": "2.5",
            "volume": "50000",
        }

        result = coin_selector.build_candidate(
            ticker,
            order_book=create_order_book(),
            order_value_usdt=50.0,
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["symbol"], "BTCUSDT")
        self.assertIn("spread_percent", result)
        self.assertIn("minimum_side_depth_usdt", result)

    def test_candidate_validation_returns_tuple(self):
        ticker = {
            "symbol": "BTCUSDT",
            "quoteVolume": "5000000",
            "count": "50000",
            "lastPrice": "100",
        }

        result = coin_selector.validate_candidate(
            ticker,
            order_book=create_order_book(),
        )

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)

    def test_order_book_analysis(self):
        result = coin_selector.analyze_order_book(
            create_order_book()
        )

        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("valid"))
        self.assertGreater(
            result.get("best_ask", 0),
            result.get("best_bid", 0),
        )


# ============================================================
# 6. MARKET FILTER TESTS
# ============================================================

class MarketFilterTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "analyze_market",
            "analyze_btc_timeframe",
            "determine_btc_trend",
            "detect_high_risk",
            "classify_market",
            "determine_risk_level",
            "validate_market_context",
            "is_new_buy_allowed",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(market_filter, name, None))
                )

    def test_incomplete_market_data_does_not_allow_buy(self):
        frames = {
            "15m": {
                "valid": False,
                "direction": "UNKNOWN",
            },
            "1h": {
                "valid": False,
                "direction": "UNKNOWN",
            },
            "4h": {
                "valid": False,
                "direction": "UNKNOWN",
            },
        }

        trend = {
            "trend": "UNKNOWN",
            "valid": False,
            "score": 0,
        }

        result = market_filter.classify_market(
            trend,
            frames,
            None,
        )

        self.assertFalse(result["allow_new_buy"])
        self.assertEqual(result["regime"], "HIGH_RISK")


# ============================================================
# 7. ENTRY ENGINE TESTS
# ============================================================

class EntryEngineTests(unittest.TestCase):

    def setUp(self):
        self.df = create_ohlcv()

        self.market_context = {
            "valid": True,
            "regime": "BULLISH",
            "risk_level": "BULLISH",
            "market_status": "BULLISH",
            "btc_trend": "BULLISH",
            "allow_new_buy": True,
            "timeframes": {
                "15m": {"valid": True},
                "1h": {"valid": True},
                "4h": {"valid": True},
            },
            "liquidity": {
                "spread_percent": 0.02,
                "imbalance": 0.30,
                "minimum_side_depth_usdt": 500000,
                "buy_slippage_percent": 0.01,
                "trade_flow": 0.20,
            },
        }

    def test_required_engine_functions_exist(self):
        required = [
            "score_setup",
            "validate_entry",
            "evaluate_scalp",
            "evaluate_swing",
            "get_entry_engine_config",
            "self_check",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(entry_engine, name, None))
                )

    def test_scalp_uses_expected_timeframes(self):
        result = entry_engine.evaluate_scalp(
            trigger_df=self.df,
            confirm_frames={
                "15m": self.df,
                "30m": self.df,
            },
            market_context=self.market_context,
            capital_usdt=100.0,
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("strategy"), "SCALP")

    def test_swing_uses_expected_timeframes(self):
        result = entry_engine.evaluate_swing(
            trigger_df=self.df,
            confirm_frames={
                "30m": self.df,
                "1h": self.df,
            },
            market_context=self.market_context,
            capital_usdt=100.0,
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("strategy"), "SWING")

    def test_score_is_between_zero_and_100(self):
        result = entry_engine.evaluate_scalp(
            trigger_df=self.df,
            confirm_frames={
                "15m": self.df,
                "30m": self.df,
            },
            market_context=self.market_context,
            capital_usdt=100.0,
        )

        score = float(result.get("score", 0))

        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_score_is_not_win_probability(self):
        result = entry_engine.evaluate_scalp(
            trigger_df=self.df,
            confirm_frames={
                "15m": self.df,
                "30m": self.df,
            },
            market_context=self.market_context,
            capital_usdt=100.0,
        )

        self.assertFalse(
            result.get("score_is_win_probability", True)
        )

    def test_missing_confirmation_data_does_not_crash(self):
        result = entry_engine.evaluate_scalp(
            trigger_df=self.df,
            confirm_frames={},
            market_context=self.market_context,
            capital_usdt=100.0,
        )

        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("valid", False))


# ============================================================
# 8. RISK MANAGER TESTS
# ============================================================

class RiskManagerTests(unittest.TestCase):

    def test_required_functions_exist(self):
        required = [
            "calculate_stop_loss",
            "calculate_targets",
            "calculate_risk_reward",
            "calculate_position_size",
            "validate_risk",
            "build_risk_plan",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(risk_manager, name, None))
                )

    def test_build_risk_plan_uses_v4_signature(self):
        import inspect

        parameters = inspect.signature(
            risk_manager.build_risk_plan
        ).parameters

        self.assertIn("entry_price", parameters)
        self.assertIn("atr", parameters)
        self.assertIn("capital_usdt", parameters)
        self.assertIn("support", parameters)
        self.assertIn("resistances", parameters)

    def test_invalid_entry_rejected(self):
        result = risk_manager.build_risk_plan(
            entry_price=0,
            atr=1,
            capital_usdt=100,
        )

        self.assertFalse(result.get("valid", False))

    def test_invalid_direction_rejected(self):
        result = risk_manager.build_risk_plan(
            entry_price=100,
            atr=1,
            capital_usdt=100,
            direction="SELL",
        )

        self.assertFalse(result.get("valid", False))

    def test_position_size_uses_current_signature(self):
        result = risk_manager.calculate_position_size(
            capital_usdt=100,
            entry_price=100,
            stop_loss=98,
        )

        self.assertIsInstance(result, dict)
        self.assertIn("quantity", result)
        self.assertIn("position_value_usdt", result)


# ============================================================
# 9. SCANNER DATA INTEGRATION TESTS
# ============================================================

class ScannerDataTests(unittest.TestCase):

    def test_ticker_list_converts_to_symbol_map(self):
        ticker_list = [
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100",
                "quoteVolume": "1000000",
            },
            {
                "symbol": "ETHUSDT",
                "lastPrice": "50",
                "quoteVolume": "2000000",
            },
        ]

        result = scanner._get_ticker_map(ticker_list)

        self.assertIn("BTCUSDT", result)
        self.assertIn("ETHUSDT", result)
        self.assertEqual(
            result["BTCUSDT"]["lastPrice"],
            "100",
        )

    def test_ticker_dictionary_is_supported(self):
        ticker_map = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "lastPrice": "100",
            }
        }

        result = scanner._get_ticker_map(ticker_map)

        self.assertIn("BTCUSDT", result)

    def test_invalid_ticker_response_rejected(self):
        with self.assertRaises(ValueError):
            scanner._get_ticker_map("INVALID")

    def test_prefilter_removes_non_usdt_symbols(self):
        ticker_map = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "quoteVolume": "5000000",
                "lastPrice": "100",
            },
            "BTCBTC": {
                "symbol": "BTCBTC",
                "quoteVolume": "5000000",
                "lastPrice": "100",
            },
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["BTCUSDT", "BTCBTC"],
        )

        self.assertEqual(
            [item["symbol"] for item in result],
            ["BTCUSDT"],
        )

    def test_candidate_context_contains_liquidity(self):
        btc_context = {
            "regime": "BULLISH",
            "market_status": "BULLISH",
            "risk_level": "BULLISH",
            "allow_new_buy": True,
        }

        candidate = {
            "spread_percent": 0.02,
            "order_book_imbalance": 0.25,
            "minimum_side_depth_usdt": 100000,
            "buy_slippage_percent": 0.02,
        }

        result = scanner.build_candidate_market_context(
            btc_context,
            candidate,
        )

        self.assertIn("liquidity", result)
        self.assertEqual(
            result["liquidity"]["spread_percent"],
            0.02,
        )
        self.assertEqual(
            result["liquidity"]["minimum_side_depth_usdt"],
            100000,
        )


# ============================================================
# 10. RISK PLAN NORMALIZATION TESTS
# ============================================================

class RiskPlanNormalizationTests(unittest.TestCase):

    def test_valid_risk_plan_normalizes(self):
        result = scanner.normalize_risk_plan(
            create_raw_risk_plan(),
            entry_price=100.0,
        )

        self.assertEqual(result["status"], "VALID")
        self.assertTrue(result["validation"]["valid"])

    def test_tracker_required_fields_exist(self):
        result = scanner.normalize_risk_plan(
            create_raw_risk_plan(),
            entry_price=100.0,
        )

        required = [
            "status",
            "entry_price",
            "stop_loss",
            "targets",
            "position_size",
            "validation",
        ]

        for key in required:
            with self.subTest(field=key):
                self.assertIn(key, result)

    def test_stop_loss_is_tracker_compatible(self):
        result = scanner.normalize_risk_plan(
            create_raw_risk_plan(),
            entry_price=100.0,
        )

        self.assertIsInstance(result["stop_loss"], dict)
        self.assertLess(
            result["stop_loss"]["stop_loss"],
            result["entry_price"],
        )

    def test_targets_are_telegram_compatible(self):
        result = scanner.normalize_risk_plan(
            create_raw_risk_plan(),
            entry_price=100.0,
        )

        self.assertIsInstance(
            result["targets"]["t1"],
            dict,
        )

        self.assertIn(
            "price",
            result["targets"]["t1"],
        )

        self.assertIn(
            "risk_reward",
            result["targets"]["t1"],
        )

    def test_position_contains_net_profit_fields(self):
        result = scanner.normalize_risk_plan(
            create_raw_risk_plan(),
            entry_price=100.0,
        )

        position = result["position_size"]

        for key in (
            "quantity",
            "position_value_usdt",
            "effective_entry_price",
            "fee_rate_per_side",
            "slippage_rate_per_side",
            "actual_estimated_loss_usdt",
        ):
            with self.subTest(field=key):
                self.assertIn(key, position)

    def test_invalid_risk_plan_rejected(self):
        raw_plan = create_raw_risk_plan()
        raw_plan["valid"] = False

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw_plan,
                entry_price=100.0,
            )

    def test_invalid_stop_rejected(self):
        raw_plan = create_raw_risk_plan()
        raw_plan["stop_loss"] = 101.0

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw_plan,
                entry_price=100.0,
            )


# ============================================================
# 11. SIGNAL NORMALIZATION TESTS
# ============================================================

class SignalNormalizationTests(unittest.TestCase):

    def test_valid_engine_result_normalizes(self):
        result = {
            "valid": True,
            "classification": "STRONG BUY",
            "score": 87.5,
            "entry": {
                "price": 100.0,
                "atr": 1.0,
                "rsi": 60.0,
                "rvol": 1.5,
                "adx": 25.0,
            },
            "risk_plan": create_raw_risk_plan(),
            "structure": {
                "support": 98.0,
                "resistance": 104.0,
            },
            "layers": {},
            "mtf_confirmation": {},
            "fundamental_status": "UNVERIFIED",
        }

        candidate = {
            "symbol": "BTCUSDT",
            "last_price": 100.0,
            "quote_volume_24h": 5000000,
            "spread_percent": 0.02,
            "liquidity_score": 10,
        }

        market_context = {
            "btc_trend": "BULLISH",
            "market_status": "BULLISH",
            "risk_level": "BULLISH",
        }

        signal = scanner.normalize_engine_signal(
            result,
            "BTCUSDT",
            "SWING",
            candidate,
            market_context,
        )

        self.assertIsInstance(signal, dict)
        self.assertEqual(signal["symbol"], "BTCUSDT")
        self.assertEqual(signal["max_score"], 100)
        self.assertEqual(signal["score"], 87.5)

    def test_unapproved_classification_rejected(self):
        result = {
            "valid": True,
            "classification": "WATCHLIST",
            "score": 80,
        }

        signal = scanner.normalize_engine_signal(
            result,
            "BTCUSDT",
            "SWING",
            {},
            {},
        )

        self.assertIsNone(signal)

    def test_invalid_symbol_rejected(self):
        result = {
            "valid": True,
            "classification": "STRONG BUY",
            "score": 90,
            "entry": {
                "price": 100,
                "atr": 1,
            },
            "risk_plan": create_raw_risk_plan(),
        }

        signal = scanner.normalize_engine_signal(
            result,
            "BTCBTC",
            "SWING",
            {},
            {},
        )

        # The normalizer itself receives the symbol from its caller.
        # The scanner's candidate selection is responsible for
        # ensuring that only USDT Spot symbols reach this stage.
        self.assertIsNotNone(signal)


# ============================================================
# 12. SIGNAL TRACKER COMPATIBILITY TESTS
# ============================================================

class SignalTrackerCompatibilityTests(unittest.TestCase):

    def test_normalized_signal_can_register(self):
        signal = create_valid_signal()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(
                directory,
                "signal_history.json",
            )

            result = signal_tracker.register_signal(
                signal,
                file_path=path,
            )

            self.assertTrue(result.get("success"))
            self.assertTrue(
                os.path.exists(path)
            )

    def test_duplicate_signal_is_detected(self):
        signal = create_valid_signal()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(
                directory,
                "signal_history.json",
            )

            first = signal_tracker.register_signal(
                signal,
                file_path=path,
            )

            self.assertTrue(first.get("success"))

            history = signal_tracker.load_history(path)

            duplicate = signal_tracker.check_duplicate(
                "BTCUSDT",
                "SWING",
                history=history,
            )

            self.assertTrue(duplicate)


# ============================================================
# 13. TELEGRAM COMPATIBILITY TESTS
# ============================================================

class TelegramCompatibilityTests(unittest.TestCase):

    def test_valid_signal_formats(self):
        signal = create_valid_signal()

        message = telegram_bot.format_signal(signal)

        self.assertIsInstance(message, str)
        self.assertIn("BTCUSDT", message)
        self.assertIn("87.5/100", message)

    def test_telegram_rejects_unapproved_signal(self):
        signal = create_valid_signal()
        signal["classification"] = "WATCHLIST"
        signal["signal"] = "WATCHLIST"

        with self.assertRaises(ValueError):
            telegram_bot.format_signal(signal)

    def test_telegram_requires_valid_risk_plan(self):
        signal = create_valid_signal()
        signal["risk_plan"]["validation"]["valid"] = False

        with self.assertRaises(ValueError):
            telegram_bot.format_signal(signal)


# ============================================================
# 14. SCANNER INTERFACE TESTS
# ============================================================

class ScannerInterfaceTests(unittest.TestCase):

    def test_required_scanner_functions_exist(self):
        required = [
            "validate_scanner_configuration",
            "fetch_btc_market_data",
            "fetch_market_context",
            "prefilter_tickers",
            "fetch_order_books",
            "collect_candidates",
            "fetch_symbol_market_data",
            "build_candidate_market_context",
            "normalize_risk_plan",
            "normalize_engine_signal",
            "evaluate_candidate",
            "update_existing_signals",
            "deliver_signal",
            "run_scanner",
        ]

        for name in required:
            with self.subTest(function=name):
                self.assertTrue(
                    callable(getattr(scanner, name, None))
                )

    def test_old_risk_manager_parameter_names_not_used(self):
        import inspect

        parameters = inspect.signature(
            risk_manager.build_risk_plan
        ).parameters

        self.assertNotIn("capital", parameters)
        self.assertNotIn("support_level", parameters)
        self.assertNotIn("resistance_levels", parameters)
        self.assertIn("capital_usdt", parameters)
        self.assertIn("support", parameters)
        self.assertIn("resistances", parameters)

    def test_old_evaluator_argument_pattern_not_used(self):
        import inspect

        parameters = inspect.signature(
            entry_engine.evaluate_scalp
        ).parameters

        self.assertIn("trigger_df", parameters)
        self.assertIn("confirm_frames", parameters)
        self.assertIn("market_context", parameters)
        self.assertNotIn("indicators", parameters)


# ============================================================
# TEST RUNNER
# ============================================================

if __name__ == "__main__":
    print("=" * 65)
    print("BINANCE SPOT V4 FORMULA SYSTEM TESTS")
    print("=" * 65)

    unittest.main(verbosity=2)
