Binance Spot V3 Smart Signal Scanner

Version: 3.0
Status: Development and Testing
Python: 3.11
Exchange: Binance
Market: Spot Only
Quote Asset: USDT Only

---

1. Project Overview

Binance Spot V3 Smart Signal Scanner is a rule-based cryptocurrency market scanner designed to identify high-quality early trading opportunities in Binance Spot USDT trading pairs.

The system focuses on:

- Early breakout detection.
- Closed-candle confirmation.
- Breakout retest validation.
- Buyer and volume confirmation.
- BTC market condition analysis.
- Liquidity and order-book validation.
- Risk-controlled entry planning.
- Telegram signal notifications.
- Signal tracking for up to 48 hours.

The primary objective is to reduce false signals and avoid late entries after excessive price movements.

Signal quantity is secondary to signal quality.

2. Market Restrictions

The scanner is designed for:

- Binance Spot market only.
- USDT trading pairs only.
- Cryptocurrency assets only.

Excluded markets and assets:

- Futures.
- Margin.
- Non-USDT trading pairs.
- Stocks and shares.
- Tokenized stocks and equity-linked assets.
- Leveraged tokens.

Asset exclusion lists must be maintained and reviewed because Binance exchange metadata alone cannot reliably identify every tokenized stock.

3. Trading Strategies

A. Scalp Strategy

Parameter| Setting
Trigger timeframe| 5 minutes
Confirmation| 15 minutes
Additional confirmation| 30 minutes
Entry validity| 15 minutes
Trading duration| Minutes to several hours

B. Short Swing Strategy

Parameter| Setting
Trigger timeframe| 15 minutes
Confirmation| 30 minutes
Trend timeframe| 1 hour
Entry validity| 60 minutes
Maximum tracking| 48 hours

The scanner checks the market every 5 minutes. This does not mean a signal must be generated every 5 minutes.

4. Signal Classification

Only two signal classifications are permitted:

- STRONG BUY
- EXCELLENT BUY

Initial scoring model:

Score| Classification
0–8| REJECT
9–10| STRONG BUY candidate
11–12| EXCELLENT BUY candidate

Mandatory rejection rules override the numerical score.

The scoring thresholds are provisional and require historical backtesting.

The preferred daily signal range is 5–7 signals, but the system must never generate weak signals merely to meet a daily quota.

5. Market Analysis

Before evaluating individual coins, the scanner analyzes BTC market conditions.

BTC indicators include:

- SMA 20, 50 and 200.
- RSI 14.
- MACD.
- ADX.
- ATR.
- Volume trend.

Market classifications:

- BULLISH
- NEUTRAL
- BEARISH
- HIGH_RISK
- UNKNOWN

Missing or incomplete data must never be treated as confirmed market information.

HIGH_RISK and UNKNOWN market conditions prevent normal signal generation under the current conservative policy.

6. Technical Indicators

The technical analysis engine includes:

- EMA 9 and EMA 20.
- SMA 20, SMA 50 and SMA 200.
- RSI 14.
- MACD 12/26/9.
- ADX 14.
- ATR 14.
- VWAP.
- Relative Volume.
- OBV.
- CMF.
- Bollinger Bands.
- Support and Resistance.
- Candlestick analysis.

A minimum history of 220 candles is required for the configured indicator set.

7. Coin Selection

Initial candidate filters:

Filter| Initial Requirement
24-hour quote volume| $3,000,000
Minimum trade count| 1,000
Relative volume| 1.5x
Preferred relative volume| 2.0x
Maximum spread| 0.15%
Preferred RSI| 50–68

These are initial configuration thresholds, not proven optimal values.

Order-book liquidity, spread and available market depth must be validated before an entry can be approved.

8. Entry Confirmation

Preferred entry sequence:

1. Breakout detection.
2. Closed-candle confirmation.
3. Retest validation.
4. Buyer and volume confirmation.
5. Entry validation.
6. Risk validation.
7. Telegram notification.

The scanner must reject late or excessively extended entries.

A signal must not be approved solely because the price is increasing.

9. Risk Management

Risk management is mandatory.

Parameter| Rule
Maximum planned capital risk| 1% per trade
Minimum risk/reward| 1:2
Stop Loss| Technical invalidation, support and ATR
Targets| T1, T2 and T3
Scalp entry validity| 15 minutes
Swing entry validity| 60 minutes
Signal tracking| Up to 48 hours

Targets must be based on market structure and resistance levels.

Fees and estimated slippage must be included in risk calculations.

A signal that fails risk validation must be rejected.

Position sizing must not exceed the available capital.

10. System Architecture

Binance Public API
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

       scanner.py
   Controls the workflow

Main Files

