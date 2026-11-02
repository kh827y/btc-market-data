# BTC derivatives research feed

Scheduled every hour at UTC minute 09 using GitHub Actions. Output: [latest.json](data/latest.json). No Codex usage, paid API key, or manual local installation.

## Data fields

| Section | Source and scope | Observation window |
|---|---|---|
| `open_interest` | Sharpe, Binance/Bybit/OKX/Gate.io/Hyperliquid in USD notional, **same 5-venue set** | Hourly points and 31 UTC daily dates; changes 1/7/30d |
| `funding` | Sharpe actual settled BTCUSDT (Binance/Bybit), BTC-USDT-SWAP (OKX) | 30d, 90 payments per venue, 8h normalized |
| `liquidations` | Edge or Not observed Binance/Bybit forced liquidations, USD longs/shorts | 24h and 168h, by venue |
| `liquidations_30d_vendor` | Sharpe/Velo reported `quantity` per venue and direction | 31 UTC days; vendor denomination/coverage differs from Edge, **do not sum** |
| `cme_cot` | Official CFTC TFF Futures Only (CME BTC code 133741) | 252 weeks 2022–2026; contract=5 BTC; publication delay |
| `dated_futures_basis` | Sharpe dated futures Binance/Bybit/OKX/Deribit | Most recent contract/expiry + 7d annualized basis; matched four-venue expiry |
| `cme_basis` | Free Boros CME Bitcoin futures-price vs matched spot archive | CME quarterly contracts 2026; historic, latest may lag holidays/weekends |

Provider data and exchange-level open-interest definitions are as published; 5-venue coverage is NOT all BTC futures. Binance public liquidation broadcasts can be rate-limited. CME COT does not include micro futures. CME basis archives represent sampled observations and may be stale. Funding is per settlement period, not interest rate APR. Keep `generated_utc`, actual observation dates, exchange coverage, completeness flags and warnings.

Source references: https://www.sharpe.ai/docs/free-api · https://edgeornot.com/api · https://publicreporting.cftc.gov/Commitments-of-Traders/TFF-Futures-Only/gpe5-46if · https://historical-data.boros.finance/index.html .
