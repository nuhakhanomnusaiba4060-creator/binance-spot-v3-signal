Binance Spot V3 — File Architecture

Architecture Specification v1.0

1. Project Structure

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
├── FILE_ARCHITECTURE.md
├── README.md
└── .gitignore

2. File Responsibilities

config.py

- Central configuration.
- Trading parameters.
- Timeframes.
- Volume and liquidity thresholds.
- Risk limits.
- Signal classifications.
- API endpoints.

data_provider.py

- Binance Spot market data.
- USDT trading pair validation.
- Kline retrieval.
- 24-hour ticker data.
- Order book data.
- API rate-limit handling.
- Data validation.

indicators.py

- EMA and SMA.
- RSI.
- MACD.
- ADX.
- ATR.
- VWAP.
- Relative Volume.
- OBV.
- CMF.
- Bollinger Bands.
- Support and Resistance.
- Candlestick analysis.

market_filter.py

- BTC trend.
- BTC market condition.
- Overall market risk.
- External market-data validation.
- BULLISH, NEUTRAL, BEARISH and HIGH RISK classification.

coin_selector.py

- Binance Spot USDT pair selection.
- Liquidity filtering.
- Spread and slippage checks.
- Relative strength.
- Volume analysis.
- Pump detection.
- Suspicious asset exclusion.

entry_engine.py

- Scalp setup detection.
- Short-swing setup detection.
- Breakout confirmation.
- Retest confirmation.
- False breakout rejection.
- Signal scoring.
- STRONG BUY and EXCELLENT BUY classification.

risk_manager.py

- Entry zone calculation.
- Stop Loss calculation.
- T1, T2 and T3 calculation.
- Risk/Reward calculation.
- Position sizing.
- Maximum 1% capital risk enforcement.
- Fee and slippage estimation.

telegram_bot.py

- Telegram connection testing.
- Signal formatting.
- Telegram delivery.
- Error handling.
- Duplicate notification protection.

signal_tracker.py

- Signal history.
- Entry and target tracking.
- Stop Loss tracking.
- 48-hour expiry.
- Performance statistics.
- Duplicate signal prevention.

scanner.py

- Main execution controller.
- Load configuration.
- Fetch market data.
- Run market filter.
- Select eligible coins.
- Calculate indicators.
- Confirm entries.
- Apply risk management.
- Send approved signals.
- Update signal tracking.
- Log execution results.

test_system.py

- Unit tests.
- Indicator tests.
- Market-filter tests.
- Coin-selection tests.
- Entry tests.
- Risk calculation tests.
- Telegram tests.
- Integration tests.

requirements.txt

- Python dependencies with tested compatible versions.

README.md

- Installation.
- Configuration.
- GitHub Actions setup.
- Telegram setup.
- Operation and maintenance.
- Risk disclaimer.

.github/workflows/scanner.yml

- Automated 5-minute scanning.
- Python environment.
- Dependency installation.
- Test execution.
- Scanner execution.
- Safe history persistence.

.gitignore

- Temporary files.
- Python cache.
- Local environment files.
- Secret files.
- Unnecessary generated files.

3. Dependency Flow

config.py
    |
    v
data_provider.py
    |
    v
market_filter.py
    |
    v
coin_selector.py
    |
    v
indicators.py
    |
    v
entry_engine.py
    |
    v
risk_manager.py
    |
    v
telegram_bot.py
    |
    v
signal_tracker.py

scanner.py controls the complete execution flow.
test_system.py validates all components.

4. Development Rules

1. Every file must follow this architecture.
2. Function names and data structures must be agreed before implementation.
3. No duplicate indicator calculations across modules.
4. All market data must be validated.
5. No signal may bypass mandatory risk checks.
6. Only Binance Spot USDT crypto pairs are eligible.
7. No stock, equity or tokenized-stock signals.
8. No Futures or Margin.
9. All modules must pass integration tests.
10. Completed files must not be changed without a documented reason.

5. Development Order

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

6. Architecture Status

This document defines the planned architecture. A file is not considered implemented or tested merely because it appears in this structure.

Implementation and testing status must be maintained separately.

Architecture Version: 1.0
