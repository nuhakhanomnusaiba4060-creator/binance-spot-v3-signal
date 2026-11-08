Binance Spot V3 — Signal Logic Specification

Signal Engine Version 1.0

1. Core Objective

Identify early, high-quality Binance Spot USDT trading opportunities.

Priority:

1. Entry accuracy.
2. Capital protection.
3. Risk/Reward.
4. Signal quality.
5. Signal frequency.

Daily target: 5–7 signals, but never force a signal to meet the target.

Only:

- STRONG BUY
- EXCELLENT BUY

No weak or moderate signals.

2. Eligible Market

- Binance Spot only.
- USDT quote pairs only.
- Active crypto trading pairs only.
- Exclude Futures and Margin.
- Exclude stocks, equities and tokenized stocks.
- Exclude inactive, suspended and suspicious markets.

3. Two Independent Trading Strategies

Strategy A: SHORT-TERM SCALP

Expected holding period:
Minutes to several hours.

Timeframes:

- Trigger: 5m.
- Confirmation: 15m.
- Additional confirmation: 30m.

Preferred conditions:

- EMA 9 above EMA 20.
- Price above VWAP.
- RSI showing positive momentum without excessive extension.
- Relative Volume expansion.
- MACD bullish confirmation.
- ADX showing sufficient trend strength.
- Breakout or successful retest.
- Adequate liquidity and tight spread.

Strategy B: SHORT SWING

Expected holding period:
Several hours to 1–2 days.

Timeframes:

- Trigger: 15m.
- Confirmation: 30m.
- Trend confirmation: 1H.

Preferred conditions:

- Price structure showing higher highs and higher lows.
- MA20 and MA50 supporting the trend.
- EMA 9 and EMA 20 bullish alignment.
- RSI showing sustained momentum.
- Positive MACD momentum.
- Relative Volume expansion.
- Strong support or confirmed resistance retest.
- BTC market condition not showing severe downside risk.

The two strategies must have separate scoring and performance statistics.

4. Market Filter

Classify market conditions:

BULLISH:

- BTC trend positive.
- Momentum and volume supportive.
- No critical market warning.

NEUTRAL:

- Mixed market conditions.
- Require stronger coin-specific confirmation.
- Reduce position risk where appropriate.

BEARISH:

- BTC trend weak.
- Major support threatened or broken.
- Require exceptional independent strength or reject new setups.

HIGH RISK:

- Sudden BTC crash.
- Major market-wide liquidation event.
- Critical security or regulatory event.
- Suspend new Buy Signals until conditions normalize.

Missing external data must be marked UNKNOWN.

5. Coin Selection Filters

Initial testing parameters:

- Minimum 24H quote volume: $3 million.
- Minimum relative volume: 1.5x.
- Preferred relative volume: 2x or higher.
- RSI initial preferred range: 50–68.
- Minimum liquidity and order-book depth must be established through testing.
- Spread and estimated slippage must remain within configured limits.

Do not treat these initial values as proven optimal settings.

6. Pump Protection

Reject or penalize a setup when:

- Price has already experienced an excessive 24H pump.
- Multiple large bullish candles have occurred without a healthy consolidation.
- Relative Volume collapses after a sharp price increase.
- Price is too far above EMA20 or VWAP.
- RSI is excessively extended.
- Price is immediately below major resistance.
- Buying pressure is weakening.
- Breakout occurs without meaningful follow-through.

Never chase a coin merely because it is moving rapidly.

7. Breakout Confirmation

Required sequence:

1. Identify a meaningful resistance level.
2. Wait for a closed candle above resistance.
3. Confirm relative volume expansion.
4. Confirm momentum.
5. Check that breakout is not excessively extended.
6. Prefer a successful retest.
7. Confirm buyers defend the retest.
8. Calculate Entry, Stop Loss and Targets.
9. Reject if Risk/Reward is insufficient.

A wick above resistance without a confirmed candle close is not a valid breakout.

8. Retest Confirmation

A valid retest should show:

