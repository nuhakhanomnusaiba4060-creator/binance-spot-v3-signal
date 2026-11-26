
import html
import json
import logging
import math
import os
import sys
import time

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


ANALYTICS_FILE = Path("signal_analytics.json")
HISTORY_FILE = Path("signal_history.json")

TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"

DHAKA = ZoneInfo("Asia/Dhaka")

REQUEST_TIMEOUT = 20
MESSAGE_LIMIT = 3900

TELEGRAM_MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 2
MAX_RETRY_AFTER_SECONDS = 30

# Analytics-এর নির্ধারিত terminal outcomes.
COMPLETED_OUTCOMES = {
    "STOP_LOSS",
    "T3",
    "EXPIRED_AFTER_ENTRY",
}

# Analytics Snapshot এই সময়ের বেশি পুরোনো হলে সতর্কতা দেখাবে।
STALE_SNAPSHOT_MINUTES = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


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


def read_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def safe_float(value):
    try:
        result = float(value)

        if math.isfinite(result):
            return result

    except (TypeError, ValueError, OverflowError):
        pass

    return None


def fmt_price(value):
    number = safe_float(value)

    if number is None or number <= 0:
        return "N/A"

    return f"{number:.8f}".rstrip("0").rstrip(".")


def fmt_pct(value):
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"{number:+.2f}%"


def safe_text(value, default="N/A"):
    if value is None:
        return html.escape(str(default))

    return html.escape(str(value))


def normalize_outcome(record):
    return str(
        record.get("outcome", "PENDING")
    ).strip().upper()


def status_label(record):
    outcome = normalize_outcome(record)

    labels = {
        "PENDING": "চলমান",
        "STOP_LOSS": "STOP LOSS HIT",
        "T1": "T1 HIT - চলমান",
        "T2": "T2 HIT - চলমান",
        "T3": "T3 সম্পন্ন",
        "EXPIRED_AFTER_ENTRY": "Entry-এর পর মেয়াদ শেষ",
        "ENTRY_WINDOW_EXPIRED": "Entry হয়নি - Expired",
    }

    return safe_text(labels.get(outcome, outcome))


def get_snapshot_time(analytics):
    """
    Analytics updated_at-কে Report Snapshot হিসেবে ব্যবহার করে।
    Invalid timestamp হলে বর্তমান সময় দিয়ে প্রতিস্থাপন করা হবে না।
    """

    snapshot = parse_time(analytics.get("updated_at"))

    if snapshot is None:
        raise ValueError(
            "Analytics updated_at missing or invalid. "
            "Cannot create a reliable report cutoff."
        )

    return snapshot


def get_snapshot_warning(snapshot):
    """
    Snapshot পুরোনো হলে সতর্কতা দেখায়।
    Report cutoff পরিবর্তন করে না।
    """

    now = datetime.now(timezone.utc)
    age_seconds = (now - snapshot).total_seconds()

    if age_seconds < 0:
        return "⚠️ Analytics Snapshot ভবিষ্যতের সময় দেখাচ্ছে।"

    age_minutes = age_seconds / 60

    if age_minutes > STALE_SNAPSHOT_MINUTES:
        return (
            "⚠️ Analytics Data পুরোনো: "
            f"প্রায় {age_minutes:.0f} মিনিট আগে আপডেট হয়েছে।"
        )

    return None


def get_recent_signals(analytics, history, snapshot):
    records = analytics.get("signals", {})

    if not isinstance(records, dict):
        raise ValueError("Invalid analytics signals data")

    history_signals = history.get("signals", [])

    if not isinstance(history_signals, list):
        raise ValueError("Invalid history signals data")

    score_map = {}

    for item in history_signals:

        if not isinstance(item, dict):
            continue

        signal_id = item.get("signal_id")

        if signal_id:
            score_map[str(signal_id)] = item.get("score")

    start = snapshot - timedelta(hours=24)

    recent = []

    for signal_id, record in records.items():

        if not isinstance(record, dict):
            continue

        created = parse_time(record.get("created_at"))

        if created is None:
            continue

        if not (start <= created <= snapshot):
            continue

        item = dict(record)

        item["_signal_id"] = str(signal_id)
        item["_created"] = created
        item["_score"] = score_map.get(str(signal_id))
        item["_outcome"] = normalize_outcome(item)

        item["_return"] = safe_float(
            item.get("return_pct")
        )

        item["_strategy"] = str(
            item.get("strategy", "UNKNOWN")
        ).strip().upper() or "UNKNOWN"

        recent.append(item)

    recent.sort(
        key=lambda item: item["_created"]
    )

    return recent, start


