
import json
import os
import sys
import time
import tempfile
import math

from datetime import datetime, timezone, timedelta

import requests


HISTORY_FILE = "signal_history.json"
ANALYTICS_FILE = "signal_analytics.json"

API_URL = "https://data-api.binance.vision/api/v3/klines"

RETENTION_DAYS = 7
INTERVAL_MS = 60_000
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    if value is None:
        return None

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

    except (ValueError, TypeError):
        return None


def number(value):
    try:
        result = float(value)

        if math.isfinite(result) and result > 0:
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

        response = None

        for attempt in range(MAX_RETRIES):

            try:
                response = requests.get(
                    API_URL,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                response.raise_for_status()
                break

            except requests.RequestException:

                if attempt == MAX_RETRIES - 1:
                    raise

                time.sleep(2 ** attempt)

        batch = response.json()

        if not isinstance(batch, list):
            raise ValueError("Invalid Binance candle response")

        if not batch:
            break

        candles.extend(batch)

        last_open = int(batch[-1][0])
        next_cursor = last_open + INTERVAL_MS

        if next_cursor <= cursor:
            break

        cursor = next_cursor

        if len(batch) < 1000:
            break

    return candles


def create_record(signal):
    targets = signal.get("targets") or {}

    return {
        "signal_id": signal["signal_id"],
        "symbol": signal["symbol"],
        "strategy": signal.get("strategy"),
        "classification": signal.get("classification"),
        "created_at": signal.get("created_at"),

        "entry_price": number(signal.get("entry_price")),
        "stop_loss": number(signal.get("stop_loss")),

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
        "return_pct": None,

        "last_checked_at": None,
        "data_error": None,
    }


def validate_record(signal, record):
    symbol = str(signal.get("symbol", "")).upper()

    if not symbol.endswith("USDT"):
        raise ValueError("Only USDT Spot symbols are supported")

    entry = record.get("entry_price")
    stop = record.get("stop_loss")
    targets = record.get("targets") or {}

    if not entry or not stop or stop >= entry:
        raise ValueError("Invalid entry price or stop loss")

    t1 = targets.get("t1")
    t2 = targets.get("t2")
    t3 = targets.get("t3")

    if t1 is None or t2 is None or t3 is None:
        raise ValueError("One or more target prices are missing")

    if not (entry < t1 < t2 < t3):
        raise ValueError("Invalid target price sequence")

    created = parse_time(signal.get("created_at"))
    entry_expiry = parse_time(signal.get("entry_expiry"))
    signal_expiry = parse_time(signal.get("expires_at"))

    if not created or not entry_expiry or not signal_expiry:
        raise ValueError("Invalid signal timestamps")

    if entry_expiry > signal_expiry:
        raise ValueError("Entry expiry is later than signal expiry")

    return created, entry_expiry, signal_expiry


def calculate_return(record):
    entry = record.get("entry_price")
    exit_price = number(record.get("exit_price"))

    if entry and exit_price:

        record["return_pct"] = round(
            ((exit_price - entry) / entry) * 100,
            4,
        )


def finish_signal(record, outcome, exit_price, exit_time):
    record["outcome"] = outcome
    record["exit_price"] = exit_price
    record["exit_at"] = iso(exit_time)

    calculate_return(record)


def update_signal(signal, record, now):
    created, entry_expiry, signal_expiry = validate_record(
        signal,
        record,
    )

    symbol = str(signal.get("symbol", "")).upper()

    entry = record["entry_price"]
    stop = record["stop_loss"]
    targets = record["targets"]

    last_checked = parse_time(record.get("last_checked_at"))

    if last_checked:
        start = last_checked + timedelta(minutes=1)
    else:
        start = created

    # Only fully closed 1-minute candles are used.
    now_ms = int(now.timestamp() * 1000)
    end_ms = now_ms - 1

    deadline = signal_expiry

    if not record["entry_reached"]:
        deadline = min(entry_expiry, signal_expiry)

    deadline_ms = int(deadline.timestamp() * 1000)
    end_ms = min(end_ms, deadline_ms)

    start_ms = int(start.timestamp() * 1000)

    if start_ms <= end_ms:

        candles = fetch_klines(
            symbol,
            start_ms,
            end_ms,
        )

        for candle in candles:

            open_ms = int(candle[0])
            close_ms = int(candle[6])

            # Ignore candles that have not fully closed.
            if close_ms >= now_ms:
                continue

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

            high = number(candle[2])
            low = number(candle[3])

            if high is None or low is None:
                continue

            # ENTRY DETECTION
            if not record["entry_reached"]:

                if low <= entry <= high:

                    record["entry_reached"] = True
                    record["entry_reached_at"] = iso(candle_time)

                    # Conservative assumption:
                    # SL takes priority if touched in entry candle.
                    if low <= stop:

                        record["stop_loss_hit"] = True

                        finish_signal(
                            record,
                            "STOP_LOSS",
                            stop,
                            candle_close,
                        )

                    # Targets are not counted in the entry candle.
                    record["last_checked_at"] = iso(candle_time)

                    if record["outcome"] == "STOP_LOSS":
                        break

                else:
                    record["last_checked_at"] = iso(candle_time)

                continue

            # STOP LOSS HAS PRIORITY OVER TARGETS.
            if low <= stop:

                record["stop_loss_hit"] = True

                finish_signal(
                    record,
                    "STOP_LOSS",
                    stop,
                    candle_close,
                )

                record["last_checked_at"] = iso(candle_time)
                break

            # TARGET DETECTION
            for key in ("t1", "t2", "t3"):

                target = targets.get(key)

                if target is not None and high >= target:
                    record[f"{key}_hit"] = True

            record["last_checked_at"] = iso(candle_time)

            # T3 is treated as the final target.
            if record["t3_hit"]:

                finish_signal(
                    record,
                    "T3",
                    targets["t3"],
                    candle_close,
                )

                break

    # ENTRY WINDOW EXPIRED
    if (
        not record["entry_reached"]
        and now >= entry_expiry
        and record["outcome"] == "PENDING"
    ):

        record["entry_expired"] = True
        record["outcome"] = "ENTRY_WINDOW_EXPIRED"

    # SIGNAL EXPIRED AFTER ENTRY
    if (
        record["entry_reached"]
        and now >= signal_expiry
        and record["outcome"] == "PENDING"
    ):

        if record["t2_hit"]:
            exit_price = targets["t2"]

        elif record["t1_hit"]:
            exit_price = targets["t1"]

        else:
            exit_price = entry

        finish_signal(
            record,
            "EXPIRED_AFTER_ENTRY",
            exit_price,
            signal_expiry,
        )


def build_summary(records):
    values = list(records.values())

    total = len(values)

    entered = sum(
        bool(r.get("entry_reached"))
        for r in values
    )

    sl_hits = sum(
        bool(r.get("stop_loss_hit"))
        for r in values
    )

    t1_hits = sum(bool(r.get("t1_hit")) for r in values)
    t2_hits = sum(bool(r.get("t2_hit")) for r in values)
    t3_hits = sum(bool(r.get("t3_hit")) for r in values)

    expired_before = sum(
        r.get("outcome") == "ENTRY_WINDOW_EXPIRED"
        for r in values
    )

    pending = sum(
        r.get("outcome") == "PENDING"
        for r in values
    )

    completed = [
        r for r in values
        if number(r.get("return_pct")) is not None
    ]

    wins = sum(
        r["return_pct"] > 0
        for r in completed
    )

    losses = sum(
        r["return_pct"] < 0
        for r in completed
    )

    average_return = None

    if completed:
        average_return = round(
            sum(r["return_pct"] for r in completed)
            / len(completed),
            4,
        )

    average_profit = None

    if wins:
        average_profit = round(
            sum(
                r["return_pct"]
                for r in completed
                if r["return_pct"] > 0
            ) / wins,
            4,
        )

    average_loss = None

    if losses:
        average_loss = round(
            sum(
                r["return_pct"]
                for r in completed
                if r["return_pct"] < 0
            ) / losses,
            4,
        )

    return {
        "total_signals": total,
        "entry_reached": entered,
        "entry_not_reached_expired": expired_before,

        "stop_loss_hits": sl_hits,

        "t1_hits": t1_hits,
        "t2_hits": t2_hits,
        "t3_hits": t3_hits,

        "pending": pending,

        "completed_results": len(completed),
        "wins": wins,
        "losses": losses,

        "win_rate_pct": (
            round(wins / len(completed) * 100, 2)
            if completed else None
        ),

        "average_return_pct": average_return,
        "average_profit_pct": average_profit,
        "average_loss_pct": average_loss,
    }


def main():
    now = utc_now()
    cutoff = now - timedelta(days=RETENTION_DAYS)

    history = load_json(HISTORY_FILE, {})

    if not isinstance(history, dict):
        raise ValueError("Invalid signal_history.json")

    source_signals = history.get("signals", [])

    if not isinstance(source_signals, list):
        raise ValueError("History signals must be a list")

    analytics = load_json(ANALYTICS_FILE, {})

    if not isinstance(analytics, dict):
        raise ValueError("Invalid signal_analytics.json")

    records = analytics.get("signals", {})

    if not isinstance(records, dict):
        raise ValueError("Analytics signals must be a dictionary")

    # Delete records older than seven days.
    records = {
        key: value
        for key, value in records.items()
        if (
            isinstance(value, dict)
            and parse_time(value.get("created_at"))
            and parse_time(value.get("created_at")) >= cutoff
        )
    }

    processed = 0
    errors = 0

    for signal in source_signals:

        if not isinstance(signal, dict):
            continue

        signal_id = signal.get("signal_id")
        created = parse_time(signal.get("created_at"))

        if not signal_id or not created:
            continue

        if created < cutoff:
            continue

        record = records.get(signal_id)

        if record is None:

            try:
                record = create_record(signal)
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
            print(f"WARNING: Invalid analytics record: {signal_id}")
            continue

        # Do not process already completed signals again.
        if record.get("outcome") not in ("PENDING", None):
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

    # Final seven-day cleanup.
    records = {
        key: value
        for key, value in records.items()
        if (
            isinstance(value, dict)
            and parse_time(value.get("created_at"))
            and parse_time(value.get("created_at")) >= cutoff
        )
    }

    output = {
        "version": 1,
        "updated_at": iso(now),
        "retention_days": RETENTION_DAYS,
        "summary": build_summary(records),
        "signals": records,
    }

    atomic_save(
        ANALYTICS_FILE,
        output,
    )

    print("\n========== V3 SIGNAL ANALYTICS ==========")

    print(
        json.dumps(
            output["summary"],
            indent=2,
            ensure_ascii=False,
        )
    )

    print(f"\nProcessed signals: {processed}")
    print(f"Data errors: {errors}")
    print(f"Saved file: {ANALYTICS_FILE}")

    print("==========================================")


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(f"FATAL ERROR: {exc}")
        sys.exit(1)
