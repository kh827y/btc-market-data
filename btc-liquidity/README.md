# BTC visible order-book depth — plan item 6/8

Automatic hourly collection without API keys or paid services of BTC spot and perpetual order books. GitHub Actions runs at UTC minute 19, ahead of the risk monitor at minute 34.

## Live sources and quality

Spot markets: Binance BTC/USDT, Coinbase BTC/USD, Bybit BTC/USDT, OKX BTC/USDT. Perpetual markets: Binance, Bybit and OKX BTCUSDT. Data are **venue-local quotes**, not a worldwide BTC book. Each observed snapshot records time, best bid/ask midpoint, spread, level count, observed book reach, visible bid and ask notional within 0.05%, 0.2% and 1% of midpoint, and bid share.

Bands beyond actually observed depth are **null, never zero**. Missing API, stale timestamps, abnormal spreads, crossed/unordered books and price outliers are quarantined. A resting visible order can be cancelled, so visible depth is NOT executed trades, guaranteed support, or liquidation-price density.

For OKX perpetuals, contract counts are converted into BTC using the current public instrument ctVal and ctMult (BTC-denominated contracts only), and are rejected if denomination changes. Like-for-like changes over 24 hours, 7 days and 30 days are calculated ONLY when a genuine earlier snapshot exists, within +/-3 hours of target time, for the same venue/instrument/band. The raw hourly sampled history is retained ~32 days; the history genuinely begins when the GitHub workflow runs. There is no invented or reconstructed older spot orderbook.

## Archived futures: independent older historical series

Binance public USD-M perpetual bookDepth 30-second archival samples are used for 2026-06-01 to 2026-09-02 ONLY. A background backfill processes up to 100 daily ZIPs per run (450-second limit; resumes if incomplete), validates archive rows, and derives daily medians of bid/ask USD notional at 0.2%, 1% and 2% bands. Historical perpetual prices must not be mixed with spot liquidity and are not a substitute for modern spot-depth data.

**Known upstream defect**: Binance futures archival ask depth froze in several inner bands from 2026-09-03. See https://github.com/binance/binance-public-data/issues/496 . Newer archived dates are excluded; a valid ZIP checksum does not imply valid underlying observations.

## Outputs

- btc-liquidity/data/latest.json — machine-readable current snapshot, venue coverage, comparable history only where it exists, source timestamps, quality status, and errors.
- btc-liquidity/data/history.json — retained live snapshots, backfilled historical Binance futures daily aggregates, per-day failures. Data files will be created by the first successful workflow run.

The scheduled monitoring automation must verify generated_at and status, check book reach for every band, and treat this as additional market context, NOT a stand-alone reversal signal. The monitor reading this JSON is **not** automatically guaranteed until item 7/8 (integration) is completed.

Limits: Source APIs can block GitHub runner IPs; errors stay visible. 1h REST snapshots miss brief liquidity events. The quote is USDT on most venues and is treated as approximately USD for large-scale research (not exact execution cost). A free multi-year multi-venue spot Level 2 archive is not claimed.


## Full free source backfill (additional historical layer)

A separate verified historical L2 collector now reads free [CryptoHFTData](https://www.cryptohftdata.com/docs/rest-orderbook) hourly Parquet files from the published archive since 2025-06-28. Public GET /download requires no key (60 requests/minute free). A genuine daily checkpoint in the 11:00, 12:00 or 13:00 UTC hourly file is extracted (12:00 preferred) for **Binance Spot, Bybit Spot, Bitget Spot, OKX Spot, Binance USD-M Futures, Bybit linear perpetuals, and OKX USDT perpetuals**. Only genuine vendor snapshot rows are used, including checkpoints that occur later within the selected hour. If the preferred hour lacks a verifiable snapshot, it attempts neighboring 11:00 and 13:00 UTC files, never extrapolating unanchored updates as full depth. It excludes malformed/non-Parquet responses, crossed books and incomplete price-band reach. Historical quantities on OKX USDT perpetuals assume 0.01 BTC/contract: check historical contract changes before relying on distant dates.

* btc-liquidity/data/hft_latest.json — source-qualified daily 12:00 UTC historical book-depth snapshots by exchange, 1/7/30/90/365-day like-for-like date comparisons (only when observation clock times differ by at most 2 hours) and 7/30/90/365-day observed baselines **only after enough distinct valid days exist**.
* btc-liquidity/data/hft_history.json — actual 12:00 snapshots with source path, date, instrument type, levels, spread, 0.05%/0.2%/1% reach, bid/ask USD notional and validation errors. It does not publish the raw provider dataset or pretend that one checkpoint is continuous L2 coverage. The original 2026-06 to 09 pre-defect Binance futures bookDepth records remain a separate type of archive.

GitHub Actions [btc-hft-l2.yml](../.github/workflows/btc-hft-l2.yml) runs on every hour at UTC :23, fills a bounded batch from the entire available publication history beginning 2025-06-28, prioritizes comparators before sequential backfill, and rechecks missing source checkpoints after 7 days, and continues over subsequent runs. There is no payment or Codex. Historical completeness is reported per venue and never assumed if an old file is absent or lacks a starting snapshot. Read the provider's [documented gaps and corrections](https://www.cryptohftdata.com/docs/data-gaps-and-corrections) before declaring a long-term statistical conclusion.

**Important:** archive backfilling does not automatically update the ChatGPT risk-monitor automation's prompt. The next integration item needs to read and verify freshness and quality of BOTH hft_latest.json and latest.json. Unlike our current live REST sampled books, daily source checkpoints can provide reliable backdated anchors for like-for-like historical comparisons.

### Item 6 verified-data policy

Missing exchange snapshots remain a **real completeness limitation**, not a reason to fabricate depth. Provider documentation explicitly says an old hourly file can contain only changes but no anchor. We do not call an unanchored reconstruction a 'verified full order book'. The collector tries three nearby hourly files and transparently records unresolved gaps for future rechecks. Real source time, complete band coverage, observation method and UTC-hour offset are retained in each comparison. Seven markets do not equal worldwide liquidity. A historical daily point-in-time snapshot cannot detect short-lived intraday liquidity withdrawal; live REST and other monitoring metrics are needed for that use.

The QA target is to obtain useful same-clock 1/7/30-day comparisons, defensible longer comparisons where snapshots exist, and a reproducible coverage report. Do not call the older multi-year series exhaustive until its actual per-exchange coverage supports that claim.
