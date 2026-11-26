"""
Binance Spot V3 Smart Signal Scanner
Telegram Notification Engine

- Bengali signal notifications.
- Estimated net profit at T1/T2/T3.
- Entry fee, exit fee and slippage included.
- Telegram credentials read from environment variables.
- Only STRONG BUY and EXCELLENT BUY signals are allowed.
- Safe HTML message truncation.
- Entry expiry uses the signal's original timestamp when available.
"""

import html
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from config import TELEGRAM_CONFIG, TRACKING_CONFIG


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

def _normalize_key(value):
    return (
        str(value)
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


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


BOT_TOKEN_ENV = str(
    _find_value(TELEGRAM_CONFIG, "BOT_TOKEN_ENV")
    or "TELEGRAM_BOT_TOKEN"
)

CHAT_ID_ENV = str(
    _find_value(TELEGRAM_CONFIG, "CHAT_ID_ENV")
    or "TELEGRAM_CHAT_ID"
)

REQUEST_TIMEOUT = int(
    _find_value(TELEGRAM_CONFIG, "REQUEST_TIMEOUT_SECONDS")
    or 15
)

MAX_MESSAGE_LENGTH = int(
    _find_value(TELEGRAM_CONFIG, "MAX_MESSAGE_LENGTH")
    or 4000
)

SCALP_ENTRY_VALIDITY_MINUTES = int(
    _find_value(TRACKING_CONFIG, "SCALP_ENTRY_VALIDITY_MINUTES")
    or 15
)

SWING_ENTRY_VALIDITY_MINUTES = int(
    _find_value(TRACKING_CONFIG, "SWING_ENTRY_VALIDITY_MINUTES")
    or 60
)

MAX_MESSAGE_LENGTH = max(500, min(MAX_MESSAGE_LENGTH, 4096))

REAL_B_CRYPTOS = {
    "ARBUSDT", "BNBUSDT", "SUBUSDT", "BBUSDT", "WBTCUSDT", "BUSDUSDT",
}

EXCLUDED_SPOT_SYMBOLS = {
    "USDCUSDT", "BUSDUSDT", "TUSDUSDT", "USDPUSDT",
    "FDUSDUSDT", "USD1USDT", "RLUSDUSDT", "XUSDUSDT",
    "USDEUSDT", "USDEBUSDT", "DUSDT", "AEURUSDT",
    "EURUSDT", "GBPUSDT", "AUDUSDT", "BFUSDUSDT",
    "XAUTUSDT", "PAXGUSDT", "WBTCUSDT",
    "WETHUSDT", "STETHUSDT", "CBBTCUSDT",
}


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def _number(value, default=None):
    try:
        number = float(value)
        if not math.isfinite(number):
            return default
        return number
    except (TypeError, ValueError, OverflowError):
        return default


def _format_price(value):
    number = _number(value)
    if number is None or number <= 0:
        return "N/A"
    if number >= 1000:
        return f"{number:,.4f}"
    if number >= 1:
        return f"{number:.6f}".rstrip("0").rstrip(".")
    return f"{number:.10f}".rstrip("0").rstrip(".")


def _format_usdt(value):
    number = _number(value)
    if number is None:
        return "N/A"
    return f"{number:,.4f}"


def _format_percent(value):
    number = _number(value)
    if number is None:
        return "N/A"
    return f"{number:.2f}%"


def _format_number(value, decimals=2):
    number = _number(value)
    if number is None:
        return "N/A"
    return f"{number:.{decimals}f}"


def _translate_signal(value):
    translations = {
        "STRONG BUY": "শক্তিশালী ক্রয়",
        "EXCELLENT BUY": "অত্যন্ত শক্তিশালী ক্রয়",
    }
    return translations.get(str(value).upper(), str(value))


def _translate_strategy(value):
    translations = {
        "SCALP": "স্বল্পমেয়াদি ট্রেড",
        "SWING": "সুইং ট্রেড",
    }
    return translations.get(str(value).upper(), str(value))


def _translate_market(value):
    translations = {
        "BULLISH": "ঊর্ধ্বমুখী",
        "BEARISH": "নিম্নমুখী",
        "NEUTRAL": "নিরপেক্ষ",
        "HIGH_RISK": "উচ্চ ঝুঁকি",
        "UNKNOWN": "অজানা",
    }
    return translations.get(str(value).upper(), str(value))


def _is_valid_spot_symbol(symbol):
    if not isinstance(symbol, str):
        return False

    symbol = symbol.upper().strip()

    if not re.fullmatch(r"[A-Z0-9]{2,24}USDT", symbol):
        return False

    if symbol in EXCLUDED_SPOT_SYMBOLS:
        return False

    base_asset = symbol[:-4]
    forbidden_suffixes = ("UP", "DOWN", "BULL", "BEAR")
    if base_asset.endswith(forbidden_suffixes):
        return False

    if symbol.endswith("BUSDT") and symbol not in REAL_B_CRYPTOS:
        return False

    return True


# ---------------------------------------------------------
# SAFE HTML TRUNCATION
# ---------------------------------------------------------

def _truncate_html(message, max_length):
    if len(message) <= max_length:
        return message

    tokens = re.findall(
        r"<[^>]*>|&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);|[^<&]+|.",
        message,
        flags=re.DOTALL,
    )

    output = []
    open_tags = []
    used = 0

    suffix = "\n\n[বার্তা সংক্ষিপ্ত করা হয়েছে]"
    reserve = len(suffix) + 40
    limit = max(100, max_length - reserve)

    for token in tokens:
        if used + len(token) > limit:
            break

        if token.startswith("<") and token.endswith(">"):
            closing = re.fullmatch(r"</([a-zA-Z0-9]+)\s*>", token)
            opening = re.fullmatch(r"<([a-zA-Z0-9]+)(?:\s+[^>]*)?>", token)

            if closing:
                tag_name = closing.group(1).lower()
                if tag_name in open_tags:
                    index = len(open_tags) - 1 - open_tags[::-1].index(tag_name)
                    open_tags = open_tags[:index]

            elif opening:
                tag_name = opening.group(1).lower()
                if tag_name in ("b", "strong", "i", "em", "u", "s", "code", "pre"):
                    open_tags.append(tag_name)

        output.append(token)
        used += len(token)

    result = "".join(output) + suffix

    for tag in reversed(open_tags):
        result += f"</{tag}>"

    return result[:max_length]


# ---------------------------------------------------------
# NET PROFIT CALCULATION
# ---------------------------------------------------------

def _calculate_net_profit(position, target):
    if not isinstance(position, dict) or not isinstance(target, dict):
        return None

    quantity = _number(position.get("quantity"))
    effective_entry = _number(position.get("effective_entry_price"))
    target_price = _number(target.get("price"))

    if quantity is None or quantity <= 0:
        return None
    if effective_entry is None or effective_entry <= 0:
        return None
    if target_price is None or target_price <= 0:
        return None

    fee = _number(position.get("fee_rate_per_side"))
    slippage = _number(position.get("slippage_rate_per_side"))

    if fee is None or slippage is None:
        return None
    if fee < 0 or slippage < 0 or fee >= 1 or slippage >= 1:
        return None

    exit_cost = fee + slippage
    if exit_cost >= 1:
        return None

    effective_exit = target_price * (1.0 - exit_cost)
    net_profit = quantity * (effective_exit - effective_entry)

    if not math.isfinite(net_profit):
        return None

    return net_profit


def _format_profit_line(position, target, label):
    if not isinstance(target, dict):
        return f"<b>{label} সম্ভাব্য নিট লাভ:</b> লক্ষ্য নির্ধারিত নেই"

    profit = _calculate_net_profit(position, target)
    if profit is None:
        return f"<b>{label} সম্ভাব্য নিট লাভ:</b> হিসাব করা যায়নি"

    if profit > 0:
        profit_text = f"+{_format_usdt(profit)}"
    elif profit < 0:
        profit_text = _format_usdt(profit)
    else:
        profit_text = "0.0000"

    return f"<b>{label} সম্ভাব্য নিট লাভ:</b> {profit_text} USDT"


# ---------------------------------------------------------
# CREDENTIALS
# ---------------------------------------------------------

def _get_credentials():
    token = os.getenv(BOT_TOKEN_ENV, "").strip()
    chat_id = os.getenv(CHAT_ID_ENV, "").strip()

    if not token or not chat_id:
        return None, None

    return token, chat_id


def credentials_available():
    token, chat_id = _get_credentials()
    return bool(token and chat_id)


# ---------------------------------------------------------
# TELEGRAM API
# ---------------------------------------------------------

def _telegram_request(method, payload, max_retries=2):
    token, chat_id = _get_credentials()

    if not token or not chat_id:
        logger.error("Telegram credentials are missing from environment")
        return {
            "success": False,
            "description": "Telegram credentials missing",
        }

    url = f"https://api.telegram.org/bot{token}/{method}"
    request_payload = dict(payload)
    request_payload["chat_id"] = chat_id

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                url,
                json=request_payload,
                timeout=REQUEST_TIMEOUT,
            )

            try:
                result = response.json()
            except ValueError:
                result = {}

            if (
                response.ok
                and isinstance(result, dict)
                and result.get("ok") is True
            ):
                return {
                    "success": True,
                    "description": "Message sent successfully",
                }

            description = "Telegram API request failed"
            retry_after_sec = None

            if isinstance(result, dict):
                api_description = result.get("description")
                if isinstance(api_description, str):
                    description = api_description[:300]

                params = result.get("parameters")
                if isinstance(params, dict):
                    retry_after_sec = _number(params.get("retry_after"))

            if response.status_code == 429 and attempt < max_retries:
                sleep_sec = min(max(retry_after_sec or 1.0, 0.5), 10.0)
                time.sleep(sleep_sec)
                continue

            if response.status_code >= 500 and attempt < max_retries:
                time.sleep(1.0 * (2 ** attempt))
                continue

            logger.error(
                "Telegram API error: HTTP %s - %s",
                response.status_code,
                description,
            )

            return {
                "success": False,
                "description": description,
            }

        except requests.RequestException as exc:
            if attempt < max_retries:
                time.sleep(1.0 * (2 ** attempt))
                continue

            logger.error(
                "Telegram network request failed: %s",
                type(exc).__name__,
            )

            return {
                "success": False,
                "description": "Telegram network request failed",
            }

        except Exception:
            logger.exception("Unexpected Telegram request error")
            return {
                "success": False,
                "description": "Unexpected Telegram request error",
            }

    return {
        "success": False,
        "description": "Telegram request failed",
    }


