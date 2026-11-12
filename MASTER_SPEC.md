# Binance Spot V3 Smart Signal Scanner

**Master Project Specification — Version 2.0**

---

## 1. Project Objective

Build an automated Binance Spot cryptocurrency scanner that identifies high-quality early trading opportunities, reduces false signals, avoids late entries after excessive pumps, and sends actionable trading plans through Telegram.

**Primary objective:** Signal quality over signal quantity.

---

## 2. Trading Scope

- **Exchange:** Binance
- **Market:** Spot only
- **Quote currency:** USDT only
- **Eligible symbols:** Active Binance Spot crypto pairs ending in USDT
- **Exclude:** Futures, Margin, non-USDT pairs, stocks, equities, tokenized stocks (xStocks), stablecoins, gold tokens, wrapped tokens, and other non-crypto or pegged securities.
- No Futures or Margin recommendations.

---

## 3. Trading Duration

Two independent trading setups with separate scoring and thresholds:

### A. Short-term Scalp
- **Expected holding period:** Minutes to several hours
- **Entry trigger:** 5m chart
- **Confirmation:** 15m and 30m charts
- **Entry validity window:** 15 minutes
- **SCALP-specific thresholds:**
  - RSI: 50–68
  - ADX: ≥ 18
  - Minimum RVOL: ≥ 1.2
  - Maximum ROC: 4.0%
  - Maximum BB Width: 0.20

### B. Short Swing
- **Expected holding period:** Several hours to 1–2 days
- **Entry trigger:** 15m chart
- **Confirmation:** 30m and 1H charts
- **Entry validity window:** 60 minutes
- **SWING-specific thresholds:**
  - RSI: 52–70
  - ADX: ≥ 22
  - Minimum RVOL: ≥ 1.3
  - Maximum ROC: 5.0%
  - Maximum BB Width: 0.25

---

## 4. Scanning and Signal Frequency

- **Scan interval:** Every 5 minutes
- **Desired signal frequency:** 5–7 quality signals per day
- This is a target, not a mandatory quota
- Never generate weak signals to meet a daily target
- Duplicate signals controlled via 6-hour cooldown per symbol + strategy

---

## 5. Market Filter Engine

### Evaluated Data:
- BTC trend across 15m, 1H and 4H
- BTC MA20, MA50, MA200
- BTC RSI, volume and momentum
- BTC dominance (where reliable data is available)
- Total crypto market capitalization (where reliable)
- Fear & Greed sentiment (where available)
- Major macroeconomic and regulatory risk events

### Market Classifications:
- **BULLISH** — BTC trend up, momentum supportive
- **NEUTRAL** — Mixed conditions
- **BEARISH** — BTC trend down, major support threatened
- **HIGH RISK** — Sudden crash, liquidation cascade, critical event
- **UNKNOWN** — Missing external data

When external data is unavailable, mark as **UNKNOWN**. Never invent or silently assume market conditions.

### Signal Policy Rules:
- `HIGH_RISK` and `UNKNOWN` → reject all new signals
- `NEUTRAL` → require stronger coin-specific confirmation (2-point score deduction)
- `BEARISH` → require extra caution (1-point score penalty)

---

## 6. Coin Selection Engine

### Evaluate:
- Binance Spot trading status
- USDT quote-pair eligibility
- 24-hour quote volume (minimum: $3 million)
- Trade count (minimum: 1,000)
- Bid-ask spread (maximum: 0.15%)
- Order-book depth and slippage
- **Relative volume: minimum 1.2x (tuned for early pump detection), preferred 1.5x+**
- Relative strength against BTC
- Abnormal price movement
- Pump-and-dump risk
- Listing and project-related risk
- Token unlock and major negative news (where reliable information is available)

### Explicit Exclusions:
- **Tokenized stocks (xStocks):** AAPLBUSDT, TSLABUSDT, NVDABUSDT, etc.
- **Stablecoins:** USDCUSDT, USDTUSDT, TUSDUSDT, FDUSDUSDT, etc.
- **Low-volatility assets:** XAUTUSDT, PAXGUSDT, WBTCUSDT, WETHUSDT, STETHUSDT
- **Leveraged tokens:** Any symbol ending in UPUSDT, DOWNUSDT, BULLUSDT, BEARUSDT
- **Inactive, suspended, delisted symbols**

---

## 7. Technical Analysis Engine

### Indicators Calculated:
- EMA 9 and EMA 20
- SMA 20, SMA 50, SMA 200
- RSI 14
- MACD (12, 26, 9)
- ADX 14
- ATR 14
- VWAP (UTC-day anchored)
- Relative Volume (20-period baseline)
- OBV
- CMF 20
- Bollinger Bands (20, 2.0)
- **Bollinger Band Width (BBW)** — squeeze detection
- **Rate of Change (ROC, 5-period)** — early momentum detection
- **Volume Momentum (3-period)** — volume acceleration
- Support and Resistance (pivot-based)
- Candlestick patterns (engulfing, strong body)
- Buying and selling volume pressure

