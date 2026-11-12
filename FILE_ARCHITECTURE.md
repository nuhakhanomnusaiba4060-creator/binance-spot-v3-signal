# Binance Spot V3 — File Architecture

**Architecture Specification v2.0**

---

## 1. Project Structure

    binance-spot-v3-signal/
    │
    ├── .github/
    │   └── workflows/
    │       └── scanner.yml
    │
    ├── scanner.py
    ├── config.py
    ├── indicators.py
    ├── market_filter.py
    ├── coin_selector.py
    ├── entry_engine.py
    ├── risk_manager.py
    ├── telegram_bot.py
    ├── signal_tracker.py
    ├── data_provider.py
    ├── test_system.py
    ├── requirements.txt
    ├── MASTER_SPEC.md
    ├── SIGNAL_LOGIC.md
    ├── FILE_ARCHITECTURE.md
    ├── API_CONTRACTS.md
    ├── CONFIG_SPEC.md
    ├── README.md
    └── .gitignore

---

## 2. File Responsibilities

### config.py
- Central configuration (SCALP, SWING, Risk, Filter, Indicators, Tracking, API, Telegram).
- 15-point scoring model components and thresholds.
- SCALP/SWING specific thresholds (RSI, ADX, RVOL, ROC, BB Width).
- Pump protection thresholds (MAX_ROC_PERCENT, MAX_BB_WIDTH).
- Entry validity windows (15 min for Scalp, 60 min for Swing).
- Stop loss distance bounds (max 8%, min 0.5%).
- API endpoints and data freshness rules.

### data_provider.py
- Binance Spot public market data.
- USDT trading pair validation.
- Kline retrieval (drops unclosed/live candles before returning).
- 24-hour ticker data with staleness check (>120s rejected).
- Order book data validation.
- Explicit exclusion of tokenized stocks (xStocks), stablecoins, and low-volatility assets.
- API rate-limit handling with exponential backoff.

### indicators.py
- EMA and SMA.
- RSI, MACD, ADX, ATR, VWAP.
- Relative Volume (RVOL), OBV, CMF.
- Bollinger Bands + Bollinger Band Width (BBW).
- Rate of Change (ROC) — early price momentum.
- Volume Momentum — early volume acceleration.
- Support and Resistance (pivot-based).
- Candlestick analysis (engulfing, strong body).

### market_filter.py
- BTC trend analysis across 15m, 1H, 4H (drops unclosed candles).
- Config-driven thresholds (RSI, ADX, RVOL).
- Overall market risk classification (BULLISH, NEUTRAL, BEARISH, HIGH_RISK, UNKNOWN).
- Signal policy generation (allow_new_signals, market_caution).
- Detailed diagnostic logging for trend breakdowns.

### coin_selector.py
- Binance Spot USDT pair selection.
- 24h quote volume and trade count filtering.
- Spread and order-book depth validation.
- Exclusion of tokenized stocks (NVDABUSDT, TSLABUSDT), stablecoins (USDCUSDT), and low-volatility assets (XAUTUSDT).
- Suspicious asset and leveraged token exclusion.

### entry_engine.py
- SCALP and SWING split scoring (different thresholds for each).
- Breakout confirmation + separate candle retest logic.
- False breakout rejection.
- Pump Protection checks:
  - Consecutive strong bullish candles (>1.5% body).
  - RVOL collapse after a spike.
  - Insufficient upside to next resistance (<1.5%).
- 15-point scoring with early-pump components (BB squeeze, ROC, volume acceleration).
- STRONG BUY and EXCELLENT BUY classification.

### risk_manager.py
- Entry zone calculation.
- Stop Loss calculation with distance bounds (0.5% to 8%).
- ATR fallback targets if no valid resistance exists.
- T1, T2, T3 calculation from resistance structure.
- Risk/Reward calculation (minimum 1:2).
- Position sizing (max 1% capital risk).
- Fee and slippage estimation.

