# Binance Spot V3 — API Contracts

**Function and Data Structure Specification v2.0**

---

## 1. General Rules

- Python version: 3.11
- Use consistent type hints.
- Use dictionaries for structured market and signal data.
- Use UTC timestamps.
- Use Decimal or controlled floating-point precision for prices and quantities.
- All functions must have documented inputs and outputs.
- Errors must be handled explicitly.
- No module may silently invent missing data.
- No module may send a signal without passing mandatory risk validation.
- Unclosed (live) candles must be dropped before indicator calculation.

---

## 2. config.py

Exports:

- CONFIG
- TIMEFRAMES
- STRATEGIES
- RISK_CONFIG
- FILTER_CONFIG
- INDICATOR_CONFIG
- MARKET_CONFIG
- SIGNAL_CONFIG
- TRACKING_CONFIG
- API_CONFIG
- TELEGRAM_CONFIG

All other modules must import configuration from this module rather than duplicate constants.

---

## 3. data_provider.py

Required functions:

`get_exchange_info()`
- Returns validated Binance Spot trading-pair metadata.

`get_usdt_symbols()`
- Returns only eligible active Binance Spot USDT crypto pairs (excludes xStocks, stablecoins, low-volatility assets).

`get_klines(symbol, interval, limit)`
- Returns validated OHLCV candle data (only closed candles).
- Required candle fields: open_time, open, high, low, close, volume, close_time.

`get_24h_ticker(symbols=None)`
- Returns a dictionary of tickers. If `symbols` list is provided, filters to those.
- Required fields: symbol, price_change_percent, quote_volume, trade_count, last_price.

`get_order_book(symbol, limit)`
- Returns: `last_update_id`, `bids`, `asks`.

All API functions must validate HTTP status, response structure and data freshness. Stale tickers (>120s) are rejected.

---

## 4. indicators.py

Required functions:

- `calculate_ema()`
- `calculate_sma()`
- `calculate_rsi()`
- `calculate_macd()`
- `calculate_adx()`
- `calculate_atr()`
- `calculate_vwap()`
- `calculate_relative_volume()`
- `calculate_volume_momentum()` **(NEW)**
- `calculate_roc()` **(NEW)**
- `calculate_obv()`
- `calculate_cmf()`
- `calculate_bollinger_bands()` (Returns BB Width as well) **(UPDATED)**
- `support_resistance()`
- `analyze_candles()`

Main function:
`calculate_all_indicators(candles)`
- Returns a validated indicator DataFrame including `bb_width`, `roc`, `volume_momentum`.
- Missing or invalid indicator values must not be interpreted as bullish confirmation.

---

## 5. market_filter.py

Required function:
`analyze_market(btc_data, external_data=None)`

Returns:
- market_status
- btc_trend
- btc_rsi
- btc_volume_status
- btc_dominance_status
- total_market_status
- sentiment_status
- risk_level
- warnings
- data_quality
- **signal_policy** (allow_new_signals, market_caution)
- **timeframes** (detailed 15m/1h/4h breakdown)

Allowed market_status: BULLISH, NEUTRAL, BEARISH, HIGH_RISK, UNKNOWN.
External data fields must explicitly indicate unavailable or stale information.

---

## 6. coin_selector.py

Required function:
`select_coins(symbols, ticker_data, order_book_data)`

Returns a list of eligible coin candidates. Excludes tokenized stocks, stablecoins, leveraged tokens, and low-volatility assets.

Each candidate must contain:
- symbol
- quote_volume
- trade_count
- price_change_percent
- spread_percent
- liquidity_status
- relative_strength

Rejected symbols must never enter the entry engine.

---

## 7. entry_engine.py

Required functions:

- `evaluate_scalp(symbol, market_data, indicators, market_context)`
- `evaluate_swing(symbol, market_data, indicators, market_context)`
- `score_setup(setup_data)` (15-point scoring model)
- `validate_entry(setup_data, market_context, strategy)`
- **Pump Protection functions** (`_has_consecutive_bullish_candles`, `_has_rvol_collapse`, `_has_insufficient_upside`) **(NEW)**

Each evaluation returns:
- symbol
- strategy (SCALP / SWING)
- classification (STRONG BUY / EXCELLENT BUY)
- score / max_score / required_score
- components (dict of scoring components)
- entry_price
- support / resistance
- rsi / rvol
- breakout_confirmed / retest_confirmed / buyer_confirmation
- warnings / rejection_reasons

A rejected setup must not be passed to `risk_manager.py`.

---

## 8. risk_manager.py

Required functions:

