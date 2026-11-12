# CONFIG SPECIFICATION

**Binance Spot V3 Smart Signal Scanner**

**Version:** 2.0  
**Status:** Initial Configuration — Pending Backtesting  
**Python:** 3.11  
**Exchange:** Binance  
**Market:** Spot Only  
**Quote Asset:** USDT Only  

---

## 1. CORE CONFIGURATION

| Parameter | Value |
|---|---|
| Exchange | Binance |
| Market Type | Spot |
| Allowed Quote Asset | USDT |
| Scan Interval | 5 minutes |
| Target Signals | 5–7 per day (not mandatory) |
| Allowed Signal Types | STRONG BUY, EXCELLENT BUY |
| Maximum Trade Duration | 48 hours |
| Maximum Capital Risk | 1% per trade |
| Minimum Risk/Reward | 1:2 |
| Signal Tracking | 48 hours |
| Timezone | UTC |

**Strict Exclusions:**
- Futures, Margin
- Non-USDT trading pairs
- Stocks, shares, equities
- Tokenized stocks (xStocks like NVDABUSDT, TSLABUSDT)
- Stablecoins (USDCUSDT, TUSDUSDT)
- Wrapped/Low-volatility assets (WBTCUSDT, XAUTUSDT)
- Leveraged tokens (UP, DOWN, BULL, BEAR)

Only eligible Binance Spot crypto/USDT pairs are permitted.

---

## 2. STRATEGY TIMEFRAMES & THRESHOLDS

### Scalp Strategy
| Parameter | Value |
|---|---|
| Trigger | 5m |
| Confirmation | 15m, 30m |
| Entry Validity | 15 minutes |
| RSI Range | 50–68 |
| Minimum ADX | 18 |
| Minimum RVOL | 1.2x |
| Max ROC | 4.0% |
| Max BB Width | 0.20 |

### Swing Strategy
| Parameter | Value |
|---|---|
| Trigger | 15m |
| Confirmation | 30m, 1H |
| Entry Validity | 60 minutes |
| RSI Range | 52–70 |
| Minimum ADX | 22 |
| Minimum RVOL | 1.3x |
| Max ROC | 5.0% |
| Max BB Width | 0.25 |

*Only closed candles may confirm a signal. An incomplete candle must never independently trigger an entry.*

---

## 3. MARKET FILTER CONFIGURATION

**BTC Market Analysis:**
- Required timeframes: 15m, 1H, 4H
- Required indicators: MA20, MA50, MA200, RSI14, MACD, ADX14, ATR14, Volume trend

**Market Classification & Signal Policy:**
| Status | Action |
|---|---|
| BULLISH | Normal signal evaluation |
| NEUTRAL | Require stronger confirmation (2-point score deduction) |
| BEARISH | Strict confirmation required (1-point score penalty) |
| HIGH_RISK | Reject new signals |
| UNKNOWN | Reject new signals |

Missing market data must be classified as UNKNOWN. Never invent market conditions.

---

## 4. COIN SELECTION FILTERS

**Liquidity Requirements:**
| Parameter | Threshold |
|---|---|
| Minimum 24H Quote Volume | $3,000,000 |
| Minimum Relative Volume | **1.2x (tuned for early pump)** |
| Preferred Relative Volume | 1.5x or higher |
| Maximum Spread | 0.15% |
| Minimum Trade Count | 1,000 |

**Order Book Validation:**
- Bid/ask spread, depth, and imbalance checks
- Estimated slippage must not violate risk/reward bounds
- Reject spoofable order-book walls

**RSI Filter (Base Guideline):**
- Below 45: Weak
- 50–68 (Scalp) / 52–70 (Swing): Preferred
- Above 74: Reject fresh breakout unless separately validated

---

## 5. INDICATOR CONFIGURATION