# ---------------------------------------------------------
# MESSAGE SENDING
# ---------------------------------------------------------

def send_message(
    message,
    disable_notification=False,
    parse_mode="HTML",
):
    if not isinstance(message, str) or not message.strip():
        return {
            "success": False,
            "description": "Empty message",
        }

    if len(message) > MAX_MESSAGE_LENGTH:
        if parse_mode == "HTML":
            message = _truncate_html(message, MAX_MESSAGE_LENGTH)
        else:
            message = (
                message[: MAX_MESSAGE_LENGTH - 40]
                + "\n\n[বার্তা সংক্ষিপ্ত করা হয়েছে]"
            )

    payload = {
        "text": message,
        "disable_notification": bool(disable_notification),
        "disable_web_page_preview": True,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    result = _telegram_request("sendMessage", payload)

    if not isinstance(result, dict):
        return {
            "success": False,
            "description": "Invalid Telegram response",
        }

    if result.get("success") is not True and parse_mode:
        error_desc = str(result.get("description", "")).lower()
        if "parse" in error_desc or "entit" in error_desc:
            logger.warning("HTML parsing failed; falling back to plain text.")

            plain_text = re.sub(
                r"</?(?:b|strong|i|em|u|s|code|pre)>",
                "",
                message,
                flags=re.IGNORECASE,
            )
            plain_text = html.unescape(plain_text)

            payload["text"] = plain_text
            payload.pop("parse_mode", None)
            result = _telegram_request("sendMessage", payload)

    return result


def send_connection_test():
    message = (
        "<b>BINANCE SPOT V3 SMART SIGNAL SCANNER</b>\n\n"
        "টেলিগ্রাম সংযোগ সফল হয়েছে।\n\n"
        "<b>মার্কেট:</b> Binance Spot\n"
        "<b>কোট অ্যাসেট:</b> USDT\n"
        "<b>ট্রেডিং:</b> শুধু Spot\n"
        "<b>সিগন্যাল:</b> শক্তিশালী ক্রয় / অত্যন্ত শক্তিশালী ক্রয়\n\n"
        "<i>এটি শুধু সংযোগ পরীক্ষা, "
        "কোনো ট্রেডিং সিগন্যাল নয়।</i>"
    )
    return send_message(message)


# ---------------------------------------------------------
# TIME HELPERS
# ---------------------------------------------------------

def _parse_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _format_time_utc(iso_value):
    parsed = _parse_datetime(iso_value)
    if parsed is None:
        return "N/A"
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")


def _compute_entry_expiry(signal, strategy):
    existing_expiry = _parse_datetime(signal.get("entry_expiry"))
    if existing_expiry is not None:
        return existing_expiry.isoformat()

    strategy = str(strategy).upper().strip()
    if strategy == "SCALP":
        minutes = SCALP_ENTRY_VALIDITY_MINUTES
    elif strategy == "SWING":
        minutes = SWING_ENTRY_VALIDITY_MINUTES
    else:
        raise ValueError("Unsupported trading strategy")

    generated_at = _parse_datetime(
        signal.get("generated_at") or signal.get("created_at")
    )
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    return (generated_at + timedelta(minutes=minutes)).isoformat()


# ---------------------------------------------------------
# TARGET FORMATTING
# ---------------------------------------------------------

def _format_target(target, label):
    if not isinstance(target, dict):
        return f"<b>{label}:</b> পাওয়া যায়নি"

    price = _format_price(target.get("price"))
    if price == "N/A":
        return f"<b>{label}:</b> পাওয়া যায়নি"

    rr = _number(target.get("risk_reward"))
    if rr is None or rr <= 0:
        return f"<b>{label}:</b> {price}"

    return f"<b>{label}:</b> {price} | R:R 1:{rr:.2f}"


# ---------------------------------------------------------
# SIGNAL FORMATTING
# ---------------------------------------------------------

def format_signal(signal):
    if not isinstance(signal, dict):
        raise ValueError("Signal must be a dictionary")

    classification = str(
        signal.get("classification") or signal.get("signal") or ""
    ).upper().strip()

    allowed_signals = ("STRONG BUY", "EXCELLENT BUY")
    if classification not in allowed_signals:
        raise ValueError("Only approved BUY signals are allowed")

    if str(signal.get("status", "")).upper().strip() == "REJECTED":
        raise ValueError("Rejected signals cannot be sent")

    risk_plan = signal.get("risk_plan")
    if not isinstance(risk_plan, dict):
        raise ValueError("Risk plan is missing")

    if str(risk_plan.get("status", "")).upper().strip() != "VALID":
        raise ValueError("Risk plan is not valid")

    validation = risk_plan.get("validation", {})
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise ValueError("Risk validation failed")

    symbol = str(signal.get("symbol", "")).upper().strip()
    if not _is_valid_spot_symbol(symbol):
        raise ValueError("Invalid Binance Spot USDT symbol")

    strategy = str(signal.get("strategy", "")).upper().strip()
    if strategy not in ("SCALP", "SWING"):
        raise ValueError("Unsupported trading strategy")

    score = html.escape(str(signal.get("score", "N/A")))
    max_score = html.escape(str(signal.get("max_score", 15)))

    entry = _format_price(risk_plan.get("entry_price"))
    if entry == "N/A":
        raise ValueError("Invalid entry price")

    stop_data = risk_plan.get("stop_loss", {})
    if not isinstance(stop_data, dict):
        raise ValueError("Stop Loss information missing")

    stop = _format_price(stop_data.get("stop_loss"))
    if stop == "N/A":
        raise ValueError("Invalid Stop Loss price")

    stop_pct = _format_percent(stop_data.get("risk_percent"))
    stop_method = html.escape(str(stop_data.get("method", "N/A")))

    targets = risk_plan.get("targets", {})
    if not isinstance(targets, dict):
        raise ValueError("Target information missing")

    position = risk_plan.get("position_size", {})
    if not isinstance(position, dict):
        raise ValueError("Position size information missing")

    rsi = _format_number(signal.get("rsi"), 2)
    rvol = _format_number(signal.get("rvol"), 2)

    btc_trend = _translate_market(signal.get("btc_trend", "UNKNOWN"))
    market_status = _translate_market(signal.get("market_status", "UNKNOWN"))

    raw_time = signal.get("generated_at") or signal.get("created_at")
    created_at = _format_time_utc(raw_time)

    expiry_value = _compute_entry_expiry(signal, strategy)
    entry_expiry = _format_time_utc(expiry_value)

    invested_amount = position.get("position_value_usdt")
    estimated_loss = position.get("actual_estimated_loss_usdt")
    actual_risk = position.get("actual_risk_percent")
    quantity = position.get("quantity")

    t1 = targets.get("t1")
    t2 = targets.get("t2")
    t3 = targets.get("t3")

    warnings = signal.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []

    lines = [
        "📊 <b>BINANCE SPOT V3 — ট্রেডিং সিগন্যাল</b>",
        "",
        f"<b>কয়েন:</b> <code>{html.escape(symbol)}</code>",
        f"<b>সিগন্যাল:</b> {html.escape(_translate_signal(classification))}",
        f"<b>কৌশল:</b> {html.escape(_translate_strategy(strategy))}",
        f"<b>স্কোর:</b> {score}/{max_score}",
        "",
        "📌 <b>এন্ট্রি পরিকল্পনা</b>",
        f"<b>কেনার দাম:</b> <code>{entry}</code>",
        f"<b>স্টপ লস:</b> <code>{stop}</code>",
        f"<b>স্টপ লসের দূরত্ব:</b> {stop_pct}",
        f"<b>স্টপ লসের ভিত্তি:</b> {stop_method}",
        "",
        "🎯 <b>সম্ভাব্য বিক্রির লক্ষ্য</b>",
        _format_target(t1, "T1"),
        _format_profit_line(position, t1, "T1"),
        "",
        _format_target(t2, "T2"),
        _format_profit_line(position, t2, "T2"),
        "",
        _format_target(t3, "T3"),
        _format_profit_line(position, t3, "T3"),
        "",
        "💰 <b>বিনিয়োগ ও ঝুঁকি</b>",
        f"<b>মোট বিনিয়োগ:</b> {_format_usdt(invested_amount)} USDT",
        f"<b>কয়েনের পরিমাণ:</b> {_format_number(quantity, 8)}",
        f"<b>সর্বোচ্চ নির্ধারিত ঝুঁকি:</b> {_format_percent(actual_risk)}",
        f"<b>স্টপ লসে সম্ভাব্য ক্ষতি:</b> {_format_usdt(estimated_loss)} USDT",
        "",
        (
            "<i>সম্ভাব্য নিট লাভের হিসাব থেকে বিনিয়োগের "
            "মূল টাকা বাদ দেওয়া হয়েছে। "
            "ফি ও স্লিপেজও আনুমানিকভাবে বাদ দেওয়া হয়েছে। "
            "বাস্তব লাভ বাজারদর ও অর্ডার সম্পাদনের ওপর "
            "নির্ভর করবে।</i>"
        ),
        "",
        "🌐 <b>বাজারের অবস্থা</b>",
        f"<b>BTC-এর প্রবণতা:</b> {html.escape(btc_trend)}",
        f"<b>সামগ্রিক বাজার:</b> {html.escape(market_status)}",
        "",
        "📈 <b>সূচক</b>",
        f"<b>RSI:</b> {rsi}",
        f"<b>আপেক্ষিক ভলিউম:</b> {rvol}x",
        "",
        "⏰ <b>সিগন্যালের মেয়াদ</b>",
        f"<b>তৈরির সময়:</b> {created_at}",
        f"<b>এন্ট্রির শেষ সময়:</b> {entry_expiry}",
    ]

    if warnings:
        lines.append("")
        lines.append("⚠️ <b>সতর্কতা</b>")
        for warning in warnings:
            lines.append(f"• {html.escape(str(warning))}")

    lines.extend([
        "",
        "🛑 <b>সিগন্যাল বাতিলের নিয়ম</b>",
        "দাম স্টপ লসের নিচে ক্লোজ করলে সিগন্যাল বাতিল।",
        "নির্ধারিত সময়ের মধ্যে এন্ট্রি না হলে অর্ডার বাতিল করুন।",
        "",
        "<i>মার্কেট: Binance Spot | কোট: USDT | শুধু Spot Trading</i>",
        "",
        "⚠️ অর্ডার দেওয়ার আগে Binance-এ বর্তমান দাম যাচাই করুন।",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------
# SIGNAL NOTIFICATION
# ---------------------------------------------------------

def send_signal(signal):
    try:
        message = format_signal(signal)
        result = send_message(message)

        if not isinstance(result, dict):
            logger.error("Telegram returned an invalid response")
            return {
                "success": False,
                "description": "Invalid Telegram response",
            }

        if result.get("success") is not True:
            logger.error(
                "Telegram delivery failed for %s: %s",
                signal.get("symbol", "UNKNOWN"),
                result.get("description", "Unknown error"),
            )

        return result

    except (ValueError, TypeError) as exc:
        logger.warning("Signal notification rejected: %s", str(exc))
        return {
            "success": False,
            "description": str(exc),
        }

    except Exception:
        logger.exception("Unexpected signal notification error")
        return {
            "success": False,
            "description": "Unexpected signal notification error",
        }


# ---------------------------------------------------------
# STATUS HELPERS
# ---------------------------------------------------------

def get_telegram_status():
    return {
        "credentials_available": credentials_available(),
        "bot_token_env": BOT_TOKEN_ENV,
        "chat_id_env": CHAT_ID_ENV,
        "request_timeout": REQUEST_TIMEOUT,
        "max_message_length": MAX_MESSAGE_LENGTH,
        "html_formatting": True,
        "bengali_messages": True,
        "net_profit_calculation": True,
        "scalp_entry_validity_minutes": SCALP_ENTRY_VALIDITY_MINUTES,
        "swing_entry_validity_minutes": SWING_ENTRY_VALIDITY_MINUTES,
    }
