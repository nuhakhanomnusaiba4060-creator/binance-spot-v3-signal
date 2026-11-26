# Binance Spot V3 — Signal Logic Specification
**Signal Engine Version 1.1**

---

## 1. Core Objective
Identify early, high-quality Binance Spot USDT trading opportunities.

**Priority Order:**
1. Entry accuracy
2. Capital protection
3. Risk/Reward
4. Signal quality
5. Signal frequency

- **Daily Target:** 5–7 signals (never force a signal to meet the target).
- **Allowed Output Classifications Only:**
  - `STRONG BUY`
  - `EXCELLENT BUY`
- No weak, neutral, or moderate signals are emitted.

---

## 2. Eligible Market
- Binance Spot public endpoints only.
- `USDT` quote pairs only.
- Active `TRADING` spot crypto pairs only (`isSpotTradingAllowed == True`).
- Exclude Futures and Margin pairs.
- Exclude stocks, equities, and tokenized stocks (e.g., `*BUSDT` xStocks except verified native crypto assets).
- Exclude stablecoins, low-volatility pegged assets (`PAXG`, `XAUT`, `WBTC`, `WETH`, `STETH`, `CBBTC`), and leveraged tokens (`*UP`, `*DOWN`, `*BULL`, `*BEAR`).
- Exclude inactive, suspended, or anomalous markets.

---

## 3. Two Independent Trading Strategies

### Strategy A: SHORT-TERM SCALP
- **Expected Holding Period:** Minutes to several hours.
- **Timeframes:**
  - Trigger: `5m`
  - Confirmation: `15m`
  - Trend Context: `30m`
- **Preferred Conditions:**
  - `EMA 9 > EMA 20`
  - Price above `VWAP`
  - RSI showing positive momentum without overextension (`50–68`)
  - Relative Volume expansion (`RVOL >= 1.2x`)
  - MACD bullish confirmation
  - ADX trend strength (`ADX >= 18`)
  - Confirmed resistance breakout or valid retest
  - Adequate order-book depth and tight spread

### Strategy B: SHORT SWING
- **Expected Holding Period:** Several hours to 1–2 days.
- **Timeframes:**
  - Trigger: `15m`
  - Confirmation: `30m`
  - Trend Confirmation: `1h`
- **Preferred Conditions:**
  - Price structure showing higher highs and higher lows
  - `MA20` and `MA50` supporting the uptrend
  - `EMA 9` and `EMA 20` bullish alignment
  - Sustained RSI momentum (`52–70`)
  - Positive MACD momentum
  - Relative Volume expansion (`RVOL >= 1.3x`)
  - Strong support bounce or confirmed resistance retest
  - BTC market condition not showing severe downside risk

> Both strategies maintain independent scoring thresholds, entry windows, and performance statistics.

---

## 4. Market Filter
Classify overall market regime using closed BTC candles:

- **BULLISH:**
  - BTC trend positive (`EMA/MA` alignment supportive).
  - Momentum and volume supportive.
  - No critical market warning.
- **NEUTRAL:**
  - Mixed BTC price action or range-bound structure.
  - Require stronger coin-specific confirmation.
  - Reduce position risk where configured.
- **BEARISH:**
  - BTC trend weak or below key trend structure.
  - Major support threatened or broken.
  - Require exceptional independent relative strength or reject new setups.
- **HIGH RISK:**
  - Sudden BTC crash / extreme volatility spike.
  - Major market-wide liquidation event.
  - Critical security or regulatory shock.
  - **Action:** Suspend all new Buy Signals until conditions normalize.

> Missing or stale external market data must be marked `UNKNOWN` and handled conservatively.

---

