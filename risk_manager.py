"""
File: risk_manager.py
System: Binance Spot V3 Smart Signal Scanner
Code Version: 4.0.0
Formula Version: 4.0
Python: 3.11+
Compatibility: New internal architecture
Test Status: NOT RUN

Purpose:
- ATR and structure-aware Stop Loss.
- Resistance-aware T1/T2/T3 targets.
- Fee and slippage adjusted net Risk/Reward.
- Risk-based position sizing for Spot trading.
- Capital allocation and maximum risk controls.

Spot only. No Futures. No Margin.
All prices are estimates, not guaranteed execution prices.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import config as app_config
except Exception:
    app_config = None


# ============================================================
# DEFAULT CONFIGURATION
# ============================================================

DEFAULT_RISK_PER_TRADE_PCT = 1.0
DEFAULT_MAX_POSITION_PCT = 25.0
DEFAULT_MAX_PORTFOLIO_RISK_PCT = 3.0

DEFAULT_ATR_STOP_MULTIPLIER = 1.8
DEFAULT_MIN_STOP_PCT = 0.5
DEFAULT_MAX_STOP_PCT = 5.0
DEFAULT_SUPPORT_BUFFER_ATR = 0.25

DEFAULT_TARGET_ATR_MULTIPLIERS = (1.5, 2.5, 3.5)
DEFAULT_MIN_NET_RR_T1 = 1.2
DEFAULT_MIN_NET_RR_T2 = 1.5
DEFAULT_MIN_NET_RR_T3 = 2.0

DEFAULT_ENTRY_FEE_PCT = 0.1
DEFAULT_EXIT_FEE_PCT = 0.1
DEFAULT_SLIPPAGE_PCT = 0.05

EPSILON = 1e-12


# ============================================================
# GENERAL HELPERS
# ============================================================

def _finite(value: Any) -> Optional[float]:
    try:
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value: Any, default: float = 0.0) -> float:
    result = _finite(value)
    if result is None or result < 0:
        return default
    return result


def _config_section(name: str) -> Dict[str, Any]:
    if app_config is None:
        return {}

    value = getattr(app_config, name, None)
    return value if isinstance(value, dict) else {}


def _config_value(
    section_names: Iterable[str],
    key_names: Iterable[str],
    default: float,
) -> float:
    for section_name in section_names:
        section = _config_section(section_name)

        for key in key_names:
            if key in section:
                value = _finite(section[key])
                if value is not None:
                    return value

    return default


def _risk_settings() -> Dict[str, float]:
    return {
        "risk_per_trade_pct": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("risk_per_trade_pct", "RISK_PER_TRADE_PCT"),
            DEFAULT_RISK_PER_TRADE_PCT,
        ),
        "max_position_pct": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("max_position_pct", "MAX_POSITION_PCT"),
            DEFAULT_MAX_POSITION_PCT,
        ),
        "max_portfolio_risk_pct": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("max_portfolio_risk_pct", "MAX_PORTFOLIO_RISK_PCT"),
            DEFAULT_MAX_PORTFOLIO_RISK_PCT,
        ),
        "atr_stop_multiplier": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("atr_stop_multiplier", "ATR_STOP_MULTIPLIER"),
            DEFAULT_ATR_STOP_MULTIPLIER,
        ),
        "min_stop_pct": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("min_stop_pct", "MIN_STOP_PCT"),
            DEFAULT_MIN_STOP_PCT,
        ),
        "max_stop_pct": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("max_stop_pct", "MAX_STOP_PCT"),
            DEFAULT_MAX_STOP_PCT,
        ),
        "support_buffer_atr": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("support_buffer_atr", "SUPPORT_BUFFER_ATR"),
            DEFAULT_SUPPORT_BUFFER_ATR,
        ),
        "min_net_rr_t1": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("min_net_rr_t1", "MIN_NET_RR_T1"),
            DEFAULT_MIN_NET_RR_T1,
        ),
        "min_net_rr_t2": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("min_net_rr_t2", "MIN_NET_RR_T2"),
            DEFAULT_MIN_NET_RR_T2,
        ),
        "min_net_rr_t3": _config_value(
            ("RISK_CONFIG", "RISK_MANAGEMENT_CONFIG"),
            ("min_net_rr_t3", "MIN_NET_RR_T3"),
            DEFAULT_MIN_NET_RR_T3,
        ),
        "entry_fee_pct": _config_value(
            ("EXECUTION_COST_CONFIG", "RISK_CONFIG"),
            ("entry_fee_pct", "ENTRY_FEE_PCT"),
            DEFAULT_ENTRY_FEE_PCT,
        ),
        "exit_fee_pct": _config_value(
            ("EXECUTION_COST_CONFIG", "RISK_CONFIG"),
            ("exit_fee_pct", "EXIT_FEE_PCT"),
            DEFAULT_EXIT_FEE_PCT,
        ),
        "slippage_pct": _config_value(
            ("EXECUTION_COST_CONFIG", "RISK_CONFIG"),
            ("slippage_pct", "SLIPPAGE_PCT"),
            DEFAULT_SLIPPAGE_PCT,
        ),
    }


def _valid_price(value: Any) -> Optional[float]:
    result = _finite(value)
    if result is None or result <= 0:
        return None
    return result


def _normalize_levels(
    values: Optional[Iterable[Any]],
    entry: float,
    direction: str,
) -> List[float]:
    if values is None:
        return []

    if isinstance(values, (int, float, str)):
        values = [values]

    result = []

    for value in values:
        price = _valid_price(value)
        if price is None:
            continue

        if direction == "BUY" and price > entry:
            result.append(price)
        elif direction == "SELL" and price < entry:
            result.append(price)

    return sorted(set(result), reverse=(direction == "SELL"))


# ============================================================
# EXECUTION COSTS
# ============================================================

def calculate_execution_cost_pct(
    entry_fee_pct: Optional[float] = None,
    exit_fee_pct: Optional[float] = None,
    slippage_pct: Optional[float] = None,
) -> float:
    """
    Estimate round-trip cost as percentage of notional.

    Slippage is assumed to be a total round-trip estimate.
    Do not pass a one-way slippage estimate as a round-trip value.
    """
    settings = _risk_settings()

    entry_fee = (
        settings["entry_fee_pct"]
        if entry_fee_pct is None
        else _positive(entry_fee_pct)
    )

    exit_fee = (
        settings["exit_fee_pct"]
        if exit_fee_pct is None
        else _positive(exit_fee_pct)
    )

    slippage = (
        settings["slippage_pct"]
        if slippage_pct is None
        else _positive(slippage_pct)
    )

    if min(entry_fee, exit_fee, slippage) < 0:
        raise ValueError("Execution costs cannot be negative")

    return entry_fee + exit_fee + slippage


def estimate_net_return_pct(
    entry_price: float,
    exit_price: float,
    direction: str = "BUY",
    entry_fee_pct: Optional[float] = None,
    exit_fee_pct: Optional[float] = None,
    slippage_pct: Optional[float] = None,
) -> Optional[float]:
    """Return estimated net percentage return after round-trip costs."""
    entry = _valid_price(entry_price)
    exit_value = _valid_price(exit_price)

    if entry is None or exit_value is None:
        return None

    direction = direction.upper()

    if direction == "BUY":
        gross_pct = ((exit_value - entry) / entry) * 100.0
    elif direction == "SELL":
        gross_pct = ((entry - exit_value) / entry) * 100.0
    else:
        return None

    costs = calculate_execution_cost_pct(
        entry_fee_pct,
        exit_fee_pct,
        slippage_pct,
    )

    return gross_pct - costs


# ============================================================
# STOP LOSS
# ============================================================

def calculate_stop_loss(
    entry_price: float,
    atr: Optional[float] = None,
    support: Optional[float] = None,
    resistance: Optional[float] = None,
    direction: str = "BUY",
    atr_multiplier: Optional[float] = None,
    min_stop_pct: Optional[float] = None,
    max_stop_pct: Optional[float] = None,
    support_buffer_atr: Optional[float] = None,
) -> Optional[float]:
    """
    Calculate a structure-aware ATR Stop Loss.

    BUY:
        Stop below entry, preferably below nearby support.

    SELL:
        Stop above entry, preferably above nearby resistance.
        SELL calculation is provided for analysis compatibility only;
        this scanner's trade execution is Spot BUY-only.
    """
    entry = _valid_price(entry_price)
    if entry is None:
        return None

    direction = direction.upper()
    if direction not in {"BUY", "SELL"}:
        return None

    settings = _risk_settings()

    atr_value = _positive(atr)
    if atr_value <= 0:
        return None

    multiplier = (
        settings["atr_stop_multiplier"]
        if atr_multiplier is None
        else _positive(atr_multiplier)
    )

    min_pct = (
        settings["min_stop_pct"]
        if min_stop_pct is None
        else _positive(min_stop_pct)
    )

    max_pct = (
        settings["max_stop_pct"]
        if max_stop_pct is None
        else _positive(max_stop_pct)
    )

    buffer_multiplier = (
        settings["support_buffer_atr"]
        if support_buffer_atr is None
        else _positive(support_buffer_atr)
    )

    if multiplier <= 0 or min_pct <= 0 or max_pct < min_pct:
        return None

    min_distance = entry * min_pct / 100.0
    max_distance = entry * max_pct / 100.0
    atr_distance = atr_value * multiplier

    if direction == "BUY":
        proposed_stop = entry - atr_distance

        support_price = _valid_price(support)
        if support_price is not None and support_price < entry:
            structural_stop = (
                support_price - atr_value * buffer_multiplier
            )

            # Use support only when it does not exceed the maximum
            # permitted stop distance.
            structural_distance = entry - structural_stop

            if min_distance <= structural_distance <= max_distance:
                proposed_stop = min(proposed_stop, structural_stop)

        distance = entry - proposed_stop
        distance = max(min_distance, min(distance, max_distance))
        stop = entry - distance

        if stop <= 0 or stop >= entry:
            return None

        return stop

    proposed_stop = entry + atr_distance

    resistance_price = _valid_price(resistance)
    if resistance_price is not None and resistance_price > entry:
        structural_stop = (
            resistance_price + atr_value * buffer_multiplier
        )

        structural_distance = structural_stop - entry

        if min_distance <= structural_distance <= max_distance:
            proposed_stop = max(proposed_stop, structural_stop)

    distance = proposed_stop - entry
    distance = max(min_distance, min(distance, max_distance))
    stop = entry + distance

    if stop <= entry:
        return None

    return stop


# ============================================================
# TARGETS
# ============================================================

def calculate_targets(
    entry_price: float,
    stop_loss: float,
    atr: Optional[float] = None,
    resistances: Optional[Iterable[Any]] = None,
    supports: Optional[Iterable[Any]] = None,
    direction: str = "BUY",
    target_multipliers: Optional[Tuple[float, float, float]] = None,
) -> Dict[str, Optional[float]]:
    """
    Calculate three targets using ATR multiples and structure.

    For BUY, nearby resistance levels can be used as targets,
    but a resistance too close to entry is skipped.

    T1/T2/T3 are ascending for BUY.
    """
    entry = _valid_price(entry_price)
    stop = _valid_price(stop_loss)

    if entry is None or stop is None:
        return {"t1": None, "t2": None, "t3": None}

    direction = direction.upper()

    if direction == "BUY" and stop >= entry:
        return {"t1": None, "t2": None, "t3": None}

    if direction == "SELL" and stop <= entry:
        return {"t1": None, "t2": None, "t3": None}

    atr_value = _positive(atr)

    if atr_value <= 0:
        return {"t1": None, "t2": None, "t3": None}

    risk_distance = abs(entry - stop)

    if target_multipliers is None:
        target_multipliers = DEFAULT_TARGET_ATR_MULTIPLIERS

    if (
        not isinstance(target_multipliers, (tuple, list))
        or len(target_multipliers) != 3
    ):
        raise ValueError("Exactly three target multipliers are required")

    multipliers = [_positive(x) for x in target_multipliers]

    if any(x <= 0 for x in multipliers):
        return {"t1": None, "t2": None, "t3": None}

    multipliers.sort()

    if direction == "BUY":
        structural_levels = _normalize_levels(
            resistances, entry, "BUY"
        )

        raw_targets = [
            entry + max(atr_value * multiplier, risk_distance * multiplier)
            for multiplier in multipliers
        ]

        targets = []

        for index, raw_target in enumerate(raw_targets):
            candidates = [
                level for level in structural_levels
                if level > entry
                and (not targets or level > targets[-1])
                and level >= entry + risk_distance * 1.05
            ]

            if candidates:
                # Select the nearest meaningful resistance above entry.
                selected = candidates[0]

                # Do not collapse later targets onto the same resistance.
                if selected > (targets[-1] if targets else entry):
                    targets.append(selected)
                    continue

            targets.append(raw_target)

        targets = sorted(targets)

        # Ensure distinct and strictly increasing targets.
        for i in range(1, 3):
            if targets[i] <= targets[i - 1]:
                targets[i] = targets[i - 1] + atr_value * 0.25

        return {
            "t1": targets[0],
            "t2": targets[1],
            "t3": targets[2],
        }

    structural_levels = _normalize_levels(
        supports, entry, "SELL"
    )

    raw_targets = [
        entry - max(atr_value * multiplier, risk_distance * multiplier)
        for multiplier in multipliers
    ]

    targets = []

    for raw_target in raw_targets:
        candidates = [
            level for level in structural_levels
            if level < entry
            and (not targets or level < targets[-1])
            and level <= entry - risk_distance * 1.05
        ]

        if candidates:
            targets.append(candidates[0])
        else:
            targets.append(raw_target)

    targets = sorted(targets, reverse=True)

    for i in range(1, 3):
        if targets[i] >= targets[i - 1]:
            targets[i] = targets[i - 1] - atr_value * 0.25

    return {
        "t1": targets[0],
        "t2": targets[1],
        "t3": targets[2],
    }


# ============================================================
# RISK / REWARD
# ============================================================

def calculate_risk_reward(
    entry_price: float,
    stop_loss: float,
    target_price: float,
    direction: str = "BUY",
    entry_fee_pct: Optional[float] = None,
    exit_fee_pct: Optional[float] = None,
    slippage_pct: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """
    Calculate gross and net reward/risk.

    Costs are converted to price-equivalent amounts.
    Net R:R = net reward / net loss.
    """
    entry = _valid_price(entry_price)
    stop = _valid_price(stop_loss)
    target = _valid_price(target_price)

    if entry is None or stop is None or target is None:
        return None

    direction = direction.upper()

    if direction == "BUY":
        if not (stop < entry < target):
            return None

        gross_risk_pct = ((entry - stop) / entry) * 100.0
        gross_reward_pct = ((target - entry) / entry) * 100.0

    elif direction == "SELL":
        if not (target < entry < stop):
            return None

        gross_risk_pct = ((stop - entry) / entry) * 100.0
        gross_reward_pct = ((entry - target) / entry) * 100.0

    else:
        return None

    costs_pct = calculate_execution_cost_pct(
        entry_fee_pct,
        exit_fee_pct,
        slippage_pct,
    )

    net_reward_pct = gross_reward_pct - costs_pct
    net_risk_pct = gross_risk_pct + costs_pct

    if net_reward_pct <= 0 or net_risk_pct <= 0:
        return {
            "gross_reward_pct": gross_reward_pct,
            "gross_risk_pct": gross_risk_pct,
            "execution_cost_pct": costs_pct,
            "net_reward_pct": net_reward_pct,
            "net_risk_pct": net_risk_pct,
            "gross_rr": gross_reward_pct / gross_risk_pct,
            "net_rr": 0.0,
        }

    return {
        "gross_reward_pct": gross_reward_pct,
        "gross_risk_pct": gross_risk_pct,
        "execution_cost_pct": costs_pct,
        "net_reward_pct": net_reward_pct,
        "net_risk_pct": net_risk_pct,
        "gross_rr": gross_reward_pct / gross_risk_pct,
        "net_rr": net_reward_pct / net_risk_pct,
    }


# ============================================================
# POSITION SIZING
# ============================================================

def calculate_position_size(
    capital_usdt: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    entry_fee_pct: Optional[float] = None,
    exit_fee_pct: Optional[float] = None,
    slippage_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calculate Spot position size from account risk.

    Risk budget:
        capital * risk_pct

    Estimated loss per unit:
        entry-stop distance + estimated execution costs

    Position notional is capped by max_position_pct of capital.
    """
    capital = _positive(capital_usdt)
    entry = _valid_price(entry_price)
    stop = _valid_price(stop_loss)

    settings = _risk_settings()

    if capital <= 0 or entry is None or stop is None:
        return {
            "valid": False,
            "reason": "INVALID_CAPITAL_OR_PRICE",
            "quantity": 0.0,
            "position_value_usdt": 0.0,
        }

    if stop >= entry:
        return {
            "valid": False,
            "reason": "INVALID_SPOT_BUY_STOP",
            "quantity": 0.0,
            "position_value_usdt": 0.0,
        }

    risk_percent = (
        settings["risk_per_trade_pct"]
        if risk_pct is None
        else _positive(risk_pct)
    )

    allocation_percent = (
        settings["max_position_pct"]
        if max_position_pct is None
        else _positive(max_position_pct)
    )

    if not (0 < risk_percent <= 100):
        return {
            "valid": False,
            "reason": "INVALID_RISK_PERCENT",
            "quantity": 0.0,
            "position_value_usdt": 0.0,
        }

    if not (0 < allocation_percent <= 100):
        return {
            "valid": False,
            "reason": "INVALID_ALLOCATION_PERCENT",
            "quantity": 0.0,
            "position_value_usdt": 0.0,
        }

    costs_pct = calculate_execution_cost_pct(
        entry_fee_pct,
        exit_fee_pct,
        slippage_pct,
    )

    stop_distance_pct = ((entry - stop) / entry) * 100.0

    # Cost-adjusted loss estimate per unit, expressed as a
    # percentage of entry notional.
    estimated_loss_pct = stop_distance_pct + costs_pct

    if estimated_loss_pct <= 0:
        return {
            "valid": False,
            "reason": "INVALID_ESTIMATED_LOSS",
            "quantity": 0.0,
            "position_value_usdt": 0.0,
        }

    risk_budget = capital * risk_percent / 100.0
    max_allocation = capital * allocation_percent / 100.0

    risk_limited_notional = (
        risk_budget / (estimated_loss_pct / 100.0)
    )

    position_value = min(
        risk_limited_notional,
        max_allocation,
    )

    quantity = position_value / entry

    estimated_loss_usdt = (
        position_value * estimated_loss_pct / 100.0
    )

    return {
        "valid": True,
        "reason": "VALID",
        "capital_usdt": capital,
        "risk_percent": risk_percent,
        "risk_budget_usdt": risk_budget,
        "max_position_percent": allocation_percent,
        "max_allocation_usdt": max_allocation,
        "risk_limited_notional_usdt": risk_limited_notional,
        "position_value_usdt": position_value,
        "quantity": quantity,
        "entry_price": entry,
        "stop_loss": stop,
        "stop_distance_percent": stop_distance_pct,
        "execution_cost_percent": costs_pct,
        "estimated_loss_percent": estimated_loss_pct,
        "estimated_loss_usdt": estimated_loss_usdt,
        "estimated_loss_within_budget": (
            estimated_loss_usdt <= risk_budget + 1e-8
        ),
    }


