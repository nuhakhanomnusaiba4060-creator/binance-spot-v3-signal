Binance Spot V3 — API Contracts

Function and Data Structure Specification v1.0

1. General Rules

- Python version: 3.11
- Use consistent type hints.
- Use dictionaries for structured market and signal data.
- Use UTC timestamps.
- Use Decimal or controlled floating-point precision for prices and quantities.
- All functions must have documented inputs and outputs.
- Errors must be handled explicitly.
- No module may silently invent missing data.
- No module may send a signal without passing mandatory risk validation.

2. config.py

Exports:

- CONFIG
- TIMEFRAMES
- STRATEGIES
- RISK_CONFIG
- FILTER_CONFIG
- API_CONFIG

All other modules must import configuration from this module rather than duplicate constants.

3. data_provider.py

Required functions:

"get_exchange_info()"

Returns validated Binance Spot trading-pair metadata.

"get_usdt_symbols()"

Returns only eligible active Binance Spot USDT crypto pairs.

"get_klines(symbol, interval, limit)"

Returns validated OHLCV candle data.

Required candle fields:

- open_time
- open
- high
- low
- close
- volume
- close_time

"get_24h_ticker(symbol)"

Returns:

- symbol
- price_change_percent
- quote_volume
- trade_count
- last_price

"get_order_book(symbol, limit)"

Returns:

- bids
- asks
- spread
- bid_depth
- ask_depth

All API functions must validate HTTP status, response structure and data freshness.

4. indicators.py

Required functions:

- calculate_ema()
- calculate_sma()
- calculate_rsi()
- calculate_macd()
- calculate_adx()
- calculate_atr()
- calculate_vwap()
- calculate_relative_volume()
- calculate_obv()
- calculate_cmf()
- calculate_bollinger()
- calculate_support_resistance()
- analyze_candles()

Main function:

"calculate_all_indicators(candles)"

Returns a validated indicator dictionary.

Missing or invalid indicator values must not be interpreted as bullish confirmation.

5. market_filter.py

Required function:

"analyze_market(btc_data, external_data=None)"

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

Allowed market_status:

- BULLISH
- NEUTRAL
- BEARISH
- HIGH_RISK
- UNKNOWN

External data fields must explicitly indicate unavailable or stale information.

6. coin_selector.py

Required function:

"select_coins(symbols, ticker_data, order_book_data)"

Returns a list of eligible coin candidates.

Each candidate must contain:

- symbol
- quote_volume
- trade_count
- price_change_percent
- spread_percent
- liquidity_status
- relative_strength
- pump_risk
- eligibility_status
- rejection_reasons

Rejected symbols must never enter the entry engine.

7. entry_engine.py

Required functions:

"evaluate_scalp(symbol, market_data, indicators, market_context)"

"evaluate_swing(symbol, market_data, indicators, market_context)"

"score_setup(setup_data)"

"validate_entry(setup_data)"

Each evaluation returns:

- symbol
- strategy
- setup_type
- score
- classification
- entry_zone
- confirmation_status
- invalidation_level
- reasons
- rejection_reasons
- candle_timestamp

A rejected setup must not be passed to risk_manager.py.

8. risk_manager.py

Required functions:

"calculate_stop_loss(setup_data)"

"calculate_targets(entry_zone, stop_loss, resistance_data)"

"calculate_position_size(capital, entry, stop_loss, risk_percent, fee_rate, slippage_rate)"

"validate_risk(signal_data)"

Returns:

- entry_zone
- stop_loss
- target_1
- target_2
- target_3
- risk_reward
- risk_amount
- position_quantity
- estimated_fees
- estimated_slippage
- risk_valid
- rejection_reasons

Maximum planned capital risk must never exceed 1%.

Minimum planned risk/reward: 1:2.

9. telegram_bot.py

Required functions:

"send_message(text)"

"send_connection_test()"

"format_signal(signal_data)"

"send_signal(signal_data)"

Requirements:

- Read credentials from environment variables.
- Never expose credentials in logs.
- Handle Telegram API errors.
- Confirm successful delivery from API response.
- Never report delivery success without confirmation.

10. signal_tracker.py

Required functions:

"load_history()"

"save_history()"

"register_signal(signal_data)"

"check_duplicate(signal_data)"

"update_signal_status(signal_id, market_data)"

"expire_old_signals()"

"calculate_performance()"

Track:

- signal_id
- symbol
- strategy
- created_at
- entry_expiry
- entry_zone
- stop_loss
- targets
- current_status
- target_hits
- final_outcome

Maximum tracking duration: 48 hours.

11. scanner.py

Main execution function:

"run_scanner()"

Execution order:

1. Load configuration.
2. Validate exchange information.
3. Fetch BTC market data.
4. Analyze market condition.
5. Fetch eligible USDT symbols.
6. Apply liquidity and coin-selection filters.
7. Fetch required timeframe candles.
8. Calculate indicators.
9. Evaluate scalp setups.
10. Evaluate swing setups.
11. Validate entry conditions.
12. Calculate position size, Stop Loss and targets.
13. Apply mandatory risk validation.
14. Check duplicate signals.
15. Send approved Telegram signals.
16. Update signal history.
17. Log execution statistics.

Any critical data failure must stop the affected signal pipeline safely.

12. Standard Signal Data Structure

All modules must use the same signal structure:

- signal_id
- symbol
- strategy
- classification
- score
- setup_type
- entry_zone
- stop_loss
- target_1
- target_2
- target_3
- risk_reward
- risk_amount
- position_quantity
- timeframe
- rsi
- relative_volume
- btc_condition
- reasons
- invalidation_condition
- created_at
- entry_expiry

No module may silently rename these fields.

13. Standard Error Handling

Errors must be categorized:

- API_ERROR
- RATE_LIMIT_ERROR
- INVALID_MARKET_DATA
- INSUFFICIENT_CANDLES
- INDICATOR_ERROR
- MARKET_FILTER_ERROR
- ENTRY_VALIDATION_ERROR
- RISK_VALIDATION_ERROR
- TELEGRAM_DELIVERY_ERROR
- HISTORY_STORAGE_ERROR

Errors must be logged without exposing secrets.

14. Testing Contract

Every public function must have tests for:

- Valid input.
- Invalid input.
- Missing data.
- Boundary values.
- Expected output.
- Error handling.

Integration tests must verify that actual module outputs match the receiving module's expected input.

15. Compatibility Rule

This document is the authoritative function contract.

Any implementation that changes a function name, parameter, return field or data type must first update this document and the related tests.

Specification Version: 1.0
