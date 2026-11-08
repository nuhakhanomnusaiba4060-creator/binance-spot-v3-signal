CONFIG SPECIFICATION

Binance Spot V3 Smart Signal Scanner

Version: 1.0
Status: Initial Configuration — Pending Backtesting
Python: 3.11
Exchange: Binance
Market: Spot Only
Quote Asset: USDT Only

---

1. CORE CONFIGURATION

Parameter| Value
Exchange| Binance
Market Type| Spot
Allowed Quote Asset| USDT
Scan Interval| 5 minutes
Target Signals| 5–7 per day (not mandatory)
Allowed Signal Types| STRONG BUY, EXCELLENT BUY
Maximum Trade Duration| 48 hours
Maximum Capital Risk| 1% per trade
Minimum Risk/Reward| 1:2
Signal Tracking| 48 hours
Timezone| UTC

Strict Exclusions

- Futures
- Margin
- Non-USDT trading pairs
- Stocks and shares
- Equities
- Tokenized stocks
- Non-crypto assets

Only eligible Binance Spot crypto/USDT pairs are permitted.

---

2. STRATEGY TIMEFRAMES

Scalp Strategy

Parameter| Timeframe
Trigger| 5m
Confirmation| 15m
Additional Confirmation| 30m
Entry Validity| 15 minutes
Maximum Duration| Several hours

Swing Strategy

Parameter| Timeframe
Trigger| 15m
Confirmation| 30m
Trend Confirmation| 1H
Entry Validity| 60 minutes
Maximum Duration| 48 hours

Only closed candles may confirm a signal. An incomplete candle must never independently trigger an entry.

---

3. MARKET FILTER CONFIGURATION

BTC Market Analysis

Required indicators:

- MA20
- MA50
- MA200
- RSI14
- MACD
- ADX14
- ATR14
- Volume trend

Required timeframes:

- 15m
- 1H
- 4H

Market Classification

Status| Action
BULLISH| Normal signal evaluation
NEUTRAL| Selective signal evaluation
BEARISH| Strict confirmation required
HIGH_RISK| Reject new signals
UNKNOWN| No market-based assumptions; apply conservative rules

A single bearish BTC indicator must not automatically reject every coin. However, strong BTC weakness, abnormal volatility or major market risk must increase rejection requirements.

Missing market data must be classified as UNKNOWN.

---

4. COIN SELECTION FILTERS

Liquidity Requirements

Parameter| Initial Threshold
Minimum 24H Quote Volume| $3,000,000
Minimum Relative Volume| 1.5x
Preferred Relative Volume| 2.0x or higher
Maximum Spread| 0.15%
Minimum Trade Count| 1,000
Quote Asset| USDT

These are initial screening thresholds, not guaranteed liquidity or execution conditions.

Order Book Validation

Check:

- Bid/ask spread
- Order book depth
- Buy-side liquidity
- Sell-side liquidity
- Estimated slippage
- Abnormal order-book imbalance

Reject a candidate when the expected execution cost makes the required risk/reward invalid.

Do not treat spoofable order-book walls as confirmed buying pressure.

RSI Filter

RSI14| Interpretation
Below 45| Weak momentum
45–49| Caution
50–68| Preferred range
69–74| Overextension warning
Above 74| Reject fresh breakout entry unless separately validated

RSI alone must never create a BUY signal.

---

5. INDICATOR CONFIGURATION

Indicator| Configuration
EMA Fast| 9
EMA Slow| 20
SMA| 20
SMA| 50
SMA| 200
RSI| 14
MACD Fast| 12
MACD Slow| 26
MACD Signal| 9
ADX| 14
ATR| 14
Bollinger Period| 20
Bollinger Standard Deviation| 2
VWAP| Session-based
Relative Volume| 20-candle baseline
OBV| Standard
CMF| 20
Support/Resistance| Recent confirmed swing levels

All indicators must use sufficient historical candle data.

Minimum required candle history: 220 candles where MA200 is required.

If sufficient data is unavailable, the relevant setup must not receive a fabricated indicator value.

---

6. BREAKOUT AND ENTRY CONFIGURATION

Breakout Requirements

A valid breakout candidate should have:

1. Confirmed resistance breakout.
2. Closed-candle confirmation.
3. Relative volume confirmation.
4. Positive momentum confirmation.
5. Acceptable RSI.
6. No excessive price extension.
7. Valid stop-loss placement.
8. Minimum 1:2 risk/reward.

Retest Requirements

Preferred entry sequence:

Breakout → Candle Close → Retest → Buyer Confirmation → Entry

A retest is preferred over chasing an already extended candle.

If price moves too far from the planned entry, expire the signal rather than chasing the pump.

Late Entry Protection

Reject signals when:

- Price is excessively extended from EMA20.
- Breakout already occurred without a valid retest.
- Remaining upside is insufficient for 1:2 R:R.
- Resistance is too close.
- Volume confirmation disappears.
- The setup becomes invalid before entry.

---

7. SIGNAL SCORING CONFIGURATION

Maximum score: 12 points.

Component| Maximum Points
Market Condition| 1
BTC Context| 1
Trend Structure| 1
EMA Confirmation| 1
MA Confirmation| 1
RSI Momentum| 1
MACD Confirmation| 1
ADX Strength| 1
Relative Volume| 1
VWAP Confirmation| 1
OBV/CMF Confirmation| 1
Breakout/Retest Quality| 1
Total| 12

Signal Classification

Score| Classification
0–8| REJECT
9–10| STRONG BUY candidate
11–12| EXCELLENT BUY candidate

A high score does not override mandatory rejection conditions.

If required data is missing, do not award points based on assumptions.

