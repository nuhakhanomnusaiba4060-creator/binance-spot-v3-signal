
"""Binance Spot V4 Risk Management Engine.

All percentage values are percentage points:
0.25 means 0.25%.

Spot BUY execution only.
Config-driven risk, ATR stops, targets and position sizing.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    import config as app_config
except Exception:
    app_config = None


CODE_VERSION = "4.0.1"
FORMULA_VERSION = "4.0"


DEFAULTS = {
    "risk_percent": 1.0,
    "maximum_risk_percent": 1.0,
    "max_position_percent": 100.0,
    "max_portfolio_risk_percent": 3.0,
    "atr_stop_multiplier": 1.8,
    "scalp_atr_stop_multiplier": 1.5,
    "swing_atr_stop_multiplier": 2.0,
    "min_stop_percent": 0.5,
    "max_stop_percent": 5.0,
    "scalp_min_stop_percent": 0.30,
    "scalp_max_stop_percent": 3.0,
    "swing_min_stop_percent": 0.50,
    "swing_max_stop_percent": 5.0,
    "support_buffer_atr": 0.25,
    "target_atr_multipliers": (1.5, 2.5, 3.5),
    "min_net_rr_t1": 1.5,
    "min_net_rr_t2": 1.5,
    "min_net_rr_t3": 2.0,
    "entry_fee_percent": 0.10,
    "exit_fee_percent": 0.10,
    "slippage_percent": 0.05,
    "minimum_notional_usdt": 10.0,
}


# =========================================================
# SAFE VALUE AND CONFIG HELPERS
# =========================================================

def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _config_root(name: str) -> Dict[str, Any]:
    if app_config is None:
        return {}

    return _dict(getattr(app_config, name, {}))


def _first_value(
    roots: Sequence[Dict[str, Any]],
    names: Sequence[str],
    default: Any,
) -> Any:
    for root in roots:
        for name in names:
            if name in root and root[name] is not None:
                return root[name]

    return default


def _strategy_name(strategy: Optional[str]) -> str:
    value = str(strategy or "DEFAULT").upper()

    if value in ("SCALP", "SWING"):
        return value

    return "DEFAULT"


def _risk_settings(
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Read both flat and nested V4 configuration safely."""

    settings = dict(DEFAULTS)

    risk = _config_root("RISK_CONFIG")
    legacy_risk = _config_root("RISK_MANAGEMENT_CONFIG")
    costs = _config_root("EXECUTION_COST_CONFIG")

    roots = (risk, legacy_risk, costs)

    # -----------------------------------------------------
    # Flat risk settings
    # -----------------------------------------------------

    aliases = {
        "risk_percent": (
            "risk_percent",
            "risk_per_trade_percent",
            "max_risk_per_trade_pct",
        ),
        "maximum_risk_percent": (
            "maximum_risk_percent",
            "max_risk_percent",
            "maximum_risk_per_trade_pct",
        ),
        "max_position_percent": (
            "max_position_percent",
            "maximum_position_percent",
            "max_allocation_percent",
        ),
        "max_portfolio_risk_percent": (
            "max_portfolio_risk_percent",
            "portfolio_risk_limit_percent",
        ),
        "atr_stop_multiplier": (
            "atr_stop_multiplier",
            "stop_atr_multiplier",
        ),
        "min_stop_percent": (
            "min_stop_percent",
            "minimum_stop_percent",
        ),
        "max_stop_percent": (
            "max_stop_percent",
            "maximum_stop_percent",
        ),
        "support_buffer_atr": (
            "support_buffer_atr",
            "support_buffer_atr_multiplier",
        ),
        "min_net_rr_t1": (
            "min_net_rr_t1",
            "minimum_net_rr_t1",
            "min_risk_reward_t1",
        ),
        "min_net_rr_t2": (
            "min_net_rr_t2",
            "minimum_net_rr_t2",
            "min_risk_reward_t2",
        ),
        "min_net_rr_t3": (
            "min_net_rr_t3",
            "minimum_net_rr_t3",
            "min_risk_reward_t3",
        ),
        "entry_fee_percent": (
            "entry_fee_percent",
            "entry_fee_pct",
            "taker_fee_percent",
        ),
        "exit_fee_percent": (
            "exit_fee_percent",
            "exit_fee_pct",
        ),
        "slippage_percent": (
            "slippage_percent",
            "slippage_pct",
            "estimated_slippage_percent",
        ),
        "minimum_notional_usdt": (
            "minimum_notional_usdt",
            "min_notional_usdt",
        ),
    }

    for key, names in aliases.items():
        settings[key] = _first_value(
            roots,
            names,
            settings[key],
        )

    # -----------------------------------------------------
    # Nested ATR Stop Loss configuration
    # -----------------------------------------------------

    atr_config = _dict(risk.get("atr_stop_loss"))

    if atr_config:
        settings["atr_stop_multiplier"] = _number(
            atr_config.get("multiplier"),
            settings["atr_stop_multiplier"],
        )

        settings["min_stop_percent"] = _number(
            atr_config.get("minimum_distance_percent"),
            settings["min_stop_percent"],
        )

        settings["max_stop_percent"] = _number(
            atr_config.get("maximum_distance_percent"),
            settings["max_stop_percent"],
        )

        strategy_multipliers = _dict(
            atr_config.get("multiplier_by_strategy")
        )

        strategy_minimums = _dict(
            atr_config.get("minimum_distance_by_strategy")
        )

        strategy_maximums = _dict(
            atr_config.get("maximum_distance_by_strategy")
        )

        if "SCALP" in strategy_multipliers:
            settings["scalp_atr_stop_multiplier"] = _number(
                strategy_multipliers["SCALP"],
                settings["scalp_atr_stop_multiplier"],
            )

        if "SWING" in strategy_multipliers:
            settings["swing_atr_stop_multiplier"] = _number(
                strategy_multipliers["SWING"],
                settings["swing_atr_stop_multiplier"],
            )

        if "SCALP" in strategy_minimums:
            settings["scalp_min_stop_percent"] = _number(
                strategy_minimums["SCALP"],
                settings["scalp_min_stop_percent"],
            )

        if "SWING" in strategy_minimums:
            settings["swing_min_stop_percent"] = _number(
                strategy_minimums["SWING"],
                settings["swing_min_stop_percent"],
            )

        if "SCALP" in strategy_maximums:
            settings["scalp_max_stop_percent"] = _number(
                strategy_maximums["SCALP"],
                settings["scalp_max_stop_percent"],
            )

        if "SWING" in strategy_maximums:
            settings["swing_max_stop_percent"] = _number(
                strategy_maximums["SWING"],
                settings["swing_max_stop_percent"],
            )

    # Also support the documented V4 strategy values
    # when the nested dictionary uses direct keys.
    if "SCALP" in atr_config:
        scalp = _dict(atr_config["SCALP"])
        settings["scalp_atr_stop_multiplier"] = _number(
            scalp.get("multiplier"),
            settings["scalp_atr_stop_multiplier"],
        )
        settings["scalp_min_stop_percent"] = _number(
            scalp.get("minimum_distance_percent"),
            settings["scalp_min_stop_percent"],
        )
        settings["scalp_max_stop_percent"] = _number(
            scalp.get("maximum_distance_percent"),
            settings["scalp_max_stop_percent"],
        )

    if "SWING" in atr_config:
        swing = _dict(atr_config["SWING"])
        settings["swing_atr_stop_multiplier"] = _number(
            swing.get("multiplier"),
            settings["swing_atr_stop_multiplier"],
        )
        settings["swing_min_stop_percent"] = _number(
            swing.get("minimum_distance_percent"),
            settings["swing_min_stop_percent"],
        )
        settings["swing_max_stop_percent"] = _number(
            swing.get("maximum_distance_percent"),
            settings["swing_max_stop_percent"],
        )

    # -----------------------------------------------------
    # Nested position sizing
    # -----------------------------------------------------

    sizing = _dict(risk.get("position_sizing"))

    settings["minimum_notional_usdt"] = _number(
        sizing.get(
            "minimum_order_value_usdt",
            sizing.get(
                "minimum_notional_usdt",
                settings["minimum_notional_usdt"],
            ),
        ),
        settings["minimum_notional_usdt"],
    )

    settings["max_position_percent"] = _number(
        sizing.get(
            "maximum_position_percent",
            sizing.get(
                "max_position_percent",
                settings["max_position_percent"],
            ),
        ),
        settings["max_position_percent"],
    )

    # -----------------------------------------------------
    # Nested targets
    # -----------------------------------------------------

    target_config = _dict(risk.get("targets"))

    multipliers = target_config.get(
        "atr_multipliers",
        target_config.get("target_atr_multipliers"),
    )

    if isinstance(multipliers, (list, tuple)):
        parsed = tuple(
            _number(value, 0.0)
            for value in multipliers[:3]
        )

        if len(parsed) == 3 and all(value > 0 for value in parsed):
            settings["target_atr_multipliers"] = parsed

    # The V4 central setting is the minimum T1 Net RR.
    # It must override the old 1.2 fallback.
    configured_minimum_rr = risk.get(
        "minimum_net_risk_reward"
    )

    if configured_minimum_rr is not None:
        minimum_rr = _number(
            configured_minimum_rr,
            settings["min_net_rr_t1"],
        )

        settings["min_net_rr_t1"] = minimum_rr

        # T2/T3 must not be weaker than the configured
        # minimum T1 requirement.
        settings["min_net_rr_t2"] = max(
            settings["min_net_rr_t2"],
            minimum_rr,
        )

        settings["min_net_rr_t3"] = max(
            settings["min_net_rr_t3"],
            minimum_rr,
        )

    # -----------------------------------------------------
    # Strategy-specific effective stop settings
    # -----------------------------------------------------

    selected_strategy = _strategy_name(strategy)

    if selected_strategy == "SCALP":
        settings["effective_atr_stop_multiplier"] = (
            settings["scalp_atr_stop_multiplier"]
        )
        settings["effective_min_stop_percent"] = (
            settings["scalp_min_stop_percent"]
        )
        settings["effective_max_stop_percent"] = (
            settings["scalp_max_stop_percent"]
        )

    elif selected_strategy == "SWING":
        settings["effective_atr_stop_multiplier"] = (
            settings["swing_atr_stop_multiplier"]
        )
        settings["effective_min_stop_percent"] = (
            settings["swing_min_stop_percent"]
        )
        settings["effective_max_stop_percent"] = (
            settings["swing_max_stop_percent"]
        )

    else:
        settings["effective_atr_stop_multiplier"] = (
            settings["atr_stop_multiplier"]
        )
        settings["effective_min_stop_percent"] = (
            settings["min_stop_percent"]
        )
        settings["effective_max_stop_percent"] = (
            settings["max_stop_percent"]
        )

    # -----------------------------------------------------
    # Sanitize settings
    # -----------------------------------------------------

    non_negative = (
        "risk_percent",
        "maximum_risk_percent",
        "max_position_percent",
        "max_portfolio_risk_percent",
        "min_stop_percent",
        "max_stop_percent",
        "min_net_rr_t1",
        "min_net_rr_t2",
        "min_net_rr_t3",
        "minimum_notional_usdt",
    )

    for key in non_negative:
        settings[key] = max(
            0.0,
            _number(settings[key], DEFAULTS.get(key, 0.0)),
        )

    settings["maximum_risk_percent"] = min(
        settings["maximum_risk_percent"],
        settings["risk_percent"],
    )

    settings["max_position_percent"] = min(
        100.0,
        settings["max_position_percent"],
    )

    settings["max_stop_percent"] = max(
        settings["min_stop_percent"],
        settings["max_stop_percent"],
    )

    settings["effective_max_stop_percent"] = max(
        settings["effective_min_stop_percent"],
        settings["effective_max_stop_percent"],
    )

    return settings


