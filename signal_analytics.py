
"""
Binance Spot V3 - Independent Signal Performance Analytics
Version 5

- Reads signal_history.json; never modifies it.
- Binance Spot USDT 1m closed candles only.
- Rebuilds derived analytics when version changes.
- Never guesses price movement inside an unfinished expiry candle.
- Same-candle SL/Target touches are AMBIGUOUS, not confirmed SL.
- Tracks T1_THEN_STOP and T2_THEN_STOP.
- Estimated fee-adjusted return; not actual exchange PNL.
"""

import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import requests


HISTORY_FILE = "signal_history.json"
ANALYTICS_FILE = "signal_analytics.json"
API_URL = "https://data-api.binance.vision/api/v3/klines"

ANALYTICS_VERSION = 5
RETENTION_DAYS = 7
INTERVAL_MS = 60_000
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3

ROUND_TRIP_FEE_PCT = float(
    os.getenv("V3_ROUND_TRIP_FEE_PCT", "0.20")
)

COMPLETED_OUTCOMES = {
    "STOP_LOSS",
    "T1_THEN_STOP",
    "T2_THEN_STOP",
    "T3",
    "EXPIRED_AFTER_ENTRY",
}

TERMINAL_OUTCOMES = COMPLETED_OUTCOMES | {
    "ENTRY_WINDOW_EXPIRED",
    "INVALIDATED_BEFORE_ENTRY",
    "AMBIGUOUS",
    "ENTRY_WINDOW_UNVERIFIED",
    "EXPIRED_AFTER_ENTRY_UNVERIFIED",
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
    try:
        result = float(value)
        if math.isfinite(result) and result > 0:
            return result
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def signed_number(value):
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
    milliseconds = int(timestamp.timestamp() * 1000)
    return (
        (milliseconds + INTERVAL_MS - 1)
        // INTERVAL_MS
    ) * INTERVAL_MS


def expected_last_candle_open(deadline):
    """
    Return the last 1m candle open whose complete close is
    at or before deadline. If deadline falls inside a minute,
    that partial minute cannot be verified using 1m candles.
    """
    deadline_ms = int(deadline.timestamp() * 1000)
    remainder = deadline_ms % INTERVAL_MS

    if remainder == 0:
        return deadline_ms - INTERVAL_MS

    return None


def candle_coverage_complete(record, deadline):
    expected_open = expected_last_candle_open(deadline)

    if expected_open is None:
        return False

    last_checked = parse_time(record.get("last_checked_at"))
    if last_checked is None:
        return False

    actual_open = int(last_checked.timestamp() * 1000)
    return actual_open >= expected_open


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

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == MAX_RETRIES - 1:
                        response.raise_for_status()

                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after)
                    except (TypeError, ValueError):
                        delay = 2 ** attempt

                    time.sleep(min(max(delay, 1), 30))
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
            raise ValueError("Invalid Binance candle response")

        if not batch:
            break

        candles.extend(batch)
        next_cursor = int(batch[-1][0]) + INTERVAL_MS

        if next_cursor <= cursor:
            raise ValueError("Binance candle pagination did not advance")

        cursor = next_cursor

        if len(batch) < 1000:
            break

    return candles


def parse_candle(candle):
    if not isinstance(candle, list) or len(candle) < 7:
        raise ValueError("Malformed Binance candle")

    open_ms = int(candle[0])
    close_ms = int(candle[6])

    open_price = number(candle[1])
    high = number(candle[2])
    low = number(candle[3])
    close_price = number(candle[4])

    if None in (open_price, high, low, close_price):
        raise ValueError("Invalid candle OHLC prices")

    if high < low:
        raise ValueError("Candle high is below candle low")

    if high < max(open_price, close_price):
        raise ValueError("Invalid candle high")

    if low > min(open_price, close_price):
        raise ValueError("Invalid candle low")

    if close_ms < open_ms:
        raise ValueError("Invalid candle timestamps")

    return {
        "open_ms": open_ms,
        "close_ms": close_ms,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
    }


# =========================================================
# RECORD CREATION AND VALIDATION
# =========================================================

