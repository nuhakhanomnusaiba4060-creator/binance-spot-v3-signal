
"""
File: test_system.py
System: Binance Spot V3 Smart Signal Scanner
Version: 4.0.0
Formula: V4 Seven-Layer Signal Architecture
Python: 3.11+

Tests are aligned with the supplied config.py and scanner.py.
No live Binance requests or Telegram messages are sent.
"""

from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

import config
import scanner


# ============================================================
# TEST DATA BUILDERS
# ============================================================

def make_valid_raw_risk_plan(
    entry_price: float = 100.0,
    stop_loss: float = 95.0,
) -> dict:
    return {
        "valid": True,
        "reason": "VALID",
        "stop_loss": stop_loss,
        "targets": {
            "t1": 110.0,
            "t2": 115.0,
            "t3": 120.0,
        },
        "position": {
            "quantity": 1.0,
            "position_value_usdt": entry_price,
            "estimated_loss_usdt": 5.0,
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
        "execution_cost_pct": 0.25,
    }


def make_valid_engine_result() -> dict:
    return {
        "valid": True,
        "classification": "STRONG BUY",
        "score": 87.5,
        "reason": "Test signal",
        "entry": {
            "price": 100.0,
            "atr": 2.0,
            "rsi": 58.0,
            "rvol": 1.8,
            "adx": 26.0,
        },
        "risk_plan": make_valid_raw_risk_plan(),
        "structure": {
            "support": 96.0,
            "resistance": 112.0,
        },
        "layers": {
            "btc_market_regime": 13,
            "technical_structure": 18,
            "volume_momentum": 13,
            "liquidity_order_flow": 14,
            "entry_quality": 13,
            "risk_reward": 9,
            "fundamental_onchain": 7.5,
        },
        "mtf_confirmation": {
            "entry": "5m",
            "confirmation": "15m",
            "structure": "30m",
            "confirmed": True,
        },
        "hard_gates": {
            "passed": True,
        },
        "fundamental_status": "UNVERIFIED",
    }


def make_valid_candidate() -> dict:
    return {
        "symbol": "BTCUSDT",
        "last_price": 100.0,
        "quote_volume_24h": 5_000_000.0,
        "spread_percent": 0.05,
        "liquidity_score": 90,
        "order_book_imbalance": 1.2,
        "minimum_side_depth_usdt": 10_000.0,
        "buy_slippage_percent": 0.03,
    }


# ============================================================
# CONFIGURATION TESTS
# ============================================================

class ConfigTests(unittest.TestCase):

    def test_config_validation_passes(self):
        errors = config.validate_config()
        self.assertEqual(errors, [])

    def test_config_validation_or_raise_passes(self):
        self.assertTrue(
            config.validate_config_or_raise()
        )

    def test_layer_weights_total_100(self):
        total = sum(
            float(layer["total"])
            for layer in config.LAYER_WEIGHTS.values()
        )

        self.assertEqual(total, 100)
        self.assertEqual(
            total,
            config.TOTAL_FORMULA_SCORE,
        )

    def test_each_layer_component_matches_declared_total(self):
        for layer_name, layer in config.LAYER_WEIGHTS.items():
            component_total = sum(
                value
                for key, value in layer.items()
                if key != "total"
            )

            with self.subTest(layer=layer_name):
                self.assertEqual(
                    component_total,
                    layer["total"],
                )

    def test_seven_signal_layers_exist(self):
        self.assertEqual(
            len(config.LAYER_WEIGHTS),
            7,
        )

    def test_classification_ranges(self):
        expected = {
            "EXCELLENT BUY": (90, 100),
            "STRONG BUY": (85, 89),
            "WATCHLIST": (75, 84),
            "WAIT": (60, 74),
            "REJECT": (0, 59),
        }

        for name, score_range in expected.items():
            with self.subTest(classification=name):
                item = config.CLASSIFICATION_CONFIG[name]

                self.assertEqual(
                    (
                        item["minimum_score"],
                        item["maximum_score"],
                    ),
                    score_range,
                )

    def test_spot_only_configuration(self):
        self.assertEqual(config.MARKET_TYPE, "SPOT")
        self.assertEqual(config.QUOTE_ASSET, "USDT")
        self.assertTrue(
            config.RUNTIME_CONFIG["spot_only"]
        )
        self.assertFalse(
            config.RUNTIME_CONFIG["allow_futures"]
        )
        self.assertFalse(
            config.RUNTIME_CONFIG["allow_margin"]
        )
        self.assertFalse(
            config.RUNTIME_CONFIG["allow_short_signals"]
        )

    def test_timeframe_configuration(self):
        self.assertEqual(
            config.TIMEFRAME_CONFIG["SCALP"]["required_timeframes"],
            ["5m", "15m", "30m"],
        )

        self.assertEqual(
            config.TIMEFRAME_CONFIG["SWING"]["required_timeframes"],
            ["15m", "30m", "1h"],
        )

        self.assertEqual(
            config.TIMEFRAME_CONFIG["BTC"]["required_timeframes"],
            ["15m", "1h", "4h"],
        )

    def test_btc_high_risk_blocks_new_buy(self):
        self.assertTrue(
            config.BTC_REGIME_CONFIG[
                "high_risk_blocks_new_buy"
            ]
        )

        self.assertTrue(
            config.HARD_GATE_CONFIG[
                "block_high_risk_btc_regime"
            ]
        )

    def test_closed_candle_policy_enabled(self):
        self.assertTrue(
            config.DATA_CONFIG["use_closed_candles_only"]
        )

        self.assertTrue(
            config.MARKET_STRUCTURE_CONFIG[
                "use_closed_candles"
            ]
        )

        self.assertTrue(
            config.HARD_GATE_CONFIG[
                "require_closed_candles"
            ]
        )

    def test_risk_limit_does_not_exceed_one_percent(self):
        self.assertLessEqual(
            config.RISK_CONFIG["risk_percent"],
            1.0,
        )

        self.assertLessEqual(
            config.RISK_CONFIG["maximum_risk_percent"],
            1.0,
        )

    def test_minimum_net_risk_reward(self):
        self.assertGreaterEqual(
            config.RISK_CONFIG["minimum_net_risk_reward"],
            1.0,
        )

    def test_telegram_only_approved_classifications(self):
        expected = {
            "STRONG BUY",
            "EXCELLENT BUY",
        }

        self.assertEqual(
            set(
                config.TELEGRAM_CONFIG[
                    "allowed_classifications"
                ]
            ),
            expected,
        )

    def test_fundamental_missing_data_does_not_block_all_signals(self):
        self.assertFalse(
            config.FUNDAMENTAL_CONFIG[
                "missing_data_blocks_buy"
            ]
        )

    def test_paper_entry_hit_is_not_guaranteed_fill(self):
        self.assertTrue(
            config.PAPER_TRADING_CONFIG[
                "entry_hit_is_not_guaranteed_fill"
            ]
        )

    def test_backtest_uses_conservative_same_candle_policy(self):
        self.assertEqual(
            config.BACKTEST_CONFIG[
                "same_candle_sl_tp_policy"
            ],
            "CONSERVATIVE_STOP_FIRST",
        )

    def test_daily_report_schedule(self):
        self.assertEqual(
            config.WORKFLOW_CONFIG[
                "daily_report_schedule"
            ],
            "5 18 * * *",
        )

    def test_get_config_returns_independent_copy(self):
        first = config.get_config()
        first["runtime"]["capital_usdt"] = 999999

        second = config.get_config()

        self.assertNotEqual(
            second["runtime"]["capital_usdt"],
            999999,
        )

    def test_get_layer_weights_returns_independent_copy(self):
        weights = config.get_layer_weights()
        weights["btc_market_regime"]["total"] = 999

        self.assertNotEqual(
            config.LAYER_WEIGHTS[
                "btc_market_regime"
            ]["total"],
            999,
        )

    def test_get_strategy_config_scalp(self):
        result = config.get_strategy_config("SCALP")

        self.assertEqual(result["entry"], "5m")
        self.assertEqual(result["confirmation"], "15m")
        self.assertEqual(result["structure"], "30m")

    def test_get_strategy_config_swing(self):
        result = config.get_strategy_config("SWING")

        self.assertEqual(result["entry"], "15m")
        self.assertEqual(result["confirmation"], "30m")
        self.assertEqual(result["structure"], "1h")

    def test_get_strategy_config_rejects_btc(self):
        with self.assertRaises(ValueError):
            config.get_strategy_config("BTC")

    def test_get_strategy_config_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            config.get_strategy_config("UNKNOWN")

    def test_invalid_custom_config_is_rejected(self):
        broken = config.get_config()
        broken["runtime"]["allow_futures"] = True

        errors = config.validate_config(broken)

        self.assertTrue(
            any("Futures" in error for error in errors)
        )


# ============================================================
# SCANNER BASIC HELPER TESTS
# ============================================================

class ScannerHelperTests(unittest.TestCase):

    def test_safe_float_valid_value(self):
        self.assertEqual(
            scanner._safe_float("12.5"),
            12.5,
        )

    def test_safe_float_invalid_value(self):
        self.assertIsNone(
            scanner._safe_float("invalid")
        )

    def test_safe_float_rejects_infinity(self):
        self.assertIsNone(
            scanner._safe_float(float("inf"))
        )

    def test_safe_float_rejects_nan(self):
        self.assertIsNone(
            scanner._safe_float(float("nan"))
        )

    def test_safe_int_valid_value(self):
        self.assertEqual(
            scanner._safe_int("12"),
            12,
        )

    def test_safe_int_invalid_value_uses_default(self):
        self.assertEqual(
            scanner._safe_int("invalid", 7),
            7,
        )

    def test_positive_accepts_positive_value(self):
        self.assertEqual(
            scanner._positive("10"),
            10.0,
        )

    def test_positive_rejects_zero(self):
        self.assertEqual(
            scanner._positive(0),
            0.0,
        )

    def test_positive_rejects_negative(self):
        self.assertEqual(
            scanner._positive(-5),
            0.0,
        )

    def test_env_bool_true_values(self):
        for value in ("1", "true", "yes", "on"):
            with patch.dict(os.environ, {"TEST_BOOL": value}):
                self.assertTrue(
                    scanner._env_bool("TEST_BOOL", False)
                )

    def test_env_bool_false_values(self):
        for value in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {"TEST_BOOL": value}):
                self.assertFalse(
                    scanner._env_bool("TEST_BOOL", True)
                )

    def test_env_bool_invalid_value_raises(self):
        with patch.dict(os.environ, {"TEST_BOOL": "maybe"}):
            with self.assertRaises(ValueError):
                scanner._env_bool("TEST_BOOL", False)

    def test_usdt_symbol_is_accepted(self):
        self.assertTrue(
            scanner._is_usdt_symbol("BTCUSDT")
        )

    def test_non_usdt_symbol_is_rejected(self):
        self.assertFalse(
            scanner._is_usdt_symbol("BTCBTC")
        )

    def test_empty_symbol_is_rejected(self):
        self.assertFalse(
            scanner._is_usdt_symbol("")
        )

    def test_symbol_check_is_case_insensitive(self):
        self.assertTrue(
            scanner._is_usdt_symbol("btcusdt")
        )

    def test_ticker_map_from_binance_list(self):
        result = scanner._get_ticker_map([
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100000",
            },
            {
                "symbol": "ETHUSDT",
                "lastPrice": "3000",
            },
        ])

        self.assertIn("BTCUSDT", result)
        self.assertIn("ETHUSDT", result)

    def test_ticker_map_from_symbol_dict(self):
        source = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "lastPrice": "100000",
            }
        }

        result = scanner._get_ticker_map(source)

        self.assertIn("BTCUSDT", result)

    def test_ticker_map_from_single_ticker_dict(self):
        source = {
            "symbol": "BTCUSDT",
            "lastPrice": "100000",
        }

        result = scanner._get_ticker_map(source)

        self.assertIn("BTCUSDT", result)

    def test_ticker_map_invalid_response_raises(self):
        with self.assertRaises(ValueError):
            scanner._get_ticker_map(None)

    def test_ticker_map_skips_invalid_items(self):
        result = scanner._get_ticker_map([
            None,
            "invalid",
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100000",
            },
        ])

        self.assertEqual(
            list(result.keys()),
            ["BTCUSDT"],
        )

    def test_ticker_price(self):
        self.assertEqual(
            scanner._ticker_price(
                {"lastPrice": "123.45"}
            ),
            123.45,
        )

    def test_ticker_quote_volume(self):
        self.assertEqual(
            scanner._ticker_quote_volume(
                {"quoteVolume": "5000000"}
            ),
            5_000_000.0,
        )


