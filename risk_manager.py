
"""
Binance Spot V3 - Risk Management Engine
Balanced validation edition.

- Preserves existing public function names.
- Selects a practical Stop Loss using support and ATR.
- Requires minimum NET R:R for T1.
- Allows optional T2/T3 when T1 is valid.
- Includes estimated trading fees and slippage.
- Controls position risk and available capital.
- Uses consistent Stop Loss distance validation.
- Spot trading only.
"""

import logging
import math

from config import RISK_CONFIG

logger = logging.getLogger(__name__)


# =========================================================
# CONFIG HELPERS
# =========================================================

def _num(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _norm(key):
    return (
        str(key)
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def _find(data, key):
    if not isinstance(data, dict):
        return None

    wanted = _norm(key)

    for k, value in data.items():
        if _norm(k) == wanted:
            return value

    for value in data.values():
        if isinstance(value, dict):
            found = _find(value, key)
            if found is not None:
                return found

    return None


def _setting(key, default):
    value = _find(RISK_CONFIG, key)
    return default if value is None else value


def _cfg(key, default, minimum=None, maximum=None):
    value = _num(_setting(key, default))

    if value is None:
        raise ValueError(f"Invalid risk configuration: {key}")

    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")

    if maximum is not None and value > maximum:
        raise ValueError(f"{key} must be <= {maximum}")

    return value


def _positive(value, name):
    value = _num(value)

    if value is None or value <= 0:
        raise ValueError(
            f"{name} must be a positive finite number"
        )

    return value


MAX_RISK_PERCENT = _cfg(
    "MAX_RISK_PERCENT",
    _setting("MAX_RISK_PER_TRADE_PERCENT", 1.0),
    0.01,
    100.0,
)

MIN_RISK_REWARD = _cfg(
    "MIN_RISK_REWARD",
    1.5,
    0.5,
    10.0,
)

DEFAULT_ATR_MULTIPLIER = _cfg(
    "ATR_MULTIPLIER",
    1.5,
    0.1,
    10.0,
)

DEFAULT_FEE_RATE = _cfg(
    "FEE_RATE",
    0.001,
    0.0,
    0.1,
)

DEFAULT_SLIPPAGE_RATE = _cfg(
    "SLIPPAGE_RATE",
    0.001,
    0.0,
    0.1,
)

MAX_STOP_LOSS_DISTANCE_PERCENT = _cfg(
    "MAX_STOP_LOSS_DISTANCE_PERCENT",
    8.0,
    0.1,
    50.0,
)

MIN_STOP_LOSS_DISTANCE_PERCENT = _cfg(
    "MIN_STOP_LOSS_DISTANCE_PERCENT",
    0.3,
    0.0,
    20.0,
)

MIN_TARGET_SPACING_PERCENT = _cfg(
    "MIN_TARGET_SPACING_PERCENT",
    0.10,
    0.0,
    5.0,
)

INCLUDE_TRADING_FEES = bool(
    _setting("INCLUDE_TRADING_FEES", True)
)

INCLUDE_ESTIMATED_SLIPPAGE = bool(
    _setting("INCLUDE_ESTIMATED_SLIPPAGE", True)
)


# =========================================================
# COST CALCULATIONS
# =========================================================

def _cost_rates(fee_rate=None, slippage_rate=None):
    fee = (
        DEFAULT_FEE_RATE
        if fee_rate is None
        else _num(fee_rate)
    )

    slip = (
        DEFAULT_SLIPPAGE_RATE
        if slippage_rate is None
        else _num(slippage_rate)
    )

    if fee is None or not 0 <= fee <= 0.1:
        raise ValueError("Invalid fee_rate")

    if slip is None or not 0 <= slip <= 0.1:
        raise ValueError("Invalid slippage_rate")

    return (
        fee if INCLUDE_TRADING_FEES else 0.0,
        slip if INCLUDE_ESTIMATED_SLIPPAGE else 0.0,
    )


def _effective_prices(entry, exit_price, fee, slippage):
    cost = fee + slippage

    return (
        entry * (1.0 + cost),
        exit_price * (1.0 - cost),
    )


def _net_rr(entry, stop, target, fee, slippage):
    effective_entry, effective_stop = _effective_prices(
        entry, stop, fee, slippage
    )

    _, effective_target = _effective_prices(
        entry, target, fee, slippage
    )

    loss = effective_entry - effective_stop
    reward = effective_target - effective_entry

    if loss <= 0 or reward <= 0:
        return None

    return reward / loss


def _minimum_net_target_price(
    entry,
    stop,
    minimum_rr,
    fee,
    slippage,
):
    cost = fee + slippage

    effective_entry = entry * (1.0 + cost)
    effective_stop = stop * (1.0 - cost)

    net_loss = effective_entry - effective_stop
    exit_factor = 1.0 - cost

    if net_loss <= 0 or exit_factor <= 0:
        raise ValueError("Invalid net target calculation")

    required_reward = minimum_rr * net_loss

    return (
        effective_entry + required_reward
    ) / exit_factor


# =========================================================
# STOP LOSS
# =========================================================

def calculate_stop_loss(
    entry_price,
    support_level=None,
    atr=None,
    atr_multiplier=None,
    max_distance_percent=None,
    min_distance_percent=None,
):
    entry = _positive(entry_price, "entry_price")

    support = _num(support_level)
    atr_value = _num(atr)

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
        else _num(min_distance_percent)
    )

    if (
        min_dist is None
        or min_dist < 0
        or min_dist >= max_dist
    ):
        raise ValueError("Invalid Stop Loss distance bounds")

    if support is not None and support <= 0:
        support = None

    if atr_value is not None and atr_value <= 0:
        atr_value = None

    candidates = []

    # Structural support candidate.
    if support is not None and support < entry:
        candidates.append(("SUPPORT", support))

    # ATR candidates.
    if atr_value is not None:
        for mult in (
            multiplier,
            multiplier * 1.25,
            multiplier * 0.75,
        ):
            level = entry - atr_value * mult

            if 0 < level < entry:
                candidates.append(
                    (f"ATR_{mult:.2f}x", level)
                )

    valid = []

    for method, level in candidates:
        distance = (entry - level) / entry * 100.0

        if min_dist <= distance <= max_dist:
            valid.append({
                "method": method,
                "price": level,
                "distance": distance,
            })

    if not valid:
        raise ValueError(
            "No Stop Loss candidate fits configured distance limits"
        )

    # Prefer a technically meaningful support when it is not
    # excessively wider than the normal ATR-based stop.
    support_candidate = next(
        (
            item for item in valid
            if item["method"] == "SUPPORT"
        ),
        None,
    )

    atr_candidate = next(
        (
            item for item in valid
            if item["method"] == f"ATR_{multiplier:.2f}x"
        ),
        None,
    )

    if support_candidate and atr_candidate:
        atr_distance = atr_candidate["distance"]
        support_distance = support_candidate["distance"]

        # A support stop more than 2x the ATR stop is too wide.
        if support_distance <= atr_distance * 2.0:
            chosen = support_candidate
        else:
            chosen = atr_candidate

    elif support_candidate:
        chosen = support_candidate

    elif atr_candidate:
        chosen = atr_candidate

    else:
        # Select the closest valid ATR candidate.
        atr_candidates = [
            item for item in valid
            if item["method"].startswith("ATR_")
        ]

        if atr_candidates:
            chosen = min(
                atr_candidates,
                key=lambda item: item["distance"],
            )
        else:
            chosen = min(
                valid,
                key=lambda item: item["distance"],
            )

    level = chosen["price"]
    distance = chosen["distance"]

    return {
        "stop_loss": round(level, 12),
        "method": chosen["method"],
        "risk_distance": round(entry - level, 12),
        "risk_percent": round(distance, 4),
        "max_allowed_percent": round(max_dist, 4),
        "min_allowed_percent": round(min_dist, 4),
    }


# =========================================================
# TARGET HELPERS
# =========================================================

def _levels(values, entry):
    if values is None:
        return []

    if not isinstance(values, (list, tuple, set)):
        values = [values]

    output = []

    for item in values:
        level = _num(item)

        if level is not None and level > entry:
            output.append(level)

    return sorted(set(output))


def _target_item(
    entry,
    stop,
    price,
    source,
    fee,
    slip,
):
    gross_rr = (price - entry) / (entry - stop)
    net_rr = _net_rr(entry, stop, price, fee, slip)

    return {
        "price": round(price, 12),
        "reward_percent": round(
            (price - entry) / entry * 100.0,
            4,
        ),
        "risk_reward": round(gross_rr, 3),
        "net_risk_reward": (
            round(net_rr, 3)
            if net_rr is not None
            else None
        ),
        "source": source,
    }


# =========================================================
# TARGET CALCULATION
# =========================================================

def calculate_targets(
    entry_price,
    stop_loss,
    resistance_levels=None,
    min_risk_reward=None,
    atr=None,
    fee_rate=None,
    slippage_rate=None,
):
    entry = _positive(entry_price, "entry_price")
    stop = _positive(stop_loss, "stop_loss")

    if stop >= entry:
        raise ValueError(
            "Stop Loss must be below entry price"
        )

    minimum_rr = (
        MIN_RISK_REWARD
        if min_risk_reward is None
        else _positive(min_risk_reward, "min_risk_reward")
    )

    fee, slip = _cost_rates(fee_rate, slippage_rate)

    spacing = (
        entry * MIN_TARGET_SPACING_PERCENT / 100.0
    )

    selected = []
    sources = []

    def add(price, source):
        if len(selected) >= 3:
            return

        price = _num(price)

        if price is None or price <= entry:
            return

        if selected and price <= selected[-1]:
            return

        if selected and (price - selected[-1]) < spacing:
            return

        net_rr = _net_rr(
            entry, stop, price, fee, slip
        )

        # T1 must satisfy minimum NET R:R.
        # Later targets only need to be above the previous
        # target and maintain minimum target spacing.
        if not selected:
            if net_rr is None or (
                net_rr + 1e-9
            ) < minimum_rr:
                return

        elif net_rr is None:
            return

        selected.append(price)
        sources.append(source)

    # Resistance levels first.
    for level in _levels(resistance_levels, entry):
        add(level, "RESISTANCE")

        if len(selected) == 3:
            break

    # ATR-based fallback targets.
    atr_value = _num(atr)

    if atr_value is not None and atr_value > 0:
        for mult in (1.5, 2.25, 3.0, 4.0, 5.0):
            add(
                entry + atr_value * mult,
                f"ATR_{mult:g}x",
            )

            if len(selected) == 3:
                break

    # Fixed percentage fallback only when ATR is unavailable.
    if len(selected) < 3 and (
        atr_value is None or atr_value <= 0
    ):
        for pct in (2.0, 3.0, 4.5, 6.0, 8.0):
            add(
                entry * (1.0 + pct / 100.0),
                f"FIXED_{pct:g}%",
            )

            if len(selected) == 3:
                break

    items = [
        _target_item(
            entry,
            stop,
            price,
            source,
            fee,
            slip,
        )
        for price, source in zip(selected, sources)
    ]

    minimum_t1 = _minimum_net_target_price(
        entry,
        stop,
        minimum_rr,
        fee,
        slip,
    )

    return {
        "entry_price": round(entry, 12),
        "stop_loss": round(stop, 12),
        "risk_distance": round(entry - stop, 12),
        "minimum_t1_price": round(minimum_t1, 12),
        "t1": items[0] if len(items) > 0 else None,
        "t2": items[1] if len(items) > 1 else None,
        "t3": items[2] if len(items) > 2 else None,
        "targets_available": len(items),
        "target_status": (
            "VALID"
            if len(items) == 3
            else "PARTIAL"
            if items
            else "NO_VALID_TARGET"
        ),
    }


# =========================================================
# POSITION SIZE
# =========================================================

def calculate_position_size(
    capital,
    entry,
    stop_loss,
    risk_percent=MAX_RISK_PERCENT,
    fee_rate=None,
    slippage_rate=None,
):
    capital = _positive(capital, "capital")
    entry = _positive(entry, "entry")
    stop = _positive(stop_loss, "stop_loss")
    risk_pct = _positive(risk_percent, "risk_percent")

    if stop >= entry:
        raise ValueError(
            "Stop Loss must be below entry"
        )

    if risk_pct > MAX_RISK_PERCENT + 1e-9:
        raise ValueError(
            "Risk exceeds configured maximum"
        )

    fee, slip = _cost_rates(
        fee_rate,
        slippage_rate,
    )

    budget = capital * risk_pct / 100.0

    effective_entry, effective_stop = _effective_prices(
        entry,
        stop,
        fee,
        slip,
    )

    loss_per_unit = effective_entry - effective_stop

    if loss_per_unit <= 0:
        raise ValueError(
            "Invalid effective loss per unit"
        )

    qty_risk = budget / loss_per_unit
    qty_capital = capital / effective_entry

    qty = min(qty_risk, qty_capital)

    if not math.isfinite(qty) or qty <= 0:
        raise ValueError(
            "Calculated quantity is invalid"
        )

    loss = qty * loss_per_unit
    position_value = qty * entry
    entry_outlay = qty * effective_entry

    return {
        "capital_usdt": round(capital, 8),
        "risk_budget_usdt": round(budget, 8),
        "risk_percent_requested": round(risk_pct, 4),
        "actual_estimated_loss_usdt": round(loss, 8),
        "actual_risk_percent": round(
            loss / capital * 100.0,
            4,
        ),
        "quantity": round(qty, 12),
        "position_value_usdt": round(
            position_value, 8
        ),
        "total_entry_outlay_usdt": round(
            entry_outlay, 8
        ),
        "estimated_entry_cost_usdt": round(
            qty * entry * (fee + slip), 8
        ),
        "effective_entry_price": round(
            effective_entry, 12
        ),
        "effective_stop_price": round(
            effective_stop, 12
        ),
        "fee_rate_per_side": fee,
        "slippage_rate_per_side": slip,
        "capital_limited": qty_capital < qty_risk,
        "status": "VALID",
    }


# =========================================================
# RISK VALIDATION
# =========================================================

def validate_risk(
    entry_price,
    stop_loss,
    targets,
    position_size=None,
    risk_percent=MAX_RISK_PERCENT,
    min_risk_reward=MIN_RISK_REWARD,
    fee_rate=None,
    slippage_rate=None,
):
    errors = []

    entry = _num(entry_price)
    stop = _num(stop_loss)

    if entry is None or entry <= 0:
        errors.append("Invalid entry price")

    if stop is None or stop <= 0:
        errors.append("Invalid Stop Loss")

    if (
        entry is not None
        and stop is not None
        and stop >= entry
    ):
        errors.append(
            "Stop Loss must be below entry"
        )

    if (
        entry is not None
        and stop is not None
        and 0 < stop < entry
    ):
        distance_pct = (
            (entry - stop) / entry * 100.0
        )

        if (
            distance_pct
            > MAX_STOP_LOSS_DISTANCE_PERCENT + 1e-9
        ):
            errors.append(
                "Stop Loss exceeds maximum distance"
            )

        if (
            distance_pct
            < MIN_STOP_LOSS_DISTANCE_PERCENT - 1e-9
        ):
            errors.append(
                "Stop Loss is below minimum distance"
            )

    rp = _num(risk_percent)

    if (
        rp is None
        or rp <= 0
        or rp > MAX_RISK_PERCENT + 1e-9
    ):
        errors.append(
            "Risk percentage is invalid or exceeds limit"
        )

    min_rr = (
        MIN_RISK_REWARD
        if min_risk_reward is None
        else _num(min_risk_reward)
    )

    if min_rr is None or min_rr <= 0:
        errors.append(
            "Minimum Risk/Reward is invalid"
        )
        min_rr = MIN_RISK_REWARD

    elif min_rr + 1e-9 < MIN_RISK_REWARD:
        errors.append(
            "Minimum Risk/Reward is below configured policy"
        )

    fee, slip = _cost_rates(
        fee_rate,
        slippage_rate,
    )

    if (
        not isinstance(targets, dict)
        or not isinstance(targets.get("t1"), dict)
    ):
        errors.append(
            "Valid T1 target is unavailable"
        )

    else:
        previous = entry

        for key in ("t1", "t2", "t3"):
            item = targets.get(key)

            if item is None:
                continue

            if not isinstance(item, dict):
                errors.append(
                    f"Invalid {key.upper()} target structure"
                )
                continue

            price = _num(item.get("price"))

            if (
                price is None
                or entry is None
                or price <= entry
            ):
                errors.append(
                    f"Invalid {key.upper()} price"
                )
                continue

            if price <= previous:
                errors.append(
                    f"{key.upper()} must be above previous target"
                )
                continue

            previous = price

            if (
                key == "t1"
                and stop is not None
                and entry is not None
                and stop < entry
            ):
                rr = _net_rr(
                    entry,
                    stop,
                    price,
                    fee,
                    slip,
                )

                if (
                    rr is None
                    or rr + 1e-9 < min_rr
                ):
                    errors.append(
                        "T1 net R:R is below minimum"
                    )

    if position_size is not None:
        if not isinstance(position_size, dict):
            errors.append(
                "Invalid position size data"
            )

        else:
            qty = _num(
                position_size.get("quantity")
            )
            actual_risk = _num(
                position_size.get("actual_risk_percent")
            )
            loss = _num(
                position_size.get(
                    "actual_estimated_loss_usdt"
                )
            )
            budget = _num(
                position_size.get("risk_budget_usdt")
            )

            if qty is None or qty <= 0:
                errors.append(
                    "Invalid position quantity"
                )

            if (
                actual_risk is None
                or actual_risk > MAX_RISK_PERCENT + 1e-6
            ):
                errors.append(
                    "Position risk exceeds limit or is unavailable"
                )

            if (
                loss is None
                or budget is None
                or loss > budget + max(
                    1e-8,
                    budget * 1e-6,
                )
            ):
                errors.append(
                    "Estimated loss exceeds risk budget"
                )

    return {
        "valid": not errors,
        "status": "VALID" if not errors else "REJECT",
        "errors": errors,
        "max_risk_percent": MAX_RISK_PERCENT,
        "minimum_risk_reward": MIN_RISK_REWARD,
        "max_stop_loss_distance_percent": (
            MAX_STOP_LOSS_DISTANCE_PERCENT
        ),
        "min_stop_loss_distance_percent": (
            MIN_STOP_LOSS_DISTANCE_PERCENT
        ),
    }


# =========================================================
# COMPLETE RISK PLAN
# =========================================================

def build_risk_plan(
    capital,
    entry_price,
    support_level=None,
    atr=None,
    resistance_levels=None,
    risk_percent=MAX_RISK_PERCENT,
    fee_rate=None,
    slippage_rate=None,
):
    try:
        entry = _positive(
            entry_price,
            "entry_price",
        )

        stop_data = calculate_stop_loss(
            entry_price=entry,
            support_level=support_level,
            atr=atr,
        )

        stop = stop_data["stop_loss"]

        targets = calculate_targets(
            entry_price=entry,
            stop_loss=stop,
            resistance_levels=resistance_levels,
            atr=atr,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
        )

        position = calculate_position_size(
            capital=capital,
            entry=entry,
            stop_loss=stop,
            risk_percent=risk_percent,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
        )

        validation = validate_risk(
            entry_price=entry,
            stop_loss=stop,
            targets=targets,
            position_size=position,
            risk_percent=risk_percent,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
        )

        return {
            "status": (
                "VALID"
                if validation["valid"]
                else "REJECT"
            ),
            "entry_price": round(entry, 12),
            "stop_loss": stop_data,
            "targets": targets,
            "position_size": position,
            "validation": validation,
        }

    except (
        ValueError,
        TypeError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        logger.warning(
            "RISK PLAN REJECTED: %s",
            exc,
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