# =========================================================
# EXECUTION COST
# =========================================================

def calculate_execution_cost_pct(
    entry_fee_percent: Optional[float] = None,
    exit_fee_percent: Optional[float] = None,
    slippage_percent: Optional[float] = None,
) -> float:
    """Round-trip fees and estimated slippage, in percent."""

    settings = _risk_settings()

    entry_fee = (
        settings["entry_fee_percent"]
        if entry_fee_percent is None
        else _number(
            entry_fee_percent,
            settings["entry_fee_percent"],
        )
    )

    exit_fee = (
        settings["exit_fee_percent"]
        if exit_fee_percent is None
        else _number(
            exit_fee_percent,
            settings["exit_fee_percent"],
        )
    )

    slippage = (
        settings["slippage_percent"]
        if slippage_percent is None
        else _number(
            slippage_percent,
            settings["slippage_percent"],
        )
    )

    return (
        max(0.0, entry_fee)
        + max(0.0, exit_fee)
        + max(0.0, slippage)
    )


def estimate_net_return_pct(
    entry: float,
    exit_price: float,
    direction: str = "BUY",
    costs_pct: Optional[float] = None,
) -> float:

    entry = _number(entry, 0.0)
    exit_price = _number(exit_price, 0.0)

    if entry <= 0 or exit_price <= 0:
        return 0.0

    if direction.upper() != "BUY":
        return 0.0

    costs = (
        calculate_execution_cost_pct()
        if costs_pct is None
        else max(0.0, _number(costs_pct, 0.0))
    )

    gross = (exit_price - entry) / entry * 100.0

    return gross - costs