# ============================================================
# CANDIDATE PREFILTER TESTS
# ============================================================

class CandidatePrefilterTests(unittest.TestCase):

    def test_candidate_builder(self):
        ticker_map = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "lastPrice": "100000",
                "quoteVolume": "5000000",
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "lastPrice": "3000",
                "quoteVolume": "4000000",
            },
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["BTCUSDT", "ETHUSDT"],
        )

        self.assertEqual(len(result), 2)

    def test_candidate_prefilter_sorts_by_volume(self):
        ticker_map = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "lastPrice": "100000",
                "quoteVolume": "2000000",
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "lastPrice": "3000",
                "quoteVolume": "5000000",
            },
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["BTCUSDT", "ETHUSDT"],
        )

        self.assertEqual(
            result[0]["symbol"],
            "ETHUSDT",
        )

    def test_candidate_prefilter_rejects_low_volume(self):
        ticker_map = {
            "LOWUSDT": {
                "symbol": "LOWUSDT",
                "lastPrice": "1",
                "quoteVolume": "100",
            }
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["LOWUSDT"],
        )

        self.assertEqual(result, [])

    def test_candidate_prefilter_rejects_non_usdt(self):
        ticker_map = {
            "BTCBTC": {
                "symbol": "BTCBTC",
                "lastPrice": "100000",
                "quoteVolume": "5000000",
            }
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["BTCBTC"],
        )

        self.assertEqual(result, [])

    def test_candidate_prefilter_rejects_excluded_symbol(self):
        ticker_map = {
            "USDCUSDT": {
                "symbol": "USDCUSDT",
                "lastPrice": "1",
                "quoteVolume": "5000000",
            }
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["USDCUSDT"],
        )

        self.assertEqual(result, [])

    def test_candidate_prefilter_rejects_leveraged_token(self):
        ticker_map = {
            "BTCUPUSDT": {
                "symbol": "BTCUPUSDT",
                "lastPrice": "1",
                "quoteVolume": "5000000",
            }
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["BTCUPUSDT"],
        )

        self.assertEqual(result, [])

    def test_candidate_prefilter_rejects_zero_price(self):
        ticker_map = {
            "ZEROUSDT": {
                "symbol": "ZEROUSDT",
                "lastPrice": "0",
                "quoteVolume": "5000000",
            }
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["ZEROUSDT"],
        )

        self.assertEqual(result, [])

    def test_candidate_prefilter_respects_allowed_symbols(self):
        ticker_map = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "lastPrice": "100000",
                "quoteVolume": "5000000",
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "lastPrice": "3000",
                "quoteVolume": "5000000",
            },
        }

        result = scanner.prefilter_tickers(
            ticker_map,
            ["BTCUSDT"],
        )

        self.assertEqual(
            [item["symbol"] for item in result],
            ["BTCUSDT"],
        )