All indicators must be calculated using **closed candles only** for confirmation. Unclosed candles are dropped before calculation.

---

## 8. Entry Confirmation Engine

### Preferred Setup:
`BREAKOUT → CLOSED-CANDLE CONFIRMATION → RETEST → BUYER CONFIRMATION → ENTRY`

### Required Confirmations:
1. Breakout candle closes above resistance
2. Retest candle low touches resistance zone (±0.5%)
3. Retest candle closes above resistance
4. Buyer confirmation: bullish candle with volume ≥ previous candle
5. Multi-timeframe trend aligned (both confirmation TFs bullish)
6. Not overly extended from EMA20 (max 3% / 3.5%)

### Pump Protection Rules (Mandatory Rejection):
- **3 or more consecutive strong bullish candles** (>1.5% body each) without consolidation
- **RVOL collapse after spike** — RVOL peaked ≥2.0, now below 70% of peak
- **Insufficient upside** — next resistance < 1.5% above entry
- Price already experienced excessive 24H pump
- Price too far above EMA20 or VWAP
- RSI excessively extended (>74)
- Breakout without meaningful follow-through

### Additional Rejections:
- Late entries after excessive pumps (ROC > MAX_ROC)
- Breakouts without sufficient volume
- Fake breakouts (wick above resistance without close)
- Weak retests (close back below resistance)
- Entries too close to major resistance
- Setups with inadequate risk/reward
- Setups where Stop Loss cannot be placed logically

---

## 9. Signal Classification

Only two categories:
- **STRONG BUY**
- **EXCELLENT BUY**

No weak or moderate signals.

### 15-Point Scoring Model:

**Base components (12):**
1. Market condition (BULLISH)
2. BTC relative strength context
3. Multi-timeframe trend alignment
4. EMA 9/20 confirmation
5. MA structure (price > SMA20 > SMA50)
6. RSI momentum (SCALP: 50–68 / SWING: 52–70)
7. MACD histogram positive
8. ADX trend strength (SCALP: ≥18 / SWING: ≥22)
9. Relative volume (SCALP: ≥1.2 / SWING: ≥1.3)
10. VWAP position (price above VWAP)
11. OBV/CMF buying pressure
12. Breakout/retest quality

**Early-pump components (3):**
13. Bollinger Band squeeze (width < 0.10)
14. Early momentum (ROC between 0.5% and MAX_ROC)
15. Volume acceleration (volume_momentum ≥ 1.2)

### Classification Thresholds:
- **0–9:** REJECT
- **10–12:** STRONG BUY candidate
- **13–15:** EXCELLENT BUY candidate

**Market context adjustment:**
- NEUTRAL market: required_score -= 2
- BEARISH market: required_score += 1

**Mandatory rejection rules override all scores.**

---

## 10. Risk Management Engine

### Core Rules:
- Maximum planned risk per trade: **1% of total trading capital**
- Minimum planned Risk/Reward: **1:2**
- Include estimated trading fees (0.1% per side) and slippage (0.1% per side)

### Stop Loss Calculation:
- Based on technical invalidation, support, and ATR
- Method: prefer widest valid SL (support-based or ATR-based)
- **Minimum SL distance: 0.5%** (prevent noise stop-outs)
- **Maximum SL distance: 8%** (prevent oversized losses)
- Reject setup if no SL fits within these bounds

### Target Calculation:
- **T1:** First meaningful resistance meeting minimum 1:2 RR
- **T2:** Next higher resistance
- **T3:** Third higher resistance
- **ATR fallback:** If no resistance meets T1 RR, generate targets at 2x, 3.5x, 5x ATR above entry
- Never calculate targets without checking resistance and available upside

### Position Sizing:
- Risk Amount = Total Capital × Risk Percentage
- Position Quantity = Risk Amount / (Entry − Stop Loss) / (1 + fees + slippage)
- Capped by available capital
- **Never promise guaranteed profits**

---

## 11. Telegram Notification Engine

### Every Approved Signal Must Include:
- Coin and Binance Spot symbol
- Signal classification (STRONG BUY / EXCELLENT BUY)
- Trading setup (SCALP / SWING)
- Score (X/15)
- Entry price and entry zone
- Stop Loss with % distance
- T1, T2, T3 with R:R for each
- Risk/Reward ratio
- Position risk %, estimated loss, position value
- Relevant timeframe
- **RSI value**
- **Relative Volume value**
- **BTC market condition and trend**
- Signal reasons / warnings
- Invalidation condition
- **Signal creation timestamp (UTC)**
- **Entry expiry timestamp (UTC)** — 15 min for scalp, 60 min for swing