def create_record(signal):
    targets = signal.get("targets") or {}

    return {
        "signal_id": str(signal["signal_id"]),
        "symbol": str(signal["symbol"]).upper(),
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
        "entry_expired": False,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "stop_loss_hit": False,
        "stop_loss_touched": False,
        "outcome": "PENDING",
        "exit_price": None,
        "exit_at": None,
        "gross_return_pct": None,
        "return_pct": None,
        "fee_estimate_pct": ROUND_TRIP_FEE_PCT,
        "last_checked_at": None,
        "last_closed_candle_at": None,
        "last_closed_candle_close": None,
        "data_error": None,
    }


def validate_record(signal, record):
    symbol = str(signal.get("symbol", "")).upper()

    if not symbol.endswith("USDT"):
        raise ValueError("Only USDT Spot symbols are supported")

    entry = number(record.get("entry_price"))
    stop = number(record.get("stop_loss"))
    targets = record.get("targets") or {}

    if entry is None or stop is None:
        raise ValueError("Missing entry price or stop loss")

    if stop >= entry:
        raise ValueError("Stop loss must be below entry")

    t1 = number(targets.get("t1"))
    t2 = number(targets.get("t2"))
    t3 = number(targets.get("t3"))

    if t1 is None:
        raise ValueError("T1 target price is missing")

    available = [x for x in (t1, t2, t3) if x is not None]
    previous = entry

    for target in available:
        if target <= previous:
            raise ValueError("Invalid target price sequence")
        previous = target

    record["entry_price"] = entry
    record["stop_loss"] = stop
    record["targets"] = {"t1": t1, "t2": t2, "t3": t3}

    created = parse_time(signal.get("created_at"))
    entry_expiry = parse_time(signal.get("entry_expiry"))
    signal_expiry = parse_time(signal.get("expires_at"))

    if not created or not entry_expiry or not signal_expiry:
        raise ValueError("Invalid signal timestamps")

    if entry_expiry > signal_expiry:
        raise ValueError("Entry expiry is later than signal expiry")

    if entry_expiry < created:
        raise ValueError("Entry expiry is earlier than signal creation")

    if signal_expiry <= created:
        raise ValueError("Signal expiry is invalid")

    return created, entry_expiry, signal_expiry


# =========================================================
# RETURNS AND OUTCOMES
# =========================================================

def calculate_return(record):
    entry = number(record.get("entry_price"))
    exit_price = number(record.get("exit_price"))
    fee = signed_number(record.get("fee_estimate_pct"))

    if fee is None:
        fee = ROUND_TRIP_FEE_PCT

    if entry is None or exit_price is None:
        record["gross_return_pct"] = None
        record["return_pct"] = None
        return

    gross = ((exit_price - entry) / entry) * 100
    record["gross_return_pct"] = round(gross, 4)
    record["return_pct"] = round(gross - fee, 4)


def finish_signal(record, outcome, exit_price, exit_time):
    record["outcome"] = outcome
    record["exit_price"] = exit_price
    record["exit_at"] = iso(exit_time)
    calculate_return(record)


def mark_ambiguous(record, candle_close):
    record["outcome"] = "AMBIGUOUS"
    record["stop_loss_touched"] = True

    # Not a confirmed SL hit: candle event order is unknown.
    record["stop_loss_hit"] = False

    record["exit_price"] = None
    record["exit_at"] = iso(candle_close)
    record["gross_return_pct"] = None
    record["return_pct"] = None
    record["ambiguity_reason"] = (
        "The same closed 1m candle touched Stop Loss and "
        "at least one Target. Intracandle event order is unknown."
    )


def update_target_flags(record, high):
    for key in ("t1", "t2", "t3"):
        target = record["targets"].get(key)
        if target is not None and high >= target:
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
# CANDLE PROCESSING
# =========================================================

