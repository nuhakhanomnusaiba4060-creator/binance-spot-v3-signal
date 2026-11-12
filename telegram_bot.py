"""
Binance Spot V3 Smart Signal Scanner
Telegram Notification Engine

Responsibilities:
- Read Telegram credentials from environment variables.
- Send Telegram connection test messages.
- Format STRONG BUY and EXCELLENT BUY signals with full context.
- Send signal notifications with HTML formatting.
- Never expose bot credentials in logs or messages.
"""

import os
import logging
import html
from datetime import datetime, timezone, timedelta

import requests

from config import TELEGRAM_CONFIG, TRACKING_CONFIG


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

def _normalize_key(value):
    return str(value).lower().replace("_", "").replace("-", "").replace(" ", "")


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
    _find_value(TELEGRAM_CONFIG, "REQUEST_TIMEOUT_SECONDS") or 15
)

MAX_MESSAGE_LENGTH = int(
    _find_value(TELEGRAM_CONFIG, "MAX_MESSAGE_LENGTH") or 4000
)

SCALP_ENTRY_VALIDITY_MINUTES = int(
    _find_value(TRACKING_CONFIG, "SCALP_ENTRY_VALIDITY_MINUTES") or 15
)

SWING_ENTRY_VALIDITY_MINUTES = int(
    _find_value(TRACKING_CONFIG, "SWING_ENTRY_VALIDITY_MINUTES") or 60
)


# ---------------------------------------------------------
# CREDENTIALS
# ---------------------------------------------------------

def _get_credentials():
    """
    Read credentials from environment variables.
    Never print or log the actual credentials.
    """
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

def _telegram_request(method, payload):
    """
    Send a request to Telegram Bot API.

    Returns:
        {
            "success": bool,
            "description": str
        }
    """

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

        if isinstance(result, dict):
            description = str(result.get("description", description))

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
        logger.error(
            "Telegram network request failed: %s",
            type(exc).__name__,
        )

        return {
            "success": False,
            "description": "Telegram network request failed",
        }


# ---------------------------------------------------------
# MESSAGE SENDING
# ---------------------------------------------------------