# ============================================================
# RISK VALIDATION
# ============================================================

def validate_risk(
    entry_price: float,
    stop_loss: float,
    targets: Dict[str, Any],
    capital_usdt: Optional[float] = None,
    position_size: Optional[Dict[str, Any]] = None,
    min_net_rr_t1: Optional[float] = None,
    min_net_rr_t2: Optional[float] = None,
    min_net_rr_t3: Optional[float] = None,
) -> Dict[str, Any]:
    """Validate Spot BUY risk plan using net R:R."""
    entry = _valid_price(entry_price)
    stop = _valid_price(stop_loss)

    settings = _risk_settings()

    minimums = {
        "t1": (
            settings["min_net_rr_t1"]
            if min_net_rr_t1 is None
            else _positive(min_net_rr_t1)
        ),
        "t2": (
            settings["min_net_rr_t2"]
            if min_net_rr_t2 is None
            else _positive(min_net_rr_t2)
        ),
        "t3": (
            settings["min_net_rr_t3"]
            if min_net_rr_t3 is None
            else _positive(min_net_rr_t3)
        ),
    }

    if entry is None or stop is None or stop >= entry:
        return {
            "valid": False,
            "reason": "INVALID_ENTRY_OR_STOP",
            "target_checks": {},
        }

    if not isinstance(targets, dict):
        return {
            "valid": False,
            "reason": "INVALID_TARGETS",
            "target_checks": {},
        }

    target_checks: Dict[str, Any] = {}

    for name in ("t1", "t2", "t3"):
        target = _valid_price(targets.get(name))

        if target is None:
            target_checks[name] = {
                "valid": False,
                "reason": "MISSING_TARGET",
                "net_rr": None,
            }
            continue

        rr = calculate_risk_reward(
            entry_price=entry,
            stop_loss=stop,
            target_price=target,
            direction="BUY",
        )

        if rr is None:
            target_checks[name] = {
                "valid": False,
                "reason": "INVALID_TARGET_GEOMETRY",
                "net_rr": None,
            }
            continue

        target_checks[name] = {
            "valid": rr["net_rr"] >= minimums[name],
            "reason": (
                "VALID"
                if rr["net_rr"] >= minimums[name]
                else "NET_RR_BELOW_MINIMUM"
            ),
            "minimum_net_rr": minimums[name],
            **rr,
        }

    t1_valid = target_checks["t1"]["valid"]
    t2_valid = target_checks["t2"]["valid"]
    t3_valid = target_checks["t3"]["valid"]

    if not t1_valid:
        return {
            "valid": False,
            "reason": "T1_NET_RR_FAILED",
            "target_checks": target_checks,
        }

    if position_size is not None and not position_size.get("valid", False):
        return {
            "valid": False,
            "reason": "POSITION_SIZE_INVALID",
            "target_checks": target_checks,
        }

    if (
        position_size is not None
        and not position_size.get("estimated_loss_within_budget", False)
    ):
        return {
            "valid": False,
            "reason": "RISK_BUDGET_EXCEEDED",
            "target_checks": target_checks,
        }

    return {
        "valid": True,
        "reason": "VALID",
        "target_checks": target_checks,
        "t1_valid": t1_valid,
        "t2_valid": t2_valid,
        "t3_valid": t3_valid,
        "capital_usdt": _positive(capital_usdt),
    }