# =========================================================
# STOP LOSS
# =========================================================

def calculate_stop_loss(
    entry_price: float,
    atr: float,
    support: Optional[float] = None,
    direction: str = "BUY",
    strategy: Optional[str] = None,
) -> float:

    if direction.upper() != "BUY":
        raise ValueError("V4 execution is Spot BUY only")

    entry = _number(entry_price, 0.0)
    atr_value = _number(atr, 0.0)

    if entry <= 0 or atr_value <= 0:
        raise ValueError(
            "entry_price and ATR must be positive"
        )

    settings = _risk_settings(strategy)

    multiplier = settings["effective_atr_stop_multiplier"]

    minimum_distance = settings[
        "effective_min_stop_percent"
    ]

    maximum_distance = settings[
        "effective_max_stop_percent"
    ]

    if multiplier <= 0:
        raise ValueError("ATR stop multiplier must be positive")

    distance = atr_value * multiplier

    if support is not None:
        support_value = _number(support, 0.0)

        if 0 < support_value < entry:
            structural_distance = (
                entry
                - (
                    support_value
                    - atr_value * settings["support_buffer_atr"]
                )
            )

            if structural_distance > 0:
                distance = max(
                    distance,
                    structural_distance,
                )

    distance_pct = distance / entry * 100.0

    distance_pct = min(
        maximum_distance,
        max(minimum_distance, distance_pct),
    )

    stop = entry * (
        1.0 - distance_pct / 100.0
    )

    if not 0 < stop < entry:
        raise ValueError(
            "Calculated BUY stop loss is invalid"
        )

    return stop