- `calculate_stop_loss(entry_price, support_level, atr, atr_multiplier)`
  - Enforces min (0.5%) and max (8%) stop loss distance. **(UPDATED)**
- `calculate_targets(entry_price, stop_loss, resistance_levels, atr)`
  - Uses ATR fallback if no valid resistance meets T1 R:R. **(UPDATED)**
- `calculate_position_size(capital, entry, stop_loss, risk_percent, fee_rate, slippage_rate)`
- `validate_risk(entry_price, stop_loss, targets, position_size, risk_percent, min_risk_reward)`
- `build_risk_plan(...)`

Returns:
- status (VALID / REJECT)
- entry_price
- stop_loss (dict: price, method, risk_percent)
- targets (dict: t1, t2, t3)
- position_size (dict: quantity, actual_risk_percent)
- validation (dict: valid, errors)

Maximum planned capital risk must never exceed 1%. Minimum planned risk/reward: 1:2.

---

## 9. telegram_bot.py

Required functions:

- `send_message(text, disable_notification, parse_mode="HTML")`
- `send_connection_test()`
- `format_signal(signal_data)`
- `send_signal(signal_data)`

Requirements:
- Read credentials from environment variables.
- Never expose credentials in logs.
- Handle Telegram API errors.
- **HTML formatting with plain-text fallback.** **(UPDATED)**
- Includes RSI, RVOL, BTC trend, market status, and entry expiry time. **(UPDATED)**
- Confirm successful delivery from API response.

---

## 10. signal_tracker.py

Required functions:

- `load_history()`
- `save_history()`
- `register_signal(signal_data)`
- `check_duplicate(symbol, strategy, current_time, history)`
- `update_signal_status(signal_id, current_price)`
- `expire_old_signals()`
- **`expire_unfilled_entries()`** **(NEW)**
- `calculate_performance()`

Track:
- signal_id
- symbol
- strategy
- created_at
- **entry_expiry** (15 min Scalp, 60 min Swing) **(NEW)**
- **entry_window_expired** (bool) **(NEW)**
- entry_price / stop_loss / targets
- current_status / target_hits / final_outcome

Maximum tracking duration: 48 hours. Signals that never reached entry are marked `EXPIRED_BEFORE_ENTRY`.

---

## 11. scanner.py

Main execution function:
`run_scanner()`

Execution order:
1. Load configuration and validate.
2. Fetch BTC market data and analyze market context.
3. Fetch eligible USDT symbols.
4. Apply liquidity and coin-selection filters.
5. Fetch required timeframe candles.
6. Calculate indicators.
7. Evaluate scalp setups.
8. Evaluate swing setups.
9. Validate entry conditions (including Pump Protection).
10. Calculate position size, Stop Loss and targets.
11. Apply mandatory risk validation.
12. Check duplicate signals.
13. Send approved Telegram signals (if not DRY_RUN).
14. Update signal history.
15. Log execution statistics.

Any critical data failure must stop the affected signal pipeline safely.

---

## 12. Standard Signal Data Structure

All modules must use the same signal structure:

- symbol
- strategy
- classification
- score / max_score / required_score
- components
- entry_price / current_price / last_price
- support / support_level / nearest_support
- resistance / resistance_levels
- atr / atr_value
- rsi / rvol
- market_status / btc_trend
- breakout_confirmed / retest_confirmed / buyer_confirmation
- entry_status / risk_status
- risk_plan
- warnings
- generated_at
- entry_expiry (added by signal_tracker)

No module may silently rename these fields.

---

## 13. Standard Error Handling

Errors must be categorized:

- API_ERROR
- RATE_LIMIT_ERROR
- INVALID_MARKET_DATA
- INSUFFICIENT_CANDLES
- INDICATOR_ERROR
- MARKET_FILTER_ERROR
- ENTRY_VALIDATION_ERROR
- **PUMP_PROTECTION_REJECTED** **(NEW)**
- RISK_VALIDATION_ERROR
- TELEGRAM_DELIVERY_ERROR
- HISTORY_STORAGE_ERROR
- **ENTRY_WINDOW_EXPIRED** **(NEW)**

Errors must be logged without exposing secrets.

---

## 14. Testing Contract

Every public function must have tests for:
- Valid input.
- Invalid input.
- Missing data.
- Boundary values.
- Expected output.
- Error handling.

Integration tests must verify that actual module outputs match the receiving module's expected input. (45 tests total).

---

## 15. Compatibility Rule

This document is the authoritative function contract.

Any implementation that changes a function name, parameter, return field or data type must first update this document and the related tests.

---

**Specification Version:** 2.0
**Last Updated:** 2024-11-12
