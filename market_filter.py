
def detect_high_risk(timeframe_results):
    """
    Detect severe BTC downside conditions.
    Diagnostic logging only. Existing risk rules are preserved.
    """

    one_hour = timeframe_results.get("1h", {})
    four_hour = timeframe_results.get("4h", {})

    if (
        one_hour.get("data_quality") != "VALID"
        or four_hour.get("data_quality") != "VALID"
    ):
        logger.warning(
            "HIGH_RISK CHECK SKIPPED | "
            "1h quality=%s | 4h quality=%s",
            one_hour.get("data_quality"),
            four_hour.get("data_quality"),
        )
        return False, []

    warnings = []

    one_hour_bearish = (
        one_hour.get("trend") == "BEARISH"
    )

    four_hour_bearish = (
        four_hour.get("trend") == "BEARISH"
    )

    one_hour_rsi = one_hour.get("rsi")
    four_hour_rsi = four_hour.get("rsi")

    one_hour_adx = one_hour.get("adx")
    four_hour_adx = four_hour.get("adx")

    strong_downtrend = (
        one_hour_bearish
        and four_hour_bearish
    )

    oversold_confirmation = (
        one_hour_rsi is not None
        and four_hour_rsi is not None
        and one_hour_rsi <= HIGH_RISK_RSI_MAX
        and four_hour_rsi <= HIGH_RISK_RSI_MAX
    )

    adx_confirmation = (
        (
            one_hour_adx is not None
            and one_hour_adx >= STRONG_ADX_MIN
        )
        or (
            four_hour_adx is not None
            and four_hour_adx >= STRONG_ADX_MIN
        )
    )

    logger.info(
        "BTC HIGH_RISK DIAGNOSTICS | "
        "1h trend=%s RSI=%s ADX=%s | "
        "4h trend=%s RSI=%s ADX=%s",
        one_hour.get("trend"),
        one_hour_rsi,
        one_hour_adx,
        four_hour.get("trend"),
        four_hour_rsi,
        four_hour_adx,
    )

    logger.info(
        "BTC HIGH_RISK CONDITIONS | "
        "strong_downtrend=%s | "
        "oversold_confirmation=%s | "
        "adx_confirmation=%s | "
        "RSI threshold=%.2f | ADX threshold=%.2f",
        strong_downtrend,
        oversold_confirmation,
        adx_confirmation,
        HIGH_RISK_RSI_MAX,
        STRONG_ADX_MIN,
    )

    if (
        strong_downtrend
        and (
            oversold_confirmation
            or adx_confirmation
        )
    ):

        if oversold_confirmation:
            warnings.append(
                "HIGH_RISK triggered by oversold RSI "
                "confirmation on both 1h and 4h."
            )

        if adx_confirmation:
            warnings.append(
                "HIGH_RISK triggered by strong ADX confirmation."
            )

        warnings.append(
            "BTC shows confirmed bearish conditions "
            "on both 1h and 4h."
        )

        logger.warning(
            "BTC MARKET HIGH_RISK CONFIRMED."
        )

        return True, warnings

    logger.info(
        "BTC HIGH_RISK NOT CONFIRMED."
    )

    return False, warnings