def send_message(
    message,
    disable_notification=False,
    parse_mode="HTML",
):
    """
    Send a message to the configured Telegram chat.

    Default parse mode is HTML for nice formatting.
    Falls back to plain text if HTML parsing fails.
    """

    if not isinstance(message, str) or not message.strip():
        return {
            "success": False,
            "description": "Empty message",
        }

    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[: MAX_MESSAGE_LENGTH - 30]
        message += "\n\n[Message shortened]"

    payload = {
        "text": message,
        "disable_notification": bool(disable_notification),
        "disable_web_page_preview": True,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    result = _telegram_request("sendMessage", payload)

    # Fallback to plain text if HTML parsing fails
    if not result.get("success") and parse_mode:
        error_desc = str(result.get("description", "")).lower()

        if "parse" in error_desc or "entit" in error_desc:
            logger.warning(
                "HTML parsing failed; falling back to plain text."
            )

            payload.pop("parse_mode", None)
            result = _telegram_request("sendMessage", payload)

    return result


def send_connection_test():
    """
    Send a separate Telegram connection test message.
    """

    message = (
        "<b>BINANCE SPOT V3 SMART SIGNAL SCANNER</b>\n\n"
        "Telegram connection test successful.\n\n"
        "<b>Market:</b> Binance Spot\n"
        "<b>Quote Asset:</b> USDT\n"
        "<b>Mode:</b> Spot Only\n"
        "<b>Signal Types:</b> STRONG BUY / EXCELLENT BUY\n"
        "<b>Scoring:</b> 15-point model\n\n"
        "<i>This is a connection test, not a trading signal.</i>"
    )

    return send_message(message)


# ---------------------------------------------------------
# FORMATTING HELPERS
# ---------------------------------------------------------

def _format_price(value):
    if value is None:
        return "N/A"

    try:
        number = float(value)

        if number <= 0:
            return "N/A"

        if number >= 1000:
            return f"{number:,.4f}"

        if number >= 1:
            return f"{number:.6f}".rstrip("0").rstrip(".")

        return f"{number:.10f}".rstrip("0").rstrip(".")

    except (TypeError, ValueError):
        return "N/A"


def _format_percent(value):
    if value is None:
        return "N/A"

    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _format_number(value, decimals=2):
    if value is None:
        return "N/A"

    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def _format_target(target, label):
    if not isinstance(target, dict):
        return f"<b>{label}:</b> N/A"

    price = _format_price(target.get("price"))
    rr = target.get("risk_reward")

    if rr is None:
        return f"<b>{label}:</b> {price}"

    try:
        return f"<b>{label}:</b> {price} | R:R 1:{float(rr):.2f}"
    except (TypeError, ValueError):
        return f"<b>{label}:</b> {price}"


def _format_time_utc(iso_value):
    if not iso_value:
        return "N/A"

    try:
        parsed = datetime.fromisoformat(
            str(iso_value).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    except (TypeError, ValueError):
        return "N/A"


def _compute_entry_expiry(strategy):
    """
    Compute entry expiry from now based on strategy.
    """
    minutes = (
        SCALP_ENTRY_VALIDITY_MINUTES
        if strategy == "SCALP"
        else SWING_ENTRY_VALIDITY_MINUTES
    )

    return (
        datetime.now(timezone.utc) + timedelta(minutes=minutes)
    ).isoformat()


# ---------------------------------------------------------
# SIGNAL FORMATTING
# ---------------------------------------------------------

def format_signal(signal):
    """
    Format an approved signal into a readable HTML Telegram message.

    Includes all spec-required fields:
    - Symbol, Strategy, Classification, Score
    - Entry, Stop Loss, T1, T2, T3, R:R
    - Position risk, loss, value
    - RSI, Relative Volume
    - BTC trend and market status
    - Creation time, Entry expiry
    - Invalidation condition
    """

    if not isinstance(signal, dict):
        raise ValueError("Signal must be a dictionary")

    classification = str(
        signal.get("classification") or signal.get("signal") or ""
    ).upper()

    allowed_signals = ("STRONG BUY", "EXCELLENT BUY")

    if classification not in allowed_signals:
        raise ValueError("Only STRONG BUY and EXCELLENT BUY are allowed")

    if signal.get("status") == "REJECTED":
        raise ValueError("Rejected signals cannot be sent")

    risk_plan = signal.get("risk_plan")

    if not isinstance(risk_plan, dict):
        raise ValueError("Risk plan is missing")

    if risk_plan.get("status") != "VALID":
        raise ValueError("Risk plan is not valid")

    validation = risk_plan.get("validation", {})

    if not isinstance(validation, dict):
        raise ValueError("Risk validation is missing")

    if validation.get("valid") is not True:
        raise ValueError("Risk validation failed")

    symbol = str(signal.get("symbol", "UNKNOWN")).upper()

    if not symbol.endswith("USDT"):
        raise ValueError("Only USDT symbols are allowed")

    strategy = str(signal.get("strategy", "UNKNOWN")).upper()

    # 🔥 Dynamic score display (works for 15-point system)
    score = signal.get("score", "N/A")
    max_score = signal.get("max_score", 15)

    entry = _format_price(risk_plan.get("entry_price"))

    stop_data = risk_plan.get("stop_loss", {})

    if not isinstance(stop_data, dict):
        raise ValueError("Stop Loss information missing")

    stop = _format_price(stop_data.get("stop_loss"))
    stop_pct = _format_percent(stop_data.get("risk_percent"))
    stop_method = stop_data.get("method", "N/A")

    targets = risk_plan.get("targets", {})

    if not isinstance(targets, dict):
        raise ValueError("Target information missing")

    position = risk_plan.get("position_size", {})

    if not isinstance(position, dict):
        raise ValueError("Position size information missing")

    # 🔥 Indicators
    rsi = _format_number(signal.get("rsi"), 2)
    rvol = _format_number(signal.get("rvol"), 2)

    # 🔥 Market context
    btc_trend = str(signal.get("btc_trend", "UNKNOWN")).upper()
    market_status = str(signal.get("market_status", "UNKNOWN")).upper()

    # 🔥 Times
    created_at = _format_time_utc(signal.get("generated_at"))
    entry_expiry = _format_time_utc(
        signal.get("entry_expiry") or _compute_entry_expiry(strategy)
    )

    # 🔥 Warnings
    warnings = signal.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []

    lines = [
        "<b>BINANCE SPOT V3 SMART SIGNAL</b>",
        "",
        f"<b>Coin:</b> <code>{html.escape(symbol)}</code>",
        f"<b>Signal:</b> {html.escape(classification)}",
        f"<b>Strategy:</b> {html.escape(strategy)}",
        f"<b>Score:</b> {score}/{max_score}",
        "",
        "<b>ENTRY PLAN</b>",
        f"<b>Entry Price:</b> <code>{entry}</code>",
        f"<b>Stop Loss:</b> <code>{stop}</code> ({stop_pct}, {html.escape(stop_method)})",
        "",
        _format_target(targets.get("t1"), "T1"),
        _format_target(targets.get("t2"), "T2"),
        _format_target(targets.get("t3"), "T3"),
        "",
        "<b>RISK MANAGEMENT</b>",
        f"<b>Estimated Risk:</b> {_format_percent(position.get('actual_risk_percent'))}",
        f"<b>Estimated Loss:</b> {_format_price(position.get('actual_estimated_loss_usdt'))} USDT",
        f"<b>Position Value:</b> {_format_price(position.get('position_value_usdt'))} USDT",
        "",
        "<b>MARKET CONTEXT</b>",
        f"<b>BTC Trend:</b> {html.escape(btc_trend)}",
        f"<b>Market Status:</b> {html.escape(market_status)}",
        "",
        "<b>INDICATORS</b>",
        f"<b>RSI:</b> {rsi}",
        f"<b>RVOL:</b> {rvol}x",
        "",
        "<b>VALIDITY</b>",
        f"<b>Created:</b> {created_at}",
        f"<b>Entry Expiry:</b> {entry_expiry}",
    ]

    if warnings:
        lines.append("")
        lines.append("<b>WARNINGS</b>")
        for warning in warnings:
            lines.append(f"• {html.escape(str(warning))}")

    lines.extend([
        "",
        "<b>INVALIDATION</b>",
        "Signal is invalid if price closes below Stop Loss.",
        "Cancel entry if price does not reach entry before expiry.",
        "",
        "<i>Market: Binance Spot | Quote: USDT | Mode: Spot Only</i>",
        "",
        "⚠️ Verify the current price before placing an order.",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------
# SIGNAL NOTIFICATION
# ---------------------------------------------------------

def send_signal(signal):
    """
    Send a validated BUY signal.
    A signal must include a complete valid risk_plan.
    """

    try:
        message = format_signal(signal)

    except (ValueError, TypeError) as exc:
        logger.warning("Signal notification rejected: %s", str(exc))
        return {
            "success": False,
            "description": str(exc),
        }

    return send_message(message)


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
        "scalp_entry_validity_minutes": SCALP_ENTRY_VALIDITY_MINUTES,
        "swing_entry_validity_minutes": SWING_ENTRY_VALIDITY_MINUTES,
    }