## 5. Coin Selection Filters
Pre-screening parameters (configurable in `config.py`):
- **Minimum 24H Quote Volume:** `$3,000,000` (`3M USDT`).
- **Pre-Filter Minimum Relative Volume:** `1.2x` (strategy scoring enforces `>= 1.2x` for SCALP and `>= 1.3x` for SWING).
- **Preferred Relative Volume:** `>= 1.5x`.
- **Preferred RSI Range:** `50–68` (`SCALP`) / `52–70` (`SWING`).
- **Liquidity & Order-Book Depth:** Sufficient top-of-book depth relative to intended position size.
- **Spread & Slippage:** Must remain within configured maximum thresholds.

---

## 6. Pump Protection
Reject or penalize a setup immediately when any of the following occur:
- Excessive 24H price surge already occurred (chasing risk).
- **3 or more consecutive strong bullish candles (`> 1.5%` body each) without consolidation.**
- **RVOL spikes above `2.0x` and then collapses below `70%` of its recent peak (fading momentum).**
- **Next major resistance is within `1.5%` above entry (insufficient upside).**
- Price is overextended above `EMA20` or `VWAP` (`extension > 3.0%`).
- RSI is excessively overbought (`RSI > 74`).
- Buying pressure (OBV/CMF or taker-buy ratio) is weakening on upward pushes.
- Breakout occurs without meaningful volume/candle follow-through.

---

## 7. Breakout Confirmation
Mandatory sequence:
1. Identify a meaningful horizontal or structural resistance level.
2. Wait for a **closed candle** above resistance (wicks above resistance do not qualify).
3. Confirm Relative Volume expansion on the breakout.
4. Confirm momentum alignment (RSI / MACD).
5. Verify breakout is not overextended (`<= 3.0%` from EMA20/VWAP).
6. Prefer a successful retest when price pulls back to the breakout zone.
7. Confirm buyers defend the retest zone.
8. Calculate Entry, Stop Loss, and Targets (`T1`, `T2`, `T3`).
9. Reject if net Risk/Reward is insufficient.

---

## 8. Retest Confirmation
A valid retest must demonstrate:
- Previous resistance holding as new support.
- Price stabilizing within the retest zone without deep breakdown.
- Selling volume decreasing during pullback.
- Renewed buyer defense (bullish rejection wick / bounce close).
- Adequate remaining upside to next overhead resistance (`> 1.5%`).

> Never enter if price closes back below the broken structure.

---

## 9. Mandatory Rejection Conditions
Reject the signal regardless of its numerical score if any condition is true:
- Trading pair is ineligible or excluded.
- Market or candle data is incomplete, unclosed, or stale.
- Order-book liquidity is insufficient.
- Spread or estimated slippage exceeds configured limits.
- Entry is excessively extended (`> 3.0%` above EMA20/VWAP or `RSI > 74`).
- Stop Loss cannot be placed logically below technical invalidation.
- Minimum net Risk/Reward is not achieved.
- Overhead resistance leaves insufficient upside (`< 1.5%`).
- Technical setup has already invalidated.
- Duplicate signal cooldown is active.
- Market regime is classified as `HIGH RISK`.

---

## 10. Signal Scoring (15-Point Model)

### Base Components (12 Points)
1. Market condition (`BULLISH` / supportive context)
2. BTC relative strength context
3. Multi-timeframe trend alignment
4. EMA alignment (`EMA 9 > EMA 20`)
5. MA structure (`MA20` / `MA50` support)
6. RSI momentum (`SCALP: 50–68` / `SWING: 52–70`)
7. MACD bullish confirmation
8. ADX trend strength (`SCALP: >= 18` / `SWING: >= 22`)
9. Relative Volume (`SCALP: >= 1.2x` / `SWING: >= 1.3x`)
10. VWAP position (`Close > VWAP`)
11. OBV / CMF buying pressure
12. Breakout / retest quality

### Early-Pump Detection Components (3 Points)
13. Bollinger Band Squeeze (`width < 0.10`)
14. Early Momentum (`ROC` between `0.5%` and `3.0%`)
15. Volume Acceleration (`volume_momentum >= 1.2`)

### Classification Thresholds
- `0–9`: **REJECT**
- `10–12`: **STRONG BUY** candidate
- `13–15`: **EXCELLENT BUY** candidate