def update_signal(signal, record, now):
    created, entry_expiry, signal_expiry = validate_record(signal, record)

    symbol = str(signal.get("symbol", "")).upper()
    last_checked = parse_time(record.get("last_checked_at"))

    if last_checked:
        start_ms = int(
            (last_checked + timedelta(minutes=1)).timestamp() * 1000
        )
    else:
        start_ms = next_full_minute(created)

    now_ms = int(now.timestamp() * 1000)

    deadline = (
        min(entry_expiry, signal_expiry)
        if not record.get("entry_reached")
        else signal_expiry
    )

    deadline_ms = int(deadline.timestamp() * 1000)

    # Only fully closed candles whose close time is at/before
    # both current time and the relevant deadline are eligible.
    end_ms = min(now_ms - 1, deadline_ms - 1)

    if start_ms <= end_ms:
        candles = fetch_klines(symbol, start_ms, end_ms)

        for raw in candles:
            candle = parse_candle(raw)
            open_ms = candle["open_ms"]
            close_ms = candle["close_ms"]

            if close_ms >= now_ms or close_ms >= deadline_ms:
                continue

            candle_time = datetime.fromtimestamp(
                open_ms / 1000, timezone.utc
            )
            candle_close = datetime.fromtimestamp(
                (close_ms + 1) / 1000, timezone.utc
            )

            high = candle["high"]
            low = candle["low"]
            close_price = candle["close"]

            record["last_checked_at"] = iso(candle_time)
            record["last_closed_candle_at"] = iso(candle_close)
            record["last_closed_candle_close"] = close_price

            # BEFORE ENTRY
            if not record.get("entry_reached"):
                entry_touched = high >= record["entry_price"]
                stop_touched = low <= record["stop_loss"]

                if stop_touched and not entry_touched:
                    record["outcome"] = "INVALIDATED_BEFORE_ENTRY"
                    record["stop_loss_hit"] = False
                    record["exit_price"] = None
                    record["exit_at"] = iso(candle_close)
                    break

                if entry_touched and stop_touched:
                    record["entry_reached"] = True
                    record["entry_reached_at"] = iso(candle_time)
                    update_target_flags(record, high)
                    mark_ambiguous(record, candle_close)
                    break

                if not entry_touched:
                    continue

                record["entry_reached"] = True
                record["entry_reached_at"] = iso(candle_time)
                update_target_flags(record, high)

                if record.get("t3_hit"):
                    finish_signal(
                        record, "T3",
                        record["targets"]["t3"], candle_close
                    )
                    break

                continue

            # AFTER ENTRY
            stop_touched = low <= record["stop_loss"]

            target_touched = any(
                record["targets"].get(key) is not None
                and high >= record["targets"][key]
                for key in ("t1", "t2", "t3")
            )

            if stop_touched and target_touched:
                update_target_flags(record, high)
                mark_ambiguous(record, candle_close)
                break

            if stop_touched:
                record["stop_loss_touched"] = True
                record["stop_loss_hit"] = True
                finish_signal(
                    record,
                    stop_outcome_after_targets(record),
                    record["stop_loss"],
                    candle_close,
                )
                break

            update_target_flags(record, high)

            if record.get("t3_hit"):
                finish_signal(
                    record, "T3",
                    record["targets"]["t3"], candle_close
                )
                break

    # ENTRY WINDOW EXPIRY
    if (
        not record.get("entry_reached")
        and now >= entry_expiry
        and record.get("outcome") == "PENDING"
    ):
        if candle_coverage_complete(record, entry_expiry):
            record["entry_expired"] = True
            record["outcome"] = "ENTRY_WINDOW_EXPIRED"
            record["exit_price"] = None
            record["exit_at"] = iso(entry_expiry)
            record["data_error"] = None
        else:
            record["outcome"] = "ENTRY_WINDOW_UNVERIFIED"
            record["entry_expired"] = False
            record["data_error"] = (
                "The entry expiry falls inside an unfinished 1m "
                "interval or candle coverage is incomplete. "
                "Entry expiry cannot be verified from 1m candles."
            )

    # SIGNAL EXPIRY AFTER ENTRY
    if (
        record.get("entry_reached")
        and now >= signal_expiry
        and record.get("outcome") == "PENDING"
    ):
        if candle_coverage_complete(record, signal_expiry):
            last_close = number(
                record.get("last_closed_candle_close")
            )
            last_close_time = parse_time(
                record.get("last_closed_candle_at")
            )

            if last_close is not None and last_close_time is not None:
                finish_signal(
                    record,
                    "EXPIRED_AFTER_ENTRY",
                    last_close,
                    last_close_time,
                )
                record["data_error"] = None
            else:
                record["outcome"] = "EXPIRED_AFTER_ENTRY_UNVERIFIED"
                record["data_error"] = (
                    "No verified closed 1m candle price is available "
                    "at signal expiry."
                )
        else:
            record["outcome"] = "EXPIRED_AFTER_ENTRY_UNVERIFIED"
            record["data_error"] = (
                "Signal expiry falls inside an unfinished 1m interval "
                "or candle coverage is incomplete. No expiry return "
                "has been calculated."
            )

    if record.get("outcome") == "PENDING":
        record["data_error"] = None


