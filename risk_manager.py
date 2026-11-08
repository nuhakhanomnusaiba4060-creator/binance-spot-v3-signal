
"""
Binance Spot V3 Smart Signal Scanner
Risk Management Engine

Responsibilities:
- Calculate technical Stop Loss.
- Calculate structure-based T1, T2 and T3 targets.
- Calculate position size using maximum capital risk.
- Include estimated fees and slippage.
- Validate minimum Risk/Reward ratio.

Spot long positions only.
No Futures or Margin calculations.
"""

import logging
import math
from typing import Any

from config import RISK_CONFIG


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CONFIG HELPERS
# ---------------------------------------------------------

def _normalize_key(value):
    return str(value).lower().replace("_", "").replace("-", "").replace(" ", "")


def _find_value(data, target):
    if not isinstance(data, dict):
        return None

    target_key = _normalize_key(target)

    for key, value in data.items():
        if _normalize_key(key) == target_key:
            return value

    for value in data.values():
        if isinstance(value, dict):
            result = _find_value(value, target)
            if result is not None:
                return result

    return None


def _setting(key, default):
    value = _find_value(RISK_CONFIG, key)
    return default if value is None else value


MAX_RISK_PERCENT = float(
    _setting("MAX_RISK_PERCENT", 1.0)
)

MIN_RISK_REWARD = float(
    _setting("MIN_RISK_REWARD_RATIO", 2.0)
)

DEFAULT_ATR_MULTIPLIER = float(
    _setting("ATR_MULTIPLIER", 1.5)
)

DEFAULT_FEE_RATE = float(
    _setting("FEE_RATE", 0.001)
)

DEFAULT_SLIPPAGE_RATE = float(
    _setting("SLIPPAGE_RATE", 0.001)
)


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def _number(value, default=None):
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError):
        return default


def _positive(value, name):
    number = _number(value)

    if number is None or number <= 0:
        raise ValueError(f"{name} must be a positive number")

    return number


def _unique_sorted_levels(levels, entry_price):
    """
    Return unique resistance levels above entry price.
    """

    if levels is None:
        return []

    if not isinstance(levels, (list, tuple, set)):
        levels = [levels]

    result = []

    for level in levels:
        value = _number(level)

        if value is None or value <= entry_price:
            continue

        result.append(value)

    return sorted(set(result))


# ---------------------------------------------------------
# STOP LOSS
# ---------------------------------------------------------

def calculate_stop_loss(
    entry_price,
    support_level=None,
    atr=None,
    atr_multiplier=None,
):
    """
    Calculate a technical Stop Loss for a Spot long position.

    Method:
    - Use support and ATR when both are available.
    - Place SL below the lower of support and ATR-based level.
    - Use ATR only when support is unavailable.
    - Reject when neither valid support nor ATR is available.

    Returns:
        {
            "stop_loss": float,
            "method": str,
            "risk_distance": float,
            "risk_percent": float
        }
    """

    entry = _positive(entry_price, "entry_price")

    support = _number(support_level)
    atr_value = _number(atr)

    multiplier = (
        DEFAULT_ATR_MULTIPLIER
        if atr_multiplier is None
        else _positive(atr_multiplier, "atr_multiplier")
    )

    if support is not None and support <= 0:
        support = None

    if atr_value is not None and atr_value <= 0:
        atr_value = None

    if support is None and atr_value is None:
        raise ValueError(
            "Cannot calculate Stop Loss without valid support or ATR"
        )

    candidates = []

    if support is not None:
        candidates.append(support)

    if atr_value is not None:
        candidates.append(entry - (atr_value * multiplier))

    stop_loss = min(candidates)

    if stop_loss <= 0 or stop_loss >= entry:
        raise ValueError("Calculated Stop Loss is invalid")

    if support is not None and atr_value is not None:
        method = "SUPPORT_AND_ATR"
    elif support is not None:
        method = "SUPPORT"
    else:
        method = "ATR"

    risk_distance = entry - stop_loss

    return {
        "stop_loss": round(stop_loss, 12),
        "method": method,
        "risk_distance": round(risk_distance, 12),
        "risk_percent": round(
            (risk_distance / entry) * 100,
            4,
        ),
    }


# ---------------------------------------------------------
# TARGET CALCULATION
# ---------------------------------------------------------

