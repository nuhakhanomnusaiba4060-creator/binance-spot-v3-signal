
"""
Binance Spot V4.0 - Signal Performance Analytics
------------------------------------------------
- Binance Spot public API; no API key required.
- Closed 1-minute candles only.
- Entry/SL same-candle ambiguity is never guessed.
- Entry-before-fill invalidation is tracked separately.
- Targets and stop-loss are tracked conservatively.
- Original signal_history.json is never modified.
- Analytics output is written atomically.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

HISTORY_FILE = Path(
    os.getenv("SIGNAL_HISTORY_FILE", str(BASE_DIR / "signal_history.json"))
)

ANALYTICS_FILE = Path(
    os.getenv("SIGNAL_ANALYTICS_FILE", str(BASE_DIR / "signal_analytics.json"))
)

BACKUP_DIR = BASE_DIR / "analytics_backups"

API_URL = "https://data-api.binance.vision/api/v3/klines"

INTERVAL = "1m"
INTERVAL_MS = 60_000

MAX_TRACKING_HOURS = 48
RETENTION_DAYS = 7

REQUEST_TIMEOUT = 15
REQUEST_LIMIT = 1000

# Percent values, not decimal fractions.
ROUND_TRIP_FEE_PERCENT = float(
    os.getenv("ROUND_TRIP_FEE_PERCENT", "0.20")
)
ESTIMATED_SLIPPAGE_PERCENT = float(
    os.getenv("ESTIMATED_SLIPPAGE_PERCENT", "0.10")
)

ANALYTICS_VERSION = "4.0.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("signal_analytics")


# ============================================================
# GENERAL HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def parse_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            # Support Unix seconds and milliseconds.
            timestamp = float(value)

            if timestamp > 10_000_000_000:
                timestamp /= 1000

            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (ValueError, OverflowError, OSError):
            return None

    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except ValueError:
        return None


def number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        result = float(value)

        if result != result or result in (float("inf"), float("-inf")):
            return default

        return result

    except (TypeError, ValueError):
        return default


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Cannot read %s: %s", path.name, exc)
        return default


def atomic_save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )

    os.replace(temporary, path)


def extract_signals(history: Any) -> dict:
    """
    Supports:
      {"signals": {"id": {...}}}
      {"id": {...}}
      [{"id": "...", ...}]
    """

    if isinstance(history, dict):
        signals = history.get("signals")

        if isinstance(signals, dict):
            return signals

        if isinstance(signals, list):
            result = {}

            for index, item in enumerate(signals):
                if isinstance(item, dict):
                    signal_id = str(
                        item.get("signal_id")
                        or item.get("id")
                        or index
                    )
                    result[signal_id] = item

            return result

        # Direct dictionary of signal records.
        result = {}

        for key, value in history.items():
            if isinstance(value, dict):
                result[str(key)] = value

        return result

    if isinstance(history, list):
        result = {}

        for index, item in enumerate(history):
            if isinstance(item, dict):
                signal_id = str(
                    item.get("signal_id")
                    or item.get("id")
                    or index
                )
                result[signal_id] = item

        return result

    return {}


# ============================================================
# SIGNAL FIELD NORMALIZATION
# ============================================================

def get_price(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        for key in ("price", "target", "stop_loss", "value"):
            result = number(value.get(key))

            if result is not None:
                return result

        return None

    return number(value)


def get_entry(signal: dict) -> Optional[float]:
    for key in ("entry_price", "entry", "entryPrice"):
        value = get_price(signal.get(key))

        if value is not None:
            return value

    risk_plan = signal.get("risk_plan")

    if isinstance(risk_plan, dict):
        for key in ("entry_price", "entry"):
            value = get_price(risk_plan.get(key))

            if value is not None:
                return value

    return None


def get_stop(signal: dict) -> Optional[float]:
    for key in ("stop_loss", "sl", "stopLoss"):
        value = get_price(signal.get(key))

        if value is not None:
            return value

    risk_plan = signal.get("risk_plan")

    if isinstance(risk_plan, dict):
        value = get_price(risk_plan.get("stop_loss"))

        if value is not None:
            return value

    return None


def get_targets(signal: dict) -> dict:
    raw = signal.get("targets")

    if raw is None:
        raw = signal.get("take_profit")

    if raw is None:
        raw = signal.get("target_prices")

    result = {}

    if isinstance(raw, dict):
        aliases = {
            "t1": ("t1", "T1", "target1", "target_1"),
            "t2": ("t2", "T2", "target2", "target_2"),
            "t3": ("t3", "T3", "target3", "target_3"),
        }

        for normalized, keys in aliases.items():
            for key in keys:
                if key in raw:
                    price = get_price(raw[key])

                    if price is not None:
                        result[normalized] = price
                        break

    elif isinstance(raw, list):
        for index, value in enumerate(raw[:3], start=1):
            price = get_price(value)

            if price is not None:
                result[f"t{index}"] = price

    # Support separate target fields.
    for index in range(1, 4):
        key = f"target_{index}"

        if f"t{index}" not in result:
            price = get_price(signal.get(key))

            if price is not None:
                result[f"t{index}"] = price

    return result


def get_created_time(signal: dict) -> Optional[datetime]:
    for key in (
        "created_at",
        "timestamp",
        "signal_time",
        "created",
    ):
        parsed = parse_time(signal.get(key))

        if parsed is not None:
            return parsed

    return None


def get_expiry(signal: dict, created: datetime) -> datetime:
    for key in (
        "expires_at",
        "entry_expiry",
        "valid_until",
        "expiry_time",
    ):
        parsed = parse_time(signal.get(key))

        if parsed is not None:
            return parsed

    return created + timedelta(hours=MAX_TRACKING_HOURS)


# ============================================================
# BINANCE DATA
# ============================================================

def fetch_klines(
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> list:
    if not symbol or not symbol.endswith("USDT"):
        return []

    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": INTERVAL,
        "startTime": max(0, int(start_ms)),
        "endTime": max(0, int(end_ms)),
        "limit": REQUEST_LIMIT,
    })

    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": "Binance-Spot-V4-Analytics"},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not isinstance(payload, list):
            logger.warning("Unexpected kline response for %s", symbol)
            return []

        return payload

    except Exception as exc:
        logger.warning("Kline request failed for %s: %s", symbol, exc)
        return []


def normalize_candle(raw: list) -> Optional[dict]:
    try:
        if len(raw) < 7:
            return None

        return {
            "open_time": int(raw[0]),
            "open": float(raw[1]),
            "high": float(raw[2]),
            "low": float(raw[3]),
            "close": float(raw[4]),
            "close_time": int(raw[6]),
        }

    except (TypeError, ValueError, IndexError):
        return None


# ============================================================
# ANALYTICS RECORD
# ============================================================

def create_record(signal_id: str, signal: dict) -> Optional[dict]:
    created = get_created_time(signal)
    entry = get_entry(signal)
    stop = get_stop(signal)
    targets = get_targets(signal)

    symbol = str(
        signal.get("symbol")
        or signal.get("coin")
        or ""
    ).upper()

    if (
        created is None
        or entry is None
        or stop is None
        or entry <= 0
        or stop <= 0
        or not symbol.endswith("USDT")
    ):
        logger.warning("Invalid signal skipped: %s", signal_id)
        return None

    if stop >= entry:
        logger.warning("Invalid BUY stop-loss for %s", signal_id)
        return None

    valid_targets = {}

    previous = entry

    for key in ("t1", "t2", "t3"):
        target = targets.get(key)

        if target is None:
            continue

        if target <= previous:
            logger.warning(
                "Invalid target sequence in %s: %s",
                signal_id,
                key,
            )
            break

        valid_targets[key] = target
        previous = target

    if not valid_targets:
        logger.warning("No valid targets: %s", signal_id)
        return None

    expiry = get_expiry(signal, created)

    return {
        "signal_id": signal_id,
        "symbol": symbol,
        "strategy": signal.get("strategy", "UNKNOWN"),
        "timeframe": signal.get("timeframe", "UNKNOWN"),
        "score": number(signal.get("score"), 0),
        "created_at": to_iso(created),
        "entry_price": entry,
        "stop_loss": stop,
        "targets": valid_targets,
        "entry_expiry": to_iso(expiry),
        "entry_reached": False,
        "entry_reached_at": None,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,
        "outcome": "PENDING",
        "result": "PENDING",
        "exit_price": None,
        "exit_time": None,
        "return_pct": None,
        "net_return_pct": None,
        "last_checked_at": None,
        "data_error": None,
        "candles_checked": 0,
    }


# ============================================================
# RETURN CALCULATION
# ============================================================

def calculate_return(entry: float, exit_price: float) -> float:
    if entry <= 0:
        return 0.0

    gross_percent = ((exit_price - entry) / entry) * 100

    total_cost_percent = (
        ROUND_TRIP_FEE_PERCENT
        + ESTIMATED_SLIPPAGE_PERCENT
    )

    return gross_percent - total_cost_percent


def finish_signal(
    item: dict,
    outcome: str,
    exit_price: Optional[float],
    candle_time: datetime,
) -> None:
    item["outcome"] = outcome
    item["result"] = outcome
    item["exit_price"] = exit_price
    item["exit_time"] = to_iso(candle_time)

    if item.get("entry_reached") and exit_price is not None:
        entry = number(item.get("entry_price"), 0) or 0

        if entry > 0:
            gross = ((exit_price - entry) / entry) * 100

            item["return_pct"] = round(gross, 6)
            item["net_return_pct"] = round(
                calculate_return(entry, exit_price),
                6,
            )


# ============================================================
# CANDLE PROCESSING
# ============================================================

def process_candle(item: dict, candle: dict) -> bool:
    """
    Returns True when the signal reaches a terminal state.
    Returns False when more candles are required.
    """

    candle_time = datetime.fromtimestamp(
        candle["open_time"] / 1000,
        tz=timezone.utc,
    )

    high = candle["high"]
    low = candle["low"]

    entry = item["entry_price"]
    stop = item["stop_loss"]
    targets = item["targets"]

    expiry = parse_time(item.get("entry_expiry"))

    # --------------------------------------------------------
    # BEFORE ENTRY
    # --------------------------------------------------------

    if not item.get("entry_reached"):

        if expiry is not None and candle_time > expiry:
            return False

        entry_touched = high >= entry
        stop_touched = low <= stop

        # Entry and Stop Loss both touched in the same candle:
        # order of events cannot be known.
        if entry_touched and stop_touched:
            item["outcome"] = "AMBIGUOUS"
            item["result"] = "AMBIGUOUS"
            item["data_error"] = (
                "ENTRY_AND_STOP_TOUCHED_IN_SAME_CANDLE"
            )
            item["ambiguous_at"] = to_iso(candle_time)
            return True

        # Price reached the invalidation level before entry.
        if stop_touched and not entry_touched:
            item["outcome"] = "INVALIDATED_BEFORE_ENTRY"
            item["result"] = "INVALIDATED_BEFORE_ENTRY"
            item["exit_price"] = stop
            item["exit_time"] = to_iso(candle_time)
            item["stop_loss_hit"] = False
            return True

        if not entry_touched:
            return False

        item["entry_reached"] = True
        item["entry_reached_at"] = to_iso(candle_time)

        # Do not count targets or stop-loss from the entry candle.
        # Their order inside the same candle cannot be established.
        return False

    # --------------------------------------------------------
    # AFTER ENTRY
    # --------------------------------------------------------

    stop_touched = low <= stop

    touched_targets = []

    for key in ("t1", "t2", "t3"):
        target = targets.get(key)

        if target is not None and high >= target:
            if not item.get(f"{key}_hit"):
                touched_targets.append(key)

    # If SL and any new target are touched in one candle,
    # the sequence is unknowable. Use conservative SL-first.
    if stop_touched:
        item["stop_loss_hit"] = True

        if touched_targets:
            item["data_error"] = (
                "STOP_AND_TARGET_TOUCHED_IN_SAME_CANDLE"
            )

        previous_targets = [
            key
            for key in ("t1", "t2", "t3")
            if item.get(f"{key}_hit")
        ]

        if "t3" in previous_targets:
            outcome = "T3"

        elif "t2" in previous_targets:
            outcome = "T2_THEN_STOP"

        elif "t1" in previous_targets:
            outcome = "T1_THEN_STOP"

        else:
            outcome = "STOP_LOSS"

        finish_signal(
            item,
            outcome,
            stop,
            candle_time,
        )
        return True

    # No stop touched: count targets in ascending order.
    for key in ("t1", "t2", "t3"):
        target = targets.get(key)

        if target is None:
            continue

        if high >= target:
            item[f"{key}_hit"] = True
            item[f"{key}_hit_at"] = to_iso(candle_time)

            if key == "t3":
                finish_signal(
                    item,
                    "T3",
                    target,
                    candle_time,
                )
                return True

    return False


# ============================================================
# SIGNAL UPDATE
# ============================================================

def update_signal(
    item: dict,
    now: datetime,
) -> bool:
    if item.get("outcome") not in (
        None,
        "",
        "PENDING",
        "ENTRY_REACHED",
    ):
        return False

    created = parse_time(item.get("created_at"))

    if created is None:
        item["outcome"] = "DATA_ERROR"
        item["result"] = "DATA_ERROR"
        item["data_error"] = "INVALID_CREATED_AT"
        return True

    expiry = parse_time(item.get("entry_expiry"))

    if expiry is None:
        expiry = created + timedelta(hours=MAX_TRACKING_HOURS)

    # Do not request data beyond the signal's tracking window.
    tracking_end = min(
        now,
        expiry + timedelta(hours=MAX_TRACKING_HOURS),
    )

    if tracking_end <= created:
        return False

    last_checked = parse_time(item.get("last_checked_at"))

    if last_checked is None:
        start_ms = int(created.timestamp() * 1000)
    else:
        start_ms = int(last_checked.timestamp() * 1000) + 1

    end_ms = int(tracking_end.timestamp() * 1000)

    if end_ms <= start_ms:
        return False

    raw_candles = fetch_klines(
        item["symbol"],
        start_ms,
        end_ms,
    )

    now_ms = int(now.timestamp() * 1000)

    if not raw_candles:
        return False

    for raw in raw_candles:
        candle = normalize_candle(raw)

        if candle is None:
            continue

        close_ms = candle["close_time"]

        # Only fully closed candles are allowed.
        if close_ms >= now_ms:
            continue

        # Never process candles after the tracking deadline.
        if close_ms > end_ms:
            continue

        candle_time = datetime.fromtimestamp(
            candle["open_time"] / 1000,
            tz=timezone.utc,
        )

        item["candles_checked"] = (
            int(item.get("candles_checked", 0)) + 1
        )

        item["last_checked_at"] = to_iso(
            datetime.fromtimestamp(
                close_ms / 1000,
                tz=timezone.utc,
            )
        )

        terminal = process_candle(item, candle)

        if terminal:
            return True

    # --------------------------------------------------------
    # EXPIRY HANDLING
    # --------------------------------------------------------

    if now > expiry and not item.get("entry_reached"):
        item["outcome"] = "ENTRY_WINDOW_EXPIRED"
        item["result"] = "ENTRY_WINDOW_EXPIRED"
        item["exit_time"] = to_iso(expiry)
        return True

    max_tracking_end = expiry + timedelta(
        hours=MAX_TRACKING_HOURS
    )

    if now > max_tracking_end and item.get("entry_reached"):
        item["outcome"] = "EXPIRED_AFTER_ENTRY"
        item["result"] = "EXPIRED_AFTER_ENTRY"
        item["exit_time"] = to_iso(max_tracking_end)

        # No fabricated exit price or return.
        item["exit_price"] = None
        item["return_pct"] = None
        item["net_return_pct"] = None
        return True

    return False


# ============================================================
# SUMMARY
# ============================================================

def build_summary(signals: dict) -> dict:
    summary = {
        "total": len(signals),
        "pending": 0,
        "entry_reached": 0,
        "entry_window_expired": 0,
        "invalidated_before_entry": 0,
        "ambiguous": 0,
        "stop_loss": 0,
        "t1_hit": 0,
        "t2_hit": 0,
        "t3_hit": 0,
        "completed": 0,
        "net_positive": 0,
        "net_negative": 0,
        "average_net_return_pct": None,
    }

    returns = []

    completed_outcomes = {
        "STOP_LOSS",
        "T1_THEN_STOP",
        "T2_THEN_STOP",
        "T3",
    }

    for item in signals.values():
        outcome = item.get("outcome", "PENDING")

        if outcome in ("PENDING", "ENTRY_REACHED", None):
            summary["pending"] += 1

        if item.get("entry_reached"):
            summary["entry_reached"] += 1

        if outcome == "ENTRY_WINDOW_EXPIRED":
            summary["entry_window_expired"] += 1

        if outcome == "INVALIDATED_BEFORE_ENTRY":
            summary["invalidated_before_entry"] += 1

        if outcome == "AMBIGUOUS":
            summary["ambiguous"] += 1

        if item.get("stop_loss_hit"):
            summary["stop_loss"] += 1

        for key in ("t1", "t2", "t3"):
            if item.get(f"{key}_hit"):
                summary[f"{key}_hit"] += 1

        if outcome in completed_outcomes:
            summary["completed"] += 1

            result = number(item.get("net_return_pct"))

            if result is not None:
                returns.append(result)

                if result > 0:
                    summary["net_positive"] += 1
                elif result < 0:
                    summary["net_negative"] += 1

    if returns:
        summary["average_net_return_pct"] = round(
            sum(returns) / len(returns),
            6,
        )

    return summary


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    now = utc_now()

    history = load_json(HISTORY_FILE, {})
    source_signals = extract_signals(history)

    previous = load_json(ANALYTICS_FILE, {})
    previous_signals = previous.get("signals", {})

    if not isinstance(previous_signals, dict):
        previous_signals = {}

    analytics_signals = {}

    for signal_id, source in source_signals.items():
        if not isinstance(source, dict):
            continue

        existing = previous_signals.get(signal_id)

        if isinstance(existing, dict):
            item = existing
        else:
            item = create_record(signal_id, source)

        if item is None:
            continue

        try:
            update_signal(item, now)

        except Exception as exc:
            logger.exception(
                "Signal analytics failed for %s: %s",
                signal_id,
                exc,
            )

            item["data_error"] = (
                f"ANALYTICS_PROCESSING_ERROR: {type(exc).__name__}"
            )

        analytics_signals[signal_id] = item

    # Retain recent records, plus unresolved records.
    cutoff = now - timedelta(days=RETENTION_DAYS)

    retained = {}

    for signal_id, item in analytics_signals.items():
        created = parse_time(item.get("created_at"))
        outcome = item.get("outcome", "PENDING")

        unresolved = outcome in (
            "PENDING",
            "ENTRY_REACHED",
        )

        if unresolved or created is None or created >= cutoff:
            retained[signal_id] = item

    output = {
        "version": ANALYTICS_VERSION,
        "updated_at": to_iso(now),
        "accounting_type": "ESTIMATED_NET_RETURN",
        "round_trip_fee_pct": ROUND_TRIP_FEE_PERCENT,
        "estimated_slippage_pct": ESTIMATED_SLIPPAGE_PERCENT,
        "signals": retained,
        "summary": build_summary(retained),
    }

    atomic_save(ANALYTICS_FILE, output)

    logger.info(
        "Analytics updated | total=%s | pending=%s | completed=%s",
        output["summary"]["total"],
        output["summary"]["pending"],
        output["summary"]["completed"],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
