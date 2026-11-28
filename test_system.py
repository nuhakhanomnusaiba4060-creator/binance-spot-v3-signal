
"""Binance Spot V4 - Integrated System Tests.

Run:
    python -m unittest test_system -v

Tests:
    - Configuration validation
    - Seven-layer formula weights
    - Risk manager calculations
    - T1 net risk/reward validation
    - Position sizing and minimum notional
    - Spot-only restrictions
    - Entry engine and scanner integration contracts
"""

import importlib
import inspect
import math
import unittest


# ---------------------------------------------------------
# Safe module imports
# ---------------------------------------------------------

try:
    import config
except Exception as exc:
    config = None
    CONFIG_IMPORT_ERROR = exc
else:
    CONFIG_IMPORT_ERROR = None

try:
    import risk_manager
except Exception as exc:
    risk_manager = None
    RISK_IMPORT_ERROR = exc
else:
    RISK_IMPORT_ERROR = None

try:
    import entry_engine
except Exception as exc:
    entry_engine = None
    ENTRY_IMPORT_ERROR = exc
else:
    ENTRY_IMPORT_ERROR = None

try:
    import scanner
except Exception as exc:
    scanner = None
    SCANNER_IMPORT_ERROR = exc
else:
    SCANNER_IMPORT_ERROR = None


# ---------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------

def require_module(test_case, module, error, name):
    test_case.assertIsNotNone(
        module,
        msg=f"{name} import failed: {error}",
    )


def finite_positive(value):
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------

class ConfigurationTests(unittest.TestCase):

    def test_config_import(self):
        require_module(
            self,
            config,
            CONFIG_IMPORT_ERROR,
            "config",
        )

    def test_config_validation(self):
        require_module(
            self,
            config,
            CONFIG_IMPORT_ERROR,
            "config",
        )

        validator = getattr(config, "validate_config", None)

        self.assertTrue(
            callable(validator),
            "config.validate_config() is missing",
        )

        errors = validator()

        self.assertIsInstance(
            errors,
            (list, tuple),
            "validate_config() must return a list or tuple",
        )

        self.assertEqual(
            len(errors),
            0,
            msg=f"Configuration errors: {errors}",
        )

    def test_seven_layer_weights_total_100(self):
        require_module(
            self,
            config,
            CONFIG_IMPORT_ERROR,
            "config",
        )

        weights = getattr(config, "LAYER_WEIGHTS", None)

        self.assertIsInstance(weights, dict)

        self.assertEqual(
            len(weights),
            7,
            "V4 must contain exactly seven scoring layers",
        )

        total = 0.0

        for layer_name, layer in weights.items():

            self.assertIsInstance(
                layer,
                dict,
                f"{layer_name} must be a dictionary",
            )

            self.assertIn(
                "total",
                layer,
                f"{layer_name} has no total weight",
            )

            weight = float(layer["total"])

            self.assertGreaterEqual(weight, 0.0)

            total += weight

        self.assertAlmostEqual(
            total,
            100.0,
            places=4,
            msg="Seven-layer weights must total 100",
        )

    def test_required_spot_configuration(self):
        require_module(
            self,
            config,
            CONFIG_IMPORT_ERROR,
            "config",
        )

        runtime = getattr(config, "RUNTIME_CONFIG", {})

        if isinstance(runtime, dict):

            mode = str(
                runtime.get("market_type", "spot")
            ).lower()

            self.assertNotIn(
                mode,
                ("futures", "future", "margin"),
            )

        self.assertTrue(
            hasattr(config, "BTC_REGIME_CONFIG"),
            "BTC_REGIME_CONFIG is missing",
        )