def is_entry_expired(item):
    """
    Entry expiry-কে Final Loss হিসেবে গণনা করা হবে না।
    """

    if item["_outcome"] == "ENTRY_WINDOW_EXPIRED":
        return True

    return (
        item.get("entry_expired") is True
        and item.get("entry_reached") is not True
    )


def is_completed(item):
    return (
        item["_outcome"] in COMPLETED_OUTCOMES
        and item["_return"] is not None
    )


def calculate_statistics(recent):
    total = len(recent)

    entered = sum(
        item.get("entry_reached") is True
        for item in recent
    )

    expired = sum(
        is_entry_expired(item)
        for item in recent
    )

    expired_after_entry = sum(
        item["_outcome"] == "EXPIRED_AFTER_ENTRY"
        for item in recent
    )

    pending = sum(
        item["_outcome"] == "PENDING"
        for item in recent
    )

    sl_hits = sum(
        item.get("stop_loss_hit") is True
        for item in recent
    )

    t1_hits = sum(
        item.get("t1_hit") is True
        for item in recent
    )

    t2_hits = sum(
        item.get("t2_hit") is True
        for item in recent
    )

    t3_hits = sum(
        item.get("t3_hit") is True
        for item in recent
    )

    data_errors = sum(
        bool(item.get("data_error"))
        for item in recent
    )

    completed = [
        item for item in recent
        if is_completed(item)
    ]

    wins = [
        item for item in completed
        if item["_return"] > 0
    ]

    losses = [
        item for item in completed
        if item["_return"] < 0
    ]

    breakeven = [
        item for item in completed
        if item["_return"] == 0
    ]

    returns = [
        item["_return"]
        for item in completed
    ]

    average_return = (
        sum(returns) / len(returns)
        if returns else None
    )

    average_profit = (
        sum(item["_return"] for item in wins) / len(wins)
        if wins else None
    )

    average_loss = (
        sum(item["_return"] for item in losses) / len(losses)
        if losses else None
    )

    total_return = (
        sum(returns)
        if returns else None
    )

    best = (
        max(completed, key=lambda item: item["_return"])
        if completed else None
    )

    worst = (
        min(completed, key=lambda item: item["_return"])
        if completed else None
    )

    return {
        "total": total,
        "entered": entered,
        "expired": expired,
        "expired_after_entry": expired_after_entry,
        "pending": pending,
        "sl_hits": sl_hits,
        "t1_hits": t1_hits,
        "t2_hits": t2_hits,
        "t3_hits": t3_hits,
        "data_errors": data_errors,
        "completed": completed,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "average_return": average_return,
        "average_profit": average_profit,
        "average_loss": average_loss,
        "total_return": total_return,
        "best": best,
        "worst": worst,
    }


def calculate_strategy_statistics(recent):
    """
    SCALP, SWING এবং UNKNOWN আলাদা করে হিসাব করে।
    """

    strategies = {}

    for item in recent:
        strategy = item["_strategy"]

        strategies.setdefault(strategy, []).append(item)

    result = {}

    for strategy, items in sorted(strategies.items()):
        result[strategy] = calculate_statistics(items)

    return result


def signal_result_text(item):
    result = item["_return"]

    if result is None:
        return "N/A"

    if result > 0:
        return "WIN"

    if result < 0:
        return "LOSS"

    return "BREAK EVEN"


