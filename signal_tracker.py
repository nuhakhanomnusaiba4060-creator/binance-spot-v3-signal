"""
Binance Spot V3 Smart Signal Scanner
Signal Tracking and History Engine

Responsibilities:
- Register approved signals.
- Prevent duplicate signals during cooldown.
- Track active signals for up to 48 hours.
- Detect T1, T2, T3 and Stop Loss hits.
- Expire old signals.
- Track entry window expiration (Scalp 15m / Swing 60m).
- Calculate basic signal performance.
- Persist history safely.

Spot market only.
"""

import json
import logging
import os

from pathlib import Path
from datetime import datetime, timezone, timedelta

from config import TRACKING_CONFIG


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CONFIGURATION
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
    value = _find_value(TRACKING_CONFIG, key)
    return default if value is None else value


HISTORY_FILE = Path(
    os.getenv("SIGNAL_HISTORY_FILE", "signal_history.json")
)

TRACK_HOURS = int(
    _setting("MAX_TRACK_HOURS", 48)
)

COOLDOWN_HOURS = int(
    _setting("COOLDOWN_HOURS", 6)
)

# 🔥 Entry window limits
SCALP_ENTRY_VALIDITY_MINUTES = int(
    _setting("SCALP_ENTRY_VALIDITY_MINUTES", 15)
)

SWING_ENTRY_VALIDITY_MINUTES = int(
    _setting("SWING_ENTRY_VALIDITY_MINUTES", 60)
)

HISTORY_VERSION = 1


# ---------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------

def _utc_now():
    return datetime.now(timezone.utc)


def _to_iso(value=None):
    if value is None:
        value = _utc_now()

    if isinstance(value, str):
        parsed = _parse_time(value)
        if parsed is None:
            raise ValueError("Invalid datetime string")
        value = parsed

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value):
    try:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------
# HISTORY STRUCTURE
# ---------------------------------------------------------

def _empty_history():
    return {
        "version": HISTORY_VERSION,
        "updated_at": _to_iso(),
        "signals": [],
    }


def load_history(file_path=None):
    path = Path(file_path) if file_path else HISTORY_FILE

    if not path.exists():
        return _empty_history()

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("History root must be a dictionary")
        if not isinstance(data.get("signals"), list):
            raise ValueError("History signals must be a list")

        data.setdefault("version", HISTORY_VERSION)
        data.setdefault("updated_at", _to_iso())

        return data

    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.error("Signal history could not be loaded: %s", str(exc))
        return _empty_history()