File| Responsibility
config.py| Central configuration
data_provider.py| Binance market data
indicators.py| Technical indicators
market_filter.py| BTC market analysis
coin_selector.py| Coin and liquidity selection
entry_engine.py| Entry evaluation and scoring
risk_manager.py| Stop Loss, targets and position sizing
telegram_bot.py| Telegram notifications
signal_tracker.py| Signal history and tracking
scanner.py| Main scanner orchestration
test_system.py| Automated tests
requirements.txt| Python dependencies
scanner.yml| GitHub Actions automation

11. API Configuration

The scanner uses Binance public market-data endpoints.

Base URL:

"https://data-api.binance.vision"

Required public endpoints:

- "/api/v3/exchangeInfo"
- "/api/v3/klines"
- "/api/v3/ticker/24hr"
- "/api/v3/depth"

A Binance API key is not required for these public market-data requests.

No order-placement functionality is included in the scanner's intended design.

12. Telegram Configuration

Telegram credentials must be stored securely in GitHub Secrets.

Required Secrets:

Secret Name| Purpose
TELEGRAM_BOT_TOKEN| Telegram bot authentication
TELEGRAM_CHAT_ID| Destination chat

Never put Telegram credentials directly inside Python files or README content.

Signal messages are intended to contain:

- Coin symbol.
- Signal classification.
- Strategy.
- Entry price.
- Stop Loss.
- T1, T2 and T3.
- Risk/reward information.
- Position size and estimated risk.

13. GitHub Actions

The GitHub Actions workflow is configured to:

- Run automatically every 5 minutes.
- Support manual execution.
- Use Python 3.11.
- Install required dependencies.
- Run automated tests before scanning.
- Execute the scanner only after tests pass.
- Persist signal history after successful non-dry-run execution.

Dry Run

Dry Run is the default safety mode.

In Dry Run:

- No Telegram trading alerts are sent.
- No signal history updates are intended.
- No live trading orders are placed.

Manual Live Mode must not be enabled until all required testing and safety checks are completed.

14. Capital Configuration

The scanner reads the following GitHub Actions Repository Variable:

"SCANNER_CAPITAL_USDT"

This value represents the capital available for position-sizing calculations.

It is a configuration value, not a Telegram secret.

A valid positive capital value is required for live risk-plan validation.

Do not use an arbitrary capital value to make a signal pass risk validation.

15. Automated Testing

Run tests locally or through GitHub Actions:

python -m unittest test_system -v

The test suite is intended to verify:

- Module imports.
- Configuration validation.
- Indicator calculations.
- Coin selection.
- Order-book validation.
- Market filter interfaces.
- Entry engine interfaces.
- Risk manager interfaces.
- Telegram interfaces.
- Signal tracker persistence.
- Scanner interfaces.

Passing unit tests does not prove that the strategy is profitable.

16. Backtesting and Paper Trading

Before live deployment, the system must undergo:

1. Historical backtesting.
2. Fee and slippage simulation.
3. False-breakout analysis.
4. Stop-loss frequency analysis.
5. Target hit-rate analysis.
6. Drawdown measurement.
7. At least 30–50 paper signals.

Performance metrics should include:

- Win rate.
- Profit factor.
- Average winning trade.
- Average losing trade.
- Maximum drawdown.
- T1, T2 and T3 hit rates.
- Stop-loss frequency.
- False breakout rate.

No profitability claim should be made without verified results.

17. Known Limitations

The current implementation is under development.

The following areas require further verification:

- Actual end-to-end scanner execution.
- Retest enforcement consistency.
- Risk-plan target selection.
- Partial target and stop-loss tracking.
- Telegram delivery reliability.
- Dry-run risk-plan validation.
- Tokenized-stock exclusion coverage.
- External BTC dominance and sentiment data.
- Historical backtesting.
- Signal performance statistics.

Missing external information must be marked UNKNOWN rather than fabricated.

18. Security Rules

- Never commit API credentials.
- Never expose Telegram bot tokens.
- Use GitHub Secrets for sensitive credentials.
- Use public Binance endpoints for market data.
- Keep Dry Run enabled during development.
- Do not enable live operation before validation.
- Never assume a successful GitHub Actions run means the strategy is profitable.

19. Development Status

Current stage: Development and automated testing.

The project is not yet approved for live signal deployment.

Required completion conditions:

- All automated tests pass.
- Module interfaces are verified.
- Risk calculations are validated.
- Dry-run execution works correctly.
- Telegram integration is verified separately.
- Historical backtesting is completed.
- Paper trading performance is reviewed.

---

Project: Binance Spot V3 Smart Signal Scanner
Market: Binance Spot
Quote Asset: USDT
Primary Objective: High-quality early-entry signals with controlled risk.
