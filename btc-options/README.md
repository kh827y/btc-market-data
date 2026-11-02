# BTC options risk monitoring

This hourly collector queries only free, unauthenticated public sources and publishes a **small derived monitoring summary**, not any third-party option-chain dump or Derivasys proprietary historical dataset.

## Data feeds

* **Deribit**: real current BTC option-chain marks from /public/get_instruments and /public/get_book_summary_by_currency. Independently approximates 25-delta call and put IV from Black forward delta using expiry and strike, interpolates to ATM and 25Δ on each expiry, then applies maturity-weighted total-variance interpolation to 7d/14d/30d/90d/180d. **Negative RR25 means downside put IV is richer**, convention `call IV − put IV`. Mark-derived, not directly executable dealer quoted prices or a fitted SVI smile. Expiry gaps >50d tagged wide; no extrapolation.
* **Deribit DVOL**: public historical volatility-index daily candles, 366 complete UTC calendar days, last close and 365d percentile only. DVOL is a forward 30-day variance-based index **not** ATM IV, and does not predict price direction.
* **Derivasys daily published research**: public API https://api.derivasys.com/api/v1/data/BTC/observations, verified 194 published days since 2026-04-22 on 2026-11-02. Hourly collector computes research comparisons for one **limited** quoted tenor (1M), last snapshot timestamp, 7/30-day changes and historical rank in memory. Its full daily source observations are **not republished**. Source: https://www.derivasys.com/api/data/ . License: https://www.derivasys.com/research-artifact-license/v1 .

## Outputs and use

* `data/latest.json` — independently derived current ATM IV/RR25/BF25 for available tenors; DVOL summary; daily research reference; errors, status, source timestamps, methodology and exact coverage. This is a volatility/skew **risk indicator**, not a futures or spot price signal.
* `data/derived_history.json` — self-derived limited rolling 90-day hourly observations; real history starts at the first successful deployment, not backfilled or implied.
* Automatic GitHub Actions UTC minute 13 every hour, preceding the BTC monitor (~UTC minute 34). No Codex, paid keys or local installation.

Quality requirements: treat unavailable tenor/snapshots as null; never claim Derivasys 7-month publication history represents full 5-year options markets; check freshness of current Deribit chain, report dates of Derivasys, and 1M differences in construction. For 3M/6M the exchange expiry grid may be coarse. Use DVOL ≠ ATM IV and RR25 negative = puts richer.