# ---------------------------------------------------------
# Risk manager tests
# ---------------------------------------------------------

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
            msg=f"Risk manager self-check failed: {result}",
        )

        self.assertGreaterEqual(
            float(result["t1_net_rr"]),
            float(result["minimum_t1_net_rr"]),
        )

    def test_execution_cost_is_positive(self):

        costs = risk_manager.calculate_execution_cost_pct()

        self.assertTrue(finite_positive(costs))

    def test_execution_cost_custom_values(self):

        costs = risk_manager.calculate_execution_cost_pct(
            entry_fee_percent=0.10,
            exit_fee_percent=0.10,
            slippage_percent=0.05,
        )

        self.assertAlmostEqual(
            costs,
            0.25,
            places=6,
        )

    def test_stop_loss_below_entry(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100.0,
            atr=1.0,
        )

        self.assertGreater(stop, 0.0)
        self.assertLess(stop, 100.0)

    def test_stop_loss_rejects_invalid_atr(self):

        with self.assertRaises(ValueError):
            risk_manager.calculate_stop_loss(
                entry_price=100.0,
                atr=0.0,
            )

    def test_stop_loss_rejects_non_spot_direction(self):

        with self.assertRaises(ValueError):
            risk_manager.calculate_stop_loss(
                entry_price=100.0,
                atr=1.0,
                direction="SELL",
            )

    def test_targets_are_ascending(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100.0,
            atr=1.0,
        )

        targets = risk_manager.calculate_targets(
            entry_price=100.0,
            atr=1.0,
            stop_loss=stop,
        )

        self.assertEqual(len(targets), 3)

        self.assertTrue(
            targets[0] > 100.0
        )

        self.assertTrue(
            targets[0] < targets[1] < targets[2]
        )

    def test_target_prices_are_finite(self):

        targets = risk_manager.calculate_targets(
            entry_price=100.0,
            atr=1.0,
        )

        for target in targets:
            self.assertTrue(finite_positive(target))

    def test_net_risk_reward_accounts_for_costs(self):

        result = risk_manager.calculate_risk_reward(
            entry=100.0,
            stop_loss=98.0,
            target=104.0,
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
            0.0,
        )

    def test_t1_dynamic_target_meets_minimum_net_rr(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100.0,
            atr=1.0,
            capital_usdt=100.0,
            resistances=None,
        )

        self.assertTrue(
            plan["valid"],
            msg=f"Risk plan invalid: {plan['reason']}",
        )

        t1 = plan["target_checks"]["t1"]

        self.assertTrue(
            t1["valid"],
            msg=f"T1 validation failed: {t1}",
        )

        self.assertGreaterEqual(
            t1["net_rr"],
            t1["minimum_net_rr"],
        )

    def test_near_resistance_does_not_fake_valid_t1(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100.0,
            atr=1.0,
            capital_usdt=100.0,
            resistances=[100.5, 101.0],
        )

        self.assertFalse(
            plan["valid"],
            "An insufficient nearby resistance must not be treated as a valid T1",
        )

        self.assertFalse(
            plan["target_checks"]["t1"]["valid"]
        )

    def test_position_size_respects_capital_limit(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100.0,
            atr=1.0,
        )

        position = risk_manager.calculate_position_size(
            capital_usdt=100.0,
            entry_price=100.0,
            stop_loss=stop,
        )

        self.assertTrue(
            position["valid"],
            msg=f"Position sizing failed: {position}",
        )

        self.assertLessEqual(
            position["position_size_usdt"],
            100.0,
        )

        self.assertLessEqual(
            position["estimated_loss_usdt"],
            position["risk_budget_usdt"] + 1e-8,
        )

    def test_small_capital_below_minimum_notional_rejected(self):

        stop = risk_manager.calculate_stop_loss(
            entry_price=100.0,
            atr=1.0,
        )

        position = risk_manager.calculate_position_size(
            capital_usdt=1.0,
            entry_price=100.0,
            stop_loss=stop,
        )

        self.assertFalse(
            position["valid"],
        )

    def test_risk_plan_contains_scanner_required_fields(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100.0,
            atr=1.0,
            capital_usdt=100.0,
        )

        required_fields = (
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

        for field in required_fields:
            self.assertIn(
                field,
                plan,
                f"Risk plan missing field: {field}",
            )

    def test_risk_plan_is_spot_only(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100.0,
            atr=1.0,
            capital_usdt=100.0,
        )

        self.assertEqual(
            plan["direction"],
            "BUY",
        )

        self.assertTrue(plan["spot_only"])

    def test_sell_execution_is_rejected(self):

        plan = risk_manager.build_risk_plan(
            entry_price=100.0,
            atr=1.0,
            capital_usdt=100.0,
            direction="SELL",
        )

        self.assertFalse(plan["valid"])


# ---------------------------------------------------------
# Entry engine tests
# ---------------------------------------------------------

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
            ),
            "evaluate_scalp() is missing",
        )

    def test_entry_engine_has_swing_evaluator(self):

        self.assertTrue(
            callable(
                getattr(entry_engine, "evaluate_swing", None)
            ),
            "evaluate_swing() is missing",
        )

    def test_entry_engine_has_self_check(self):

        self.assertTrue(
            callable(
                getattr(entry_engine, "self_check", None)
            ),
            "entry_engine.self_check() is missing",
        )

    def test_entry_engine_has_seven_layer_weights(self):

        weights = getattr(
            entry_engine,
            "LAYER_WEIGHTS",
            None,
        )

        self.assertIsInstance(weights, dict)

        self.assertEqual(
            len(weights),
            7,
        )

        self.assertAlmostEqual(
            sum(float(value) for value in weights.values()),
            100.0,
            places=4,
        )

    def test_entry_engine_classification_thresholds(self):

        thresholds = getattr(
            entry_engine,
            "CLASSIFICATION_THRESHOLDS",
            None,
        )

        if thresholds is None:
            thresholds = getattr(
                entry_engine,
                "CLASSIFICATION_CONFIG",
                None,
            )

        # The exact internal representation may differ.
        # The classification function must remain available.
        classifier = getattr(
            entry_engine,
            "classify_score",
            None,
        )

        self.assertTrue(
            thresholds is not None or callable(classifier),
            "Classification thresholds/function are missing",
        )

    def test_evaluator_accepts_scanner_keyword_contract(self):

        for function_name in (
            "evaluate_scalp",
            "evaluate_swing",
        ):

            function = getattr(
                entry_engine,
                function_name,
            )

            parameters = inspect.signature(
                function
            ).parameters

            expected = (
                "trigger_df",
                "confirm_frames",
                "market_context",
                "breakout_data",
                "fundamental_data",
                "capital_usdt",
            )

            for name in expected:
                self.assertIn(
                    name,
                    parameters,
                    f"{function_name} missing parameter {name}",
                )