# ============================================================
# MARKET CONTEXT TESTS
# ============================================================

class MarketContextTests(unittest.TestCase):

    def test_candidate_market_context(self):
        btc_context = {
            "regime": "BULLISH",
            "risk_level": "BULLISH",
            "market_status": "BULLISH",
            "btc_trend": "UPTREND",
            "allow_new_buy": True,
        }

        candidate = make_valid_candidate()

        result = scanner.build_candidate_market_context(
            btc_context,
            candidate,
        )

        self.assertEqual(
            result["regime"],
            "BULLISH",
        )

        self.assertEqual(
            result["liquidity"]["spread_percent"],
            0.05,
        )

        self.assertEqual(
            result["liquidity"]["imbalance"],
            1.2,
        )

        self.assertEqual(
            result["formula_version"],
            "4.0",
        )

    def test_candidate_context_does_not_mutate_original(self):
        btc_context = {
            "regime": "NEUTRAL",
            "allow_new_buy": True,
        }

        original = deepcopy(btc_context)

        scanner.build_candidate_market_context(
            btc_context,
            make_valid_candidate(),
        )

        self.assertEqual(
            btc_context,
            original,
        )

    def test_fetch_market_context_blocks_high_risk(self):
        fake_frames = {
            "15m": object(),
            "1h": object(),
            "4h": object(),
        }

        with patch.object(
            scanner,
            "fetch_btc_market_data",
            return_value=fake_frames,
        ), patch.object(
            scanner,
            "analyze_market",
            return_value={
                "regime": "HIGH_RISK",
                "allow_new_buy": True,
            },
        ):
            result = scanner.fetch_market_context()

        self.assertEqual(
            result["regime"],
            "HIGH_RISK",
        )

        self.assertFalse(
            result["allow_new_buy"]
        )