def signal_block(index, item):
    symbol = safe_text(
        item.get("symbol", "UNKNOWN")
    )

    classification = safe_text(
        item.get("classification")
    )

    strategy = safe_text(
        item.get("strategy")
    )

    signal_id = safe_text(
        item.get("_signal_id")
    )

    created = item["_created"].astimezone(DHAKA)

    score = item.get("_score")

    score_text = (
        safe_text(score)
        if score is not None else "N/A"
    )

    targets = item.get("targets") or {}

    if not isinstance(targets, dict):
        targets = {}

    milestones = []

    for key in ("t1", "t2", "t3"):

        if item.get(f"{key}_hit") is True:
            milestones.append(key.upper() + " HIT")

    if item.get("stop_loss_hit") is True:
        milestones.append("SL HIT")

    milestone_text = (
        ", ".join(milestones)
        if milestones else "কোনো Target/SL Hit নেই"
    )

    if item.get("entry_reached") is True:
        entry_status = "ENTRY HIT"

    elif is_entry_expired(item):
        entry_status = "ENTRY EXPIRED"

    else:
        entry_status = "NOT HIT"

    lines = [
        f"<b>{index}. {symbol}</b>",
        f"Signal ID: {signal_id}",
        f"Signal: {classification}",
        f"Strategy: {strategy} | Score: {score_text}",
        f"সময়: {created:%H:%M:%S %d-%m-%Y}",
        "",
        f"Entry: {fmt_price(item.get('entry_price'))}",
        f"Stop Loss: {fmt_price(item.get('stop_loss'))}",
        f"T1: {fmt_price(targets.get('t1'))}",
        f"T2: {fmt_price(targets.get('t2'))}",
        f"T3: {fmt_price(targets.get('t3'))}",
        "",
        f"Entry Status: <b>{entry_status}</b>",
        f"Target Status: {safe_text(milestone_text)}",
        f"Final Result: <b>{status_label(item)}</b>",
        f"Win/Loss: <b>{signal_result_text(item)}</b>",
        f"Return: <b>{fmt_pct(item.get('return_pct'))}</b>",
    ]

    if item.get("data_error"):
        lines.append(
            "⚠️ Data Error: "
            + safe_text(str(item["data_error"])[:150])
        )

    return "\n".join(lines)


def strategy_summary_block(strategy_stats):
    lines = [
        "━━━━━━━━━━━━━━━━",
        "📊 <b>STRATEGY-WISE PERFORMANCE</b>",
        "━━━━━━━━━━━━━━━━",
    ]

    if not strategy_stats:
        lines.append("Strategy Data পাওয়া যায়নি।")
        return "\n".join(lines)

    for strategy, stats in strategy_stats.items():

        completed_count = len(stats["completed"])

        if completed_count:
            win_rate = (
                len(stats["wins"])
                / completed_count
                * 100
            )
            win_rate_text = f"{win_rate:.2f}%"
        else:
            win_rate_text = "N/A"

        lines.extend([
            "",
            f"<b>{safe_text(strategy)}</b>",
            f"মোট Signal: {stats['total']}",
            f"Entry Hit: {stats['entered']}",
            f"Entry Expired: {stats['expired']}",
            f"SL Hit: {stats['sl_hits']}",
            f"T1/T2/T3: "
            f"{stats['t1_hits']}/{stats['t2_hits']}/{stats['t3_hits']}",
            f"Completed: {completed_count}",
            f"Win/Loss/BE: "
            f"{len(stats['wins'])}/"
            f"{len(stats['losses'])}/"
            f"{len(stats['breakeven'])}",
            f"Win Rate: {win_rate_text}",
            f"Average Return: {fmt_pct(stats['average_return'])}",
        ])

    return "\n".join(lines)


