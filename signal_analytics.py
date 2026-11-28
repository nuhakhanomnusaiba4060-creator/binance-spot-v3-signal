
"""
Binance Spot V3 - V4 Signal Performance Analytics

System Version: 4.0.0
Formula Version: 4.0
Python: 3.11+

Input:
    signal_history.json

Output:
    signal_analytics.json

Rules:
- Binance Spot USDT only.
- Closed 1-minute candles only.
- Entry touch is not a guaranteed exchange fill.
- Same-candle target and stop touch = AMBIGUOUS.
- Missing candle data = UNVERIFIED, never fabricated.
- History file is read-only.
- Analytics output uses atomic replacement.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import tempfile

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config as cfg
from data_provider import get_klines


# ============================================================
# FILES AND SETTINGS
# ============================================================

HISTORY_FILE = Path(
    getattr(
        cfg,
        "TRACKING_CONFIG",
        {},
    ).get(
        "history_file",
        "signal_history.json",
    )
)

ANALYTICS_FILE = Path(
    getattr(
        cfg,
        "TRACKING_CONFIG",
        {},
    ).get(
        "analytics_file",
        "signal_analytics.json",
    )
)

BACKUP_DIRECTORY = Path(
    getattr(
        cfg,
        "TRACKING_CONFIG",
        {},
    ).get(
        "backup_directory",
        "backups",
    )
)

ANALYTICS_CONFIG = getattr(
    cfg,
    "ANALYTICS_CONFIG",
    {},
)

TRACKING_CONFIG = getattr(
    cfg,
    "TRACKING_CONFIG",
    {},
)

EXECUTION_COST_CONFIG = getattr(
    cfg,
    "EXECUTION_COST_CONFIG",
    {},
)

RETENTION_DAYS = int(
    TRACKING_CONFIG.get(
        "retention_days",
        30,
    )
)

MAX_TRACKING_HOURS = int(
    TRACKING_CONFIG.get(
        "maximum_tracking_hours",
        48,
    )
)

CANDLE_INTERVAL = "1m"
CANDLE_LIMIT = 1000

CODE_VERSION = "4.0.0"
FORMULA_VERSION = "4.0"
ANALYTICS_VERSION = 5

ROUND_TRIP_FEE_PCT = float(
    EXECUTION_COST_CONFIG.get(
        "round_trip_fee_percent",
        0.20,
    )
)

ESTIMATED_SLIPPAGE_PCT = float(
    EXECUTION_COST_CONFIG.get(
        "estimated_slippage_percent",
        0.05,
    )
)

TOTAL_ESTIMATED_COST_PCT = (
    ROUND_TRIP_FEE_PCT
    + ESTIMATED_SLIPPAGE_PCT
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result.astimezone(timezone.utc)

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):
        return None


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)

        if not math.isfinite(result):
            return None

        return result

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def positive(value: Any) -> float | None:
    number = safe_float(value)

    if number is None or number <= 0:
        return None

    return number


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid JSON root in {path}"
        )

    return data


def is_usdt_symbol(symbol: str) -> bool:
    symbol = str(symbol or "").upper().strip()

    return (
        symbol.endswith("USDT")
        and len(symbol) > 4
    )


def safe_target_value(
    targets: dict,
    name: str,
) -> float | None:
    if not isinstance(targets, dict):
        return None

    value = targets.get(name)

    if isinstance(value, dict):
        value = value.get("price")

    return positive(value)


# ============================================================
# ATOMIC JSON WRITE
# ============================================================

def atomic_write_json(
    path: Path,
    data: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )

            file.flush()
            os.fsync(file.fileno())

        # Preserve the previous analytics snapshot.
        if path.exists():
            BACKUP_DIRECTORY.mkdir(
                parents=True,
                exist_ok=True,
            )

            backup_path = (
                BACKUP_DIRECTORY
                / (
                    path.stem
                    + "_previous"
                    + path.suffix
                )
            )

            shutil.copy2(
                path,
                backup_path,
            )

        os.replace(
            temporary_path,
            path,
        )

    except Exception:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()
            except OSError:
                pass

        raise


# ============================================================
# CANDLE DATA
# ============================================================

def fetch_closed_candles(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict]:
    """
    Fetch closed 1m candles in pages.

    Pagination is based on the previous candle open_time.
    """
    if not is_usdt_symbol(symbol):
        raise ValueError(
            "Only Binance Spot USDT symbols are supported."
        )

    start_ms = int(
        start_time.timestamp() * 1000
    )

    end_ms = int(
        end_time.timestamp() * 1000
    )

    if start_ms >= end_ms:
        return []

    candles = []
    cursor = start_ms

    while cursor < end_ms:
        frame = get_klines(
            symbol=symbol,
            interval=CANDLE_INTERVAL,
            limit=CANDLE_LIMIT,
            start_time=cursor,
            end_time=end_ms,
            closed_only=True,
            min_rows=1,
        )

        if frame is None or frame.empty:
            break

        if (
            "open_time" not in frame.columns
            or "high" not in frame.columns
            or "low" not in frame.columns
            or "close" not in frame.columns
        ):
            raise ValueError(
                "Invalid Binance 1m candle columns."
            )

        page_count = 0
        last_open_time = None

        for row in frame.itertuples(index=False):
            open_time = int(
                getattr(row, "open_time")
            )

            high = positive(
                getattr(row, "high")
            )

            low = positive(
                getattr(row, "low")
            )

            close = positive(
                getattr(row, "close")
            )

            close_time = getattr(
                row,
                "close_time",
                None,
            )

            if (
                high is None
                or low is None
                or close is None
                or high < low
            ):
                continue

            if open_time < start_ms:
                continue

            if open_time > end_ms:
                continue

            candles.append({
                "open_time": open_time,
                "close_time": (
                    int(close_time)
                    if close_time is not None
                    else open_time + 59999
                ),
                "high": high,
                "low": low,
                "close": close,
            })

            page_count += 1
            last_open_time = open_time

        if page_count == 0 or last_open_time is None:
            break

        next_cursor = last_open_time + 60_000

        if next_cursor <= cursor:
            raise RuntimeError(
                "Candle pagination did not advance."
            )

        cursor = next_cursor

        if page_count < CANDLE_LIMIT:
            break

    candles.sort(
        key=lambda item: item["open_time"]
    )

    # Remove duplicate candle timestamps.
    unique = {}
    for candle in candles:
        unique[candle["open_time"]] = candle

    return [
        unique[key]
        for key in sorted(unique)
    ]


# ============================================================
# RETURN CALCULATION
# ============================================================

def calculate_gross_return_pct(
    entry_price: float,
    exit_price: float,
) -> float:
    return (
        (exit_price / entry_price) - 1.0
    ) * 100.0


def calculate_net_return_pct(
    gross_return_pct: float,
) -> float:
    return (
        gross_return_pct
        - TOTAL_ESTIMATED_COST_PCT
    )


def build_terminal_result(
    record: dict,
    outcome: str,
    exit_price: float | None,
    exit_time: datetime | None,
) -> dict:
    entry = positive(
        record.get("entry_price")
    )

    result = {
        "outcome": outcome,
        "exit_price": exit_price,
        "exit_time": (
            to_iso(exit_time)
            if exit_time is not None
            else None
        ),
        "gross_return_pct": None,
        "return_pct": None,
        "completed": False,
    }

    if entry is None or exit_price is None:
        return result

    gross = calculate_gross_return_pct(
        entry,
        exit_price,
    )

    net = calculate_net_return_pct(gross)

    result.update({
        "gross_return_pct": round(gross, 6),
        "return_pct": round(net, 6),
        "completed": True,
    })

    return result


# ============================================================
# SIGNAL INITIALIZATION
# ============================================================

def initialize_signal_record(
    signal: dict,
    signal_id: str,
) -> dict:
    targets = signal.get("targets", {})

    if not isinstance(targets, dict):
        targets = {}

    return {
        "signal_id": str(signal_id),
        "symbol": str(
            signal.get("symbol", "")
        ).upper(),
        "strategy": str(
            signal.get("strategy", "UNKNOWN")
        ).upper(),
        "classification": signal.get(
            "classification",
            signal.get("signal", "UNKNOWN"),
        ),
        "score": signal.get("score"),
        "created_at": signal.get("created_at"),
        "entry_price": positive(
            signal.get("entry_price")
        ),
        "stop_loss": positive(
            signal.get("stop_loss")
        ),
        "targets": {
            "t1": safe_target_value(targets, "t1"),
            "t2": safe_target_value(targets, "t2"),
            "t3": safe_target_value(targets, "t3"),
        },
        "entry_expiry": signal.get("entry_expiry"),
        "expires_at": signal.get("expires_at"),
        "entry_reached": False,
        "entry_reached_at": None,
        "entry_expired": False,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,
        "outcome": "PENDING",
        "result": None,
        "exit_price": None,
        "exit_time": None,
        "gross_return_pct": None,
        "return_pct": None,
        "mfe_pct": None,
        "mae_pct": None,
        "last_checked_at": None,
        "last_candle_close": None,
        "data_error": None,
        "accounting_method": "CLOSED_1M_CANDLE",
    }


# ============================================================
# CANDLE PROCESSING
# ============================================================

def process_candle(
    item: dict,
    candle: dict,
) -> bool:
    """
    Process one closed 1m candle.

    Returns True when the signal reaches a terminal state.
    """
    entry = positive(item.get("entry_price"))
    stop = positive(item.get("stop_loss"))

    if entry is None or stop is None or stop >= entry:
        item["outcome"] = "AMBIGUOUS"
        item["data_error"] = "INVALID_ENTRY_OR_STOP"
        return True

    high = candle["high"]
    low = candle["low"]
    close = candle["close"]

    candle_time = datetime.fromtimestamp(
        candle["close_time"] / 1000,
        tz=timezone.utc,
    )

    expiry = parse_time(
        item.get("entry_expiry")
    )

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
            item["data_error"] = (
                "ENTRY_AND_STOP_TOUCHED_IN_SAME_CANDLE"
            )
            return True

        if stop_touched and not entry_touched:
            item["outcome"] = "INVALIDATED_BEFORE_ENTRY"
            item["result"] = "INVALIDATED_BEFORE_ENTRY"
            item["exit_price"] = stop
            item["exit_time"] = to_iso(candle_time)
            return True

        if not entry_touched:
            return False

        item["entry_reached"] = True
        item["entry_reached_at"] = to_iso(candle_time)

    # --------------------------------------------------------
    # AFTER ENTRY
    # --------------------------------------------------------

    targets = item.get("targets", {})

    t1 = positive(targets.get("t1"))
    t2 = positive(targets.get("t2"))
    t3 = positive(targets.get("t3"))

    touched = {
        "t1": t1 is not None and high >= t1,
        "t2": t2 is not None and high >= t2,
        "t3": t3 is not None and high >= t3,
    }

    stop_touched = low <= stop

    target_touched = any(touched.values())

    # Same candle touches both target and stop:
    # do not guess which one happened first.
    if stop_touched and target_touched:
        item["outcome"] = "AMBIGUOUS"
        item["data_error"] = (
            "TARGET_AND_STOP_TOUCHED_IN_SAME_CANDLE"
        )
        return True

    if touched["t1"]:
        item["t1_hit"] = True

    if touched["t2"]:
        item["t2_hit"] = True

    if touched["t3"]:
        item["t3_hit"] = True

    if stop_touched:
        item["stop_loss_hit"] = True

        if item["t2_hit"]:
            outcome = "T2_THEN_STOP"
        elif item["t1_hit"]:
            outcome = "T1_THEN_STOP"
        else:
            outcome = "STOP_LOSS"

        terminal = build_terminal_result(
            item,
            outcome,
            stop,
            candle_time,
        )

        item.update(terminal)
        item["result"] = outcome

        return True

    if touched["t3"]:
        terminal = build_terminal_result(
            item,
            "T3",
            t3,
            candle_time,
        )

        item.update(terminal)
        item["result"] = "T3"

        return True

    if touched["t2"]:
        item["outcome"] = "T2"
        item["result"] = "T2"

    elif touched["t1"]:
        item["outcome"] = "T1"
        item["result"] = "T1"

    item["current_price"] = close

    # MFE / MAE use observed candle extremes after entry.
    previous_high = positive(
        item.get("max_high_after_entry")
    )

    previous_low = positive(
        item.get("min_low_after_entry")
    )

    max_high = max(
        high,
        previous_high or high,
    )

    min_low = min(
        low,
        previous_low or low,
    )

    item["max_high_after_entry"] = max_high
    item["min_low_after_entry"] = min_low

    item["mfe_pct"] = round(
        ((max_high / entry) - 1.0) * 100.0,
        6,
    )

    item["mae_pct"] = round(
        ((min_low / entry) - 1.0) * 100.0,
        6,
    )

    return False


# ============================================================
# EXPIRY HANDLING
# ============================================================

def finalize_expiry(
    item: dict,
    now: datetime,
) -> None:
    entry_expiry = parse_time(
        item.get("entry_expiry")
    )

    signal_expiry = parse_time(
        item.get("expires_at")
    )

    if not item.get("entry_reached"):
        if (
            entry_expiry is not None
            and now >= entry_expiry
        ):
            item["entry_expired"] = True
            item["outcome"] = "ENTRY_WINDOW_EXPIRED"
            item["result"] = "ENTRY_WINDOW_EXPIRED"

        return

    if (
        signal_expiry is None
        or now < signal_expiry
    ):
        return

    current_price = positive(
        item.get("current_price")
    )

    if current_price is None:
        item["outcome"] = "EXPIRED_AFTER_ENTRY_UNVERIFIED"
        item["data_error"] = (
            "NO_VERIFIED_CLOSE_PRICE_AT_EXPIRY"
        )
        return

    terminal = build_terminal_result(
        item,
        "EXPIRED_AFTER_ENTRY",
        current_price,
        now,
    )

    item.update(terminal)
    item["result"] = "EXPIRED_AFTER_ENTRY"


# ============================================================
# SIGNAL ANALYSIS
# ============================================================

def analyze_signal(
    signal: dict,
    signal_id: str,
    previous: dict | None,
    now: datetime,
) -> dict:
    if previous and previous.get("outcome") in {
        "STOP_LOSS",
        "T1_THEN_STOP",
        "T2_THEN_STOP",
        "T3",
        "EXPIRED_AFTER_ENTRY",
        "INVALIDATED_BEFORE_ENTRY",
        "AMBIGUOUS",
        "ENTRY_WINDOW_EXPIRED",
    }:
        # Terminal records are immutable.
        return previous

    if previous:
        item = dict(previous)
    else:
        item = initialize_signal_record(
            signal,
            signal_id,
        )

    symbol = str(
        item.get("symbol", "")
    ).upper()

    created = parse_time(
        item.get("created_at")
    )

    if not is_usdt_symbol(symbol):
        item["outcome"] = "AMBIGUOUS"
        item["data_error"] = "INVALID_USDT_SYMBOL"
        return item

    if created is None:
        item["outcome"] = "AMBIGUOUS"
        item["data_error"] = "INVALID_CREATED_AT"
        return item

    if (
        positive(item.get("entry_price")) is None
        or positive(item.get("stop_loss")) is None
    ):
        item["outcome"] = "AMBIGUOUS"
        item["data_error"] = "INVALID_SIGNAL_PRICES"
        return item

    # --------------------------------------------------------
    # INCREMENTAL CURSOR
    # --------------------------------------------------------

    previous_cursor = parse_time(
        item.get("last_checked_at")
    )

    if previous_cursor is not None:
        start_time = previous_cursor + timedelta(
            milliseconds=1
        )
    else:
        start_time = created + timedelta(
            milliseconds=1
        )

        maximum_start = now - timedelta(
            hours=MAX_TRACKING_HOURS
        )

        # Do not fabricate a result when initial historical
        # candle data is outside the reliable tracking window.
        if start_time < maximum_start:
            item["outcome"] = (
                "EXPIRED_AFTER_ENTRY_UNVERIFIED"
                if item.get("entry_reached")
                else "ENTRY_WINDOW_UNVERIFIED"
            )

            item["data_error"] = (
                "INITIAL_CANDLE_HISTORY_EXCEEDS_TRACKING_WINDOW"
            )

            item["last_checked_at"] = to_iso(now)

            return item

    try:
        candles = fetch_closed_candles(
            symbol,
            start_time,
            now,
        )

    except Exception as exc:
        item["data_error"] = (
            f"CANDLE_FETCH_FAILED: {str(exc)[:180]}"
        )

        logger.warning(
            "Analytics candle fetch failed for %s: %s",
            symbol,
            exc,
        )

        # Keep the last verified state. Do not invent a result.
        return item

    terminal = False

    for candle in candles:
        terminal = process_candle(
            item,
            candle,
        )

        item["last_candle_close"] = (
            datetime.fromtimestamp(
                candle["close_time"] / 1000,
                tz=timezone.utc,
            ).isoformat()
        )

        item["last_checked_at"] = item[
            "last_candle_close"
        ]

        if terminal:
            break

    if candles:
        item["data_error"] = None

    finalize_expiry(
        item,
        now,
    )

    if (
        item.get("outcome")
        == "EXPIRED_AFTER_ENTRY_UNVERIFIED"
        and item.get("return_pct") is not None
    ):
        item["outcome"] = "EXPIRED_AFTER_ENTRY"

    return item


# ============================================================
# ANALYTICS BUILD
# ============================================================

def load_previous_analytics() -> dict:
    if not ANALYTICS_FILE.exists():
        return {}

    try:
        data = read_json(ANALYTICS_FILE)

        if not isinstance(data.get("signals"), dict):
            return {}

        return data

    except Exception as exc:
        logger.warning(
            "Previous analytics could not be loaded: %s",
            exc,
        )

        return {}


def build_analytics(
    history: dict,
    previous_analytics: dict | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or utc_now()

    previous_analytics = (
        previous_analytics
        if isinstance(previous_analytics, dict)
        else {}
    )

    previous_signals = previous_analytics.get(
        "signals",
        {},
    )

    if not isinstance(previous_signals, dict):
        previous_signals = {}

    history_signals = history.get(
        "signals",
        [],
    )

    if not isinstance(history_signals, list):
        raise ValueError(
            "signal_history.json signals must be a list."
        )

    retention_start = now - timedelta(
        days=RETENTION_DAYS
    )

    analytics_signals = {}

    for signal in history_signals:
        if not isinstance(signal, dict):
            continue

        signal_id = (
            signal.get("signal_id")
            or signal.get("id")
        )

        if not signal_id:
            logger.warning(
                "Signal without signal_id skipped."
            )
            continue

        created = parse_time(
            signal.get("created_at")
        )

        if created is None:
            logger.warning(
                "Signal %s has invalid created_at.",
                signal_id,
            )
            continue

        if created < retention_start:
            continue

        previous = previous_signals.get(
            str(signal_id)
        )

        if not isinstance(previous, dict):
            previous = None

        analyzed = analyze_signal(
            signal=signal,
            signal_id=str(signal_id),
            previous=previous,
            now=now,
        )

        analytics_signals[str(signal_id)] = analyzed

    return {
        "version": ANALYTICS_VERSION,
        "code_version": CODE_VERSION,
        "formula_version": FORMULA_VERSION,
        "updated_at": to_iso(now),
        "retention_days": RETENTION_DAYS,
        "tracking_hours": MAX_TRACKING_HOURS,
        "round_trip_fee_pct": ROUND_TRIP_FEE_PCT,
        "estimated_slippage_pct": ESTIMATED_SLIPPAGE_PCT,
        "total_estimated_cost_pct": TOTAL_ESTIMATED_COST_PCT,
        "accounting_type": "SIMULATED_CANDLE_BASED",
        "accounting_note": (
            "Closed Binance Spot 1m candles. Entry touch is not "
            "guaranteed exchange fill. Net return subtracts configured "
            "round-trip fee and estimated slippage. T1/T2 followed by "
            "Stop Loss uses conservative full-position Stop Loss exit "
            "because partial-exit quantities are not stored. Same-candle "
            "target and stop touches are marked AMBIGUOUS."
        ),
        "signals": analytics_signals,
    }


# ============================================================
# VALIDATION
# ============================================================

def validate_analytics(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("Analytics root must be a dictionary.")

    if data.get("version") != ANALYTICS_VERSION:
        raise ValueError("Invalid analytics version.")

    if parse_time(data.get("updated_at")) is None:
        raise ValueError("Invalid analytics updated_at.")

    signals = data.get("signals")

    if not isinstance(signals, dict):
        raise ValueError("Analytics signals must be a dictionary.")

    for signal_id, item in signals.items():
        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid analytics record: {signal_id}"
            )

        if item.get("signal_id") != signal_id:
            raise ValueError(
                f"Signal ID mismatch: {signal_id}"
            )

        outcome = item.get("outcome")

        allowed = {
            "PENDING",
            "T1",
            "T2",
            "T3",
            "STOP_LOSS",
            "T1_THEN_STOP",
            "T2_THEN_STOP",
            "EXPIRED_AFTER_ENTRY",
            "EXPIRED_AFTER_ENTRY_UNVERIFIED",
            "ENTRY_WINDOW_EXPIRED",
            "ENTRY_WINDOW_UNVERIFIED",
            "INVALIDATED_BEFORE_ENTRY",
            "AMBIGUOUS",
        }

        if outcome not in allowed:
            raise ValueError(
                f"Unknown outcome for {signal_id}: {outcome}"
            )

        return_pct = item.get("return_pct")

        if return_pct is not None:
            number = safe_float(return_pct)

            if number is None:
                raise ValueError(
                    f"Invalid return_pct for {signal_id}"
                )


# ============================================================
# MAIN
# ============================================================

def main() -> dict:
    if not ANALYTICS_CONFIG.get("enabled", True):
        logger.info("Analytics is disabled by configuration.")
        return {
            "success": True,
            "skipped": True,
        }

    logger.info(
        "Starting V4 Signal Analytics."
    )

    history = read_json(HISTORY_FILE)

    if not isinstance(
        history.get("signals"),
        list,
    ):
        raise ValueError(
            "Invalid signal_history.json structure."
        )

    previous = load_previous_analytics()

    analytics = build_analytics(
        history=history,
        previous_analytics=previous,
        now=utc_now(),
    )

    validate_analytics(analytics)

    atomic_write_json(
        ANALYTICS_FILE,
        analytics,
    )

    summary = {
        "success": True,
        "signals": len(analytics["signals"]),
        "updated_at": analytics["updated_at"],
        "analytics_file": str(ANALYTICS_FILE),
    }

    logger.info(
        "Analytics updated: %s",
        summary,
    )

    return summary


if __name__ == "__main__":
    try:
        result = main()
        logger.info(
            "FINAL ANALYTICS RESULT: %s",
            result,
        )

    except Exception as exc:
        logger.exception(
            "Signal analytics failed: %s",
            exc,
        )
        raise
