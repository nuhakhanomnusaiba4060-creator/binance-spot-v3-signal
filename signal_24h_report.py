
import html
import json
import logging
import os
import sys
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


def fmt_price(value):
    try:
        number = float(value)

        if not (0 < number < float("inf")):
            return "N/A"

        return f"{number:.8f}".rstrip("0").rstrip(".")

    except (TypeError, ValueError, OverflowError):
        return "N/A"


def fmt_pct(value):
    try:
        number = float(value)

        if not (-float("inf") < number < float("inf")):
            return "N/A"

        return f"{number:+.2f}%"

    except (TypeError, ValueError, OverflowError):
        return "N/A"


def safe_float(value):
    try:
        number = float(value)

        if -float("inf") < number < float("inf"):
            return number

    except (TypeError, ValueError, OverflowError):
        pass

    return None


def status_label(record):
    outcome = str(
        record.get("outcome", "PENDING")
    ).upper()

    labels = {
        "PENDING": "চলমান",
        "STOP_LOSS": "STOP LOSS HIT",
        "T1": "T1 সম্পন্ন",
        "T2": "T2 সম্পন্ন",
        "T3": "T3 সম্পন্ন",
        "EXPIRED_AFTER_ENTRY": "Entry-এর পর মেয়াদ শেষ",
        "ENTRY_WINDOW_EXPIRED": "Entry হয়নি — Expired",
    }

    return labels.get(outcome, outcome)


def split_message(message):
    if len(message) <= MESSAGE_LIMIT:
        return [message]

    chunks = []
    current = ""

    for block in message.split("\n\n"):
        candidate = (
            block if not current
            else current + "\n\n" + block
        )

        if len(candidate) <= MESSAGE_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)

            while len(block) > MESSAGE_LIMIT:
                chunks.append(block[:MESSAGE_LIMIT])
                block = block[MESSAGE_LIMIT:]

            current = block

    if current:
        chunks.append(current)

    return chunks