# ============================================================
# RISK PLAN NORMALIZATION TESTS
# ============================================================

class RiskPlanNormalizationTests(unittest.TestCase):

    def test_valid_risk_plan_is_normalized(self):
        raw = make_valid_raw_risk_plan()

        result = scanner.normalize_risk_plan(
            raw,
            100.0,
        )

        self.assertEqual(
            result["status"],
            "VALID",
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["direction"], "BUY")
        self.assertTrue(result["spot_only"])

    def test_normalized_risk_plan_has_stop_loss(self):
        result = scanner.normalize_risk_plan(
            make_valid_raw_risk_plan(),
            100.0,
        )

        self.assertEqual(
            result["stop_loss"]["stop_loss"],
            95.0,
        )

    def test_normalized_risk_plan_has_t1(self):
        result = scanner.normalize_risk_plan(
            make_valid_raw_risk_plan(),
            100.0,
        )

        self.assertEqual(
            result["targets"]["t1"]["price"],
            110.0,
        )

    def test_normalized_risk_plan_has_position_size(self):
        result = scanner.normalize_risk_plan(
            make_valid_raw_risk_plan(),
            100.0,
        )

        self.assertEqual(
            result["position_size"]["quantity"],
            1.0,
        )

        self.assertEqual(
            result["position_size"]["position_value_usdt"],
            100.0,
        )

    def test_invalid_raw_plan_is_rejected(self):
        raw = make_valid_raw_risk_plan()
        raw["valid"] = False

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_invalid_stop_loss_is_rejected(self):
        raw = make_valid_raw_risk_plan(
            entry_price=100.0,
            stop_loss=100.0,
        )

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_stop_loss_above_entry_is_rejected(self):
        raw = make_valid_raw_risk_plan(
            entry_price=100.0,
            stop_loss=105.0,
        )

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_invalid_risk_validation_is_rejected(self):
        raw = make_valid_raw_risk_plan()
        raw["risk_validation"]["valid"] = False

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_missing_t1_is_rejected(self):
        raw = make_valid_raw_risk_plan()
        raw["targets"]["t1"] = None

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_invalid_position_quantity_is_rejected(self):
        raw = make_valid_raw_risk_plan()
        raw["position"]["quantity"] = 0

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_invalid_position_value_is_rejected(self):
        raw = make_valid_raw_risk_plan()
        raw["position"]["position_value_usdt"] = 0

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )

    def test_missing_estimated_loss_is_rejected(self):
        raw = make_valid_raw_risk_plan()
        raw["position"]["estimated_loss_usdt"] = 0

        with self.assertRaises(ValueError):
            scanner.normalize_risk_plan(
                raw,
                100.0,
            )


