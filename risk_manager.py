
"""Binance Spot V4 risk manager.

All percentage values are expressed in percentage points:
0.25 means 0.25%. Spot BUY execution only.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    import config as app_config
except Exception:
    app_config = None


DEFAULTS = {
    "risk_percent": 1.0,
    "maximum_risk_percent": 1.0,
    "max_position_percent": 25.0,
    "max_portfolio_risk_percent": 3.0,
    "atr_stop_multiplier": 1.8,
    "min_stop_percent": 0.5,
    "max_stop_percent": 5.0,
    "support_buffer_atr": 0.25,
    "target_atr_multipliers": (1.5, 2.5, 3.5),
    "min_net_rr_t1": 1.2,
    "min_net_rr_t2": 1.5,
    "min_net_rr_t3": 2.0,
    "entry_fee_percent": 0.10,
    "exit_fee_percent": 0.10,
    "slippage_percent": 0.05,
    "minimum_notional_usdt": 5.0,
}


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _find_config_value(names: Sequence[str], default: float) -> float:
    if app_config is None:
        return default

    roots = []
    for root_name in (
        "RISK_CONFIG",
        "RISK_MANAGEMENT_CONFIG",
        "EXECUTION_COST_CONFIG",
    ):
        root = getattr(app_config, root_name, None)
        if isinstance(root, dict):
            roots.append(root)

    for root in roots:
        for name in names:
            if name in root:
                return _number(root[name], default)

    return default


def _risk_settings() -> Dict[str, Any]:
    settings = dict(DEFAULTS)

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
        settings[key] = _find_config_value(names, settings[key])

    for key in (
        "risk_percent",
        "maximum_risk_percent",
        "max_position_percent",
        "max_portfolio_risk_percent",
        "min_stop_percent",
        "max_stop_percent",
        "min_net_rr_t1",
        "min_net_rr_t2",
        "min_net_rr_t3",
    ):
        settings[key] = max(0.0, settings[key])

    settings["maximum_risk_percent"] = min(
        settings["maximum_risk_percent"],
        settings["risk_percent"] or settings["maximum_risk_percent"],
    )

    settings["max_stop_percent"] = max(
        settings["min_stop_percent"],
        settings["max_stop_percent"],
    )

    return settings


def calculate_execution_cost_pct(
    entry_fee_percent: Optional[float] = None,
    exit_fee_percent: Optional[float] = None,
    slippage_percent: Optional[float] = None,
) -> float:
    """Estimated round-trip fees and slippage in percentage points."""

    settings = _risk_settings()

    entry_fee = (
        settings["entry_fee_percent"]
        if entry_fee_percent is None
        else _number(entry_fee_percent, settings["entry_fee_percent"])
    )

    exit_fee = (
        settings["exit_fee_percent"]
        if exit_fee_percent is None
        else _number(exit_fee_percent, settings["exit_fee_percent"])
    )

    slippage = (
        settings["slippage_percent"]
        if slippage_percent is None
        else _number(slippage_percent, settings["slippage_percent"])
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

    if entry <= 0 or exit_price <= 0:
        return 0.0

    costs = (
        calculate_execution_cost_pct()
        if costs_pct is None
        else max(0.0, _number(costs_pct, 0.0))
    )

    if direction.upper() == "BUY":
        gross = (exit_price - entry) / entry * 100.0
    else:
        gross = (entry - exit_price) / entry * 100.0

    return gross - costs


def calculate_stop_loss(
    entry_price: float,
    atr: float,
    support: Optional[float] = None,
    direction: str = "BUY",
) -> float:

    if direction.upper() != "BUY":
        raise ValueError("V4 execution is Spot BUY only")

    entry = _number(entry_price, 0.0)
    atr_value = _number(atr, 0.0)

    if entry <= 0 or atr_value <= 0:
        raise ValueError("entry_price and ATR must be positive")

    settings = _risk_settings()

    distance = atr_value * settings["atr_stop_multiplier"]

    if support is not None:
        support_value = _number(support, 0.0)

        if 0 < support_value < entry:
            structural_distance = entry - (
                support_value
                - atr_value * settings["support_buffer_atr"]
            )

            if structural_distance > 0:
                distance = max(distance, structural_distance)

    distance_pct = distance / entry * 100.0

    distance_pct = min(
        settings["max_stop_percent"],
        max(settings["min_stop_percent"], distance_pct),
    )

    stop = entry * (1.0 - distance_pct / 100.0)

    if not 0 < stop < entry:
        raise ValueError("Calculated BUY stop loss is invalid")

    return stop


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

    risk_pct = (entry - stop) / entry * 100.0

    required_gross_reward_pct = (
        min_net_rr * (risk_pct + costs_pct)
        + costs_pct
    )

    # Small rounding buffer prevents floating-point rejection at the threshold.
    return entry * (
        1.0 + (required_gross_reward_pct + 0.001) / 100.0
    )


def calculate_targets(
    entry_price: float,
    atr: float,
    stop_loss: Optional[float] = None,
    resistances: Optional[Iterable[Any]] = None,
    direction: str = "BUY",
    execution_cost_pct: Optional[float] = None,
) -> List[float]:

    if direction.upper() != "BUY":
        raise ValueError("V4 execution is Spot BUY only")

    entry = _number(entry_price, 0.0)
    atr_value = _number(atr, 0.0)

    if entry <= 0 or atr_value <= 0:
        raise ValueError("entry_price and ATR must be positive")

    settings = _risk_settings()

    stop = (
        _number(stop_loss, 0.0)
        if stop_loss is not None
        else calculate_stop_loss(entry, atr_value)
    )

    if not 0 < stop < entry:
        raise ValueError("stop_loss must be below entry for BUY")

    costs = (
        calculate_execution_cost_pct()
        if execution_cost_pct is None
        else max(0.0, _number(execution_cost_pct, 0.0))
    )

    resistance_levels = _valid_resistances(entry, resistances)

    multipliers = tuple(settings["target_atr_multipliers"])

    targets = []
    previous = entry

    rr_limits = (
        settings["min_net_rr_t1"],
        settings["min_net_rr_t2"],
        settings["min_net_rr_t3"],
    )

    for index, multiplier in enumerate(multipliers[:3]):

        fallback = entry + atr_value * float(multiplier)

        required = _required_target_price(
            entry,
            stop,
            rr_limits[index],
            costs,
        )

        next_resistance = next(
            (
                level
                for level in resistance_levels
                if level > previous * 1.0001
            ),
            None,
        )

        if next_resistance is not None:
            # Keep the actual nearby resistance.
            # Validation will reject insufficient T1 reward.
            candidate = next_resistance
        else:
            candidate = max(fallback, required)

        if candidate <= previous * 1.0001:
            candidate = max(
                previous + atr_value * 0.25,
                required,
            )

        targets.append(candidate)
        previous = candidate

    while len(targets) < 3:
        index = len(targets)

        candidate = max(
            previous + atr_value,
            _required_target_price(
                entry,
                stop,
                rr_limits[index],
                costs,
            ),
        )

        targets.append(candidate)
        previous = candidate

    return targets[:3]


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
        else max(0.0, _number(execution_cost_pct, 0.0))
    )

    if entry <= 0 or stop <= 0 or target <= 0:
        return {
            "gross_reward_pct": 0.0,
            "gross_risk_pct": 0.0,
            "net_reward_pct": 0.0,
            "net_risk_pct": 0.0,
            "net_rr": 0.0,
        }

    if direction.upper() == "BUY":
        gross_reward = max(
            0.0,
            (target - entry) / entry * 100.0,
        )

        gross_risk = max(
            0.0,
            (entry - stop) / entry * 100.0,
        )
    else:
        gross_reward = max(
            0.0,
            (entry - target) / entry * 100.0,
        )

        gross_risk = max(
            0.0,
            (stop - entry) / entry * 100.0,
        )

    net_reward = max(0.0, gross_reward - costs)
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

    risk_pct = (
        settings["risk_percent"]
        if risk_percent is None
        else min(
            settings["maximum_risk_percent"],
            max(0.0, _number(risk_percent, 0.0)),
        )
    )

    costs = (
        calculate_execution_cost_pct()
        if execution_cost_pct is None
        else max(0.0, _number(execution_cost_pct, 0.0))
    )

    result = {
        "valid": False,
        "quantity": 0.0,
        "position_size_usdt": 0.0,
        "risk_budget_usdt": 0.0,
        "estimated_loss_usdt": 0.0,
        "estimated_loss_within_budget": False,
        "reason": "invalid inputs",
    }

    if capital <= 0 or entry <= 0 or not 0 < stop < entry:
        return result

    risk_budget = capital * risk_pct / 100.0

    per_unit_loss = (
        entry - stop
        + entry * costs / 100.0
    )

    if per_unit_loss <= 0:
        result["reason"] = "invalid per-unit risk"
        return result

    quantity_by_risk = risk_budget / per_unit_loss

    max_position_usdt = (
        capital * settings["max_position_percent"] / 100.0
    )

    quantity_by_allocation = max_position_usdt / entry

    quantity = min(
        quantity_by_risk,
        quantity_by_allocation,
    )

    position_usdt = quantity * entry
    estimated_loss = quantity * per_unit_loss

    min_notional = settings["minimum_notional_usdt"]

    valid = (
        quantity > 0
        and position_usdt >= min_notional
        and estimated_loss <= risk_budget + 1e-9
    )

    result.update({
        "valid": valid,
        "quantity": quantity,
        "position_size_usdt": position_usdt,
        "risk_budget_usdt": risk_budget,
        "estimated_loss_usdt": estimated_loss,
        "estimated_loss_within_budget": (
            estimated_loss <= risk_budget + 1e-9
        ),
        "reason": (
            "ok"
            if valid
            else (
                "position below minimum notional"
                if position_usdt < min_notional
                else "risk budget exceeded"
            )
        ),
    })

    return result


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
            "valid": metrics["net_rr"] >= limits[index],
        }

    position_valid = bool(
        position
        and position.get("valid")
        and position.get("estimated_loss_within_budget")
    )

    # T1 is the minimum executable profit objective.
    # T2/T3 are additional objectives, not mandatory gates.
    valid = bool(
        checks["t1"]["valid"]
        and position_valid
    )

    reasons = []

    if not checks["t1"]["valid"]:
        reasons.append("T1 net risk/reward below minimum")

    if not position_valid:
        reasons.append(
            "position sizing invalid or over risk budget"
        )

    return {
        "valid": valid,
        "reason": "; ".join(reasons) if reasons else "ok",
        "target_checks": checks,
        "position_valid": position_valid,
        "minimum_net_rr_t1": settings["min_net_rr_t1"],
    }


def build_risk_plan(
    entry_price: float,
    atr: float,
    capital_usdt: float,
    support: Optional[float] = None,
    resistances: Optional[Iterable[Any]] = None,
    direction: str = "BUY",
    **kwargs: Any,
) -> Dict[str, Any]:

    entry = _number(entry_price, 0.0)
    atr_value = _number(atr, 0.0)

    base = {
        "valid": False,
        "reason": "invalid inputs",
        "direction": "BUY",
        "spot_only": True,
        "formula_version": "4.0",
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
        base["reason"] = "V4 execution is Spot BUY only"
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
        )

        targets = calculate_targets(
            entry,
            atr_value,
            stop_loss=stop,
            resistances=resistances,
            direction="BUY",
            execution_cost_pct=costs,
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

    except (ValueError, TypeError, ArithmeticError) as exc:
        base["reason"] = str(exc)
        return base


def get_risk_manager_config() -> Dict[str, Any]:
    return _risk_settings()


def self_check() -> Dict[str, Any]:

    plan = build_risk_plan(
        entry_price=100.0,
        atr=1.0,
        capital_usdt=100.0,
        resistances=None,
    )

    t1_check = (
        plan.get("target_checks", {})
        .get("t1", {})
    )

    return {
        "ok": bool(
            plan.get("valid")
            and t1_check.get("valid")
        ),
        "plan_valid": plan.get("valid", False),
        "t1_net_rr": t1_check.get("net_rr", 0.0),
        "minimum_t1_net_rr": _risk_settings()["min_net_rr_t1"],
        "reason": plan.get("reason", ""),
    }


if __name__ == "__main__":
    print(self_check())