- Previous resistance acting as support.
- Price holding the retest area.
- Selling pressure decreasing.
- Buyers returning.
- No major support breakdown.
- Adequate remaining upside to the next resistance.

Do not enter if the retest fails.

9. Mandatory Rejection Conditions

Reject the signal regardless of its numerical score if:

- Trading pair is not eligible.
- Market data is incomplete or stale.
- Liquidity is insufficient.
- Spread or slippage is excessive.
- Entry is excessively extended.
- Stop Loss cannot be placed logically.
- Minimum Risk/Reward is not achieved.
- Major resistance leaves insufficient upside.
- Setup has failed.
- Duplicate signal cooldown is active.
- Market is classified HIGH RISK.

10. Signal Scoring

Use a 12-point scoring model.

Each category contributes one point:

1. Market condition.
2. BTC relative strength context.
3. Trend alignment.
4. EMA confirmation.
5. MA structure.
6. RSI momentum.
7. MACD confirmation.
8. ADX trend strength.
9. Relative Volume.
10. VWAP position.
11. OBV/CMF buying pressure.
12. Breakout/retest quality.

Classification:

- 0–8: REJECT.
- 9–10: STRONG BUY candidate.
- 11–12: EXCELLENT BUY candidate.

Mandatory rejection rules override all scores.

Scoring thresholds must be validated using historical data before live deployment.

11. Risk Management

Maximum planned capital risk: 1% per trade.

Position size calculation:

Risk Amount = Total Trading Capital × Risk Percentage

Position Quantity = Risk Amount / Absolute Difference Between Entry and Stop Loss

Include estimated trading fees and slippage in the risk calculation.

Minimum planned Risk/Reward: 1:2.

Stop Loss:

- Below technical invalidation/support where appropriate.
- ATR-based volatility adjustment.
- Reject setups where stop distance is unreasonable.

Targets:

- T1: First meaningful resistance or tested reward level.
- T2: Next resistance or continuation level.
- T3: Extended target based on market structure.

Never calculate targets without checking resistance and available upside.

12. Signal Expiration

- Scalp entry validity: Initial 15-minute window.
- Swing entry validity: Initial 60-minute window.
- Cancel unfilled signals after expiration.
- Cancel immediately if technical invalidation occurs.
- Recalculate only after a fresh setup forms.

13. Duplicate and Cooldown Rules

- Do not send identical signals repeatedly.
- Use symbol, strategy and setup identity.
- Apply configurable cooldown.
- Allow a new signal only after a meaningful new setup or confirmed reset.
- Track previous signals before generating another notification.

14. BTC Risk Override

If BTC suddenly loses major support:

- Suspend new ordinary Buy Signals.
- Recalculate all pending setups.
- Cancel invalid entries.
- Do not blindly assume an altcoin remains safe because its chart is bullish.

15. Signal Output

Each approved signal must include:

- Symbol.
- Strategy.
- Classification.
- Score.
- Entry zone.
- Stop Loss.
- T1, T2 and T3.
- Risk/Reward.
- Estimated position risk.
- RSI.
- Relative Volume.
- Relevant trend information.
- BTC market condition.
- Signal reasons.
- Invalidation condition.
- Creation time.
- Entry expiration time.

16. Performance Evaluation

Evaluate separately for Scalp and Swing:

- Number of signals.
- Win rate.
- Profit factor.
- Average reward.
- Average loss.
- Stop Loss frequency.
- T1/T2/T3 hit rates.
- False breakout frequency.
- Maximum adverse excursion.
- Maximum favorable excursion.
- Performance after fees and slippage.

17. Final Signal Principle

A high score cannot compensate for a failed mandatory condition.

A coin must pass:

MARKET FILTER
→ COIN SELECTION
→ TECHNICAL CONFIRMATION
→ ENTRY VALIDATION
→ RISK VALIDATION
→ TELEGRAM SIGNAL

No shortcuts.

Primary objective: Reduce bad entries, avoid chasing pumps, and protect trading capital.

Specification Version: 1.0
