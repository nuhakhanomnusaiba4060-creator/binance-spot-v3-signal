Binance Spot V3 Smart Signal Scanner

Master Project Specification — Version 1.0

1. Project Objective

Build an automated Binance Spot cryptocurrency scanner that identifies high-quality early trading opportunities, reduces false signals, avoids late entries after excessive pumps, and sends actionable trading plans through Telegram.

Primary objective: Signal quality over signal quantity.

2. Trading Scope

- Exchange: Binance
- Market: Spot only
- Quote currency: USDT only
- Eligible symbols: Active Binance Spot crypto pairs ending in USDT
- Exclude: Futures, Margin, non-USDT pairs, stocks, equities, tokenized stocks and other non-crypto securities.
- No Futures or Margin recommendations.

3. Trading Duration

Two independent trading setups:

A. Short-term Scalp

- Expected holding period: Minutes to several hours.
- Entry trigger: 5m chart.
- Confirmation: 15m and 30m charts.

B. Short Swing

- Expected holding period: Several hours to 1–2 days.
- Entry trigger: 15m chart.
- Confirmation: 30m and 1H charts.

4. Scanning and Signal Frequency

- Scan interval: Every 5 minutes.
- Desired signal frequency: 5–7 quality signals per day.
- This is a target, not a mandatory quota.
- Never generate weak signals to meet a daily target.
- Duplicate signals must be controlled through cooldown and signal tracking.

5. Market Filter Engine

Evaluate:

- BTC trend across 15m, 1H and 4H.
- BTC MA20, MA50 and MA200.
- BTC RSI, volume and momentum.
- BTC dominance, where reliable data is available.
- Total crypto market capitalization, where reliable data is available.
- Fear & Greed sentiment, where available.
- Major macroeconomic and regulatory risk events.

Market classification:

- BULLISH
- NEUTRAL
- BEARISH
- HIGH RISK

When external data is unavailable, mark it UNKNOWN. Never invent or silently assume market conditions.

6. Coin Selection Engine

Evaluate:

- Binance Spot trading status.
- USDT quote-pair eligibility.
- 24-hour quote volume.
- Trade count.
- Bid-ask spread.
- Order-book depth and slippage.
- Relative volume.
- Relative strength against BTC.
- Abnormal price movement.
- Pump-and-dump risk.
- Listing and project-related risk.
- Token unlock and major negative news, where reliable information is available.

Initial liquidity and volume thresholds must be validated through historical testing before final deployment.

Exclude suspicious, illiquid, manipulated and non-crypto securities-related assets.

7. Technical Analysis Engine

Indicators:

- EMA 9 and EMA 20.
- MA20, MA50 and MA200.
- RSI 14.
- MACD.
- ADX.
- ATR.
- VWAP.
- Relative Volume.
- OBV.
- CMF.
- Bollinger Bands.
- Support and Resistance.
- Candlestick patterns.
- Buying and selling volume pressure.

Indicators must be calculated using closed candles for confirmation.

8. Entry Confirmation Engine

Preferred setup:

BREAKOUT → CLOSED-CANDLE CONFIRMATION → RETEST → BUYER CONFIRMATION → ENTRY

Alternative early-entry setups must independently pass strict confirmation rules.

Reject:

- Late entries after excessive pumps.
- Breakouts without sufficient volume.
- Fake breakouts.
- Weak retests.
- Entries too close to major resistance.
- Setups with inadequate risk/reward.
- Setups where Stop Loss cannot be placed logically.

9. Signal Classification

Only two categories:

- STRONG BUY
- EXCELLENT BUY

A signal must satisfy all mandatory safety and entry conditions before classification.

Scoring must not override a failed mandatory condition.

10. Risk Management Engine

- Maximum planned risk per trade: 1% of total trading capital.
- Minimum planned Risk/Reward: 1:2.
- Stop Loss: Based on technical invalidation, support and ATR.
- Targets: T1, T2 and T3.
- Position size: Calculated from entry price, Stop Loss and risk budget.
- Include estimated trading fees and slippage.
- Never promise guaranteed profits.

T1/T2/T3 management rules must be tested before live deployment.

11. Telegram Notification Engine

Every signal should contain:

- Coin and Binance Spot symbol.
- Signal classification.
- Trading setup.
- Entry zone.
- Stop Loss.
- T1, T2 and T3.
- Risk/Reward.
- Position-risk guidance.
- Relevant timeframe.
- RSI, Relative Volume and trend information.
- BTC market condition.
- Signal reasons.
- Invalidation condition.
- Signal timestamp.

Telegram connection test must be independent of normal scanning.

12. Signal Tracking Engine

Track:

- Signal creation time.
- Entry zone.
- Actual entry status.
- Stop Loss.
- T1/T2/T3 hits.
- Maximum favorable excursion.
- Maximum adverse excursion.
- Expiration.
- Signal outcome.
- Estimated fees and slippage.
- Performance by setup and timeframe.

Maximum tracking period: 48 hours.

Avoid counting one signal multiple times.

13. Testing and Quality Assurance

Before live deployment:

1. Python syntax and import tests.
2. Indicator calculation tests.
3. Market-filter tests.
4. Coin-selection tests.
5. Entry and invalidation tests.
6. Stop Loss and target tests.
7. Telegram message tests.
8. Cross-file integration tests.
9. Historical backtesting.
10. Paper trading with at least 30–50 signals.

Historical evaluation should include:

- Win rate.
- Profit factor.
- Average win/loss.
- Maximum drawdown.
- False breakout rate.
- Stop Loss frequency.
- Target hit rates.
- Performance after fees and slippage.

Do not deploy live merely because GitHub Actions reports success.

14. Technology and Infrastructure

- Python 3.11.
- Binance Public Market Data API.
- GitHub Actions.
- Telegram Bot API.
- Automated 5-minute workflow.
- Secure GitHub Repository Secrets.
- Persistent signal history.
- Error logging and recovery.

No Binance trading API key is required for public market-data scanning.

15. Security and Reliability

- Never hardcode Telegram tokens.
- Never print secrets in logs.
- Handle API rate limits and network errors.
- Prevent duplicate workflow execution.
- Use closed-candle data.
- Validate API responses.
- Preserve signal history safely.
- Fail safely when critical data is missing.

16. Development Rules

- Keep one authoritative Master Specification.
- Maintain a file dependency map.
- Build one complete file at a time.
- Test every file.
- Test cross-file compatibility.
- Do not change completed files without a documented reason.
- Keep a development progress record.
- Do not claim a test passed unless it was actually executed.
- Do not deploy live before testing is complete.

17. Final Success Criteria

The project is ready for live evaluation only when:

- All required tests pass.
- Signals contain valid entry, Stop Loss and targets.
- Telegram delivery is verified.
- Historical and paper-trading results are reviewed.
- False signals and risk are measured.
- No critical unresolved integration or security issues remain.

Core Principle: Accuracy, risk control and consistency are more important than signal frequency.