| Indicator | Configuration |
|---|---|
| EMA | 9, 20 |
| SMA | 20, 50, 200 |
| RSI | 14 |
| MACD | 12, 26, 9 |
| ADX | 14 |
| ATR | 14 |
| Bollinger Bands | 20 period, 2 StdDev |
| **Bollinger Band Width** | **Derived from BB (Squeeze detection)** |
| **Rate of Change (ROC)** | **5 period (Early momentum)** |
| **Volume Momentum** | **3 period (Volume acceleration)** |
| VWAP | Session-based |
| Relative Volume | 20-candle baseline |
| OBV, CMF | Standard, 20 period |

- Minimum required candle history: 220 candles where MA200 is required.
- Unclosed live candles are dropped before calculation.
- If sufficient data is unavailable, do not fabricate indicator values.

---

## 6. BREAKOUT AND ENTRY CONFIGURATION

**Breakout Requirements:**
1. Confirmed resistance breakout.
2. Closed-candle confirmation.
3. Relative volume confirmation (RVOL).
4. Positive momentum (MACD, RSI).
5. No excessive price extension (ROC / EMA distance).
6. Valid stop-loss placement (within bounds).
7. Minimum 1:2 risk/reward.

**Retest Requirements:**
- Preferred sequence: Breakout → Candle Close → Retest → Buyer Confirmation → Entry
- Retest tolerance: ±0.5% of resistance.
- Retest must not close back below resistance.

**Pump Protection (Mandatory Rejection):**
- 3 or more consecutive strong bullish candles (>1.5% body each).
- RVOL spikes above 2.0 then collapses below 70% of peak.
- Next resistance is <1.5% above entry (insufficient upside).
- Price excessively extended from EMA20 or VWAP.
- Late entry (ROC exceeds max threshold).

---

## 7. SIGNAL SCORING CONFIGURATION

**Maximum score: 15 points.**

| Component | Max Points |
|---|---|
| Market Condition | 1 |
| BTC Context | 1 |
| Multi-Timeframe Trend | 1 |
| EMA Trend | 1 |
| Moving Average Trend | 1 |
| RSI Momentum | 1 |
| MACD Momentum | 1 |
| ADX Strength | 1 |
| Relative Volume | 1 |
| VWAP Confirmation | 1 |
| OBV/CMF Buyer Flow | 1 |
| Breakout/Retest Quality | 1 |
| **BB Squeeze** | **1** |
| **Early Momentum (ROC)** | **1** |
| **Volume Acceleration** | **1** |
| **Total** | **15** |

**Signal Classification:**
| Score | Classification |
|---|---|
| 0–9 | REJECT |
| 10–12 | STRONG BUY candidate |
| 13–15 | EXCELLENT BUY candidate |

*A high score does not override mandatory rejection conditions. Missing data does not award points.*

---

## 8. RISK MANAGEMENT CONFIGURATION

| Parameter | Value |
|---|---|
| Maximum Risk per Trade | 1% of Total Capital |
| Minimum Risk/Reward | 1:2 |
| Position Sizing | Stop-loss distance based |
| Trading Mode | Spot Only |

**Position sizing includes:**
Entry price, Stop-loss, Capital, Risk %, Fees (0.1%), Slippage (0.1%).

**Stop-Loss:**
- Based on technical invalidation, support, and ATR.
- **Minimum SL distance: 0.5%** (prevent noise stop-outs).
- **Maximum SL distance: 8%** (prevent oversized losses).
- Reject setup if SL cannot be placed within these bounds.

**Targets:**
- T1: First meaningful resistance meeting minimum 1:2 R:R.
- T2: Next higher resistance.
- T3: Extended resistance / trend continuation.
- **ATR Fallback:** If no resistance meets T1 R:R, use 2x, 3.5x, 5x ATR above entry.

---

## 9. SIGNAL TRACKING CONFIGURATION

| Parameter | Value |
|---|---|
| Maximum Tracking Duration | 48 hours |
| Scalp Entry Validity | 15 minutes |
| Swing Entry Validity | 60 minutes |
| Duplicate Prevention | Enabled |
| Cooldown | 6 hours per symbol + strategy |