def calculate_targets(
    entry_price,
    stop_loss,
    resistance_levels=None,
    min_risk_reward=None,
):
    """
    Calculate targets from resistance structure.

    T1:
        First resistance meeting minimum RR.

    T2:
        Next higher resistance.

    T3:
        Third higher resistance.

    No arbitrary percentage targets are generated.

    Returns None for unavailable targets.
    """

    entry = _positive(entry_price, "entry_price")
    stop = _positive(stop_loss, "stop_loss")

    minimum_rr = (
        MIN_RISK_REWARD
        if min_risk_reward is None
        else _positive(min_risk_reward, "min_risk_reward")
    )

    if stop >= entry:
        raise ValueError("Stop Loss must be below entry price")

    risk_distance = entry - stop

    minimum_t1 = entry + (risk_distance * minimum_rr)

    levels = _unique_sorted_levels(
        resistance_levels,
        entry,
    )

    valid_levels = [
        level for level in levels
        if level >= minimum_t1
    ]

    targets = []

    for level in valid_levels[:3]:
        reward = level - entry
        rr = reward / risk_distance

        targets.append({
            "price": round(level, 12),
            "reward_percent": round(
                (reward / entry) * 100,
                4,
            ),
            "risk_reward": round(rr, 2),
        })

    return {
        "entry_price": round(entry, 12),
        "stop_loss": round(stop, 12),
        "risk_distance": round(risk_distance, 12),
        "minimum_t1_price": round(minimum_t1, 12),
        "t1": targets[0] if len(targets) >= 1 else None,
        "t2": targets[1] if len(targets) >= 2 else None,
        "t3": targets[2] if len(targets) >= 3 else None,
        "targets_available": len(targets),
        "target_status": (
            "VALID"
            if targets
            else "NO_VALID_RESISTANCE_TARGET"
        ),
    }


# ---------------------------------------------------------
# POSITION SIZE
# ---------------------------------------------------------

def calculate_position_size(
    capital,
    entry,
    stop_loss,
    risk_percent=MAX_RISK_PERCENT,
    fee_rate=DEFAULT_FEE_RATE,
    slippage_rate=DEFAULT_SLIPPAGE_RATE,
):
    """
    Calculate Spot position size.

    capital:
        Total available USDT capital.

    risk_percent:
        Maximum permitted capital risk in percent.
        Example: 1.0 means 1%.

    fee_rate:
        Estimated fee rate per side.
        Example: 0.001 means 0.1%.

    slippage_rate:
        Estimated adverse slippage rate per side.

    Returns:
        Position quantity, USDT value, estimated loss and risk.
    """

    capital = _positive(capital, "capital")
    entry = _positive(entry, "entry")
    stop = _positive(stop_loss, "stop_loss")

    risk_pct = _positive(risk_percent, "risk_percent")

    fee = _number(fee_rate)
    slippage = _number(slippage_rate)

    if fee is None or fee < 0:
        raise ValueError("Invalid fee_rate")

    if slippage is None or slippage < 0:
        raise ValueError("Invalid slippage_rate")

    if stop >= entry:
        raise ValueError("Stop Loss must be below entry")

    if risk_pct > MAX_RISK_PERCENT:
        raise ValueError(
            f"Risk cannot exceed {MAX_RISK_PERCENT}%"
        )

    risk_budget = capital * (risk_pct / 100)

    # Estimated entry and exit execution costs.
    entry_cost_rate = fee + slippage
    exit_cost_rate = fee + slippage

    effective_entry = entry * (1 + entry_cost_rate)
    effective_exit = stop * (1 - exit_cost_rate)

    loss_per_unit = effective_entry - effective_exit

    if loss_per_unit <= 0:
        raise ValueError("Invalid effective loss per unit")

    quantity_by_risk = risk_budget / loss_per_unit

    # Spot purchase cannot exceed available capital.
    quantity_by_capital = capital / effective_entry

    quantity = min(
        quantity_by_risk,
        quantity_by_capital,
    )

    position_value = quantity * entry

    estimated_loss = quantity * loss_per_unit

    actual_risk_percent = (
        estimated_loss / capital
    ) * 100

    return {
        "capital_usdt": round(capital, 8),
        "risk_budget_usdt": round(risk_budget, 8),
        "risk_percent_requested": round(risk_pct, 4),
        "actual_estimated_loss_usdt": round(
            estimated_loss, 8
        ),
        "actual_risk_percent": round(
            actual_risk_percent, 4
        ),
        "quantity": round(quantity, 12),
        "position_value_usdt": round(
            position_value, 8
        ),
        "effective_entry_price": round(
            effective_entry, 12
        ),
        "effective_stop_price": round(
            effective_exit, 12
        ),
        "fee_rate_per_side": fee,
        "slippage_rate_per_side": slippage,
        "capital_limited": (
            quantity_by_capital < quantity_by_risk
        ),
        "status": "VALID",
    }


# ---------------------------------------------------------
# RISK VALIDATION
# ---------------------------------------------------------

def validate_risk(
    entry_price,
    stop_loss,
    targets,
    position_size=None,
    risk_percent=MAX_RISK_PERCENT,
    min_risk_reward=MIN_RISK_REWARD,
):
    """
    Validate:
    - Entry and Stop Loss.
    - Maximum risk percentage.
    - Minimum T1 Risk/Reward.
    - Position size, if provided.
    """

    errors = []

    entry = _number(entry_price)
    stop = _number(stop_loss)

    if entry is None or entry <= 0:
        errors.append("Invalid entry price")

    if stop is None or stop <= 0:
        errors.append("Invalid Stop Loss")

    if (
        entry is not None
        and stop is not None
        and stop >= entry
    ):
        errors.append("Stop Loss must be below entry")

    risk_pct = _number(risk_percent)

    if risk_pct is None or risk_pct <= 0:
        errors.append("Invalid risk percentage")
    elif risk_pct > MAX_RISK_PERCENT:
        errors.append("Risk exceeds maximum permitted level")

    minimum_rr = _number(min_risk_reward)

    if minimum_rr is None or minimum_rr < MIN_RISK_REWARD:
        errors.append("Minimum Risk/Reward is below policy")

    t1 = None

    if isinstance(targets, dict):
        t1 = targets.get("t1")

    if not isinstance(t1, dict):
        errors.append("Valid T1 target is unavailable")
    else:
        t1_price = _number(t1.get("price"))
        t1_rr = _number(t1.get("risk_reward"))

        if t1_price is None or t1_price <= entry:
            errors.append("Invalid T1 price")

        if t1_rr is None or t1_rr < minimum_rr:
            errors.append("T1 Risk/Reward is below minimum")

    if position_size is not None:
        if not isinstance(position_size, dict):
            errors.append("Invalid position size data")
        else:
            actual_risk = _number(
                position_size.get("actual_risk_percent")
            )

            if actual_risk is None:
                errors.append("Position risk data unavailable")
            elif actual_risk > MAX_RISK_PERCENT:
                errors.append("Calculated position risk exceeds limit")

            if position_size.get("status") != "VALID":
                errors.append("Position size is not valid")

    return {
        "valid": len(errors) == 0,
        "status": "VALID" if not errors else "REJECT",
        "errors": errors,
        "max_risk_percent": MAX_RISK_PERCENT,
        "minimum_risk_reward": MIN_RISK_REWARD,
    }


# ---------------------------------------------------------
# COMPLETE RISK PLAN
# ---------------------------------------------------------

def build_risk_plan(
    capital,
    entry_price,
    support_level=None,
    atr=None,
    resistance_levels=None,
    risk_percent=MAX_RISK_PERCENT,
    fee_rate=DEFAULT_FEE_RATE,
    slippage_rate=DEFAULT_SLIPPAGE_RATE,
):
    """
    Build a complete Spot risk plan.

    Returns a rejected plan if any mandatory risk rule fails.
    """

    try:
        stop_data = calculate_stop_loss(
            entry_price=entry_price,
            support_level=support_level,
            atr=atr,
        )

        stop_loss = stop_data["stop_loss"]

        targets = calculate_targets(
            entry_price=entry_price,
            stop_loss=stop_loss,
            resistance_levels=resistance_levels,
        )

        position = calculate_position_size(
            capital=capital,
            entry=entry_price,
            stop_loss=stop_loss,
            risk_percent=risk_percent,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
        )

        validation = validate_risk(
            entry_price=entry_price,
            stop_loss=stop_loss,
            targets=targets,
            position_size=position,
            risk_percent=risk_percent,
        )

        return {
            "status": (
                "VALID"
                if validation["valid"]
                else "REJECT"
            ),
            "entry_price": round(
                float(entry_price), 12
            ),
            "stop_loss": stop_data,
            "targets": targets,
            "position_size": position,
            "validation": validation,
        }

    except (ValueError, TypeError, ZeroDivisionError) as exc:
        logger.warning("Risk plan rejected: %s", exc)

        return {
            "status": "REJECT",
            "error": str(exc),
            "validation": {
                "valid": False,
                "status": "REJECT",
                "errors": [str(exc)],
            },
        }