# =========================================================
# TARGETS
# =========================================================

def _valid_resistances(
    entry: float,
    resistances: Optional[Iterable[Any]],
) -> List[float]:

    values = []

    for item in resistances or []:
        value = _number(item, 0.0)

        if value > entry * 1.0001:
            values.append(value)

    return sorted(set(values))


def _required_target_price(
    entry: float,
    stop: float,
    min_net_rr: float,
    costs_pct: float,
) -> float:
    """Solve for target price after fees and slippage."""

    risk_pct = (
        (entry - stop) / entry * 100.0
    )

    required_gross_reward_pct = (
        min_net_rr * (risk_pct + costs_pct)
        + costs_pct
    )

    # Small rounding buffer.
    return entry * (
        1.0
        + (required_gross_reward_pct + 0.001) / 100.0
    )


def calculate_targets(
    entry_price: float,
    atr: float,
    stop_loss: Optional[float] = None,
    resistances: Optional[Iterable[Any]] = None,
    direction: str = "BUY",
    execution_cost_pct: Optional[float] = None,
    strategy: Optional[str] = None,
) -> List[float]:

    if direction.upper() != "BUY":
        raise ValueError("V4 execution is Spot BUY only")

    entry = _number(entry_price, 0.0)
    atr_value = _number(atr, 0.0)

    if entry <= 0 or atr_value <= 0:
        raise ValueError(
            "entry_price and ATR must be positive"
        )

    settings = _risk_settings(strategy)

    stop = (
        _number(stop_loss, 0.0)
        if stop_loss is not None
        else calculate_stop_loss(
            entry,
            atr_value,
            strategy=strategy,
        )
    )

    if not 0 < stop < entry:
        raise ValueError(
            "stop_loss must be below entry for BUY"
        )

    costs = (
        calculate_execution_cost_pct()
        if execution_cost_pct is None
        else max(
            0.0,
            _number(execution_cost_pct, 0.0),
        )
    )

    resistances = _valid_resistances(
        entry,
        resistances,
    )

    multipliers = settings["target_atr_multipliers"]

    rr_limits = (
        settings["min_net_rr_t1"],
        settings["min_net_rr_t2"],
        settings["min_net_rr_t3"],
    )

    targets = []
    previous = entry

    for index in range(3):
        fallback = (
            entry
            + atr_value * float(multipliers[index])
        )

        required = _required_target_price(
            entry,
            stop,
            rr_limits[index],
            costs,
        )

        next_resistance = next(
            (
                level
                for level in resistances
                if level > previous * 1.0001
            ),
            None,
        )

        if next_resistance is not None:
            # Do not fabricate a breakout target beyond
            # a nearby real resistance. Validation decides
            # whether the reward is sufficient.
            candidate = next_resistance
        else:
            candidate = max(
                fallback,
                required,
            )

        if candidate <= previous * 1.0001:
            candidate = max(
                previous + atr_value * 0.25,
                required,
            )

        targets.append(candidate)
        previous = candidate

    return targets