# =========================================================
# SUMMARY
# =========================================================

def summarize_records(values):
    total = len(values)

    entered = sum(r.get("entry_reached") is True for r in values)
    ambiguous = sum(r.get("outcome") == "AMBIGUOUS" for r in values)

    confirmed_sl = sum(
        r.get("stop_loss_hit") is True
        and r.get("outcome") != "AMBIGUOUS"
        for r in values
    )

    t1_hits = sum(r.get("t1_hit") is True for r in values)
    t2_hits = sum(r.get("t2_hit") is True for r in values)
    t3_hits = sum(r.get("t3_hit") is True for r in values)

    completed = []
    for record in values:
        outcome = str(record.get("outcome", "")).upper()
        result = signed_number(record.get("return_pct"))
        if outcome in COMPLETED_OUTCOMES and result is not None:
            completed.append(result)

    wins = [x for x in completed if x > 0]
    losses = [x for x in completed if x < 0]
    breakeven = [x for x in completed if x == 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)
    elif gross_profit > 0:
        profit_factor = "INF"
    else:
        profit_factor = None

    return {
        "total_signals": total,
        "entry_reached": entered,
        "entry_not_reached_expired": sum(
            r.get("outcome") == "ENTRY_WINDOW_EXPIRED" for r in values
        ),
        "entry_window_unverified": sum(
            r.get("outcome") == "ENTRY_WINDOW_UNVERIFIED" for r in values
        ),
        "invalidated_before_entry": sum(
            r.get("outcome") == "INVALIDATED_BEFORE_ENTRY" for r in values
        ),
        "expired_after_entry": sum(
            r.get("outcome") == "EXPIRED_AFTER_ENTRY" for r in values
        ),
        "expired_after_entry_unverified": sum(
            r.get("outcome") == "EXPIRED_AFTER_ENTRY_UNVERIFIED"
            for r in values
        ),
        "t1_then_stop": sum(
            r.get("outcome") == "T1_THEN_STOP" for r in values
        ),
        "t2_then_stop": sum(
            r.get("outcome") == "T2_THEN_STOP" for r in values
        ),
        "ambiguous_signals": ambiguous,
        "stop_loss_hits": confirmed_sl,
        "t1_hits": t1_hits,
        "t2_hits": t2_hits,
        "t3_hits": t3_hits,
        "pending": sum(r.get("outcome") == "PENDING" for r in values),
        "data_errors": sum(bool(r.get("data_error")) for r in values),
        "completed_results": len(completed),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate_pct": (
            round(len(wins) / len(completed) * 100, 2)
            if completed else None
        ),
        "profit_factor": profit_factor,
        "average_return_pct": (
            round(sum(completed) / len(completed), 4)
            if completed else None
        ),
        "average_profit_pct": (
            round(gross_profit / len(wins), 4) if wins else None
        ),
        "average_loss_pct": (
            round(sum(losses) / len(losses), 4) if losses else None
        ),
        "total_return_pct": (
            round(sum(completed), 4) if completed else None
        ),
    }


def build_summary(records):
    values = list(records.values())
    summary = summarize_records(values)

    strategies = {}
    for record in values:
        strategy = str(record.get("strategy") or "UNKNOWN").upper()
        strategies.setdefault(strategy, []).append(record)

    summary["strategy_summary"] = {
        strategy: summarize_records(items)
        for strategy, items in sorted(strategies.items())
    }
    return summary