# ============================================================
# COMPLETE RISK PLAN
# ============================================================

def build_risk_plan(
    entry_price: float,
    atr: float,
    capital_usdt: float,
    support: Optional[float] = None,
    resistances: Optional[Iterable[Any]] = None,
    supports: Optional[Iterable[Any]] = None,
    direction: str = "BUY",
    risk_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    entry_fee_pct: Optional[float] = None,
    exit_fee_pct: Optional[float] = None,
    slippage_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build complete Spot BUY risk plan.

    If T1 does not meet minimum net R:R, plan is invalid.
    T2/T3 may be unavailable or fail their individual thresholds;
    those targets are marked accordingly.
    """
    direction = direction.upper()

    if direction != "BUY":
        return {
            "valid": False,
            "reason": "SPOT_SCANNER_BUY_ONLY",
            "direction": direction,
        }

    entry = _valid_price(entry_price)
    atr_value = _positive(atr)

    if entry is None or atr_value <= 0:
        return {
            "valid": False,
            "reason": "INVALID_ENTRY_OR_ATR",
        }

    stop = calculate_stop_loss(
        entry_price=entry,
        atr=atr_value,
        support=support,
        direction="BUY",
    )

    if stop is None:
        return {
            "valid": False,
            "reason": "STOP_LOSS_CALCULATION_FAILED",
        }

    targets = calculate_targets(
        entry_price=entry,
        stop_loss=stop,
        atr=atr_value,
        resistances=resistances,
        supports=supports,
        direction="BUY",
    )

    # Apply explicit costs consistently to sizing and validation.
    costs = calculate_execution_cost_pct(
        entry_fee_pct,
        exit_fee_pct,
        slippage_pct,
    )

    # Calculate position sizing using the same execution cost.
    settings = _risk_settings()

    entry_fee = (
        settings["entry_fee_pct"]
        if entry_fee_pct is None
        else _positive(entry_fee_pct)
    )
    exit_fee = (
        settings["exit_fee_pct"]
        if exit_fee_pct is None
        else _positive(exit_fee_pct)
    )
    slip = (
        settings["slippage_pct"]
        if slippage_pct is None
        else _positive(slippage_pct)
    )

    position = calculate_position_size(
        capital_usdt=capital_usdt,
        entry_price=entry,
        stop_loss=stop,
        risk_pct=risk_pct,
        max_position_pct=max_position_pct,
        entry_fee_pct=entry_fee,
        exit_fee_pct=exit_fee,
        slippage_pct=slip,
    )

    validation = validate_risk(
        entry_price=entry,
        stop_loss=stop,
        targets=targets,
        capital_usdt=capital_usdt,
        position_size=position,
    )

    target_net_returns = {}

    for name in ("t1", "t2", "t3"):
        target = targets.get(name)

        target_net_returns[name] = (
            estimate_net_return_pct(
                entry_price=entry,
                exit_price=target,
                direction="BUY",
                entry_fee_pct=entry_fee,
                exit_fee_pct=exit_fee,
                slippage_pct=slip,
            )
            if target is not None
            else None
        )

    return {
        "valid": validation["valid"],
        "reason": validation["reason"],
        "direction": "BUY",
        "spot_only": True,
        "formula_version": "4.0",
        "entry": entry,
        "stop_loss": stop,
        "targets": targets,
        "target_net_returns_pct": target_net_returns,
        "atr": atr_value,
        "risk_distance_pct": ((entry - stop) / entry) * 100.0,
        "execution_cost_pct": costs,
        "position": position,
        "risk_validation": validation,
        "target_checks": validation.get("target_checks", {}),
    }


# ============================================================
# CONFIG SNAPSHOT
# ============================================================

def get_risk_manager_config() -> Dict[str, Any]:
    settings = _risk_settings()

    return {
        **settings,
        "spot_only": True,
        "formula_version": "4.0",
        "code_version": "4.0.0",
    }


# ============================================================
# SELF-CHECK
# ============================================================

def self_check() -> bool:
    """Offline deterministic tests. No network calls."""

    entry = 100.0
    atr = 1.0
    capital = 1000.0

    stop = calculate_stop_loss(
        entry_price=entry,
        atr=atr,
    )

    assert stop is not None
    assert 0 < stop < entry

    targets = calculate_targets(
        entry_price=entry,
        stop_loss=stop,
        atr=atr,
        resistances=[103.0, 106.0, 110.0],
    )

    assert targets["t1"] is not None
    assert targets["t2"] is not None
    assert targets["t3"] is not None
    assert targets["t1"] < targets["t2"] < targets["t3"]

    rr = calculate_risk_reward(
        entry_price=entry,
        stop_loss=stop,
        target_price=targets["t1"],
    )

    assert rr is not None
    assert rr["net_rr"] >= 0

    position = calculate_position_size(
        capital_usdt=capital,
        entry_price=entry,
        stop_loss=stop,
    )

    assert position["valid"]
    assert position["quantity"] > 0
    assert position["position_value_usdt"] <= capital

    plan = build_risk_plan(
        entry_price=entry,
        atr=atr,
        capital_usdt=capital,
        resistances=[103.0, 106.0, 110.0],
    )

    assert plan["entry"] == entry
    assert plan["stop_loss"] < entry
    assert plan["position"]["valid"]

    # Invalid Spot BUY stop must fail.
    invalid_position = calculate_position_size(
        capital_usdt=capital,
        entry_price=entry,
        stop_loss=entry + 1,
    )
    assert not invalid_position["valid"]

    # Invalid target geometry must fail.
    invalid_rr = calculate_risk_reward(
        entry_price=entry,
        stop_loss=stop,
        target_price=stop - 1,
    )
    assert invalid_rr is None

    return True


if __name__ == "__main__":
    try:
        self_check()
        print("RISK MANAGER SELF-CHECK: PASS")
        print("ATR Stop Loss: ENABLED")
        print("Fee/Slippage Adjusted Net R:R: ENABLED")
        print("Risk-Based Spot Position Sizing: ENABLED")
        print("Spot Only: YES")
    except Exception as exc:
        print(f"RISK MANAGER SELF-CHECK: FAIL - {exc}")
        raise