# ============================================================
# SIGNAL NORMALIZATION TESTS
# ============================================================

class SignalNormalizationTests(unittest.TestCase):

    def test_valid_engine_signal_is_normalized(self):
        result = scanner.normalize_engine_signal(
            result=make_valid_engine_result(),
            symbol="BTCUSDT",
            strategy="SCALP",
            candidate=make_valid_candidate(),
            market_context={
                "btc_trend": "UPTREND",
                "market_status": "BULLISH",
                "risk_level": "BULLISH",
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["symbol"], "BTCUSDT")
        self.assertEqual(result["strategy"], "SCALP")
        self.assertEqual(result["classification"], "STRONG BUY")
        self.assertEqual(result["decision"], "BUY")
        self.assertEqual(result["max_score"], 100)

    def test_signal_contains_formula_version(self):
        result = scanner.normalize_engine_signal(
            make_valid_engine_result(),
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {"market_status": "BULLISH"},
        )

        self.assertEqual(
            result["formula_version"],
            "4.0",
        )

    def test_signal_score_is_not_win_probability(self):
        result = scanner.normalize_engine_signal(
            make_valid_engine_result(),
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {"market_status": "BULLISH"},
        )

        self.assertFalse(
            result["score_is_win_probability"]
        )

    def test_unapproved_classification_is_rejected(self):
        engine_result = make_valid_engine_result()
        engine_result["classification"] = "WATCHLIST"

        result = scanner.normalize_engine_signal(
            engine_result,
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIsNone(result)

    def test_invalid_engine_result_is_rejected(self):
        engine_result = make_valid_engine_result()
        engine_result["valid"] = False

        result = scanner.normalize_engine_signal(
            engine_result,
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIsNone(result)

    def test_score_above_100_is_rejected(self):
        engine_result = make_valid_engine_result()
        engine_result["score"] = 101

        result = scanner.normalize_engine_signal(
            engine_result,
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIsNone(result)

    def test_negative_score_is_rejected(self):
        engine_result = make_valid_engine_result()
        engine_result["score"] = -1

        result = scanner.normalize_engine_signal(
            engine_result,
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIsNone(result)

    def test_missing_entry_price_is_rejected(self):
        engine_result = make_valid_engine_result()
        engine_result["entry"]["price"] = 0

        result = scanner.normalize_engine_signal(
            engine_result,
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIsNone(result)

    def test_missing_atr_is_rejected(self):
        engine_result = make_valid_engine_result()
        engine_result["entry"]["atr"] = 0

        result = scanner.normalize_engine_signal(
            engine_result,
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIsNone(result)

    def test_signal_contains_layer_scores(self):
        result = scanner.normalize_engine_signal(
            make_valid_engine_result(),
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertIn("btc_market_regime", result["layers"])
        self.assertIn("technical_structure", result["layers"])

    def test_unverified_fundamentals_add_warning(self):
        result = scanner.normalize_engine_signal(
            make_valid_engine_result(),
            "BTCUSDT",
            "SCALP",
            make_valid_candidate(),
            {},
        )

        self.assertTrue(result["warnings"])


# ============================================================
# SCANNER CONFIGURATION TESTS
# ============================================================

class ScannerConfigurationTests(unittest.TestCase):

    def test_scanner_configuration_with_dry_run(self):
        with patch.object(scanner, "DRY_RUN", True):
            with patch.object(
                scanner,
                "CAPITAL_USDT",
                100.0,
            ):
                scanner.validate_scanner_configuration()

    def test_scanner_rejects_zero_capital(self):
        with patch.object(scanner, "DRY_RUN", True):
            with patch.object(
                scanner,
                "CAPITAL_USDT",
                0,
            ):
                with self.assertRaises(ValueError):
                    scanner.validate_scanner_configuration()

    def test_scanner_rejects_missing_telegram_credentials_in_live_mode(self):
        with patch.object(scanner, "DRY_RUN", False):
            with patch.object(
                scanner,
                "credentials_available",
                return_value=False,
            ):
                with self.assertRaises(ValueError):
                    scanner.validate_scanner_configuration()

    def test_scanner_rejects_non_spot_configuration(self):
        with patch.object(scanner, "DRY_RUN", True):
            with patch.dict(
                scanner.RUNTIME_CONFIG,
                {"spot_only": False},
            ):
                with self.assertRaises(ValueError):
                    scanner.validate_scanner_configuration()


# ============================================================
# BTC MARKET DATA AND CANDLE VALIDATION TESTS
# ============================================================

class MarketDataValidationTests(unittest.TestCase):

    def test_valid_dataframe(self):
        import pandas as pd

        frame = pd.DataFrame({
            "close": [100.0] * 60,
        })

        self.assertTrue(
            scanner._valid_dataframe(frame)
        )

    def test_empty_dataframe_is_invalid(self):
        import pandas as pd

        frame = pd.DataFrame()

        self.assertFalse(
            scanner._valid_dataframe(frame)
        )

    def test_insufficient_dataframe_is_invalid(self):
        import pandas as pd

        frame = pd.DataFrame({
            "close": [100.0] * 10,
        })

        self.assertFalse(
            scanner._valid_dataframe(frame)
        )

    def test_none_dataframe_is_invalid(self):
        self.assertFalse(
            scanner._valid_dataframe(None)
        )

    def test_symbol_market_data_rejects_non_usdt(self):
        with self.assertRaises(ValueError):
            scanner.fetch_symbol_market_data("BTCBTC")

    def test_symbol_market_data_fetches_required_timeframes(self):
        import pandas as pd

        frame = pd.DataFrame({
            "close": [100.0] * 300,
        })

        with patch.object(
            scanner,
            "get_klines",
            return_value=frame,
        ) as mock_klines:
            result = scanner.fetch_symbol_market_data(
                "BTCUSDT"
            )

        self.assertEqual(
            set(result.keys()),
            {"5m", "15m", "30m", "1h"},
        )

        self.assertEqual(
            mock_klines.call_count,
            4,
        )

    def test_btc_market_data_fetches_three_timeframes(self):
        import pandas as pd

        frame = pd.DataFrame({
            "close": [100.0] * 300,
        })

        with patch.object(
            scanner,
            "get_klines",
            return_value=frame,
        ) as mock_klines:
            result = scanner.fetch_btc_market_data()

        self.assertEqual(
            set(result.keys()),
            {"15m", "1h", "4h"},
        )

        self.assertEqual(
            mock_klines.call_count,
            3,
        )


# ============================================================
# SIGNAL DELIVERY SAFETY TESTS
# ============================================================

class SignalDeliverySafetyTests(unittest.TestCase):

    def test_non_usdt_signal_is_not_delivered(self):
        signal = {
            "symbol": "BTCBTC",
            "strategy": "SCALP",
            "classification": "STRONG BUY",
            "risk_plan": {},
        }

        result = scanner.deliver_signal(
            signal,
            {"signals": []},
        )

        self.assertFalse(result)

    def test_unapproved_signal_is_not_delivered(self):
        signal = {
            "symbol": "BTCUSDT",
            "strategy": "SCALP",
            "classification": "WATCHLIST",
            "risk_plan": {},
        }

        result = scanner.deliver_signal(
            signal,
            {"signals": []},
        )

        self.assertFalse(result)

    def test_signal_without_risk_plan_is_not_delivered(self):
        signal = {
            "symbol": "BTCUSDT",
            "strategy": "SCALP",
            "classification": "STRONG BUY",
        }

        result = scanner.deliver_signal(
            signal,
            {"signals": []},
        )

        self.assertFalse(result)

    def test_dry_run_does_not_register_or_send(self):
        signal = {
            "symbol": "BTCUSDT",
            "strategy": "SCALP",
            "classification": "STRONG BUY",
            "score": 90,
            "risk_plan": {
                "status": "VALID",
            },
        }

        with patch.object(scanner, "DRY_RUN", True):
            with patch.object(
                scanner,
                "register_signal",
            ) as register_mock:
                with patch.object(
                    scanner,
                    "send_signal",
                ) as telegram_mock:
                    result = scanner.deliver_signal(
                        signal,
                        {"signals": []},
                    )

        self.assertFalse(result)
        register_mock.assert_not_called()
        telegram_mock.assert_not_called()

    def test_duplicate_signal_is_not_registered(self):
        signal = {
            "symbol": "BTCUSDT",
            "strategy": "SCALP",
            "classification": "STRONG BUY",
            "score": 90,
            "risk_plan": {
                "status": "VALID",
            },
        }

        with patch.object(scanner, "DRY_RUN", False):
            with patch.object(
                scanner,
                "is_duplicate_signal",
                return_value=True,
            ):
                with patch.object(
                    scanner,
                    "register_signal",
                ) as register_mock:
                    result = scanner.deliver_signal(
                        signal,
                        {"signals": []},
                    )

        self.assertFalse(result)
        register_mock.assert_not_called()


# ============================================================
# TEST RUNNER
# ============================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