### telegram_bot.py
- Telegram connection testing.
- HTML-formatted signal messages (fallback to plain text on parse error).
- Includes RSI, RVOL, BTC trend, market status, and entry expiry time.
- Telegram delivery with error handling.
- Never exposes bot credentials in logs.

### signal_tracker.py
- Signal history with atomic writes (fsync + os.replace).
- Entry window tracking (15 min Scalp, 60 min Swing) with EXPIRED_BEFORE_ENTRY status.
- Entry and target tracking (T1, T2, T3).
- Stop Loss tracking.
- 48-hour expiry.
- Performance statistics (calculate_performance).
- Duplicate signal prevention (6-hour cooldown).

### scanner.py
- Main execution controller.
- Load configuration and validate scanner setup.
- Fetch BTC market context.
- Select eligible coins.
- Evaluate candidates via evaluate_scalp and evaluate_swing.
- Attach risk plans.
- Send approved signals via deliver_signal.
- Update signal tracking.
- Log detailed execution results.

### test_system.py
- Unit tests (45 total).
- Configuration validation tests.
- Indicator calculation tests (including new early-pump indicators).
- Coin selector tests (including tokenized stock/stablecoin rejection).
- Entry engine tests (SCALP/SWING split, pump protection functions).
- Risk manager tests (SL bounds, position size).
- Telegram interface tests.
- Signal tracker tests (entry expiry, persistence).
- Integration tests.

### requirements.txt
- Python dependencies with tested compatible versions (requests, pandas, numpy).

### README.md
- Installation and configuration.
- GitHub Actions setup.
- Telegram setup (Bot Token, Chat ID).
- DRY_RUN vs LIVE mode explanation.
- Operation and maintenance.
- Risk disclaimer.

### .github/workflows/scanner.yml
- Automated 5-minute scanning (cron).
- Manual workflow dispatch with dry_run input.
- Python environment setup (3.11).
- Dependency installation.
- Test execution before scanning.
- Scanner execution.
- Safe history persistence (signal_history.json).

### .gitignore
- Temporary files, Python cache, local environments.
- Secret files (.env).
- Runtime data (signal_history.json, scanner_state.json).

---

## 3. Dependency Flow

    config.py
        │
        ├──► data_provider.py
        │
        ├──► indicators.py
        │         │
        │         ├──► market_filter.py
        │         │
        │         └──► entry_engine.py
        │                    │
        ├──► coin_selector.py│
        │                    ▼
        └──► risk_manager.py ┘
                  │
                  ▼
            telegram_bot.py
                  │
                  ▼
           signal_tracker.py

    scanner.py orchestrates the complete execution flow.
    test_system.py validates all components.

---

## 4. Development Rules

1. Every file must follow this architecture.
2. Function names and data structures must be agreed before implementation.
3. No duplicate indicator calculations across modules.
4. All market data must be validated (no unclosed candles, no stale data).
5. No signal may bypass mandatory risk checks.
6. Only Binance Spot USDT crypto pairs are eligible.
7. No stock, equity, tokenized-stock, stablecoin, or wrapped asset signals.
8. No Futures or Margin.
9. All modules must pass integration tests (45 tests).
10. Completed files must not be changed without a documented reason.
11. Test pass ≠ live ready. Paper trading is required before live deployment.

---

## 5. Development Order

1. config.py
2. data_provider.py
3. indicators.py
4. market_filter.py
5. coin_selector.py
6. entry_engine.py
7. risk_manager.py
8. telegram_bot.py
9. signal_tracker.py
10. scanner.py
11. test_system.py
12. requirements.txt
13. README.md
14. .gitignore
15. scanner.yml

---

## 6. Architecture Status

This document defines the planned architecture. A file is not considered implemented or tested merely because it appears in this structure.

Implementation and testing status must be maintained separately.

---

**Architecture Version:** 2.0
**Last Updated:** 2024-11-12