**Tracked Fields:**
- Signal timestamp, Entry price, Actual entry status (`entry_reached_at`).
- **Entry window expired flag (`entry_window_expired`)**.
- Stop-loss, T1/T2/T3.
- Maximum favorable/adverse movement, Final result.

*Signals that expire before entry (`EXPIRED_BEFORE_ENTRY`) are not counted as losing trades.*

---

## 10. PUMP AND MANIPULATION PROTECTION

Reject or flag candidates showing:
- Abnormal one-candle price spikes.
- Extreme volume without follow-through.
- Excessive spread or thin order books.
- Rapid price reversal or unusual volatility.
- Unreliable or stale market data (>120s for ticker).
- Insufficient liquidity for planned position size.

*Volume spikes alone do not establish a valid breakout.*

---

## 11. DATA QUALITY AND API CONFIGURATION

**Binance Public API:**
- Base URL: `https://data-api.binance.vision`
- Endpoints: Exchange Information, Klines, 24H Ticker, Order Book Depth.

**Data Rules:**
- Validate symbol trading status (Spot only).
- Validate candle timestamps.
- Reject stale or incomplete data (drop unclosed candles).
- Handle API errors (418/429) with exponential backoff.
- Never replace missing data with invented values.

**Data Freshness Limits:**
| Data | Maximum Age |
|---|---|
| Candles (5m, 15m, 1H) | Must be closed |
| 24H Ticker | 120 seconds |
| Order Book | 10 seconds |

---

## 12. TELEGRAM CONFIGURATION

**Required GitHub Secrets:**
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**Message Formatting:**
- **HTML formatting** for readability (fallback to plain text on error).
- Bold headers, code-formatted prices.

**Every actionable alert must contain:**
- Coin symbol, Signal classification, Strategy, Score (X/15).
- Market condition, BTC trend.
- Entry zone, Stop-loss (% distance), T1/T2/T3 (with R:R).
- Position risk %, Estimated loss, Position value.
- RSI, Relative Volume.
- Entry expiry time (UTC) and Signal timestamp (UTC).
- Invalidation condition and Important warnings.

---

## 13. GITHUB ACTIONS CONFIGURATION

| Parameter | Value |
|---|---|
| Runtime | Python 3.11 |
| Scan Schedule | Every 5 minutes (cron) |
| Workflow | GitHub Actions |
| Manual Testing | Enabled (DRY_RUN) |
| Automated Tests | Required (45 tests) |

*The workflow must run tests before production signal generation. A successful GitHub Actions run does not prove profitability.*

---

## 14. TESTING AND VALIDATION

**Stage 1 — Technical Tests (45 tests):**
- Syntax/Import tests, Config, Indicators, Market filter, Coin selection, Entry engine, Risk calculation, Telegram interface, Signal tracking.

**Stage 2 — Historical Backtesting:**
- Win rate, Profit factor, Max drawdown, False breakout rate, Target hit rates, Fees/slippage impact.

**Stage 3 — Paper Trading:**
- Collect at least 30–50 paper signals before considering live deployment.

**Stage 4 — Live Deployment:**
- Enable live Telegram signals only after stages 1–3 pass.

---

## 15. CONFIGURATION CHANGE POLICY

1. All initial thresholds are provisional.
2. Do not change thresholds without a documented reason.
3. Use backtesting and paper-trading evidence before optimization.
4. Avoid overfitting to a small sample.
5. Every configuration change must be tested.
6. Do not force 5–7 daily signals.
7. Never bypass mandatory rejection rules to increase signal frequency.

---

## 16. FINAL CONFIGURATION PRINCIPLE

The scanner's primary objective is not to generate frequent alerts.

Its objective is to identify early, liquid, technically confirmed Binance Spot USDT opportunities with controlled risk and a minimum planned 1:2 risk/reward ratio.

Accuracy, execution quality and capital protection take priority over signal frequency.

**END OF CONFIG SPECIFICATION**