### Formatting Requirements:
- HTML formatting for readability
- Bold headers, code-formatted prices
- Emoji warnings for critical info
- Automatic fallback to plain text if HTML parsing fails
- Telegram connection test must be independent of normal scanning

---

## 12. Signal Tracking Engine

### Tracked Fields:
- Signal creation time
- **Entry expiry time (15 min / 60 min)**
- Entry zone
- Actual entry status (`entry_reached`, `entry_reached_at`)
- **Entry window expired flag** (`entry_window_expired`)
- Stop Loss
- T1/T2/T3 hits
- Maximum favorable excursion
- Maximum adverse excursion
- Expiration (48-hour tracking window)
- Signal outcome
- Estimated fees and slippage
- Performance by setup and timeframe (SCALP vs SWING separate stats)

### Tracking Rules:
- Maximum tracking period: **48 hours**
- **Entry window expiry:** Scalp 15 min, Swing 60 min. If price does not reach entry within this window, mark as `EXPIRED_BEFORE_ENTRY`.
- Signals that never reached entry are **not counted as losses**
- Avoid counting one signal multiple times
- Cooldown between duplicate signals: **6 hours per symbol + strategy**

---

## 13. Testing and Quality Assurance

### Before Live Deployment — 45 Required Tests:

**Module tests (1):**
1. All modules import successfully

**Configuration tests (4):**
2. Required config sections exist
3. Config validation passes
4. Spot-only configuration enforced
5. 15-point scoring matches component count
6. Early-pump components present
7. Pump protection config present
8. Entry validity minutes configured

**Indicator tests (5):**
9. Dataframe validation
10. Indicator calculation
11. Required indicator columns present
12. Indicator values are numeric
13. New early-pump indicators present

**Coin selector tests (10):**
14. Snake_case ticker support
15. Camel_case ticker support
16. Low volume rejected
17. Non-USDT pair rejected
18. Leveraged token rejected
19. Tokenized stock rejected
20. Stablecoin rejected
21. Order-book validation
22. Invalid order-book rejected

**Market filter tests (2):**
23. Market filter function exists
24. Market context validator exists

**Entry engine tests (6):**
25. Required functions exist
26. Only approved signal classes
27. SCALP/SWING configs differ
28. Pump protection functions exist
29. Breakout + separate retest confirmed
30. Failed retest rejected
31. Breakout without separate retest rejected
32. Unknown market context rejected
33. High risk market rejected

**Risk manager tests (5):**
34. Required functions exist
35. Position size calculation
36. Stop loss rejects too wide
37. Stop loss bounds configured

**Telegram tests (2):**
38. Required functions exist
39. Missing credentials do not expose secrets

**Signal tracker tests (3):**
40. Required functions exist
41. Entry expiry function exists
42. Entry validity constants present

**Scanner tests (3):**
43. Scanner functions exist
44. Non-USDT signal rejected
45. Unapproved signal rejected

### Historical Evaluation (before going live):
- Win rate, Profit factor
- Average win/loss, Maximum drawdown
- False breakout rate, Stop Loss frequency
- Target hit rates
- Performance after fees and slippage
- **Minimum 30–50 paper-trade signals** before live deployment

**Do not deploy live merely because GitHub Actions reports success.**

---

## 14. Technology and Infrastructure

- **Python:** 3.11
- **Data source:** Binance Public Market Data API
- **CI/CD:** GitHub Actions
- **Notifications:** Telegram Bot API
- **Workflow:** Automated 5-minute scan cycle
- **Secrets:** GitHub Repository Secrets
- **Persistence:** `signal_history.json` with atomic writes
- **Logging:** Structured logging with rotation-safe format

**No Binance trading API key is required for public market-data scanning.**

---

## 15. Security and Reliability

- Never hardcode Telegram tokens or secrets
- Never print secrets in logs or error messages
- Handle API rate limits (418/429) with exponential backoff
- Prevent duplicate workflow execution via concurrency control
- Use only closed-candle data for indicator calculations
- Validate all API responses strictly before use
- Preserve signal history safely (atomic write + fsync)
- Fail safely when critical data is missing
- Drop unclosed (live) candles before indicator calculation
- Reject stale ticker data (>120s old)
- Reject stale kline data based on configured freshness thresholds

---

## 16. Development Rules

- Keep one authoritative Master Specification
- Maintain a file dependency map (see below)
- Build one complete file at a time
- Test every file after changes
- Test cross-file compatibility
- Do not change completed files without a documented reason
- Keep a development progress record
- **Do not claim a test passed unless it was actually executed**
- **Do not deploy live before testing is complete**

### File Dependency Map:
