
import json
import os
import sys
import time
import tempfile
from datetime import datetime, timezone, timedelta

import requests

HISTORY_FILE = "signal_history.json"
ANALYTICS_FILE = "signal_analytics.json"
API_URL = "https://data-api.binance.vision/api/v3/klines"

RETENTION_DAYS = 7
INTERVAL = "1m"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def number(value):
    try:
        result = float(value)
        if result > 0 and result < float("inf"):
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
    except (OSError, json.JSONDecodeError):
        print(f"WARNING: Could not read {path}; using empty data.")
        return default


def atomic_save(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(
        prefix=".analytics_",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
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
            "interval": INTERVAL,
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
            raise ValueError(f"Invalid Binance response for {symbol}")

        if not batch:
            break

        candles.extend(batch)
        last_open = int(batch[-1][0])
        next_cursor = last_open + 60000

        if next_cursor <= cursor:
            break

        cursor = next_cursor

        if len(batch) < 1000:
            break

    return candles


def new_record(signal):
    return {
        "signal_id": signal["signal_id"],
        "symbol": signal["symbol"],
        "strategy": signal.get("strategy"),
        "classification": signal.get("classification"),
        "created_at": signal.get("created_at"),
        "entry_price": number(signal.get("entry_price")),
        "stop_loss": number(signal.get("stop_loss")),
        "targets": {
            "t1": number((signal.get("targets") or {}).get("t1")),
            "t2": number((signal.get("targets") or {}).get("t2")),
            "t3": number((signal.get("targets") or {}).get("t3")),
        },
        "entry_reached": False,
        "entry_reached_at": None,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,
        "entry_expired": False,
        "outcome": "PENDING",
        "exit_price": None,
        "exit_at": None,
        "return_pct": None,
        "last_checked_at": None,
        "data_error": None,
    }


def update_record(signal, record, now):
    symbol = str(signal.get("symbol", "")).upper()

    if not symbol.endswith("USDT"):
        record["data_error"] = "NOT_USDT_SPOT_SYMBOL"
        return

    entry = record["entry_price"]
    stop = record["stop_loss"]
    targets = record["targets"]

    if not entry or not stop or stop >= entry:
        record["data_error"] = "INVALID_ENTRY_OR_STOP"
        return

    created = parse_time(signal.get("created_at"))
    entry_expiry = parse_time(signal.get("entry_expiry"))
    signal_expiry = parse_time(signal.get("expires_at"))

    if not created or not entry_expiry or not signal_expiry:
        record["data_error"] = "INVALID_SIGNAL_TIMESTAMPS"
        return

    last_checked = parse_time(record.get("last_checked_at"))
    start = last_checked + timedelta(minutes=1) if last_checked else created

    # Only fully closed 1-minute candles are evaluated.
    end = min(now - timedelta(minutes=1), signal_expiry)

    if not record["entry_reached"]:
        end = min(end, entry_expiry)

    if start > end:
        if not record["entry_reached"] and now >= entry_expiry:
            record["entry_expired"] = True
            record["outcome"] = "EXPIRED_BEFORE_ENTRY"
        elif record["entry_reached"] and now >= signal_expiry:
            record["outcome"] = "EXPIRED_AFTER_ENTRY"
            record["exit_price"] = (
                targets["t3"] if record["t3_hit"] else
                targets["t2"] if record["t2_hit"] else
                targets["t1"] if record["t1_hit"] else entry
            )
            record["exit_at"] = iso(signal_expiry)
            calculate_return(record)
        return

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    candles = fetch_klines(symbol, start_ms, end_ms)

    for candle in candles:
        open_ms = int(candle[0])
        close_ms = int(candle[6])

        candle_time = datetime.fromtimestamp(
            open_ms / 1000, timezone.utc
        )
        candle_close = datetime.fromtimestamp(
            close_ms / 1000, timezone.utc
        )

        if candle_time < created:
            continue

        high = number(candle[2])
        low = number(candle[3])

        if high is None or low is None:
            continue

        if not record["entry_reached"]:
            if candle_time > entry_expiry:
                record["entry_expired"] = True
                record["outcome"] = "EXPIRED_BEFORE_ENTRY"
                break

            if low <= entry <= high:
                record["entry_reached"] = True
                record["entry_reached_at"] = iso(candle_time)

                # Do not evaluate SL/TP in the same candle as entry.
                record["last_checked_at"] = iso(candle_time)
            else:
                record["last_checked_at"] = iso(candle_time)
            continue

        # Conservative rule: SL takes priority if SL and any target
        # are touched within the same 1-minute candle.
        if low <= stop:
            record["stop_loss_hit"] = True
            record["outcome"] = "STOP_LOSS"
            record["exit_price"] = stop
            record["exit_at"] = iso(candle_close)
            record["last_checked_at"] = iso(candle_time)
            calculate_return(record)
            break

        for key in ("t1", "t2", "t3"):
            target = targets.get(key)
            if target is not None and high >= target:
                record[f"{key}_hit"] = True

        record["last_checked_at"] = iso(candle_time)

        if record["t3_hit"]:
            record["outcome"] = "T3"
            record["exit_price"] = targets["t3"]
            record["exit_at"] = iso(candle_close)
            calculate_return(record)
            break

    if (
        record["entry_reached"]
        and record["outcome"] == "PENDING"
        and now >= signal_expiry
    ):
        record["outcome"] = "EXPIRED_AFTER_ENTRY"
        record["exit_price"] = (
            targets["t2"] if record["t2_hit"] else
            targets["t1"] if record["t1_hit"] else
            entry
        )
        record["exit_at"] = iso(signal_expiry)
        calculate_return(record)

    if (
        not record["entry_reached"]
        and now >= entry_expiry
        and record["outcome"] == "PENDING"
    ):
        record["entry_expired"] = True
        record["outcome"] = "EXPIRED_BEFORE_ENTRY"


def calculate_return(record):
    entry = record.get("entry_price")
    exit_price = number(record.get("exit_price"))

    if entry and exit_price:
        record["return_pct"] = round(
            ((exit_price - entry) / entry) * 100,
            4,
        )


def build_summary(records):
    values = list(records.values())

    total = len(values)
    entered = sum(bool(r.get("entry_reached")) for r in values)
    sl_hits = sum(bool(r.get("stop_loss_hit")) for r in values)
    t1_hits = sum(bool(r.get("t1_hit")) for r in values)
    t2_hits = sum(bool(r.get("t2_hit")) for r in values)
    t3_hits = sum(bool(r.get("t3_hit")) for r in values)

    expired_before = sum(
        r.get("outcome") == "EXPIRED_BEFORE_ENTRY" for r in values
    )
    pending = sum(r.get("outcome") == "PENDING" for r in values)

    completed = [
        r for r in values
        if r.get("return_pct") is not None
    ]

    wins = sum(r["return_pct"] > 0 for r in completed)
    losses = sum(r["return_pct"] < 0 for r in completed)

    average_return = (
        round(sum(r["return_pct"] for r in completed) / len(completed), 4)
        if completed else None
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
        "average_profit_pct": (
            round(
                sum(r["return_pct"] for r in completed if r["return_pct"] > 0)
                / wins,
                4,
            ) if wins else None
        ),
        "average_loss_pct": (
            round(
                sum(r["return_pct"] for r in completed if r["return_pct"] < 0)
                / losses,
                4,
            ) if losses else None
        ),
    }


def main():
    now = utc_now()
    cutoff = now - timedelta(days=RETENTION_DAYS)

    history = load_json(HISTORY_FILE, {})
    source_signals = history.get("signals", [])

    if not isinstance(source_signals, list):
        raise ValueError("signal_history.json has no valid signals list")

    analytics = load_json(ANALYTICS_FILE, {})
    records = analytics.get("signals", {})

    if not isinstance(records, dict):
        records = {}

    # Remove analytics records older than seven days.
    records = {
        key: value for key, value in records.items()
        if parse_time(value.get("created_at"))
        and parse_time(value.get("created_at")) >= cutoff
    }

    processed = 0
    errors = 0

    for signal in source_signals:
        if not isinstance(signal, dict):
            continue

        signal_id = signal.get("signal_id")
        created = parse_time(signal.get("created_at"))

        if not signal_id or not created or created < cutoff:
            continue

        record = records.get(signal_id)

        if record is None:
            record = new_record(signal)
            records[signal_id] = record

        try:
            update_record(signal, record, now)
            record["data_error"] = None
            processed += 1
        except Exception as exc:
            record["data_error"] = str(exc)[:250]
            errors += 1
            print(f"WARNING: {signal_id}: {record['data_error']}")

    # Keep only records inside the seven-day retention window.
    records = {
        key: value for key, value in records.items()
        if parse_time(value.get("created_at"))
        and parse_time(value.get("created_at")) >= cutoff
    }

    output = {
        "version": 1,
        "updated_at": iso(now),
        "retention_days": RETENTION_DAYS,
        "summary": build_summary(records),
        "signals": records,
    }

    atomic_save(ANALYTICS_FILE, output)

    print("===== V3 SIGNAL ANALYTICS =====")
    print(json.dumps(output["summary"], indent=2))
    print(f"Processed: {processed} | Errors: {errors}")
    print(f"Saved: {ANALYTICS_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL ANALYTICS ERROR: {exc}")
        sys.exit(1)
