# Codex project instructions

## Goal
Maintain a small, auditable multi-instrument market analysis service for historical queries, extensible statistics, current indicators and rule-based allocation reminders. CSI 300 remains the bundled default instrument.

## Principles
- Never silently change indicator definitions or strategy thresholds.
- Keep the bundled CSV as the default reproducible data source.
- Add instruments through `data/instruments.json`; keep instrument-specific details out of the generic service, API and CLI layers.
- Add holding-return aggregation algorithms through the statistics-method registry instead of branching in the service.
- Treat all signals as decision support, not personalized financial advice or automatic trading instructions.
- Prefer simple, testable rules over model-heavy or overfit logic.
- When adding a live data source, preserve offline operation and validate its schema against `date,open,high,low,close,amount,return,net_value`.
- Treat `daily_return` as the canonical decimal return; retain `return` only as a legacy CSV/API alias. CSI 300 `amount` is stored in CNY thousands; provider adapters must convert their native unit before returning data.
- Tushare must never be required for normal offline, BaoStock, or AKShare operation.
- Online priority is instrument-specific through `source_priority` and follows a three-tier structure: primary source, backup source, and local CSV as the final fallback. For Chinese indices the primary path is EastMoney via AKShare `index_zh_a_hist(symbol=<plain 6-digit code>)` (market auto-detected, falling back to the prefixed `stock_zh_index_daily_em`), backed by AKShare/Tencent, then BaoStock, then optional Tushare. Verified Chinese-index adapters are BaoStock, AKShare/Tencent, AKShare/EastMoney (both entry points), and optional Tushare.
- Record which source served the latest update in a JSON sidecar next to each CSV (`data/<file>.csv.meta.json`, fields: source, source_priority, download_time, latest_date, overlap_records, new_records). View it with `csi300 source-meta --symbol <symbol>`.
- When a backup source takes over, require the last 5-10 overlapping trading days to agree with the local close before stitching; reject the update (and keep the old CSV) on mismatch.
- Tencent `amount` is lots while EastMoney `amount` is CNY yuan. Never merge those units silently: retain Tencent amount only for `LOTS` instruments and convert EastMoney amount only for `CNY_THOUSAND` instruments.
- Never write remote data until OHLC, ordering, uniqueness, and overlap-close validation all pass. Preserve the old CSV on every failure.
- Add tests for every strategy-rule change and for every new data-source adapter.
- Keep the 0-100 allocation scores separate from the legacy multiplier/reduction strategy. A score change must not silently alter the established strategy output.
- Deduplicated event backtests define an event at the false-to-true threshold crossing, then apply the configured trading-day cooldown between event starts.

## Indicator conventions
- Charts display MA60, MA250, MA500, MA1250 — simple moving averages of `close` over trading days. Windows 5/10/20/180 remain computed and available through the indicators API, but are not drawn.
- Bias = close / MA - 1.
- RSI14 uses Wilder smoothing.
- RSI pullback flags are based on the prior day's RSI crossing down through 75 or 70.

## Strategy conventions
- Accumulation primarily uses MA250 negative bias, with RSI oversold boosts and MA1250 as a long-cycle confirmation.
- Reduction primarily uses MA500 positive bias, with MA1250 and RSI pullback confirmations.
- Never recommend reducing the core allocation below 60% solely from these technical rules.

## Current instrument catalog
- Bundled offline data currently covers 16 indices: CSI 300/500/800/1000/100, CSI A500, CSI All Share, ChiNext, STAR 50, SSE Composite/50/180/380/Dividend, SZSE Component, and CSI Dividend.
- The catalog also pre-registers 6 more Chinese indices (no bundled CSV yet — fetch with `csi300 bootstrap`): 科创100 (000698), 双创50 (931643), 红利低波100 (930955), 创业板50 (399673), 北证50 (899050), 中证2000 (932000). Instruments without a local CSV are reported as `data_available: false` by `/instruments` and skipped by `/comparison` instead of failing.
- Do not use ETF prices as silent proxies for missing indices. Add STAR 50, CSI 2000, total-return indices, overseas indices, or commodities only with a clearly identified and validated provider series.
