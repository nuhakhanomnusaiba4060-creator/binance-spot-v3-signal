
"""
Binance Spot V3 Smart Signal Scanner
Independent Signal Performance Analytics - Version 4

- Binance Spot USDT only.
- Reads signal_history.json; never modifies it.
- Uses closed 1-minute Binance candles.
- Rebuilds V3 analytics records using V4 rules.
- Reconciles old terminal outcomes during the V3 -> V4 upgrade.
- Same-candle SL/Target ambiguity is never guessed.
- Tracks T1_THEN_STOP and T2_THEN_STOP separately.
- Persists last closed candle data for accurate expiry accounting.
- Estimated fee-adjusted returns; not actual exchange PNL.
"""

import json
import math
import os
import sys
import tempfile
import time

from datetime import datetime, timedelta, timezone

import requests


# =========================================================
# CONFIGURATION
# =========================================================

HISTORY_FILE = "signal_history.json"
ANALYTICS_FILE = "signal_analytics.json"

API_URL = "https://data-api.binance.vision/api/v3/klines"

ANALYTICS_VERSION = 4
RETENTION_DAYS = 7

INTERVAL_MS = 60_000
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

ROUND_TRIP_FEE_PCT = float(
    os.getenv("V3_ROUND_TRIP_FEE_PCT", "0.20")
)

# Outcomes included in completed performance.
COMPLETED_OUTCOMES = {
    "STOP_LOSS",
    "T1_THEN_STOP",
    "T2_THEN_STOP",
    "T3",
    "EXPIRED_AFTER_ENTRY",
}

# Terminal records are not updated on every run.
# Version upgrade rebuilds old terminal records once.
TERMINAL_OUTCOMES = {
    "STOP_LOSS",
    "T1_THEN_STOP",
    "T2_THEN_STOP",
    "T3",
    "EXPIRED_AFTER_ENTRY",
    "ENTRY_WINDOW_EXPIRED",
    "INVALIDATED_BEFORE_ENTRY",
    "AMBIGUOUS",
}


# =========================================================
# GENERAL HELPERS
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def parse_time(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result.astimezone(timezone.utc)

    except (ValueError, TypeError, OverflowError):
        return None


def number(value):
    """Return a positive finite number or None."""

    try:
        result = float(value)

        if math.isfinite(result) and result > 0:
            return result

    except (TypeError, ValueError, OverflowError):
        pass

    return None


def signed_number(value):
    """Return a finite number including zero and negatives."""

    try:
        result = float(value)

        if math.isfinite(result):
            return result

    except (TypeError, ValueError, OverflowError):
        pass

    return None


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot safely read {path}: {exc}"
        ) from exc


def atomic_save(path, data):
    """Save JSON atomically to prevent partial output."""

    directory = os.path.dirname(
        os.path.abspath(path)
    )

    fd, temporary = tempfile.mkstemp(
        prefix="analytics_",
        suffix=".tmp",
        dir=directory,
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )

            file.write("\n")

        os.replace(temporary, path)

    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def next_full_minute(timestamp):
    """
    First eligible candle open time.

    If signal creation is exactly on a minute boundary,
    that candle may be included.
    Otherwise, the next minute is used.
    """

    milliseconds = int(
        timestamp.timestamp() * 1000
    )

    rounded = (
        (milliseconds + INTERVAL_MS - 1)
        // INTERVAL_MS
    ) * INTERVAL_MS

    return rounded


# =========================================================
# BINANCE DATA
# =========================================================