Only STRONG BUY and EXCELLENT BUY signals may be sent to Telegram.

---

8. RISK MANAGEMENT CONFIGURATION

Capital Risk

Parameter| Value
Maximum Risk per Trade| 1% of Total Capital
Minimum Risk/Reward| 1:2
Position Sizing| Stop-loss distance based
Trading Mode| Spot Only

Position sizing must account for:

- Entry price
- Stop-loss price
- Total available capital
- Maximum risk percentage
- Trading fees
- Estimated slippage

The scanner must reject a setup if its calculated position size or execution cost violates risk limits.

Stop-Loss

Stop-loss must be based on:

- Technical invalidation
- Confirmed support
- ATR14
- Market volatility

Stop-loss must not be selected using an arbitrary fixed percentage.

Targets

Target| Calculation Basis
T1| First meaningful resistance / reward level
T2| Next resistance / market structure
T3| Extended resistance / trend continuation

The initial setup must satisfy minimum 1:2 R:R to T1.

Targets must be recalculated from actual entry and stop-loss levels.

---

9. SIGNAL TRACKING CONFIGURATION

Parameter| Value
Maximum Tracking Duration| 48 hours
Scalp Entry Validity| 15 minutes
Swing Entry Validity| 60 minutes
Duplicate Prevention| Enabled
Cooldown| 6 hours (initial)
Signal Expiry| Enabled
Performance Tracking| Enabled

Track:

- Signal timestamp
- Entry price
- Actual entry status
- Stop-loss
- T1/T2/T3
- Maximum favorable movement
- Maximum adverse movement
- Target reached
- Stop-loss reached
- Expired status
- Final result

A signal that expires before entry must not be counted as a completed trade.

---

10. PUMP AND MANIPULATION PROTECTION

Reject or flag candidates showing:

- Abnormal one-candle price spikes
- Extreme volume without sustainable follow-through
- Excessive spread
- Thin order books
- Rapid price reversal
- Unusual volatility
- Unreliable or stale market data
- Insufficient liquidity for planned position size

Volume spikes alone do not establish a valid breakout.

---

11. DATA QUALITY AND API CONFIGURATION

Binance Public API

Required endpoints:

- Exchange Information
- Kline/Candlestick Data
- 24H Ticker Statistics
- Order Book Depth

Base URL:

"https://data-api.binance.vision"

Data Rules

- Use public Spot market data only.
- Validate symbol trading status.
- Validate candle timestamps.
- Reject stale or incomplete data.
- Handle API errors and rate limits.
- Retry temporary failures with controlled backoff.
- Never replace missing data with invented values.

External data such as BTC dominance, total market cap, Fear & Greed and macro indicators may be used only when a reliable source is available.

Unavailable external data must be marked UNKNOWN.

Initial Data Freshness Limits

Data| Maximum Age
5m Candle| Must be closed
15m Candle| Must be closed
30m Candle| Must be closed
1H Candle| Must be closed
24H Ticker| 120 seconds
Order Book| 10 seconds

If data exceeds its freshness limit, reject or re-fetch it before evaluation.

---

12. TELEGRAM CONFIGURATION

Required GitHub Secrets:

- "TELEGRAM_BOT_TOKEN"
- "TELEGRAM_CHAT_ID"

Never store Telegram credentials directly in source code.

Signal Message Requirements

Every actionable alert must contain:

- Coin symbol
- Signal classification
- Strategy type
- Signal score
- Market condition
- Entry zone
- Stop-loss
- T1
- T2
- T3
- Risk/reward
- Entry expiry
- Signal timestamp in UTC
- Important warnings

Telegram test messages must be separate from actual trading signals.

---

13. GITHUB ACTIONS CONFIGURATION

Parameter| Value
Runtime| Python 3.11
Scan Schedule| Every 5 minutes
Workflow| GitHub Actions
Notifications| Telegram
Credentials| GitHub Secrets
Manual Testing| Enabled
Automated Tests| Required

The workflow must run tests before production signal generation.

A successful GitHub Actions run does not prove that the scanner generates profitable signals.

---

14. TESTING AND VALIDATION

Before live deployment:

Stage 1 — Technical Tests

- Syntax tests
- Import tests
- Indicator tests
- Market filter tests
- Coin selection tests
- Entry validation tests
- Risk calculation tests
- Telegram connection tests
- Signal tracking tests

Stage 2 — Historical Backtesting

Evaluate:

- Win rate
- Profit factor
- Average win/loss
- Maximum drawdown
- T1/T2/T3 achievement rates
- Stop-loss frequency
- False breakout frequency
- Fees and slippage
- Scalp vs swing performance

Stage 3 — Paper Trading

Collect at least 30–50 paper signals before considering live deployment.

Do not assume profitability from a small sample.

Stage 4 — Live Deployment

Enable live Telegram signals only after the previous stages pass.

Review actual execution quality and performance regularly.

---

15. CONFIGURATION CHANGE POLICY

1. All initial thresholds are provisional.
2. Do not change thresholds without a documented reason.
3. Use backtesting and paper-trading evidence before optimization.
4. Avoid overfitting to a small sample.
5. Preserve the original configuration for comparison.
6. Every configuration change must be tested.
7. Do not force 5–7 daily signals.
8. Signal quality takes priority over signal quantity.
9. Never bypass mandatory rejection rules to increase signal frequency.

---

16. FINAL CONFIGURATION PRINCIPLE

The scanner's primary objective is not to generate frequent alerts.

Its objective is to identify early, liquid, technically confirmed Binance Spot USDT opportunities with controlled risk and a minimum planned 1:2 risk/reward ratio.

Accuracy, execution quality and capital protection take priority over signal frequency.

END OF CONFIG SPECIFICATION