# =========================================================
# NET RISK / REWARD
# =========================================================

def calculate_risk_reward(
    entry: float,
    stop_loss: float,
    target: float,
    direction: str = "BUY",
    execution_cost_pct: Optional[float] = None,
) -> Dict[str, float]:

    entry = _number(entry, 0.0)
    stop = _number(stop_loss, 0.0)
    target = _number(target, 0.0)

    costs = (
        calculate_execution_cost_pct()
        if execution_cost_pct is None
        else max(
            0.0,
            _number(execution_cost_pct, 0.0),
        )
    )

    empty = {
        "gross_reward_pct": 0.0,
        "gross_risk_pct": 0.0,
        "net_reward_pct": 0.0,
        "net_risk_pct": 0.0,
        "net_rr": 0.0,
    }

    if entry <= 0 or stop <= 0 or target <= 0:
        return empty

    if direction.upper() != "BUY":
        return empty

    if not 0 < stop < entry or target <= entry:
        return empty

    gross_reward = (
        (target - entry) / entry * 100.0
    )

    gross_risk = (
        (entry - stop) / entry * 100.0
    )

    net_reward = max(
        0.0,
        gross_reward - costs,
    )

    net_risk = gross_risk + costs

    return {
        "gross_reward_pct": gross_reward,
        "gross_risk_pct": gross_risk,
        "net_reward_pct": net_reward,
        "net_risk_pct": net_risk,
        "net_rr": (
            net_reward / net_risk
            if net_risk > 0
            else 0.0
        ),
    }


# =========================================================
# POSITION SIZING
# =========================================================

