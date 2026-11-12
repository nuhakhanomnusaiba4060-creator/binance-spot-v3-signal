# Binance Spot V3 Smart Signal Scanner

**Version:** 3.0  
**Status:** Development and Testing  
**Python:** 3.11  
**Exchange:** Binance  
**Market:** Spot Only  
**Quote Asset:** USDT Only  

---

## 1. Project Overview

Binance Spot V3 Smart Signal Scanner is a rule-based cryptocurrency market scanner designed to identify high-quality early trading opportunities in Binance Spot USDT trading pairs.

The system focuses on:
- Early breakout detection.
- Closed-candle confirmation.
- Breakout retest validation.
- Buyer and volume confirmation.
- BTC market condition analysis.
- **Pump protection (rejecting exhausted/fake moves).**
- Liquidity and order-book validation.
- Risk-controlled entry planning (Max 1% risk per trade).
- Telegram signal notifications.
- Signal tracking for up to 48 hours.

The primary objective is to reduce false signals and avoid late entries after excessive price movements. **Signal quantity is secondary to signal quality.**

---

## 2. Market Restrictions

The scanner is designed for:
- Binance Spot market only.
- USDT trading pairs only.
- Cryptocurrency assets only.

**Excluded markets and assets:**
- Futures & Margin.
- Non-USDT trading pairs.
- Stocks, shares, and equities.
- **Tokenized stocks (xStocks like NVDABUSDT, TSLABUSDT).**
- **Stablecoins (USDCUSDT, TUSDUSDT).**
- **Wrapped/Low-volatility assets (WBTCUSDT, XAUTUSDT).**
- Leveraged tokens (UP, DOWN, BULL, BEAR).

---

## 3. Trading Strategies

### A. Scalp Strategy
| Parameter | Setting |
|---|---|
| Trigger timeframe | 5 minutes |
| Confirmation | 15 minutes & 30 minutes |
| Entry validity | 15 minutes |
| Trading duration | Minutes to several hours |

### B. Short Swing Strategy
| Parameter | Setting |
|---|---|
| Trigger timeframe | 15 minutes |
| Confirmation | 30 minutes & 1 hour |
| Entry validity | 60 minutes |
| Maximum tracking | 48 hours |

*The scanner checks the market every 5 minutes. This does not mean a signal must be generated every 5 minutes.*

---

## 4. Signal Classification & Scoring

Only two signal classifications are permitted:
- **STRONG BUY**
- **EXCELLENT BUY**

**15-Point Scoring Model:**

| Score | Classification |
|---|---|
| 0–9 | REJECT |
| 10–12 | STRONG BUY candidate |
| 13–15 | EXCELLENT BUY candidate |

**Base components (12):** Market Condition, BTC Context, MTF Trend, EMA, MA, RSI, MACD, ADX, RVOL, VWAP, OBV/CMF, Breakout/Retest.

**Early-Pump components (3):** Bollinger Band Squeeze, Early Momentum (ROC), Volume Acceleration.

*Mandatory rejection rules override the numerical score. The system will never generate weak signals merely to meet a daily quota.*

---

## 5. Market Analysis

Before evaluating individual coins, the scanner analyzes BTC market conditions.

**BTC indicators include:** SMA 20/50/200, RSI 14, MACD, ADX, ATR, Volume trend.

**Market classifications:**
- **BULLISH:** Normal signal evaluation.
- **NEUTRAL:** Selective evaluation (Score penalty).
- **BEARISH:** Strict confirmation required (Score penalty).
- **HIGH_RISK:** Reject new signals.
- **UNKNOWN:** No market-based assumptions; reject new signals.

*Missing or incomplete data is never treated as confirmed market information.*

---

## 6. Technical Indicators

The technical analysis engine includes:
- EMA 9 and EMA 20.
- SMA 20, SMA 50, and SMA 200.
- RSI 14.
- MACD 12/26/9.
- ADX 14.
- ATR 14.
- VWAP.
- Relative Volume (RVOL).
- OBV & CMF.
- Bollinger Bands & **Bollinger Band Width (BBW)**.
- **Rate of Change (ROC)**.
- **Volume Momentum**.
- Support and Resistance.
- Candlestick analysis.

*A minimum history of 220 closed candles is required. Unclosed (live) candles are dropped before calculation.*

---

## 7. Coin Selection

**Initial candidate filters:**

| Filter | Initial Requirement |
|---|---|
| 24-hour quote volume | $3,000,000 |
| Minimum trade count | 1,000 |
| **Minimum relative volume** | **1.2x** (Tuned for early pump) |
| Preferred relative volume | 1.5x |
| Maximum spread | 0.15% |

*Order-book liquidity, spread, and available market depth must be validated before an entry can be approved.*

---

## 8. Entry Confirmation & Pump Protection

**Preferred entry sequence:**
1. Breakout detection.
2. Closed-candle confirmation.
3. Separate-candle retest validation.
4. Buyer and volume confirmation.
5. Entry validation.
6. Risk validation.
7. Telegram notification.