def build_report(analytics, history):
    snapshot = get_snapshot_time(analytics)

    recent, start = get_recent_signals(
        analytics,
        history,
        snapshot,
    )

    stats = calculate_statistics(recent)

    strategy_stats = calculate_strategy_statistics(recent)

    start_local = start.astimezone(DHAKA)
    end_local = snapshot.astimezone(DHAKA)

    snapshot_warning = get_snapshot_warning(snapshot)

    blocks = []

    header = [
        "📊 <b>BINANCE SPOT V3</b>",
        "📅 <b>২৪ ঘণ্টার SIGNAL REPORT</b>",
        "",
        f"সময়: {start_local:%d-%m-%Y %H:%M:%S}",
        f"থেকে: {end_local:%d-%m-%Y %H:%M:%S}",
        "(বাংলাদেশ সময়)",
        "",
    ]

    if snapshot_warning:
        header.extend([
            safe_text(snapshot_warning),
            "",
        ])

    header.extend([
        "━━━━━━━━━━━━━━━━",
        "📈 <b>সার্বিক পরিসংখ্যান</b>",
        "━━━━━━━━━━━━━━━━",
        f"মোট সিগন্যাল: <b>{stats['total']}</b>",
        f"Entry Hit: <b>{stats['entered']}</b>",
        f"Entry Expired: <b>{stats['expired']}</b>",
        f"Entry-এর পর Expired: <b>{stats['expired_after_entry']}</b>",
        f"Pending: <b>{stats['pending']}</b>",
        f"Data Error: <b>{stats['data_errors']}</b>",
        "",
        f"Stop Loss Hit: <b>{stats['sl_hits']}</b>",
        f"T1 Hit: <b>{stats['t1_hits']}</b>",
        f"T2 Hit: <b>{stats['t2_hits']}</b>",
        f"T3 Hit: <b>{stats['t3_hits']}</b>",
        "",
        f"Completed: <b>{len(stats['completed'])}</b>",
        f"Win: <b>{len(stats['wins'])}</b>",
        f"Loss: <b>{len(stats['losses'])}</b>",
        f"Break Even: <b>{len(stats['breakeven'])}</b>",
    ])

    if stats["completed"]:

        win_rate = (
            len(stats["wins"])
            / len(stats["completed"])
            * 100
        )

        header.extend([
            f"Win Rate: <b>{win_rate:.2f}%</b>",
            f"Average Return: <b>{fmt_pct(stats['average_return'])}</b>",
            f"Average Profit: <b>{fmt_pct(stats['average_profit'])}</b>",
            f"Average Loss: <b>{fmt_pct(stats['average_loss'])}</b>",
            f"Completed Return-এর যোগফল: <b>{fmt_pct(stats['total_return'])}</b>",
        ])

    else:
        header.extend([
            "Win Rate: <b>N/A</b>",
            "Average Return: <b>N/A</b>",
            "Average Profit: <b>N/A</b>",
            "Average Loss: <b>N/A</b>",
            "Completed Return-এর যোগফল: <b>N/A</b>",
        ])

    header.extend([
        "USDT Net PNL: <b>তথ্য সংরক্ষিত নেই</b>",
        "",
        "━━━━━━━━━━━━━━━━",
        "🏆 <b>BEST / WORST SIGNAL</b>",
        "━━━━━━━━━━━━━━━━",
    ])

    if stats["best"]:

        best = stats["best"]
        worst = stats["worst"]

        header.extend([
            (
                f"Best: <b>{safe_text(best.get('symbol'))}</b> "
                f"({fmt_pct(best.get('return_pct'))})"
            ),
            (
                f"Worst: <b>{safe_text(worst.get('symbol'))}</b> "
                f"({fmt_pct(worst.get('return_pct'))})"
            ),
        ])

    else:
        header.append("Completed ফলাফল নেই।")

    blocks.append("\n".join(header))

    blocks.append(
        strategy_summary_block(strategy_stats)
    )

    blocks.append(
        "\n".join([
            "━━━━━━━━━━━━━━━━",
            "🪙 <b>COIN-WISE SIGNAL DETAILS</b>",
            "━━━━━━━━━━━━━━━━",
        ])
    )

    if not recent:
        blocks.append(
            "গত ২৪ ঘণ্টায় কোনো সিগন্যাল পাওয়া যায়নি।"
        )

    else:

        for index, item in enumerate(recent, 1):
            blocks.append(
                signal_block(index, item)
            )

    footer = [
        "━━━━━━━━━━━━━━━━",
        "ℹ️ <b>গুরুত্বপূর্ণ তথ্য</b>",
        "",
        "Entry Hit মানে Binance-এর বন্ধ ১-মিনিটের Candle-এ Entry Price স্পর্শ করেছে।",
        "এটি বাস্তবে Buy Order সম্পন্ন হওয়ার প্রমাণ নয়।",
        "",
        "T1/T2/T3 ও SL Hit আলাদা Price Touch হিসাব।",
        "একটি Signal Target Hit করার পরেও Stop Loss Hit করতে পারে।",
        "",
        "Win Rate = Win ÷ Completed × 100।",
        "এই হিসাবে Break-even Completed-এর মধ্যে অন্তর্ভুক্ত।",
        "",
        "Entry Expired-কে Loss হিসেবে গণনা করা হয়নি।",
        "Expired After Entry-এর Return একটি হিসাবভিত্তিক ফল; প্রকৃত Sell Order নয়।",
        "",
        "USDT Net PNL দেখানো হয়নি, কারণ প্রকৃত বিনিয়োগের পরিমাণ, Quantity ও Fee সংরক্ষিত নেই।",
        "",
        "Report cutoff: Analytics Snapshot-এর updated_at।",
    ]

    blocks.append("\n".join(footer))

    return blocks