> Mandatory rejection rules override all numerical scores.

---

## 11. Risk Management
- **Maximum Planned Capital Risk:** `1.0%` per trade (configurable).
- **Position Size Formula:**
  $$\text{Risk Amount} = \text{Total Trading Capital} \times \text{Risk Percentage}$$
  $$\text{Position Quantity} = \frac{\text{Risk Amount}}{\vert{}\text{Effective Entry} - \text{Effective Stop Loss}\vert{}}$$
- **Cost Inclusion:** Entry fee, exit fee, and estimated slippage are deducted when computing net Risk/Reward and estimated net profit.
- **Minimum Planned Net Risk/Reward:** `1:2.0` (verified after fees and slippage).
- **Stop Loss:**
  - Placed below technical support / invalidation level with ATR-based buffer.
  - Reject setups where stop distance is too tight (noise risk) or too wide (capital risk).
- **Targets:**
  - `T1`: First meaningful resistance or tested partial-profit level.
  - `T2`: Next structural resistance / continuation target.
  - `T3`: Extended trend target based on higher-timeframe structure.

---

## 12. Signal Expiration & Lifecycle
- **Scalp Entry Validity:** `15-minute` window from signal generation.
- **Swing Entry Validity:** `60-minute` window from signal generation.
- **Maximum Active Tracking Horizon:** `48 hours`.
- If price does not reach entry within the validity window, mark as `EXPIRED_BEFORE_ENTRY` (`ENTRY_WINDOW_EXPIRED`).
- If price hits Stop Loss before reaching entry, mark as `INVALIDATED_BEFORE_ENTRY`.
- Cancel unfilled signals immediately upon expiration or technical invalidation.
- Recalculate only after a fresh, independent setup forms.

---

## 13. Duplicate and Cooldown Rules
- Prevent repeated notifications for the same `symbol` + `strategy` combination while an active setup exists (`ACTIVE`, `TARGET_1_HIT`, `TARGET_2_HIT`) or within the configured cooldown window (default: `6 hours`).
- Allow a new signal only after cooldown expiration and confirmation of a fresh setup.

---

## 14. BTC Risk Override
If BTC suddenly loses major support or enters `HIGH RISK`:
- Suspend all new ordinary Buy Signals immediately.
- Re-evaluate all pending unfilled setups.
- Cancel invalidated entries rather than assuming altcoins remain immune to BTC drawdowns.

---

## 15. Signal Output Payload
Every approved signal notification and record must include:
- Symbol (`*USDT`)
- Strategy (`SCALP` / `SWING`)
- Classification (`STRONG BUY` / `EXCELLENT BUY`)
- Score (`X / 15`)
- Entry price & validity window (`entry_expiry`)
- Stop Loss price, distance %, and basis
- `T1`, `T2`, `T3` prices, R:R ratios, and estimated net profit (USDT after fees/slippage)
- Position size (USDT & base asset quantity) and max risk amount
- Indicators (`RSI`, `RVOL`, trend context)
- BTC trend & overall market status
- Signal reasons & warnings
- Invalidation condition
- Creation timestamp (`UTC`)

---

## 16. Performance Evaluation
Track and evaluate metrics **separately for `SCALP` and `SWING`**, as well as combined:
- Total signals & active/expired counts
- Win rate (`T1/T2/T3` hit vs. clean Stop Loss)
- Profit factor
- Average reward & average loss (net after fees and slippage)
- Stop Loss frequency
- Individual `T1`, `T2`, and `T3` hit rates
- False breakout / entry-window expiration frequency
- Maximum Favorable Excursion (MFE) & Maximum Adverse Excursion (MAE)

---

## 17. Final Signal Principle
A high numerical score can never compensate for a failed mandatory safety check.

```text
MARKET FILTER
  → COIN SELECTION
    → TECHNICAL CONFIRMATION
      → ENTRY VALIDATION
        → RISK VALIDATION
          → SIGNAL TRACKER & TELEGRAM ALERT