# ---------------------------------------------------------
# Scanner integration tests
# ---------------------------------------------------------

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

    def test_scanner_normalizer_signature(self):

        function = getattr(
            scanner,
            "normalize_engine_signal",
            None,
        )

        self.assertTrue(
            callable(function),
            "scanner.normalize_engine_signal() is missing",
        )

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

    def test_scanner_has_required_run_function(self):

        self.assertTrue(
            callable(
                getattr(scanner, "run_scanner", None)
            ),
            "scanner.run_scanner() is missing",
        )

    def test_scanner_spot_only_symbol_filter_exists(self):

        function = getattr(
            scanner,
            "_is_usdt_symbol",
            None,
        )

        self.assertTrue(
            callable(function),
            "_is_usdt_symbol() is missing",
        )

        self.assertTrue(
            function("BTCUSDT")
        )

        self.assertFalse(
            function("BTCBUSD")
        )

    def test_scanner_does_not_enable_futures_execution(self):

        source = inspect.getsource(scanner).lower()

        self.assertNotIn(
            "futures_create_order",
            source,
        )

        self.assertNotIn(
            "futures_account",
            source,
        )


# ---------------------------------------------------------
# Complete suite
# ---------------------------------------------------------

class SystemSmokeTests(unittest.TestCase):

    def test_all_core_modules_available(self):

        modules = {
            "config": config,
            "risk_manager": risk_manager,
            "entry_engine": entry_engine,
            "scanner": scanner,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
