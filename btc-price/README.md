# Bitcoin price technicals for hourly BTC risk monitor

Collector: btc-price/collector.py. GitHub Actions:
.github/workflows/btc-price-technicals.yml, scheduled at UTC :06 hourly.
Outputs: btc-price/data/latest.json (quality-gated signals) and
btc-price/data/history.json (genuine closed OHLCV bars).

## Two free, public spot sources

Primary: Binance BTCUSDT spot, without API key, via the officially
documented https://data-api.binance.vision/api/v3/klines .
Read 800 daily and 300 weekly candles. Separate spot ticker endpoint
is an observed intraday BTCUSDT quote, NOT the latest daily close.

Independent check: Coinbase Exchange BTC-USD daily candles:
https://api.exchange.coinbase.com/products/BTC-USD/candles .
The exact same closed UTC day must agree within 3% or the entire source
is rejected. If Coinbase is unavailable, the source is explicitly
single_venue (no invented confirmation).

## Complete UTC candles, periods and signals

- Only completed UTC 1-day candles for MA20, MA50, MA200 and 14-day
  Wilder-smoothed RSI; the last incomplete daily bar is excluded.
- 200-week SMA uses 200 completed **weekly** closes (Monday UTC open),
  never 200 daily closes. Incomplete current week is excluded.
- Last eight completed Binance weekly candles are checked against the
  corresponding seven daily OHLC candles from the SAME market.
- All candle intervals must be consecutive, with no gaps or duplicate
  UTC starts. At least 250 complete daily and 210 complete weekly bars.
- HH/HL and LH/LL pivot structure needs three closed candles both
  before and after a confirmed pivot; latest unfinished swing is
  not treated as confirmed.
- 20-day breakout: previous 20 completed days high/low versus latest
  completed-day close; volume activity compared with the previous
  20 complete days median.
- Trend classification is bullish only when closed daily close > MA200,
  MA20 > MA50 > MA200 AND last closed weekly close > 200-week MA.
  Bearish requires the reverse of all three. Otherwise mixed.
  Trend and RSI describe market context, NOT standalone reversal signals.

## Integration and caveats

The BTC bridge btc-monitor/build_feed.py reads the price source, rejects
stale/malformed observations and publishes under btc_technicals in
btc-monitor/data/brief.json, plus readiness flags
price_technical_verified and price_technical_cross_venue.

Daily price source: Binance BTCUSDT SPOT quoted in USDT, not worldwide
BTC/USD or perpetual. USDT is approximately USD but not identical.
Never treat missing values as zero, mix partial-day and completed-day
indicators, or claim Coinbase corroboration without the actual
same-date closed-candle check. Compare price with macro, derivatives,
liquidity and holder behavior before issuing risk notifications.

Regression tests cover missing periods, partial daily/weekly exclusion,
RSI edge cases, independent price mismatch quarantine, history length
and confirmed swing structure. CI persists the real public-source result;
offline tests alone do not count as a successful integration.