def calculate_position_size(
    capital_usdt: float,
    entry_price: float,
    stop_loss: float,
    risk_percent: Optional[float] = None,
    execution_cost_pct: Optional[float] = None,
) -> Dict[str, Any]:

    settings = _risk_settings()

    capital = _number(capital_usdt, 0.0)
    entry = _number(entry_price, 0.0)
    stop = _number(stop_loss, 0.0)

    configured_risk = settings["risk_percent"]

    if risk_percent is None:
        risk_pct = configured_risk
    else:
        risk_pct = min(
            settings["maximum_risk_percent"],
            max(
                0.0,
                _number(risk_percent, 0.0),
            ),
        )

    costs = (
        calculate_execution_cost_pct()
        if execution_cost_pct is None
        else max(
            0.0,
            _number(execution_cost_pct, 0.0),
        )
    )

    result = {
        "valid": False,
        "quantity": 0.0,
        "position_size_usdt": 0.0,
        "risk_budget_usdt": 0.0,
        "estimated_loss_usdt": 0.0,
        "estimated_loss_within_budget": False,
        "minimum_notional_usdt": settings[
            "minimum_notional_usdt"
        ],
        "reason": "invalid inputs",
    }

    if (
        capital <= 0
        or entry <= 0
        or not 0 < stop < entry
        or risk_pct <= 0
    ):
        return result

    risk_budget = (
        capital * risk_pct / 100.0
    )

    # Entry and exit costs are included in the
    # estimated per-unit loss.
    per_unit_loss = (
        entry - stop
        + entry * costs / 100.0
    )

    if per_unit_loss <= 0:
        result["reason"] = "invalid per-unit risk"
        return result

    quantity_by_risk = (
        risk_budget / per_unit_loss
    )

    allocation_limit = (
        capital
        * settings["max_position_percent"]
        / 100.0
    )

    quantity_by_allocation = (
        allocation_limit / entry
    )

    quantity = min(
        quantity_by_risk,
        quantity_by_allocation,
    )

    position_usdt = quantity * entry
    estimated_loss = quantity * per_unit_loss

    minimum_notional = settings[
        "minimum_notional_usdt"
    ]

    risk_within_budget = (
        estimated_loss <= risk_budget + 1e-9
    )

    valid = (
        quantity > 0
        and position_usdt + 1e-9 >= minimum_notional
        and risk_within_budget
    )

    if position_usdt + 1e-9 < minimum_notional:
        reason = (
            "position below configured minimum order value"
        )
    elif not risk_within_budget:
        reason = "risk budget exceeded"
    else:
        reason = "ok"

    result.update({
        "valid": valid,
        "quantity": quantity,
        "position_size_usdt": position_usdt,
        "risk_budget_usdt": risk_budget,
        "estimated_loss_usdt": estimated_loss,
        "estimated_loss_within_budget": risk_within_budget,
        "reason": reason,
    })

    return result


# =========================================================
# RISK VALIDATION
# =========================================================

def validate_risk(
    entry: float,
    stop_loss: float,
    targets: Sequence[float],
    position: Optional[Dict[str, Any]] = None,
    execution_cost_pct: Optional[float] = None,
) -> Dict[str, Any]:

    settings = _risk_settings()

    checks = {}

    limits = (
        settings["min_net_rr_t1"],
        settings["min_net_rr_t2"],
        settings["min_net_rr_t3"],
    )

    labels = ("t1", "t2", "t3")

    for index, label in enumerate(labels):
        target = (
            _number(targets[index], 0.0)
            if index < len(targets)
            else 0.0
        )

        metrics = calculate_risk_reward(
            entry,
            stop_loss,
            target,
            execution_cost_pct=execution_cost_pct,
        )

        checks[label] = {
            **metrics,
            "minimum_net_rr": limits[index],
            "valid": (
                metrics["net_rr"] + 1e-9
                >= limits[index]
            ),
        }

    position_valid = bool(
        isinstance(position, dict)
        and position.get("valid") is True
        and position.get("estimated_loss_within_budget") is True
    )

    # T1 is mandatory.
    # T2 and T3 remain optional extended targets.
    valid = bool(
        checks["t1"]["valid"]
        and position_valid
    )

    reasons = []

    if not checks["t1"]["valid"]:
        reasons.append(
            "T1 net risk/reward below configured minimum"
        )

    if not position_valid:
        reasons.append(
            "position sizing invalid or over risk budget"
        )

    return {
        "valid": valid,
        "reason": (
            "; ".join(reasons)
            if reasons
            else "ok"
        ),
        "target_checks": checks,
        "position_valid": position_valid,
        "minimum_net_rr_t1": settings["min_net_rr_t1"],
    }


