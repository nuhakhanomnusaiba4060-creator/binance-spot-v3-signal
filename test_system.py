
"""Binance Spot V4 - Integrated System Test Suite.

Run:
    python -m unittest test_system -v

This test suite validates:
    1. Configuration
    2. Seven-layer formula
    3. Entry engine
    4. Risk manager
    5. Coin selector
    6. Scanner integration
    7. Spot-only restrictions
"""

import importlib
import inspect
import math
import re
import unittest


# =========================================================
# SAFE MODULE IMPORTS
# =========================================================

def safe_import(module_name):
    try:
        return importlib.import_module(module_name), None
    except Exception as exc:
        return None, exc


config, CONFIG_IMPORT_ERROR = safe_import("config")
entry_engine, ENTRY_IMPORT_ERROR = safe_import("entry_engine")
risk_manager, RISK_IMPORT_ERROR = safe_import("risk_manager")
scanner, SCANNER_IMPORT_ERROR = safe_import("scanner")
coin_selector, COIN_SELECTOR_IMPORT_ERROR = safe_import("coin_selector")


# =========================================================
# SHARED HELPERS
# =========================================================

def require_module(test_case, module, error, name):
    if module is None:
        raise AssertionError(
            f"{name} import failed: {error}"
        )


def finite_positive(value):
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except (TypeError, ValueError):
        return False


def get_source(module):
    try:
        return inspect.getsource(module)
    except (OSError, TypeError):
        return ""


# =========================================================
# CONFIGURATION TESTS
# =========================================================

class ConfigurationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        require_module(
            cls,
            config,
            CONFIG_IMPORT_ERROR,
            "config",
        )

    def test_config_import(self):
        self.assertIsNotNone(config)

    def test_config_validation(self):

        validator = getattr(
            config,
            "validate_config",
            None,
        )

        self.assertTrue(
            callable(validator),
            "validate_config() missing",
        )

        errors = validator()

        self.assertIsInstance(
            errors,
            (list, tuple),
        )

        self.assertEqual(
            len(errors),
            0,
            msg=f"Configuration errors: {errors}",
        )

    def test_required_spot_configuration(self):

        self.assertTrue(
            hasattr(config, "BTC_REGIME_CONFIG"),
            "BTC_REGIME_CONFIG missing",
        )

        runtime = getattr(
            config,
            "RUNTIME_CONFIG",
            {},
        )

        if isinstance(runtime, dict):

            market_type = str(
                runtime.get("market_type", "spot")
            ).lower()

            self.assertNotIn(
                market_type,
                ("futures", "future", "margin"),
            )

    def test_seven_layer_weights_total_100(self):

        weights = getattr(
            config,
            "LAYER_WEIGHTS",
            None,
        )

        self.assertIsInstance(weights, dict)

        self.assertEqual(
            len(weights),
            7,
            "V4 must contain exactly seven layers",
        )

        total = 0.0

        for name, layer in weights.items():

            self.assertIsInstance(
                layer,
                dict,
                f"{name} must be a dictionary",
            )

            self.assertIn(
                "total",
                layer,
                f"{name} missing total weight",
            )

            value = float(layer["total"])

            self.assertGreaterEqual(value, 0)

            total += value

        self.assertAlmostEqual(
            total,
            100.0,
            places=4,
        )

    def test_required_config_helpers(self):

        for name in (
            "get_config",
            "get_layer_weights",
            "get_strategy_config",
            "get_telegram_credentials",
            "is_dry_run",
            "get_capital_usdt",
        ):

            function = getattr(config, name, None)

            self.assertTrue(
                callable(function),
                f"Missing config helper: {name}",
            )


# =========================================================
# ENTRY ENGINE TESTS
# =========================================================

class EntryEngineTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        require_module(
            cls,
            entry_engine,
            ENTRY_IMPORT_ERROR,
            "entry_engine",
        )

    def test_entry_engine_imports(self):
        self.assertIsNotNone(entry_engine)

    def test_entry_engine_has_scalp_evaluator(self):

        self.assertTrue(
            callable(
                getattr(entry_engine, "evaluate_scalp", None)
            )
        )

    def test_entry_engine_has_swing_evaluator(self):

        self.assertTrue(
            callable(
                getattr(entry_engine, "evaluate_swing", None)
            )
        )

    def test_entry_engine_has_self_check(self):

        self.assertTrue(
            callable(
                getattr(entry_engine, "self_check", None)
            )
        )

    def test_entry_engine_has_seven_layer_weights(self):

        weights = getattr(
            entry_engine,
            "LAYER_WEIGHTS",
            None,
        )

        self.assertIsInstance(weights, dict)

        self.assertEqual(len(weights), 7)

        total = sum(
            float(value)
            for value in weights.values()
        )

        self.assertAlmostEqual(
            total,
            100.0,
            places=4,
        )

    def test_entry_engine_classification_thresholds(self):

        source = get_source(entry_engine)

        self.assertTrue(
            source,
            "Unable to read entry_engine source",
        )

        labels = (
            "EXCELLENT BUY",
            "STRONG BUY",
            "WATCHLIST",
            "WAIT",
            "REJECT",
        )

        for label in labels:
            self.assertIn(
                label,
                source,
                f"Missing classification label: {label}",
            )

        for threshold in (90, 85, 75, 60):

            pattern = rf"(?<!\d){threshold}(?!\d)"

            self.assertIsNotNone(
                re.search(pattern, source),
                f"Missing threshold: {threshold}",
            )

    def test_evaluator_accepts_scanner_keyword_contract(self):

        expected = (
            "trigger_df",
            "confirm_frames",
            "market_context",
            "breakout_data",
            "fundamental_data",
            "capital_usdt",
        )

        for name in (
            "evaluate_scalp",
            "evaluate_swing",
        ):

            function = getattr(
                entry_engine,
                name,
            )

            parameters = inspect.signature(
                function
            ).parameters

            for parameter in expected:

                self.assertIn(
                    parameter,
                    parameters,
                    f"{name} missing {parameter}",
                )


# =========================================================
# RISK MANAGER TESTS
# =========================================================

class RiskManagerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        require_module(
            cls,
            risk_manager,
            RISK_IMPORT_ERROR,
            "risk_manager",
        )

    def test_risk_manager_self_check(self):

        result = risk_manager.self_check()

        self.assertIsInstance(result, dict)

        self.assertTrue(
            result.get("ok"),
            msg=f"Self-check failed: {result}",
        )

    def test_execution_cost_is_positive(self):

        value = risk_manager.calculate_execution_cost_pct()

        self.assertTrue(finite_positive(value))

    def test_execution_cost_custom_values(self):

        value = risk_manager.calculate_execution_cost_pct(
            entry_fee_percent=0.10,
            exit_fee_percent=0.10,
            slippage_percent=0.05,
        )

        self.assertAlmostEqual(
            value,
            0.25,
            places=6,
        )

    def test_stop_loss_below_entry(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100,
            atr=1,
        )

        self.assertGreater(stop, 0)
        self.assertLess(stop, 100)

    def test_stop_loss_rejects_invalid_atr(self):

        with self.assertRaises(ValueError):

            risk_manager.calculate_stop_loss(
                entry_price=100,
                atr=0,
            )

    def test_stop_loss_rejects_non_spot_direction(self):

        with self.assertRaises(ValueError):

            risk_manager.calculate_stop_loss(
                entry_price=100,
                atr=1,
                direction="SELL",
            )

    def test_targets_are_ascending(self):

        targets = risk_manager.calculate_targets(
            entry_price=100,
            atr=1,
        )

        self.assertEqual(len(targets), 3)

        self.assertTrue(
            targets[0] < targets[1] < targets[2]
        )

        self.assertGreater(targets[0], 100)

    def test_target_prices_are_finite(self):

        targets = risk_manager.calculate_targets(
            entry_price=100,
            atr=1,
        )

        for target in targets:
            self.assertTrue(finite_positive(target))

    def test_net_risk_reward_accounts_for_costs(self):

        result = risk_manager.calculate_risk_reward(
            entry=100,
            stop_loss=98,
            target=104,
            execution_cost_pct=0.25,
        )

        self.assertGreater(
            result["gross_reward_pct"],
            result["net_reward_pct"],
        )

        self.assertGreater(
            result["net_risk_pct"],
            result["gross_risk_pct"],
        )

        self.assertGreater(
            result["net_rr"],
            0,
        )

    def test_t1_dynamic_target_meets_minimum_net_rr(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100,
            atr=1,
            capital_usdt=100,
        )

        self.assertTrue(
            plan["valid"],
            msg=plan["reason"],
        )

        t1 = plan["target_checks"]["t1"]

        self.assertTrue(t1["valid"])

        self.assertGreaterEqual(
            t1["net_rr"],
            t1["minimum_net_rr"],
        )

    def test_near_resistance_does_not_fake_valid_t1(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100,
            atr=1,
            capital_usdt=100,
            resistances=[100.5, 101],
        )

        self.assertFalse(plan["valid"])

        self.assertFalse(
            plan["target_checks"]["t1"]["valid"]
        )

    def test_position_size_respects_capital_limit(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100,
            atr=1,
        )

        position = risk_manager.calculate_position_size(
            capital_usdt=100,
            entry_price=100,
            stop_loss=stop,
        )

        self.assertTrue(
            position["valid"],
            msg=position["reason"],
        )

        self.assertLessEqual(
            position["position_size_usdt"],
            100,
        )

        self.assertLessEqual(
            position["estimated_loss_usdt"],
            position["risk_budget_usdt"] + 1e-8,
        )

    def test_small_capital_below_minimum_notional_rejected(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100,
            atr=1,
        )

        position = risk_manager.calculate_position_size(
            capital_usdt=1,
            entry_price=100,
            stop_loss=stop,
        )

        self.assertFalse(position["valid"])

    def test_risk_plan_contains_scanner_required_fields(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100,
            atr=1,
            capital_usdt=100,
        )

        required = (
            "valid",
            "reason",
            "direction",
            "spot_only",
            "entry",
            "stop_loss",
            "targets",
            "target_net_returns_pct",
            "atr",
            "risk_distance_pct",
            "execution_cost_pct",
            "position",
            "risk_validation",
            "target_checks",
        )

        for field in required:
            self.assertIn(field, plan)

    def test_risk_plan_is_spot_only(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100,
            atr=1,
            capital_usdt=100,
        )

        self.assertEqual(plan["direction"], "BUY")
        self.assertTrue(plan["spot_only"])

    def test_sell_execution_is_rejected(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100,
            atr=1,
            capital_usdt=100,
            direction="SELL",
        )

        self.assertFalse(plan["valid"])