def split_message(blocks):
    """
    Paragraph boundary-তে Message ভাগ করে।
    HTML tag ভেঙে পাঠানো হবে না।
    """

    chunks = []
    current = ""

    for block in blocks:

        candidate = (
            block if not current
            else current + "\n\n" + block
        )

        if len(candidate) <= MESSAGE_LIMIT:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) > MESSAGE_LIMIT:
            raise ValueError(
                "A single report section exceeds Telegram message limit"
            )

        current = block

    if current:
        chunks.append(current)

    return chunks


def send_telegram(blocks):
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
        )

    url = TELEGRAM_URL.format(token)

    chunks = split_message(blocks)

    with requests.Session() as session:

        for index, chunk in enumerate(chunks, 1):

            sent = False

            for attempt in range(1, TELEGRAM_MAX_ATTEMPTS + 1):

                try:
                    response = session.post(
                        url,
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                        },
                        timeout=REQUEST_TIMEOUT,
                    )

                    if (
                        response.status_code == 429
                        or response.status_code >= 500
                    ):
                        if attempt == TELEGRAM_MAX_ATTEMPTS:
                            response.raise_for_status()

                        retry_after = None

                        try:
                            body = response.json()
                            retry_after = safe_float(
                                body.get("parameters", {}).get(
                                    "retry_after"
                                )
                            )
                        except (ValueError, AttributeError):
                            pass

                        if retry_after is None:
                            retry_after = (
                                RETRY_BASE_SECONDS ** attempt
                            )

                        retry_after = min(
                            max(retry_after, 1),
                            MAX_RETRY_AFTER_SECONDS,
                        )

                        logging.warning(
                            "Telegram temporary error on part %s. "
                            "Retry %s/%s after %.1f seconds.",
                            index,
                            attempt,
                            TELEGRAM_MAX_ATTEMPTS,
                            retry_after,
                        )

                        time.sleep(retry_after)
                        continue

                    response.raise_for_status()

                    try:
                        result = response.json()

                    except ValueError as exc:
                        raise RuntimeError(
                            "Telegram returned invalid JSON"
                        ) from exc

                    if (
                        not isinstance(result, dict)
                        or result.get("ok") is not True
                    ):
                        raise RuntimeError(
                            f"Telegram rejected message part {index}"
                        )

                    sent = True
                    break

                except requests.RequestException:

                    if attempt == TELEGRAM_MAX_ATTEMPTS:
                        raise

                    delay = RETRY_BASE_SECONDS ** attempt

                    logging.warning(
                        "Telegram network error on part %s. "
                        "Retry %s/%s after %s seconds.",
                        index,
                        attempt,
                        TELEGRAM_MAX_ATTEMPTS,
                        delay,
                    )

                    time.sleep(delay)

            if not sent:
                raise RuntimeError(
                    f"Telegram message part {index} was not sent"
                )

            logging.info(
                "Telegram report part %s/%s sent",
                index,
                len(chunks),
            )


def main():
    if not ANALYTICS_FILE.exists():
        raise FileNotFoundError(
            "signal_analytics.json not found"
        )

    if not HISTORY_FILE.exists():
        raise FileNotFoundError(
            "signal_history.json not found"
        )

    analytics = read_json(ANALYTICS_FILE)
    history = read_json(HISTORY_FILE)

    if not isinstance(analytics, dict):
        raise ValueError("Invalid analytics JSON")

    if not isinstance(history, dict):
        raise ValueError("Invalid history JSON")

    blocks = build_report(
        analytics,
        history,
    )

    send_telegram(blocks)

    logging.info(
        "24-hour Telegram report sent successfully"
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:
        logging.exception(
            "24-hour report failed: %s",
            exc,
        )

        sys.exit(1)
