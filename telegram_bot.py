
"""
Binance Spot V3 Smart Signal Scanner
Telegram Notification Engine

Responsibilities:
- Read Telegram credentials from environment variables.
- Send Telegram connection test messages.
- Format STRONG BUY and EXCELLENT BUY signals.
- Send signal notifications.
- Never expose bot credentials in logs or messages.
"""

import os
import logging
import html
import requests

from config import TELEGRAM_CONFIG


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

REQUEST_TIMEOUT = 15

MAX_MESSAGE_LENGTH = 4000


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
        logger.error(
            "Telegram credentials are missing from environment"
        )

        return {
            "success": False,
            "description": "Telegram credentials missing",
        }

    url = (
        f"https://api.telegram.org/bot{token}/{method}"
    )

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
            description = str(
                result.get("description", description)
            )

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
):
    """
    Send a plain text message to the configured Telegram chat.
    """

    if not isinstance(message, str) or not message.strip():
        return {
            "success": False,
            "description": "Empty message",
        }

    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH - 30]
        message += "\n\n[Message shortened]"

    return _telegram_request(
        "sendMessage",
        {
            "text": message,
            "disable_notification": bool(
                disable_notification
            ),
            "disable_web_page_preview": True,
        },
    )


def send_connection_test():
    """
    Send a separate Telegram connection test.
    """

    message = (
        "BINANCE SPOT V3 SMART SIGNAL SCANNER\n\n"
        "Telegram connection test successful.\n\n"
        "Market: Binance Spot\n"
        "Quote Asset: USDT\n"
        "Mode: Spot Only\n"
        "Signal Types: STRONG BUY / EXCELLENT BUY\n\n"
        "This is a connection test, not a trading signal."
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


def _format_target(target, label):
    if not isinstance(target, dict):
        return f"{label}: N/A"

    price = _format_price(target.get("price"))
    rr = target.get("risk_reward")

    if rr is None:
        return f"{label}: {price}"

    try:
        return f"{label}: {price} | R:R 1:{float(rr):.2f}"
    except (TypeError, ValueError):
        return f"{label}: {price}"


# ---------------------------------------------------------
# SIGNAL FORMATTING
# ---------------------------------------------------------

def format_signal(signal):
    """
    Format an approved signal into a readable Telegram message.

    The signal must already have passed:
    - Entry engine
    - Risk manager
    - Mandatory validation
    """

    if not isinstance(signal, dict):
        raise ValueError("Signal must be a dictionary")

    classification = str(
        signal.get("classification")
        or signal.get("signal")
        or ""
    ).upper()

    allowed_signals = (
        "STRONG BUY",
        "EXCELLENT BUY",
    )

    if classification not in allowed_signals:
        raise ValueError(
            "Only STRONG BUY and EXCELLENT BUY are allowed"
        )

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

    strategy = str(
        signal.get("strategy", "UNKNOWN")
    ).upper()

    score = signal.get("score", "N/A")

    entry = _format_price(
        risk_plan.get("entry_price")
    )

    stop_data = risk_plan.get("stop_loss", {})

    if not isinstance(stop_data, dict):
        raise ValueError("Stop Loss information missing")

    stop = _format_price(
        stop_data.get("stop_loss")
    )

    targets = risk_plan.get("targets", {})

    if not isinstance(targets, dict):
        raise ValueError("Target information missing")

    position = risk_plan.get("position_size", {})

    if not isinstance(position, dict):
        raise ValueError("Position size information missing")

    lines = [
        "BINANCE SPOT V3 SMART SIGNAL",
        "",
        f"Coin: {symbol}",
        f"Signal: {classification}",
        f"Strategy: {strategy}",
        f"Score: {score}/12",
        "",
        "ENTRY PLAN",
        f"Entry Price: {entry}",
        f"Stop Loss: {stop}",
        "",
        _format_target(targets.get("t1"), "T1"),
        _format_target(targets.get("t2"), "T2"),
        _format_target(targets.get("t3"), "T3"),
        "",
        "RISK MANAGEMENT",
        (
            "Estimated Risk: "
            + _format_percent(
                position.get("actual_risk_percent")
            )
        ),
        (
            "Estimated Loss: "
            + _format_price(
                position.get("actual_estimated_loss_usdt")
            )
            + " USDT"
        ),
        (
            "Position Value: "
            + _format_price(
                position.get("position_value_usdt")
            )
            + " USDT"
        ),
        "",
        "Market: Binance Spot",
        "Quote Asset: USDT",
        "Trade Mode: Spot Only",
        "",
        "IMPORTANT: Entry is valid only within its stated expiry.",
        "Always verify the current price before placing an order.",
    ]

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
        logger.warning(
            "Signal notification rejected: %s",
            str(exc),
        )

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
    }