def build_report(analytics, history):
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)

    records = analytics.get("signals", {})

    if not isinstance(records, dict):
        raise ValueError("Invalid analytics signals data")

    history_signals = history.get("signals", [])

    score_map = {}

    if isinstance(history_signals, list):
        for item in history_signals:
            if isinstance(item, dict):
                signal_id = item.get("signal_id")

                if signal_id:
                    score_map[signal_id] = item.get("score")

    recent = []

    for signal_id, record in records.items():

        if not isinstance(record, dict):
            continue

        created = parse_time(record.get("created_at"))

        if created is None:
            continue

        if start <= created <= now:

            item = dict(record)

            item["_signal_id"] = signal_id
            item["_created"] = created
            item["_score"] = score_map.get(signal_id)

            recent.append(item)

    recent.sort(key=lambda item: item["_created"])

    total = len(recent)

    entered = sum(
        bool(item.get("entry_reached"))
        for item in recent
    )

    expired = sum(
        item.get("outcome") == "ENTRY_WINDOW_EXPIRED"
        for item in recent
    )

    pending = sum(
        item.get("outcome", "PENDING") == "PENDING"
        for item in recent
    )

    sl_hits = sum(
        bool(item.get("stop_loss_hit"))
        for item in recent
    )

    t1_hits = sum(
        bool(item.get("t1_hit"))
        for item in recent
    )

    t2_hits = sum(
        bool(item.get("t2_hit"))
        for item in recent
    )

    t3_hits = sum(
        bool(item.get("t3_hit"))
        for item in recent
    )

    completed = []

    for item in recent:
        result = safe_float(item.get("return_pct"))

        if result is not None:
            completed.append(result)

    wins = sum(value > 0 for value in completed)
    losses = sum(value < 0 for value in completed)

    avg_return = (
        sum(completed) / len(completed)
        if completed else None
    )

    total_return = (
        sum(completed)
        if completed else None
    )

    start_local = start.astimezone(DHAKA)
    end_local = now.astimezone(DHAKA)

    lines = [
        "📊 <b>BINANCE SPOT V3</b>",
        "📅 <b>২৪ ঘণ্টার SIGNAL REPORT</b>",
        "",
        f"সময়: {start_local:%d-%m-%Y %H:%M}",
        f"থেকে: {end_local:%d-%m-%Y %H:%M}",
        "(বাংলাদেশ সময়)",
        "",
        "━━━━━━━━━━━━━━━━",
        "📈 <b>সার্বিক পরিসংখ্যান</b>",
        "━━━━━━━━━━━━━━━━",
        f"মোট সিগন্যাল: <b>{total}</b>",
        f"Entry Hit: <b>{entered}</b>",
        f"Entry Expired: <b>{expired}</b>",
        f"Pending: <b>{pending}</b>",
        f"Stop Loss Hit: <b>{sl_hits}</b>",
        "",
        f"T1 Hit: <b>{t1_hits}</b>",
        f"T2 Hit: <b>{t2_hits}</b>",
        f"T3 Hit: <b>{t3_hits}</b>",
        "",
        f"Completed: <b>{len(completed)}</b>",
        f"Win: <b>{wins}</b>",
        f"Loss: <b>{losses}</b>",
        (
            f"Win Rate: <b>{wins / len(completed) * 100:.2f}%</b>"
            if completed else
            "Win Rate: <b>N/A</b>"
        ),
        f"Average Return: <b>{fmt_pct(avg_return)}</b>",
        f"Completed Return-এর যোগফল: <b>{fmt_pct(total_return)}</b>",
        "USDT Net PNL: <b>তথ্য সংরক্ষিত নেই</b>",
        "",
        "━━━━━━━━━━━━━━━━",
        "🪙 <b>COIN-WISE SIGNAL DETAILS</b>",
        "━━━━━━━━━━━━━━━━",
    ]

    if not recent:
        lines.append("গত ২৪ ঘণ্টায় কোনো সিগন্যাল পাওয়া যায়নি।")

    for index, item in enumerate(recent, 1):

        symbol = html.escape(
            str(item.get("symbol", "UNKNOWN"))
        )

        classification = html.escape(
            str(item.get("classification", "N/A"))
        )

        strategy = html.escape(
            str(item.get("strategy", "N/A"))
        )

        created = item["_created"].astimezone(DHAKA)

        score = item.get("_score")

        score_text = (
            f"{html.escape(str(score))}/15"
            if score is not None else "N/A"
        )

        targets = item.get("targets") or {}

        if not isinstance(targets, dict):
            targets = {}

        milestones = []

        for key in ("t1", "t2", "t3"):
            if item.get(f"{key}_hit"):
                milestones.append(key.upper() + " HIT")

        if item.get("stop_loss_hit"):
            milestones.append("SL HIT")

        milestone_text = (
            ", ".join(milestones)
            if milestones else "এখনো কোনো Target/SL hit হয়নি"
        )

        if item.get("entry_reached"):
            entry_status = "ENTRY HIT"
        elif item.get("entry_expired"):
            entry_status = "ENTRY EXPIRED"
        else:
            entry_status = "NOT HIT"

        lines.extend([
            "",
            f"<b>{index}. {symbol}</b>",
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
            f"Target Status: {html.escape(milestone_text)}",
            f"Final Result: <b>{html.escape(status_label(item))}</b>",
            f"Return: <b>{fmt_pct(item.get('return_pct'))}</b>",
        ])

        if item.get("data_error"):
            lines.append(
                "⚠️ Data Error: "
                + html.escape(str(item["data_error"])[:150])
            )

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━",
        "ℹ️ <b>গুরুত্বপূর্ণ তথ্য</b>",
        "",
        "Entry Hit মানে Binance-এর বন্ধ ১-মিনিটের Candle-এ Entry Price স্পর্শ করেছে।",
        "এটি বাস্তবে Buy Order সম্পন্ন হওয়ার প্রমাণ নয়।",
        "",
        "T1/T2/T3 Hit আলাদা হিসাব করা হয়েছে।",
        "Pending সিগন্যালকে Win বা Loss ধরা হয়নি।",
        "",
        "USDT Net PNL দেখানো হয়নি, কারণ Analytics-এ প্রতিটি সিগন্যালের প্রকৃত বিনিয়োগ ও ফি সংরক্ষিত নেই।",
    ])

    return "\n".join(lines)


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
        )

    url = TELEGRAM_URL.format(token)

    chunks = split_message(message)

    for index, chunk in enumerate(chunks, 1):

        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError(
                f"Telegram rejected message part {index}"
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

    report = build_report(analytics, history)

    send_telegram(report)

    logging.info("24-hour Telegram report sent successfully")


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        logging.exception("24-hour report failed: %s", exc)
        sys.exit(1)