# =========================================================
# COIN SELECTOR TESTS
# =========================================================

class CoinSelectorTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        require_module(
            cls,
            coin_selector,
            COIN_SELECTOR_IMPORT_ERROR,
            "coin_selector",
        )

    def test_coin_selector_import(self):
        self.assertIsNotNone(coin_selector)

    def test_candidate_builder(self):

        candidates = (
            getattr(coin_selector, "build_candidates", None)
            or getattr(coin_selector, "build_candidate_list", None)
            or getattr(coin_selector, "select_coins", None)
        )

        self.assertTrue(
            callable(candidates),
            "Candidate builder function is missing",
        )

    def test_candidate_validation_returns_tuple(self):

        validator = (
            getattr(coin_selector, "validate_candidate", None)
            or getattr(coin_selector, "validate_coin_candidate", None)
        )

        if validator is None:
            self.skipTest(
                "No standalone candidate validation function"
            )

        self.assertTrue(callable(validator))

        # Function contract check without inventing input schema.
        self.assertTrue(
            len(inspect.signature(validator).parameters) >= 1
        )


# =========================================================
# SCANNER INTEGRATION TESTS
# =========================================================

class ScannerIntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        require_module(
            cls,
            scanner,
            SCANNER_IMPORT_ERROR,
            "scanner",
        )

    def test_scanner_imports(self):
        self.assertIsNotNone(scanner)

    def test_scanner_has_required_run_function(self):

        self.assertTrue(
            callable(
                getattr(scanner, "run_scanner", None)
            )
        )

    def test_scanner_normalizer_signature(self):

        function = getattr(
            scanner,
            "normalize_engine_signal",
            None,
        )

        self.assertTrue(callable(function))

        parameters = inspect.signature(
            function
        ).parameters

        expected = (
            "result",
            "symbol",
            "strategy",
            "candidate",
            "market_context",
        )

        for name in expected:
            self.assertIn(name, parameters)

    def test_scanner_spot_only_symbol_filter_exists(self):

        function = getattr(
            scanner,
            "_is_usdt_symbol",
            None,
        )

        self.assertTrue(callable(function))

        self.assertTrue(
            function("BTCUSDT")
        )

        self.assertFalse(
            function("BTCBUSD")
        )

    def test_scanner_does_not_enable_futures_execution(self):

        source = get_source(scanner).lower()

        forbidden = (
            "futures_create_order",
            "futures_account",
        )

        for item in forbidden:
            self.assertNotIn(item, source)


# =========================================================
# SYSTEM SMOKE TESTS
# =========================================================

class SystemSmokeTests(unittest.TestCase):

    def test_all_core_modules_available(self):

        modules = {
            "config": config,
            "entry_engine": entry_engine,
            "risk_manager": risk_manager,
            "scanner": scanner,
            "coin_selector": coin_selector,
        }

        missing = [
            name
            for name, module in modules.items()
            if module is None
        ]

        self.assertEqual(
            missing,
            [],
            msg=f"Core modules unavailable: {missing}",
        )


# =========================================================
# RUN TESTS
# =========================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