def save_history(history, file_path=None):
    path = Path(file_path) if file_path else HISTORY_FILE

    if not isinstance(history, dict):
        raise ValueError("History must be a dictionary")
    if not isinstance(history.get("signals"), list):
        raise ValueError("History signals must be a list")

    path.parent.mkdir(parents=True, exist_ok=True)

    history["version"] = HISTORY_VERSION
    history["updated_at"] = _to_iso()

    temporary_path = path.with_name(path.name + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(history, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, path)
        return True

    except OSError as exc:
        logger.error("Signal history save failed: %s", str(exc))
        try:
            if temporary_path.exists():
                temporary_path.unlink()
        except OSError:
            pass
        return False


# ---------------------------------------------------------
# SIGNAL HELPERS
# ---------------------------------------------------------

def _find_signal(history, signal_id):
    for signal in history.get("signals", []):
        if signal.get("signal_id") == signal_id:
            return signal
    return None


def _get_signal_id(signal):
    signal_id = signal.get("signal_id")
    if signal_id:
        return str(signal_id)

    created_at = signal.get("created_at") or _to_iso()
    return (
        f"{signal.get('symbol', 'UNKNOWN')}_"
        f"{signal.get('strategy', 'UNKNOWN')}_"
        f"{str(created_at).replace(':', '').replace('-', '')}"
    )


def _signal_is_active(signal):
    return signal.get("status") in (
        "ACTIVE",
        "TARGET_1_HIT",
        "TARGET_2_HIT",
    )


def _get_risk_plan(signal):
    risk_plan = signal.get("risk_plan")
    if not isinstance(risk_plan, dict):
        return None
    if risk_plan.get("status") != "VALID":
        return None
    return risk_plan


# ---------------------------------------------------------
# DUPLICATE PREVENTION
# ---------------------------------------------------------

def check_duplicate(symbol, strategy=None, current_time=None, history=None):
    if not symbol:
        return False

    current = _parse_time(current_time) if current_time else _utc_now()
    if current is None:
        return False

    data = history if isinstance(history, dict) else load_history()
    cutoff = current - timedelta(hours=COOLDOWN_HOURS)

    normalized_symbol = str(symbol).upper()
    normalized_strategy = str(strategy).upper() if strategy is not None else None

    for signal in data.get("signals", []):
        if str(signal.get("symbol", "")).upper() != normalized_symbol:
            continue

        if (
            normalized_strategy is not None
            and str(signal.get("strategy", "")).upper() != normalized_strategy
        ):
            continue

        created = _parse_time(signal.get("created_at"))
        if created is None:
            continue

        if created >= cutoff and _signal_is_active(signal):
            return True

    return False


# ---------------------------------------------------------
# REGISTER SIGNAL
# ---------------------------------------------------------

def register_signal(signal, file_path=None):
    if not isinstance(signal, dict):
        raise ValueError("Signal must be a dictionary")

    symbol = str(signal.get("symbol", "")).upper().strip()
    if not symbol.endswith("USDT"):
        raise ValueError("Only USDT symbols can be tracked")

    classification = str(
        signal.get("classification") or signal.get("signal") or ""
    ).upper()

    if classification not in ("STRONG BUY", "EXCELLENT BUY"):
        raise ValueError("Only approved BUY signals can be tracked")

    risk_plan = _get_risk_plan(signal)
    if risk_plan is None:
        raise ValueError("A valid risk plan is required")

    validation = risk_plan.get("validation", {})
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise ValueError("Risk validation failed")

    path = Path(file_path) if file_path else HISTORY_FILE
    history = load_history(path)

    strategy = str(signal.get("strategy", "UNKNOWN")).upper()

    if check_duplicate(symbol=symbol, strategy=strategy, history=history):
        return {"success": False, "reason": "DUPLICATE_COOLDOWN"}

    now = _utc_now()
    entry_price = _number(risk_plan.get("entry_price"))
    stop_data = risk_plan.get("stop_loss", {})
    targets = risk_plan.get("targets", {})

    if not isinstance(stop_data, dict):
        raise ValueError("Invalid Stop Loss data")
    if not isinstance(targets, dict):
        raise ValueError("Invalid target data")

    stop_loss = _number(stop_data.get("stop_loss"))
    if entry_price is None or stop_loss is None:
        raise ValueError("Missing entry or Stop Loss")
    if entry_price <= 0 or stop_loss <= 0:
        raise ValueError("Invalid entry or Stop Loss")
    if stop_loss >= entry_price:
        raise ValueError("Stop Loss must be below entry")

    target_values = {}
    for name in ("t1", "t2", "t3"):
        target = targets.get(name)
        target_values[name] = (
            _number(target.get("price")) if isinstance(target, dict) else None
        )

    created_at = _to_iso(now)
    
    # 🔥 Calculate entry expiry based on strategy
    entry_validity_minutes = (
        SCALP_ENTRY_VALIDITY_MINUTES
        if strategy == "SCALP"
        else SWING_ENTRY_VALIDITY_MINUTES
    )

    record = {
        "signal_id": _get_signal_id({**signal, "created_at": created_at}),
        "symbol": symbol,
        "strategy": strategy,
        "classification": classification,
        "score": signal.get("score"),
        "created_at": created_at,
        "expires_at": _to_iso(now + timedelta(hours=TRACK_HOURS)),
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "targets": target_values,
        "current_price": entry_price,
        "status": "ACTIVE",
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,
        "entry_reached": False,
        
        # 🔥 New Entry Tracking Fields
        "entry_expiry": _to_iso(now + timedelta(minutes=entry_validity_minutes)),
        "entry_window_expired": False,
        "entry_reached_at": None,
        
        "result": None,
        "closed_at": None,
        "last_updated": created_at,
    }

    history["signals"].append(record)

    if not save_history(history, path):
        return {"success": False, "reason": "HISTORY_SAVE_FAILED"}

    return {
        "success": True,
        "signal_id": record["signal_id"],
        "status": record["status"],
    }


# ---------------------------------------------------------
# SIGNAL STATUS UPDATE
# ---------------------------------------------------------

def update_signal_status(signal_id, current_price, file_path=None):
    price = _number(current_price)
    if price is None or price <= 0:
        return {"success": False, "reason": "INVALID_CURRENT_PRICE"}

    path = Path(file_path) if file_path else HISTORY_FILE
    history = load_history(path)
    signal = _find_signal(history, signal_id)

    if signal is None:
        return {"success": False, "reason": "SIGNAL_NOT_FOUND"}

    if not _signal_is_active(signal):
        return {
            "success": False,
            "reason": "SIGNAL_NOT_ACTIVE",
            "status": signal.get("status"),
        }

    now = _utc_now()
    expires_at = _parse_time(signal.get("expires_at"))

    # 1. Overall 48h tracking expiry
    if expires_at is not None and now >= expires_at:
        signal["status"] = "EXPIRED"
        signal["result"] = "EXPIRED"
        signal["closed_at"] = _to_iso(now)
        signal["last_updated"] = _to_iso(now)
        save_history(history, path)
        return {"success": True, "status": "EXPIRED"}

    entry = _number(signal.get("entry_price"))
    stop = _number(signal.get("stop_loss"))

    if entry is None or stop is None:
        return {"success": False, "reason": "INVALID_SIGNAL_PRICES"}

    signal["current_price"] = price
    signal["last_updated"] = _to_iso(now)

    # 2. Entry window logic (Only if entry not yet reached)
    if not signal.get("entry_reached"):
        entry_expiry = _parse_time(signal.get("entry_expiry"))

        # 🔥 Check if the entry window has expired
        if entry_expiry is not None and now >= entry_expiry:
            signal["status"] = "EXPIRED_BEFORE_ENTRY"
            signal["result"] = "ENTRY_WINDOW_EXPIRED"
            signal["entry_window_expired"] = True
            signal["closed_at"] = _to_iso(now)
            
            save_history(history, path)
            return {
                "success": True,
                "status": "EXPIRED_BEFORE_ENTRY",
                "entry_window_expired": True,
            }

        # If price reached entry
        if price >= entry:
            signal["entry_reached"] = True
            signal["entry_reached_at"] = _to_iso(now) # 🔥 Record time
        else:
            save_history(history, path)
            return {
                "success": True,
                "status": signal["status"],
                "entry_reached": False,
            }

    # 3. Stop Loss takes priority after entry
    if price <= stop:
        signal["stop_loss_hit"] = True
        signal["status"] = "STOP_LOSS_HIT"
        signal["result"] = "LOSS"
        signal["closed_at"] = _to_iso(now)

    else:
        targets = signal.get("targets", {})
        t1 = _number(targets.get("t1"))
        t2 = _number(targets.get("t2"))
        t3 = _number(targets.get("t3"))

        if t1 is not None and price >= t1:
            signal["t1_hit"] = True
        if t2 is not None and price >= t2:
            signal["t2_hit"] = True
        if t3 is not None and price >= t3:
            signal["t3_hit"] = True
            signal["status"] = "TARGET_3_HIT"
            signal["result"] = "TARGET_3"
            signal["closed_at"] = _to_iso(now)
        elif signal["t2_hit"]:
            signal["status"] = "TARGET_2_HIT"
        elif signal["t1_hit"]:
            signal["status"] = "TARGET_1_HIT"

    if not save_history(history, path):
        return {"success": False, "reason": "HISTORY_SAVE_FAILED"}

    return {
        "success": True,
        "status": signal["status"],
        "entry_reached": signal["entry_reached"],
        "t1_hit": signal["t1_hit"],
        "t2_hit": signal["t2_hit"],
        "t3_hit": signal["t3_hit"],
        "stop_loss_hit": signal["stop_loss_hit"],
    }


# ---------------------------------------------------------
# EXPIRE SIGNALS (Overall 48H & Entry Windows)
# ---------------------------------------------------------

def expire_old_signals(file_path=None, current_time=None):
    """
    Expire signals after the 48h tracking period.
    """
    path = Path(file_path) if file_path else HISTORY_FILE
    history = load_history(path)

    current = _parse_time(current_time) if current_time else _utc_now()
    if current is None:
        raise ValueError("Invalid current_time")

    expired_count = 0
    for signal in history.get("signals", []):
        if not _signal_is_active(signal):
            continue

        expires_at = _parse_time(signal.get("expires_at"))
        if expires_at is None or current < expires_at:
            continue

        if signal.get("entry_reached"):
            signal["status"] = "EXPIRED"
            signal["result"] = "EXPIRED_AFTER_ENTRY"
        else:
            signal["status"] = "EXPIRED_BEFORE_ENTRY"
            signal["result"] = "EXPIRED_BEFORE_ENTRY"

        signal["closed_at"] = _to_iso(current)
        signal["last_updated"] = _to_iso(current)
        expired_count += 1

    if expired_count:
        save_history(history, path)

    return {"success": True, "expired_count": expired_count}


def expire_unfilled_entries(file_path=None, current_time=None):
    """
    🔥 Expire signals whose entry window (15m/60m) closed without price reaching entry.
    This acts as a sweeper for unfilled signals.
    """
    path = Path(file_path) if file_path else HISTORY_FILE
    history = load_history(path)

    current = _parse_time(current_time) if current_time else _utc_now()
    if current is None:
        raise ValueError("Invalid current_time")

    expired_count = 0
    for signal in history.get("signals", []):
        if not _signal_is_active(signal):
            continue

        if signal.get("entry_reached"):
            continue

        entry_expiry = _parse_time(signal.get("entry_expiry"))
        if entry_expiry is None or current < entry_expiry:
            continue

        signal["status"] = "EXPIRED_BEFORE_ENTRY"
        signal["result"] = "ENTRY_WINDOW_EXPIRED"
        signal["entry_window_expired"] = True
        signal["closed_at"] = _to_iso(current)
        signal["last_updated"] = _to_iso(current)
        expired_count += 1

    if expired_count:
        save_history(history, path)

    return {"success": True, "expired_count": expired_count}


# ---------------------------------------------------------
# PERFORMANCE
# ---------------------------------------------------------

def calculate_performance(file_path=None):
    path = Path(file_path) if file_path else HISTORY_FILE
    history = load_history(path)
    signals = history.get("signals", [])
    total = len(signals)

    t1_hits = sum(bool(s.get("t1_hit")) for s in signals)
    t2_hits = sum(bool(s.get("t2_hit")) for s in signals)
    t3_hits = sum(bool(s.get("t3_hit")) for s in signals)
    stop_hits = sum(bool(s.get("stop_loss_hit")) for s in signals)
    
    expired_before_entry = sum(
        s.get("status") == "EXPIRED_BEFORE_ENTRY" for s in signals
    )
    
    # 🔥 Count entry window expirations separately
    entry_window_expiries = sum(
        bool(s.get("entry_window_expired")) for s in signals
    )

    active = sum(_signal_is_active(s) for s in signals)

    completed = sum(
        s.get("result") in ("LOSS", "TARGET_3", "EXPIRED_AFTER_ENTRY")
        for s in signals
    )

    win_rate = (
        (t3_hits / (t3_hits + stop_hits)) * 100
        if (t3_hits + stop_hits) > 0
        else None
    )

    return {
        "total_signals": total,
        "active_signals": active,
        "completed_signals": completed,
        "t1_hits": t1_hits,
        "t2_hits": t2_hits,
        "t3_hits": t3_hits,
        "stop_loss_hits": stop_hits,
        "expired_before_entry": expired_before_entry,
        "entry_window_expiries": entry_window_expiries, # 🔥 New stat
        "win_rate_t3_vs_stop_loss_pct": (
            round(win_rate, 2) if win_rate is not None else None
        ),
        "tracking_hours": TRACK_HOURS,
        "cooldown_hours": COOLDOWN_HOURS,
    }
