# BTC trend-risk macro and US spot ETF feed — free, source-qualified

Collector: `btc-macro/collector.py`. Runs automatically in GitHub Actions
`.github/workflows/btc-macro-etf.yml` at minute 19 of every UTC hour,
after tests. Persists canonical `data/latest.json` and `data/fred_history.json`.
No API keys or subscriptions. The quality bridge
`btc-monitor/build_feed.py` reads this input; the main BTC automation
consumes `btc-monitor/data/brief.json` (`macro` and `us_spot_bitcoin_etf`)
with **separate** source/component freshness readiness flags.

## Sources and interpretation

- **Fed policy**: FRED daily actual effective fed funds DFF and effective
  target range DFEDTARL/DFEDTARU. Current observations, **NOT** implied FOMC
  futures probabilities, meeting decisions before publication, or an expert
  forecast of future rates.
- **US Treasury yields**: FRED DGS2, DGS10, annual rates in percent (4.98
  means 4.98%, not 0.0498). Curve 10Y minus 2Y is computed only when both
  yields have the SAME dated FRED observation, never by independently using
  two out-of-sync latest dates.
- **Dollar strength**: FRED DTWEXBGS nominal BROAD **trade-weighted**
  dollar index against trading partners. This is **NOT** ICE DXY. DXY
  SIX-currency ICE index uses the separately obtained public Yahoo Finance
  DX-Y.NYB chart series. This optional endpoint can fail with HTTP 429/500;
  in that case DXY stays unavailable rather than being filled with the
  FRED broad USD index. The current DXY quote can be an **unfinished
  trading session**, not a finalized daily close.
- **Fed balance sheet**: FRED WALCL weekly total Fed assets, in
  **USD millions** (never billions). Its historical levels are millions
  of millions, hence the larger numerical bound than interest rates.
- **US-listed spot BTC ETF net creations/redemptions**: The Commoner Bitcoin
  ETF Tracker by TFTC, `https://www.tftc.io/bitcoin-etf-flows/latest.json`
  and `data.json`, freely usable under CC BY 4.0 with required credit
  `The Commoner Bitcoin ETF Tracker by TFTC (tftc.io/bitcoin-etf-flows)`.
  Official upstream source methodology is SoSoValue (daily aggregates and
  current per-fund) plus issuer disclosures tabulated historically by
  Farside Investors. The full history contains 720 published trading
  sessions as of the verified 2026-11-02 run; revisions possible.
  Last 1 and last 5 *trading-session* net flows are verified independently
  of the full-history 21-trading-session total. Per-fund flows must reconcile
  with the total within $5 million or are rejected. A missing current
  session is NOT zero: reports only finalize after US market close,
  weekends/holidays have no trading row, and a published session can
  be revised.

## Data quality and constraints

The bridge validates: original macro source <2.5h old, each FRED row dated
within 7 days for rates/targets or 18 days for broad dollar/Fed balance sheet;
DXY sourced from the ICE DXY instrument with no broad-dollar substitution
and <=7 day age; US spot ETF source licensed/identified and observed within
3 weekdays, with all 5 published records consistent with the latest session.
Gaps, stale or unavailable components become NULL, not zero.

Separate monitoring readiness fields:
`macro_fed_rates`, `macro_treasury_yields`,
`macro_usd_broad_not_dxy`, `macro_exact_ice_dxy`,
`us_spot_btc_etf_flows`. Only those flags equal to true allow the
respective factor to meaningfully enter a risk decision.

**Never interpret correlations as causes**: DXY appreciation, bond yields,
BTC spot ETF net flow, Fed announcements, and BTC price interact but do not
guarantee price direction. Fed policy rate and effective rate are correlated
observations, and FRED broad USD and ICE DXY both reflect currency strength;
they are not separate independent evidence by simple counting.
No alert should fire solely because a newly integrated data feed appeared.

Actual benchmark checks (02 Nov 2026): FRED 2Y/10Y respectively
4.61%/4.98% dated Oct 29; Fed target 3.75–4.00% dated Nov 1; WALCL
6,745,635 million USD dated Oct 28; TFTC Oct 30 finalized spot ETF
-$643.33m, five sessions -$202.59m, 21 sessions -$617.70m. Index
feeds and other vendor figures have differing publication delays and
may have been revised; always read the latest on GitHub.