def fetch_klines(symbol, start_ms, end_ms):

    candles = []
    cursor = start_ms

    while cursor <= end_ms:

        params = {
            "symbol": symbol,
            "interval": "1m",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }

        batch = None

        for attempt in range(MAX_RETRIES):

            try:

                response = requests.get(
                    API_URL,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                if (
                    response.status_code == 429
                    or response.status_code >= 500
                ):

                    if attempt == MAX_RETRIES - 1:
                        response.raise_for_status()

                    retry_after = response.headers.get(
                        "Retry-After"
                    )

                    try:
                        delay = float(retry_after)
                    except (TypeError, ValueError):
                        delay = 2 ** attempt

                    time.sleep(
                        min(max(delay, 1), 30)
                    )

                    continue

                response.raise_for_status()

                batch = response.json()
                break

            except requests.RequestException:

                if attempt == MAX_RETRIES - 1:
                    raise

                time.sleep(2 ** attempt)

            except ValueError:

                if attempt == MAX_RETRIES - 1:
                    raise

                time.sleep(2 ** attempt)

        if not isinstance(batch, list):
            raise ValueError(
                "Invalid Binance candle response"
            )

        if not batch:
            break

        candles.extend(batch)

        last_open = int(batch[-1][0])
        next_cursor = last_open + INTERVAL_MS

        if next_cursor <= cursor:
            raise ValueError(
                "Binance candle pagination did not advance"
            )

        cursor = next_cursor

        if len(batch) < 1000:
            break

    return candles


# =========================================================
# SIGNAL RECORD
# =========================================================

def create_record(signal):

    targets = signal.get("targets") or {}

    return {
        "signal_id": str(signal["signal_id"]),
        "symbol": str(signal["symbol"]).upper(),
        "strategy": signal.get("strategy"),
        "classification": signal.get("classification"),
        "created_at": signal.get("created_at"),

        "entry_price": number(
            signal.get("entry_price")
        ),

        "stop_loss": number(
            signal.get("stop_loss")
        ),

        "targets": {
            "t1": number(targets.get("t1")),
            "t2": number(targets.get("t2")),
            "t3": number(targets.get("t3")),
        },

        "entry_reached": False,
        "entry_reached_at": None,

        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,

        "outcome": "PENDING",
        "entry_expired": False,

        "exit_price": None,
        "exit_at": None,

        "gross_return_pct": None,
        "return_pct": None,

        "fee_estimate_pct": ROUND_TRIP_FEE_PCT,

        # Candle progress.
        # last_checked_at stores the candle OPEN time.
        "last_checked_at": None,

        # Persisted so later runs do not lose the last
        # available closed candle price.
        "last_closed_candle_at": None,
        "last_closed_candle_close": None,

        "data_error": None,
    }


def validate_record(signal, record):

    symbol = str(
        signal.get("symbol", "")
    ).upper()

    if not symbol.endswith("USDT"):
        raise ValueError(
            "Only USDT Spot symbols are supported"
        )

    entry = number(
        record.get("entry_price")
    )

    stop = number(
        record.get("stop_loss")
    )

    targets = record.get("targets") or {}

    if entry is None or stop is None:
        raise ValueError(
            "Missing entry price or stop loss"
        )

    if stop >= entry:
        raise ValueError(
            "Stop loss must be below entry"
        )

    t1 = number(targets.get("t1"))
    t2 = number(targets.get("t2"))
    t3 = number(targets.get("t3"))

    if t1 is None:
        raise ValueError(
            "T1 target price is missing"
        )

    available_targets = [
        target
        for target in (t1, t2, t3)
        if target is not None
    ]

    previous = entry

    for target in available_targets:

        if target <= previous:
            raise ValueError(
                "Invalid target price sequence"
            )

        previous = target

    record["entry_price"] = entry
    record["stop_loss"] = stop

    record["targets"] = {
        "t1": t1,
        "t2": t2,
        "t3": t3,
    }

    created = parse_time(
        signal.get("created_at")
    )

    entry_expiry = parse_time(
        signal.get("entry_expiry")
    )

    signal_expiry = parse_time(
        signal.get("expires_at")
    )

    if (
        not created
        or not entry_expiry
        or not signal_expiry
    ):
        raise ValueError(
            "Invalid signal timestamps"
        )

    if entry_expiry > signal_expiry:
        raise ValueError(
            "Entry expiry is later than signal expiry"
        )

    if entry_expiry < created:
        raise ValueError(
            "Entry expiry is earlier than signal creation"
        )

    if signal_expiry <= created:
        raise ValueError(
            "Signal expiry is invalid"
        )

    return created, entry_expiry, signal_expiry


# =========================================================
# RETURN CALCULATION
# =========================================================

def calculate_return(record):

    entry = number(
        record.get("entry_price")
    )

    exit_price = number(
        record.get("exit_price")
    )

    fee = signed_number(
        record.get("fee_estimate_pct")
    )

    if fee is None:
        fee = ROUND_TRIP_FEE_PCT

    if entry is None or exit_price is None:

        record["gross_return_pct"] = None
        record["return_pct"] = None

        return

    gross_pct = (
        (exit_price - entry) / entry
    ) * 100

    net_pct = gross_pct - fee

    record["gross_return_pct"] = round(
        gross_pct,
        4,
    )

    record["return_pct"] = round(
        net_pct,
        4,
    )


def finish_signal(
    record,
    outcome,
    exit_price,
    exit_time,
):

    record["outcome"] = outcome

    record["exit_price"] = exit_price

    record["exit_at"] = iso(
        exit_time
    )

    calculate_return(record)


def mark_ambiguous(record, candle_close):

    record["outcome"] = "AMBIGUOUS"

    record["exit_price"] = None
    record["exit_at"] = iso(candle_close)

    record["gross_return_pct"] = None
    record["return_pct"] = None

    record["ambiguity_reason"] = (
        "The same closed 1m candle touched Stop Loss "
        "and at least one Target. Intracandle event "
        "order cannot be verified."
    )


# =========================================================
# CANDLE VALIDATION
# =========================================================

def parse_candle(candle):

    if (
        not isinstance(candle, list)
        or len(candle) < 7
    ):
        raise ValueError(
            "Malformed Binance candle"
        )

    open_ms = int(candle[0])
    close_ms = int(candle[6])

    open_price = number(candle[1])
    high = number(candle[2])
    low = number(candle[3])
    close_price = number(candle[4])

    if (
        open_price is None
        or high is None
        or low is None
        or close_price is None
    ):
        raise ValueError(
            "Invalid candle OHLC prices"
        )

    if high < low:
        raise ValueError(
            "Candle high is below candle low"
        )

    if high < max(open_price, close_price):
        raise ValueError(
            "Invalid candle high"
        )

    if low > min(open_price, close_price):
        raise ValueError(
            "Invalid candle low"
        )

    if close_ms < open_ms:
        raise ValueError(
            "Invalid candle timestamps"
        )

    return {
        "open_ms": open_ms,
        "close_ms": close_ms,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
    }


# =========================================================
# TARGET HELPERS
# =========================================================

def update_target_flags(record, high):

    targets = record["targets"]

    for key in ("t1", "t2", "t3"):

        target = targets.get(key)

        if (
            target is not None
            and high >= target
        ):
            record[f"{key}_hit"] = True


def highest_target_hit(record):

    if record.get("t3_hit"):
        return 3

    if record.get("t2_hit"):
        return 2

    if record.get("t1_hit"):
        return 1

    return 0


def stop_outcome_after_targets(record):

    highest = highest_target_hit(record)

    if highest >= 2:
        return "T2_THEN_STOP"

    if highest == 1:
        return "T1_THEN_STOP"

    return "STOP_LOSS"


# =========================================================
# MAIN SIGNAL UPDATE ENGINE
# =========================================================

def update_signal(signal, record, now):

    created, entry_expiry, signal_expiry = (
        validate_record(signal, record)
    )

    symbol = str(
        signal.get("symbol", "")
    ).upper()

    entry = record["entry_price"]
    stop = record["stop_loss"]
    targets = record["targets"]

    last_checked = parse_time(
        record.get("last_checked_at")
    )

    if last_checked is not None:

        start_ms = int(
            (
                last_checked + timedelta(minutes=1)
            ).timestamp() * 1000
        )

    else:

        start_ms = next_full_minute(
            created
        )

    now_ms = int(
        now.timestamp() * 1000
    )

    # Binance candle close time is inclusive.
    end_ms = now_ms - 1

    if not record.get("entry_reached"):

        deadline = min(
            entry_expiry,
            signal_expiry,
        )

    else:

        deadline = signal_expiry

    deadline_ms = int(
        deadline.timestamp() * 1000
    )

    end_ms = min(
        end_ms,
        deadline_ms,
    )

    last_closed_candle_time = None
    last_candle_close_price = None

    # -----------------------------------------------------
    # FETCH AND PROCESS CLOSED CANDLES
    # -----------------------------------------------------

    if start_ms <= end_ms:

        candles = fetch_klines(
            symbol,
            start_ms,
            end_ms,
        )

        for raw_candle in candles:

            candle = parse_candle(
                raw_candle
            )

            open_ms = candle["open_ms"]
            close_ms = candle["close_ms"]

            # Never use an unfinished candle.
            if close_ms >= now_ms:
                continue

            # Do not use candles extending beyond expiry.
            if close_ms > deadline_ms:
                continue

            candle_time = datetime.fromtimestamp(
                open_ms / 1000,
                timezone.utc,
            )

            candle_close = datetime.fromtimestamp(
                close_ms / 1000,
                timezone.utc,
            )

            high = candle["high"]
            low = candle["low"]
            close_price = candle["close"]

            last_closed_candle_time = candle_time
            last_candle_close_price = close_price

            # Persist the last valid candle data.
            record["last_checked_at"] = iso(
                candle_time
            )

            record["last_closed_candle_at"] = iso(
                candle_close
            )

            record["last_closed_candle_close"] = (
                close_price
            )

            # -------------------------------------------------
            # BEFORE ENTRY
            # -------------------------------------------------

            if not record["entry_reached"]:

                entry_touched = high >= entry
                stop_touched = low <= stop

                # Stop reached without entry.
                if (
                    stop_touched
                    and not entry_touched
                ):

                    record["outcome"] = (
                        "INVALIDATED_BEFORE_ENTRY"
                    )

                    record["stop_loss_hit"] = False

                    record["exit_price"] = None
                    record["exit_at"] = iso(
                        candle_close
                    )

                    break

                # Entry and SL touched in the same candle.
                if (
                    entry_touched
                    and stop_touched
                ):

                    record["entry_reached"] = True

                    record["entry_reached_at"] = iso(
                        candle_time
                    )

                    record["stop_loss_hit"] = True

                    update_target_flags(
                        record,
                        high,
                    )

                    mark_ambiguous(
                        record,
                        candle_close,
                    )

                    break

                # Entry not reached yet.
                if not entry_touched:
                    continue

                # Entry reached without SL touch.
                record["entry_reached"] = True

                record["entry_reached_at"] = iso(
                    candle_time
                )

                # Targets may also be touched in entry candle.
                update_target_flags(
                    record,
                    high,
                )

                # T3 is final target.
                if record["t3_hit"]:

                    finish_signal(
                        record,
                        "T3",
                        targets["t3"],
                        candle_close,
                    )

                    break

                continue

            # -------------------------------------------------
            # AFTER ENTRY
            # -------------------------------------------------

            stop_touched = low <= stop

            target_touched = any(
                targets.get(key) is not None
                and high >= targets[key]
                for key in ("t1", "t2", "t3")
            )

            # Same candle touched SL and Target.
            if (
                stop_touched
                and target_touched
            ):

                record["stop_loss_hit"] = True

                update_target_flags(
                    record,
                    high,
                )

                mark_ambiguous(
                    record,
                    candle_close,
                )

                break

            # SL touched without a target in this candle.
            if stop_touched:

                record["stop_loss_hit"] = True

                outcome = stop_outcome_after_targets(
                    record
                )

                finish_signal(
                    record,
                    outcome,
                    stop,
                    candle_close,
                )

                break

            # Target detection.
            update_target_flags(
                record,
                high,
            )

            # Final target reached.
            if record["t3_hit"]:

                finish_signal(
                    record,
                    "T3",
                    targets["t3"],
                    candle_close,
                )

                break

    # -----------------------------------------------------
    # ENTRY WINDOW EXPIRY
    # -----------------------------------------------------

    if (
        not record["entry_reached"]
        and now >= entry_expiry
        and record["outcome"] == "PENDING"
    ):

        # Do not declare expiry if no candle has ever
        # been checked. There is insufficient evidence.
        if record.get("last_checked_at"):

            record["entry_expired"] = True

            record["outcome"] = (
                "ENTRY_WINDOW_EXPIRED"
            )

            record["exit_price"] = None
            record["exit_at"] = iso(
                entry_expiry
            )

        else:

            record["data_error"] = (
                "No closed 1m candle was available "
                "to verify the entry window."
            )

    # -----------------------------------------------------
    # SIGNAL EXPIRY AFTER ENTRY
    # -----------------------------------------------------

    if (
        record["entry_reached"]
        and now >= signal_expiry
        and record["outcome"] == "PENDING"
    ):

        last_close = number(
            record.get(
                "last_closed_candle_close"
            )
        )

        last_close_time = parse_time(
            record.get(
                "last_closed_candle_at"
            )
        )

        if (
            last_close is not None
            and last_close_time is not None
        ):

            finish_signal(
                record,
                "EXPIRED_AFTER_ENTRY",
                last_close,
                last_close_time,
            )

        else:

            # Never invent an exit price.
            record["data_error"] = (
                "Signal expired after entry, but no "
                "verified closed candle price is available."
            )

    # If the signal is still pending, preserve progress.
    if record.get("outcome") == "PENDING":

        record["data_error"] = None


# =========================================================
# PERFORMANCE SUMMARY
# =========================================================

def summarize_records(values):

    total = len(values)

    entered = sum(
        r.get("entry_reached") is True
        for r in values
    )

    sl_hits = sum(
        r.get("stop_loss_hit") is True
        for r in values
    )

    t1_hits = sum(
        r.get("t1_hit") is True
        for r in values
    )

    t2_hits = sum(
        r.get("t2_hit") is True
        for r in values
    )

    t3_hits = sum(
        r.get("t3_hit") is True
        for r in values
    )

    expired_before = sum(
        r.get("outcome") == "ENTRY_WINDOW_EXPIRED"
        for r in values
    )

    invalidated_before = sum(
        r.get("outcome") == "INVALIDATED_BEFORE_ENTRY"
        for r in values
    )

    expired_after = sum(
        r.get("outcome") == "EXPIRED_AFTER_ENTRY"
        for r in values
    )

    t1_then_stop = sum(
        r.get("outcome") == "T1_THEN_STOP"
        for r in values
    )

    t2_then_stop = sum(
        r.get("outcome") == "T2_THEN_STOP"
        for r in values
    )

    ambiguous = sum(
        r.get("outcome") == "AMBIGUOUS"
        for r in values
    )

    pending = sum(
        r.get("outcome") == "PENDING"
        for r in values
    )

    data_errors = sum(
        bool(r.get("data_error"))
        for r in values
    )

    completed = []

    for record in values:

        outcome = str(
            record.get("outcome", "")
        ).upper()

        result = signed_number(
            record.get("return_pct")
        )

        if (
            outcome in COMPLETED_OUTCOMES
            and result is not None
        ):
            completed.append(result)

    wins = sum(
        result > 0
        for result in completed
    )

    losses = sum(
        result < 0
        for result in completed
    )

    breakeven = sum(
        result == 0
        for result in completed
    )

    profits = [
        result
        for result in completed
        if result > 0
    ]

    loss_values = [
        result
        for result in completed
        if result < 0
    ]

    gross_profit = sum(profits)

    gross_loss_abs = abs(
        sum(loss_values)
    )

    if gross_loss_abs > 0:

        profit_factor = round(
            gross_profit / gross_loss_abs,
            4,
        )

    elif gross_profit > 0:

        profit_factor = "INF"

    else:

        profit_factor = None

    return {
        "total_signals": total,

        "entry_reached": entered,

        "entry_not_reached_expired": expired_before,

        "invalidated_before_entry": invalidated_before,

        "expired_after_entry": expired_after,

        "t1_then_stop": t1_then_stop,

        "t2_then_stop": t2_then_stop,

        "ambiguous_signals": ambiguous,

        "stop_loss_hits": sl_hits,

        "t1_hits": t1_hits,
        "t2_hits": t2_hits,
        "t3_hits": t3_hits,

        "pending": pending,

        "data_errors": data_errors,

        "completed_results": len(completed),

        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,

        "win_rate_pct": (
            round(
                wins / len(completed) * 100,
                2,
            )
            if completed else None
        ),

        "profit_factor": profit_factor,

        "average_return_pct": (
            round(
                sum(completed) / len(completed),
                4,
            )
            if completed else None
        ),

        "average_profit_pct": (
            round(
                gross_profit / len(profits),
                4,
            )
            if profits else None
        ),

        "average_loss_pct": (
            round(
                sum(loss_values) / len(loss_values),
                4,
            )
            if loss_values else None
        ),

        "total_return_pct": (
            round(
                sum(completed),
                4,
            )
            if completed else None
        ),
    }


def build_summary(records):

    values = list(
        records.values()
    )

    summary = summarize_records(
        values
    )

    strategies = {}

    for record in values:

        strategy = str(
            record.get("strategy") or "UNKNOWN"
        ).strip().upper()

        strategies.setdefault(
            strategy,
            [],
        ).append(record)

    summary["strategy_summary"] = {
        strategy: summarize_records(items)
        for strategy, items in sorted(
            strategies.items()
        )
    }

    return summary


# =========================================================
# MAIN
# =========================================================

def main():

    now = utc_now()

    cutoff = now - timedelta(
        days=RETENTION_DAYS
    )

    history = load_json(
        HISTORY_FILE,
        {},
    )

    if not isinstance(history, dict):
        raise ValueError(
            "Invalid signal_history.json"
        )

    source_signals = history.get(
        "signals",
        [],
    )

    if not isinstance(source_signals, list):
        raise ValueError(
            "History signals must be a list"
        )

    analytics = load_json(
        ANALYTICS_FILE,
        {},
    )

    if not isinstance(analytics, dict):
        raise ValueError(
            "Invalid signal_analytics.json"
        )

    old_version = analytics.get(
        "version",
        0,
    )

    try:
        old_version = int(old_version)
    except (TypeError, ValueError):
        old_version = 0

    records = analytics.get(
        "signals",
        {},
    )

    if not isinstance(records, dict):
        records = {}

    # -----------------------------------------------------
    # VERSION UPGRADE / REBUILD
    # -----------------------------------------------------

    if old_version < ANALYTICS_VERSION:

        print(
            f"Rebuilding analytics: "
            f"V{old_version} -> V{ANALYTICS_VERSION}"
        )

        # Rebuild all derived records from immutable history.
        # This clears old incorrect terminal outcomes.
        #
        # signal_history.json is never modified.
        records = {}

    else:

        retained_records = {}

        for key, value in records.items():

            if not isinstance(value, dict):
                continue

            created = parse_time(
                value.get("created_at")
            )

            if (
                created is not None
                and created >= cutoff
            ):

                retained_records[key] = value

        records = retained_records

    processed = 0
    errors = 0
    skipped = 0

    # -----------------------------------------------------
    # PROCESS HISTORY
    # -----------------------------------------------------

    seen_signal_ids = set()

    for signal in source_signals:

        if not isinstance(signal, dict):

            skipped += 1
            continue

        signal_id = signal.get(
            "signal_id"
        )

        created = parse_time(
            signal.get("created_at")
        )

        if not signal_id or not created:

            skipped += 1
            continue

        if created < cutoff:
            continue

        signal_id = str(signal_id)

        # Avoid processing duplicate IDs in history.
        if signal_id in seen_signal_ids:

            skipped += 1
            continue

        seen_signal_ids.add(signal_id)

        record = records.get(
            signal_id
        )

        if record is None:

            try:

                record = create_record(
                    signal
                )

                records[signal_id] = record

            except Exception as exc:

                errors += 1

                print(
                    f"WARNING: Cannot create record "
                    f"{signal_id}: {str(exc)[:250]}"
                )

                continue

        if not isinstance(record, dict):

            errors += 1

            print(
                f"WARNING: Invalid analytics record: "
                f"{signal_id}"
            )

            continue

        # Keep terminal results stable after a successful
        # V4 calculation. The V3 -> V4 rebuild above
        # recalculates old terminal results.
        if record.get("outcome") in TERMINAL_OUTCOMES:
            continue

        try:

            update_signal(
                signal,
                record,
                now,
            )

            if record.get("outcome") != "PENDING":
                record["data_error"] = None

            processed += 1

        except Exception as exc:

            record["data_error"] = str(exc)[:250]

            errors += 1

            print(
                f"WARNING: {signal_id}: "
                f"{record['data_error']}"
            )

    # -----------------------------------------------------
    # RETENTION
    # -----------------------------------------------------

    records = {
        key: value
        for key, value in records.items()
        if (
            isinstance(value, dict)
            and parse_time(
                value.get("created_at")
            ) is not None
            and parse_time(
                value.get("created_at")
            ) >= cutoff
        )
    }

    # -----------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------

    output = {
        "version": ANALYTICS_VERSION,

        "updated_at": iso(now),

        "retention_days": RETENTION_DAYS,

        "round_trip_fee_pct": ROUND_TRIP_FEE_PCT,

        "accounting_type": "SIMULATED_CANDLE_BASED",

        "accounting_note": (
            "Estimated price performance using Binance "
            "closed 1m candles. Round-trip fee is an estimate. "
            "This is not actual exchange fill PNL. "
            "Slippage, partial fills and partial target exits "
            "are not included. T1_THEN_STOP and T2_THEN_STOP "
            "identify target milestones before a later stop; "
            "their return is conservatively calculated using "
            "the full-position stop price."
        ),

        "outcome_rules": {
            "entry": "Closed candle high >= entry price",
            "stop_loss": "Closed candle low <= stop price",
            "target": "Closed candle high >= target price",
            "same_candle_sl_target": "AMBIGUOUS",
            "target_then_stop": (
                "T1_THEN_STOP or T2_THEN_STOP"
            ),
            "ambiguous_in_win_rate": False,
            "ambiguous_in_profit_factor": False,
        },

        "summary": build_summary(records),

        "signals": records,
    }

    atomic_save(
        ANALYTICS_FILE,
        output,
    )

    print(
        "\n========== V3 SIGNAL ANALYTICS V4 =========="
    )

    print(
        json.dumps(
            output["summary"],
            indent=2,
            ensure_ascii=False,
        )
    )

    print(
        f"\nProcessed signals: {processed}"
    )

    print(
        f"Data errors: {errors}"
    )

    print(
        f"Skipped invalid/duplicate history items: {skipped}"
    )

    print(
        f"Analytics version: {ANALYTICS_VERSION}"
    )

    print(
        f"Saved file: {ANALYTICS_FILE}"
    )

    if errors:

        print(
            "\nWARNING: Some signals could not be updated. "
            "Check data_error fields in signal_analytics.json."
        )

    print(
        "=============================================="
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as exc:

        print(
            f"FATAL ERROR: {exc}"
        )

        sys.exit(1)