# =========================================================
# COMPLETE RISK PLAN
# =========================================================

def build_risk_plan(
    entry_price: float,
    atr: float,
    capital_usdt: float,
    support: Optional[float] = None,
    resistances: Optional[Iterable[Any]] = None,
    direction: str = "BUY",
    strategy: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:

    entry = _number(entry_price, 0.0)
    atr_value = _number(atr, 0.0)

    base = {
        "valid": False,
        "reason": "invalid inputs",
        "direction": "BUY",
        "spot_only": True,
        "formula_version": FORMULA_VERSION,
        "code_version": CODE_VERSION,
        "strategy": _strategy_name(strategy),
        "entry": entry,
        "stop_loss": 0.0,
        "targets": [],
        "target_net_returns_pct": [],
        "atr": atr_value,
        "risk_distance_pct": 0.0,
        "execution_cost_pct": calculate_execution_cost_pct(),
        "position": {},
        "risk_validation": {},
        "target_checks": {},
    }

    if direction.upper() != "BUY":
        base["reason"] = (
            "V4 execution is Spot BUY only"
        )
        return base

    if (
        entry <= 0
        or atr_value <= 0
        or _number(capital_usdt, 0.0) <= 0
    ):
        return base

    try:
        costs = calculate_execution_cost_pct()

        stop = calculate_stop_loss(
            entry,
            atr_value,
            support=support,
            direction="BUY",
            strategy=strategy,
        )

        targets = calculate_targets(
            entry,
            atr_value,
            stop_loss=stop,
            resistances=resistances,
            direction="BUY",
            execution_cost_pct=costs,
            strategy=strategy,
        )

        position = calculate_position_size(
            capital_usdt,
            entry,
            stop,
            execution_cost_pct=costs,
        )

        validation = validate_risk(
            entry,
            stop,
            targets,
            position=position,
            execution_cost_pct=costs,
        )

        risk_distance_pct = (
            (entry - stop) / entry * 100.0
        )

        base.update({
            "valid": validation["valid"],
            "reason": validation["reason"],
            "entry": entry,
            "stop_loss": stop,
            "targets": targets,
            "target_net_returns_pct": [
                estimate_net_return_pct(
                    entry,
                    target,
                    costs_pct=costs,
                )
                for target in targets
            ],
            "atr": atr_value,
            "risk_distance_pct": risk_distance_pct,
            "execution_cost_pct": costs,
            "position": position,
            "risk_validation": validation,
            "target_checks": validation["target_checks"],
        })

        return base

    except (
        ValueError,
        TypeError,
        ArithmeticError,
        KeyError,
    ) as exc:
        base["reason"] = str(exc)
        return base


# =========================================================
# PUBLIC CONFIG HELPER
# =========================================================

def get_risk_manager_config(
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    return _risk_settings(strategy)


# =========================================================
# SELF CHECK
# =========================================================

def self_check() -> Dict[str, Any]:

    plan = build_risk_plan(
        entry_price=100.0,
        atr=1.0,
        capital_usdt=100.0,
    )

    t1 = (
        plan.get("target_checks", {})
        .get("t1", {})
    )

    settings = _risk_settings()

    passed = bool(
        plan.get("valid")
        and t1.get("valid")
        and t1.get("net_rr", 0.0)
        >= settings["min_net_rr_t1"]
    )

    return {
        "ok": passed,
        "plan_valid": plan.get("valid", False),
        "t1_net_rr": t1.get("net_rr", 0.0),
        "minimum_t1_net_rr": settings["min_net_rr_t1"],
        "reason": plan.get("reason", ""),
    }


if __name__ == "__main__":
    print(self_check())