**Pump Protection (Mandatory Rejections):**
- 3 or more consecutive strong bullish candles (>1.5% body) without consolidation.
- RVOL spikes above 2.0 and then collapses below 70% of peak.
- Next resistance is too close (<1.5% upside).
- Price is excessively extended from EMA20 or VWAP.
- Late entries (ROC exceeds max threshold).

---

## 9. Risk Management

Risk management is mandatory and cannot be bypassed.

| Parameter | Rule |
|---|---|
| Maximum planned capital risk | 1% per trade |
| Minimum risk/reward | 1:2 |
| Stop Loss | Technical invalidation, support, and ATR |
| **SL Distance Bounds** | **Minimum 0.5%, Maximum 8%** |
| Targets | T1, T2, and T3 (with ATR fallback) |
| Signal tracking | Up to 48 hours |

*Fees and estimated slippage are included in risk calculations. Position sizing is capped by available capital.*

---

## 10. System Architecture

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

**Main Files:**
- `config.py`: Central configuration.
- `data_provider.py`: Binance market data.
- `indicators.py`: Technical indicators.
- `market_filter.py`: BTC market analysis.
- `coin_selector.py`: Coin and liquidity selection.
- `entry_engine.py`: Entry evaluation and scoring.
- `risk_manager.py`: Stop Loss, targets, and position sizing.
- `telegram_bot.py`: Telegram notifications.
- `signal_tracker.py`: Signal history and tracking.
- `scanner.py`: Main scanner orchestration.
- `test_system.py`: Automated tests.
- `scanner.yml`: GitHub Actions automation.

---

## 11. API Configuration

The scanner uses Binance public market-data endpoints.
**Base URL:** `https://data-api.binance.vision`

Required public endpoints:
- `/api/v3/exchangeInfo`
- `/api/v3/klines`
- `/api/v3/ticker/24hr`
- `/api/v3/depth`

*A Binance API key is not required for these public market-data requests. No order-placement functionality is included.*

---

## 12. Telegram Configuration

Telegram credentials must be stored securely in GitHub Secrets.

**Required Secrets:**
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**Signal messages include (HTML Formatted):**
- Coin symbol, Signal classification, Strategy, Score (X/15).
- BTC Trend and Market Status.
- Entry price, Stop Loss (% distance), T1/T2/T3 (with R:R).
- Position size and estimated risk (1%).
- RSI, RVOL, and Entry Expiry timestamp.

*Never put Telegram credentials directly inside Python files or README content.*

---

## 13. GitHub Actions & DRY_RUN

The workflow is configured to:
- Run automatically every 5 minutes.
- Run automated tests (45 tests) **before** scanning.
- Persist signal history after successful non-dry-run execution.

**DRY_RUN Safety Mode:**
By default, manual runs use `dry_run: true` and scheduled runs can be configured for either testing or live mode. 
- In Dry Run: No Telegram alerts are sent, and no history is updated.
- **Manual Live Mode:** Can be enabled by unchecking `dry_run` during manual workflow dispatch.

---

## 14. Capital Configuration

The scanner reads the following GitHub Actions Repository Variable:
`SCANNER_CAPITAL_USDT`

This value represents the capital available for position-sizing calculations. A valid positive capital value is required for live risk-plan validation.

---

## 15. Automated Testing

Run tests locally or through GitHub Actions:

    python -m unittest test_system -v

The test suite (45 tests) verifies module imports, config, indicators, coin selection, market filter, entry engine, risk manager, telegram interface, signal tracker, and scanner logic.

*Passing unit tests does not prove that the strategy is profitable.*

---

## 16. Backtesting and Paper Trading

Before live deployment, the system must undergo:
1. Historical backtesting.
2. Fee and slippage simulation.
3. False-breakout and Stop-loss frequency analysis.
4. Target hit-rate and Drawdown measurement.
5. At least 30–50 paper signals.

No profitability claim should be made without verified results.

---

## 17. Known Limitations

The current implementation is under development. The following areas require further verification:
- Actual end-to-end scanner execution.
- Historical backtesting and paper-trading performance.
- External BTC dominance and sentiment data (currently marked UNKNOWN if unavailable).

---

## 18. Security Rules

- Never commit API credentials.
- Never expose Telegram bot tokens.
- Use GitHub Secrets for sensitive credentials.
- Keep Dry Run enabled during development.
- Never assume a successful GitHub Actions run means the strategy is profitable.

---

## 19. Development Status

**Current stage:** Development and automated testing (v3.0).

**Required completion conditions before Live:**
- All 45 automated tests pass.
- Risk calculations and SL bounds are validated.
- Telegram integration is verified.
- Historical backtesting is completed.
- Paper trading performance is reviewed.

---

**Project:** Binance Spot V3 Smart Signal Scanner  
**Market:** Binance Spot  
**Quote Asset:** USDT  
**Primary Objective:** High-quality early-entry signals with controlled risk.
