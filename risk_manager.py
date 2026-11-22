"""
Binance Spot V3 Smart Signal Scanner
Risk Management Engine

BALANCED MODE:
- Real R:R validation (minimum 2:1)
- Balanced SL bounds
- ATR + Fixed % fallback targets
- Diagnostic logging
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


# 🔥 BALANCED settings
MAX_RISK_PERCENT = float(_setting("MAX_RISK_PERCENT", 1.0))
MIN_RISK_REWARD = 2.0  # 🔥 Real R:R requirement
DEFAULT_ATR_MULTIPLIER = float(_setting("ATR_MULTIPLIER", 1.5))
DEFAULT_FEE_RATE = float(_setting("FEE_RATE", 0.001))
DEFAULT_SLIPPAGE_RATE = float(_setting("SLIPPAGE_RATE", 0.001))

MAX_STOP_LOSS_DISTANCE_PERCENT = 5.0  # 🔥 Balanced SL bound
MIN_STOP_LOSS_DISTANCE_PERCENT = 0.5  # 🔥 Balanced SL bound


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
    max_distance_percent=None,
    min_distance_percent=None,
):
    entry = _positive(entry_price, "entry_price")
    support = _number(support_level)
    atr_value = _number(atr)

    multiplier = (
        DEFAULT_ATR_MULTIPLIER
        if atr_multiplier is None
        else _positive(atr_multiplier, "atr_multiplier")
    )

    max_dist = (
        MAX_STOP_LOSS_DISTANCE_PERCENT
        if max_distance_percent is None
        else _positive(max_distance_percent, "max_distance_percent")
    )

    min_dist = (
        MIN_STOP_LOSS_DISTANCE_PERCENT
        if min_distance_percent is None
        else max(0.0, _number(min_distance_percent, 0.0))
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
    if support is not None and support < entry:
        candidates.append(("SUPPORT", support))

    if atr_value is not None:
        for atr_mult in (multiplier, multiplier * 0.75, multiplier * 1.25):
            atr_level = entry - (atr_value * atr_mult)
            if atr_level > 0 and atr_level < entry:
                candidates.append((f"ATR_{atr_mult:.1f}x", atr_level))

    if not candidates:
        raise ValueError("No valid Stop Loss candidate available")

    candidates.sort(key=lambda item: item[1])

    chosen_method = None
    chosen_sl = None
    rejection_notes = []

    for method, level in candidates:
        risk_pct = ((entry - level) / entry) * 100

        if risk_pct > max_dist:
            rejection_notes.append(
                f"{method} SL rejected: {risk_pct:.2f}% > {max_dist}%"
            )
            continue

        if risk_pct < min_dist:
            rejection_notes.append(
                f"{method} SL rejected: {risk_pct:.2f}% < {min_dist}%"
            )
            continue

        chosen_method = method
        chosen_sl = level
        break

    if chosen_sl is None:
        raise ValueError(
            "No Stop Loss fits distance bounds: "
            + " | ".join(rejection_notes)
        )

    risk_distance = entry - chosen_sl

    return {
        "stop_loss": round(chosen_sl, 12),
        "method": chosen_method,
        "risk_distance": round(risk_distance, 12),
        "risk_percent": round((risk_distance / entry) * 100, 4),
        "max_allowed_percent": round(max_dist, 4),
        "min_allowed_percent": round(min_dist, 4),
    }


# ---------------------------------------------------------
# TARGET CALCULATION
# ---------------------------------------------------------

def calculate_targets(
    entry_price,
    stop_loss,
    resistance_levels=None,
    min_risk_reward=None,
    atr=None,
):
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

    levels = _unique_sorted_levels(resistance_levels, entry)
    valid_levels = [level for level in levels if level >= minimum_t1]

    targets = []

    for level in valid_levels[:3]:
        reward = level - entry
        rr = reward / risk_distance
        targets.append({
            "price": round(level, 12),
            "reward_percent": round((reward / entry) * 100, 4),
            "risk_reward": round(rr, 2),
            "source": "RESISTANCE",
        })

    # ATR fallback (aggressive multipliers)
    if not targets:
        atr_value = _number(atr)
        if atr_value is not None and atr_value > 0:
            atr_multipliers = (3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
            for mult in atr_multipliers:
                level = entry + (atr_value * mult)
                if level < minimum_t1:
                    continue
                reward = level - entry
                rr = reward / risk_distance
                targets.append({
                    "price": round(level, 12),
                    "reward_percent": round((reward / entry) * 100, 4),
                    "risk_reward": round(rr, 2),
                    "source": f"ATR_{mult}x",
                })
                if len(targets) >= 3:
                    break

    # Fixed % fallback (last resort)
    if not targets:
        for pct in (2.5, 4.0, 6.0):
            level = entry * (1 + pct / 100)
            if level < minimum_t1:
                continue
            reward = level - entry
            rr = reward / risk_distance
            targets.append({
                "price": round(level, 12),
                "reward_percent": round(pct, 4),
                "risk_reward": round(rr, 2),
                "source": f"FIXED_{pct}%",
            })
            if len(targets) >= 3:
                break

    return {
        "entry_price": round(entry, 12),
        "stop_loss": round(stop, 12),
        "risk_distance": round(risk_distance, 12),
        "minimum_t1_price": round(minimum_t1, 12),
        "t1": targets[0] if len(targets) >= 1 else None,
        "t2": targets[1] if len(targets) >= 2 else None,
        "t3": targets[2] if len(targets) >= 3 else None,
        "targets_available": len(targets),
        "target_status": "VALID" if targets else "NO_VALID_RESISTANCE_TARGET",
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
        raise ValueError(f"Risk cannot exceed {MAX_RISK_PERCENT}%")

    risk_budget = capital * (risk_pct / 100)

    entry_cost_rate = fee + slippage
    exit_cost_rate = fee + slippage

    effective_entry = entry * (1 + entry_cost_rate)
    effective_exit = stop * (1 - exit_cost_rate)

    loss_per_unit = effective_entry - effective_exit

    if loss_per_unit <= 0:
        raise ValueError("Invalid effective loss per unit")

    quantity_by_risk = risk_budget / loss_per_unit
    quantity_by_capital = capital / effective_entry

    quantity = min(quantity_by_risk, quantity_by_capital)
    position_value = quantity * entry

    estimated_loss = quantity * loss_per_unit
    actual_risk_percent = (estimated_loss / capital) * 100

    return {
        "capital_usdt": round(capital, 8),
        "risk_budget_usdt": round(risk_budget, 8),
        "risk_percent_requested": round(risk_pct, 4),
        "actual_estimated_loss_usdt": round(estimated_loss, 8),
        "actual_risk_percent": round(actual_risk_percent, 4),
        "quantity": round(quantity, 12),
        "position_value_usdt": round(position_value, 8),
        "effective_entry_price": round(effective_entry, 12),
        "effective_stop_price": round(effective_exit, 12),
        "fee_rate_per_side": fee,
        "slippage_rate_per_side": slippage,
        "capital_limited": (quantity_by_capital < quantity_by_risk),
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
    errors = []

    entry = _number(entry_price)
    stop = _number(stop_loss)

    if entry is None or entry <= 0:
        errors.append("Invalid entry price")
    if stop is None or stop <= 0:
        errors.append("Invalid Stop Loss")
    if entry is not None and stop is not None and stop >= entry:
        errors.append("Stop Loss must be below entry")

    if entry is not None and entry > 0 and stop is not None and 0 < stop < entry:
        sl_distance_pct = ((entry - stop) / entry) * 100
        if sl_distance_pct > MAX_STOP_LOSS_DISTANCE_PERCENT:
            errors.append(
                f"Stop Loss too wide: {sl_distance_pct:.2f}% "
                f"> {MAX_STOP_LOSS_DISTANCE_PERCENT}%"
            )
        if sl_distance_pct < MIN_STOP_LOSS_DISTANCE_PERCENT:
            errors.append(
                f"Stop Loss too tight: {sl_distance_pct:.2f}% "
                f"< {MIN_STOP_LOSS_DISTANCE_PERCENT}%"
            )

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
            actual_risk = _number(position_size.get("actual_risk_percent"))
            if actual_risk is None:
                errors.append("Position risk data unavailable")
            elif actual_risk > MAX_RISK_PERCENT:
                errors.append("Calculated position risk exceeds limit")
            if position_size.get("status") != "VALID":
                errors.append("Position size is not valid")
            if position_size.get("quantity", 0) <= 0:
                errors.append("Position quantity is zero or negative")

    return {
        "valid": len(errors) == 0,
        "status": "VALID" if not errors else "REJECT",
        "errors": errors,
        "max_risk_percent": MAX_RISK_PERCENT,
        "minimum_risk_reward": MIN_RISK_REWARD,
        "max_stop_loss_distance_percent": MAX_STOP_LOSS_DISTANCE_PERCENT,
        "min_stop_loss_distance_percent": MIN_STOP_LOSS_DISTANCE_PERCENT,
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
    try:
        stop_data = calculate_stop_loss(
            entry_price=entry_price,
            support_level=support_level,
            atr=atr,
        )

        stop_loss = stop_data["stop_loss"]

        logger.info(
            "RISK DEBUG | entry=%.6f | SL=%.6f | method=%s | SL_pct=%.4f | support=%s | atr=%s",
            entry_price,
            stop_loss,
            stop_data.get("method"),
            stop_data.get("risk_percent", 0),
            support_level,
            atr,
        )

        targets = calculate_targets(
            entry_price=entry_price,
            stop_loss=stop_loss,
            resistance_levels=resistance_levels,
            atr=atr,
        )

        logger.info(
            "RISK DEBUG | t1=%s | t2=%s | t3=%s | targets_available=%d | resistance_levels=%s",
            targets.get("t1"),
            targets.get("t2"),
            targets.get("t3"),
            targets.get("targets_available", 0),
            resistance_levels,
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

        if not validation["valid"]:
            logger.warning(
                "RISK VALIDATION FAILED | entry=%.6f | errors=%s",
                entry_price,
                validation.get("errors", []),
            )

        return {
            "status": "VALID" if validation["valid"] else "REJECT",
            "entry_price": round(float(entry_price), 12),
            "stop_loss": stop_data,
            "targets": targets,
            "position_size": position,
            "validation": validation,
        }

    except (ValueError, TypeError, ZeroDivisionError) as exc:
        logger.warning(
            "RISK PLAN REJECTED | entry=%.6f | error=%s",
            entry_price if entry_price else 0,
            str(exc),
        )

        return {
            "status": "REJECT",
            "error": str(exc),
            "validation": {
                "valid": False,
                "status": "REJECT",
                "errors": [str(exc)],
            },
        }