# =========================================================
# MAIN
# =========================================================

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

    try:
        old_version = int(analytics.get("version", 0))
    except (TypeError, ValueError):
        old_version = 0

    records = analytics.get("signals", {})
    if not isinstance(records, dict):
        records = {}

    if old_version < ANALYTICS_VERSION:
        print(
            f"Rebuilding derived analytics V{old_version} "
            f"-> V{ANALYTICS_VERSION}"
        )
        # Only derived analytics are rebuilt.
        # signal_history.json remains untouched.
        records = {}
    else:
        records = {
            key: value
            for key, value in records.items()
            if isinstance(value, dict)
            and parse_time(value.get("created_at")) is not None
            and parse_time(value.get("created_at")) >= cutoff
        }

    processed = 0
    errors = 0
    skipped = 0
    seen_ids = set()

    for signal in source_signals:
        if not isinstance(signal, dict):
            skipped += 1
            continue

        signal_id = signal.get("signal_id")
        created = parse_time(signal.get("created_at"))

        if not signal_id or not created:
            skipped += 1
            continue

        if created < cutoff:
            continue

        signal_id = str(signal_id)

        if signal_id in seen_ids:
            skipped += 1
            continue

        seen_ids.add(signal_id)

        record = records.get(signal_id)

        if record is None:
            try:
                record = create_record(signal)
                records[signal_id] = record
            except Exception as exc:
                errors += 1
                print(
                    f"WARNING: Cannot create {signal_id}: "
                    f"{str(exc)[:250]}"
                )
                continue

        if not isinstance(record, dict):
            errors += 1
            continue

        if record.get("outcome") in TERMINAL_OUTCOMES:
            continue

        try:
            update_signal(signal, record, now)
            processed += 1
        except Exception as exc:
            record["data_error"] = str(exc)[:250]
            errors += 1
            print(
                f"WARNING: {signal_id}: "
                f"{record['data_error']}"
            )

    records = {
        key: value
        for key, value in records.items()
        if isinstance(value, dict)
        and parse_time(value.get("created_at")) is not None
        and parse_time(value.get("created_at")) >= cutoff
    }

    output = {
        "version": ANALYTICS_VERSION,
        "updated_at": iso(now),
        "retention_days": RETENTION_DAYS,
        "round_trip_fee_pct": ROUND_TRIP_FEE_PCT,
        "accounting_type": "SIMULATED_CANDLE_BASED",
        "accounting_note": (
            "Estimated price performance using Binance closed 1m "
            "candles. This is not actual exchange fill PNL. "
            "Round-trip fee is estimated. Slippage, partial fills "
            "and partial target exits are not included. T1_THEN_STOP "
            "and T2_THEN_STOP use the full-position stop price. "
            "Expiry inside an unfinished 1m interval is unverified "
            "and is excluded from completed returns."
        ),
        "outcome_rules": {
            "entry": "Closed 1m candle high >= entry price",
            "stop_loss": "Closed 1m candle low <= stop price",
            "target": "Closed 1m candle high >= target price",
            "same_candle_sl_target": "AMBIGUOUS",
            "ambiguous_is_confirmed_sl": False,
            "target_then_stop": "T1_THEN_STOP or T2_THEN_STOP",
            "expiry_inside_minute": "UNVERIFIED",
            "ambiguous_in_win_rate": False,
            "ambiguous_in_profit_factor": False,
        },
        "summary": build_summary(records),
        "signals": records,
    }

    atomic_save(ANALYTICS_FILE, output)

    print("\n========== V3 SIGNAL ANALYTICS V5 ==========")
    print(json.dumps(output["summary"], indent=2, ensure_ascii=False))
    print(f"\nProcessed signals: {processed}")
    print(f"Data errors: {errors}")
    print(f"Skipped invalid/duplicate history items: {skipped}")
    print(f"Analytics version: {ANALYTICS_VERSION}")
    print(f"Saved file: {ANALYTICS_FILE}")
    print("============================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL ERROR: {exc}")
        sys.exit(1)
