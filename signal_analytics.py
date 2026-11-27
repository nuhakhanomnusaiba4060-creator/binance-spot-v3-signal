
"""
Binance Spot V3 Smart Signal Scanner
Independent Signal Performance Analytics

- Binance Spot USDT only.
- Reads signal_history.json; never modifies it.
- Uses closed 1-minute Binance candles.
- Entry logic aligned with signal_tracker.py: High >= Entry.
- Same-candle SL/Target ambiguity is never guessed.
- Excludes the candle containing signal creation time.
- Uses expiry candle close for expiry exits.
- Rebuilds old V2 analytics records using V3 rules.
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

ANALYTICS_VERSION = 3
RETENTION_DAYS = 7

INTERVAL_MS = 60_000
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

# Estimated Binance Spot round-trip trading fee.
# Default: 0.10% entry + 0.10% exit.
# Actual user fee may differ.
ROUND_TRIP_FEE_PCT = float(
    os.getenv("V3_ROUND_TRIP_FEE_PCT", "0.20")
)

COMPLETED_OUTCOMES = {
    "STOP_LOSS",
    "T3",
    "EXPIRED_AFTER_ENTRY",
}

TERMINAL_OUTCOMES = {
    "STOP_LOSS",
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
    """Positive finite number parser."""

    try:
        result = float(value)

        if math.isfinite(result) and result > 0:
            return result

    except (TypeError, ValueError, OverflowError):
        pass

    return None


def signed_number(value):
    """Finite number parser including zero and negative values."""

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
    """Write JSON atomically to prevent partial files."""

    directory = os.path.dirname(os.path.abspath(path))

    fd, temporary = tempfile.mkstemp(
        prefix="analytics_",
        suffix=".tmp",
        dir=directory,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
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
    Return the first complete candle open time after signal creation.

    If signal is created exactly at a minute boundary,
    that candle can be included.
    Otherwise, the next minute is used.
    """

    milliseconds = int(timestamp.timestamp() * 1000)

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

        "last_checked_at": None,
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

    entry = number(record.get("entry_price"))
    stop = number(record.get("stop_loss"))

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
        raise ValueError("T1 target price is missing")

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

    if not created or not entry_expiry or not signal_expiry:
        raise ValueError(
            "Invalid signal timestamps"
        )

    if entry_expiry > signal_expiry:
        raise ValueError(
            "Entry expiry is later than signal expiry"
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

    if entry is None or exit_price is None:
        record["gross_return_pct"] = None
        record["return_pct"] = None
        return

    gross_pct = (
        (exit_price - entry) / entry
    ) * 100

    net_pct = (
        gross_pct - ROUND_TRIP_FEE_PCT
    )

    record["gross_return_pct"] = round(
        gross_pct, 4
    )

    record["return_pct"] = round(
        net_pct, 4
    )


def finish_signal(
    record,
    outcome,
    exit_price,
    exit_time,
):

    record["outcome"] = outcome
    record["exit_price"] = exit_price
    record["exit_at"] = iso(exit_time)

    calculate_return(record)


def mark_ambiguous(record, candle_close):

    record["outcome"] = "AMBIGUOUS"
    record["exit_price"] = None
    record["exit_at"] = iso(candle_close)

    record["gross_return_pct"] = None
    record["return_pct"] = None

    record["ambiguity_reason"] = (
        "Same 1m candle touched Stop Loss and Target. "
        "Intracandle event order cannot be verified."
    )


# =========================================================
# CANDLE VALIDATION
# =========================================================

def parse_candle(candle):

    if not isinstance(candle, list) or len(candle) < 7:
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

    return {
        "open_ms": open_ms,
        "close_ms": close_ms,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
    }


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

        start_ms = next_full_minute(created)

    now_ms = int(
        now.timestamp() * 1000
    )

    end_ms = now_ms - 1

    deadline = signal_expiry

    if not record.get("entry_reached"):
        deadline = min(
            entry_expiry,
            signal_expiry,
        )

    deadline_ms = int(
        deadline.timestamp() * 1000
    )

    end_ms = min(
        end_ms,
        deadline_ms,
    )

    last_closed_candle_time = None
    last_candle_close_price = None

    if start_ms <= end_ms:

        candles = fetch_klines(
            symbol,
            start_ms,
            end_ms,
        )

        for raw_candle in candles:

            candle = parse_candle(raw_candle)

            open_ms = candle["open_ms"]
            close_ms = candle["close_ms"]

            # Only fully closed candles are allowed.
            if close_ms >= now_ms:
                continue

            # Never use a candle that extends beyond expiry.
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

            # -------------------------------------------------
            # BEFORE ENTRY
            # -------------------------------------------------

            if not record["entry_reached"]:

                entry_touched = high >= entry
                stop_touched = low <= stop

                # Stop reached without entry.
                # This signal was invalidated before entry.
                if stop_touched and not entry_touched:

                    record["stop_loss_hit"] = False

                    record["outcome"] = (
                        "INVALIDATED_BEFORE_ENTRY"
                    )

                    record["exit_at"] = iso(
                        candle_close
                    )

                    record["exit_price"] = None
                    break

                # Entry and SL both touched in the same candle.
                # Event order is unknown.
                if entry_touched and stop_touched:

                    record["entry_reached"] = True

                    record["entry_reached_at"] = iso(
                        candle_time
                    )

                    record["stop_loss_hit"] = True

                    if targets.get("t1") is not None:
                        record["t1_hit"] = (
                            high >= targets["t1"]
                        )

                    if targets.get("t2") is not None:
                        record["t2_hit"] = (
                            high >= targets["t2"]
                        )

                    if targets.get("t3") is not None:
                        record["t3_hit"] = (
                            high >= targets["t3"]
                        )

                    mark_ambiguous(
                        record,
                        candle_close,
                    )

                    break

                if not entry_touched:
                    continue

                # Entry reached; no SL touched in this candle.
                record["entry_reached"] = True

                record["entry_reached_at"] = iso(
                    candle_time
                )

                # Target detection is also required on entry candle.
                for key in ("t1", "t2", "t3"):

                    target = targets.get(key)

                    if (
                        target is not None
                        and high >= target
                    ):
                        record[f"{key}_hit"] = True

                # If T3 was reached, the signal is completed.
                if (
                    targets.get("t3") is not None
                    and record["t3_hit"]
                ):

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

            # Same candle touched SL and at least one target.
            if stop_touched and target_touched:

                record["stop_loss_hit"] = True

                for key in ("t1", "t2", "t3"):

                    target = targets.get(key)

                    if (
                        target is not None
                        and high >= target
                    ):
                        record[f"{key}_hit"] = True

                mark_ambiguous(
                    record,
                    candle_close,
                )

                break

            # SL only.
            if stop_touched:

                record["stop_loss_hit"] = True

                finish_signal(
                    record,
                    "STOP_LOSS",
                    stop,
                    candle_close,
                )

                break

            # Target detection.
            for key in ("t1", "t2", "t3"):

                target = targets.get(key)

                if (
                    target is not None
                    and high >= target
                ):
                    record[f"{key}_hit"] = True

            # T3 is the final target.
            if (
                targets.get("t3") is not None
                and record["t3_hit"]
            ):

                finish_signal(
                    record,
                    "T3",
                    targets["t3"],
                    candle_close,
                )

                break

    # -----------------------------------------------------
    # UPDATE LAST CHECKED CANDLE
    # -----------------------------------------------------

    if last_closed_candle_time is not None:

        record["last_checked_at"] = iso(
            last_closed_candle_time
        )

    # -----------------------------------------------------
    # ENTRY WINDOW EXPIRED
    # -----------------------------------------------------

    if (
        not record["entry_reached"]
        and now >= entry_expiry
        and record["outcome"] == "PENDING"
    ):

        record["entry_expired"] = True

        record["outcome"] = (
            "ENTRY_WINDOW_EXPIRED"
        )

    # -----------------------------------------------------
    # SIGNAL EXPIRED AFTER ENTRY
    # -----------------------------------------------------

    if (
        record["entry_reached"]
        and now >= signal_expiry
        and record["outcome"] == "PENDING"
    ):

        # Do not assume T1 was the actual exit.
        # Use the last available closed candle price.
        if last_candle_close_price is not None:

            exit_price = last_candle_close_price

        else:
            exit_price = entry

        finish_signal(
            record,
            "EXPIRED_AFTER_ENTRY",
            exit_price,
            signal_expiry,
        )


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

    values = list(records.values())

    summary = summarize_records(values)

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
    # REBUILD OLD ANALYTICS
    # -----------------------------------------------------

    if old_version < ANALYTICS_VERSION:

        print(
            f"Rebuilding analytics: "
            f"V{old_version} -> V{ANALYTICS_VERSION}"
        )

        # Only derived analytics records are reset.
        # signal_history.json remains untouched.
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

        # Do not recalculate terminal outcomes.
        if record.get("outcome") in TERMINAL_OUTCOMES:
            continue

        try:

            update_signal(
                signal,
                record,
                now,
            )

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
            "closed 1m candles. Fee is an estimate. "
            "This is not actual exchange fill PNL. "
            "Slippage and partial fills are not included."
        ),

        "summary": build_summary(records),

        "signals": records,
    }

    atomic_save(
        ANALYTICS_FILE,
        output,
    )

    print(
        "\n========== V3 SIGNAL ANALYTICS V3 =========="
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
        f"Skipped invalid history items: {skipped}"
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
