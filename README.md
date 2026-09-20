# Support / Resistance / Breakout Scanner

A local Python tool you run whenever you want. It scans a universe of
tickers (sourced from Finviz) and flags each one as:

- **NEAR_SUPPORT_BUY** — close is within X% above its support level → buy candidate
- **BELOW_SUPPORT** — close has broken below support, by up to a configurable % → flagged as a watch item, shown with the exact % below
- **NEAR_RESISTANCE_AVOID** — close is within X% below its resistance level → avoid for now
- **BREAKOUT_RALLY** — closed **above** the prior resistance in the last 1–2 days **with a volume spike** → potential new rally
- **RETEST_BUY** — price broke out above a resistance level (on volume) at some point in the recent past, and has since pulled back to that same level (now acting as support) **and is still holding it** → often a safer, better risk/reward entry than chasing the original breakout candle
- **NEUTRAL** — none of the above

## Retest detection

A `RETEST_BUY` fires when the level currently acting as **support** can be
traced back to a close that broke *above* it on volume (`--vol-multiplier`,
default 1.5x) within the last `--retest-lookback-days` (default 40) trading
days, and price hasn't closed more than `--retest-undercut-pct` (default
2.0%) below that level since. This turns a generic "near support" bounce
into a specifically-flagged "this was resistance, it broke, now it's being
retested" setup, which is usually higher-conviction than a plain support
touch. Relevant columns: `is_retest`, `retest_level`,
`days_since_breakout`, `retest_worst_undercut_pct`.

## Tight prior base

Every `BREAKOUT_RALLY` and `RETEST_BUY` row also gets:

- **`prior_base_range_pct`** — the High/Low range (as % of price) over the
  `--tight-base-window` (default 10) bars immediately **before** the
  breakout, i.e. how tight/quiet the consolidation was right before the
  move.
- **`tight_prior_base`** — `True` when `prior_base_range_pct` is at or
  below `--tight-base-pct` (default 8.0%). A tight, low-volatility base
  right before a breakout is generally read as a cleaner, higher-quality
  setup than a breakout out of a wide, choppy range — same idea as a
  "VCP"/tight-flag base. This is informational (it doesn't change the
  category), so you can still sort/filter on it yourself.

`NEAR_SUPPORT_BUY` and `BELOW_SUPPORT` are printed together as one
**"near or below support"** watchlist, sorted so the ones furthest below
support show up first — this is where a temporary dip (still a buy) and a
real breakdown (something changed, be careful) sit side by side so you can
compare them.

It runs the model over **1-month, 3-month, and 6-month** lookback windows
(you choose one or all three per run).

## Entry signal

Every row now also includes:

- **`entry_trigger`** — the exact price that matters for that category (the
  resistance level for anything not yet a breakout, the support level for a
  support-based buy).
- **`entry_signal`** — a plain-English instruction, e.g. for a stock sitting
  under resistance at 172: `WAIT - buy trigger is a close above 172`. Once
  price actually closes above 172 on a volume spike, that same row becomes
  `BREAKOUT_RALLY` with `ENTER - closed above 172 resistance on 1.8x volume`.
- **`signal_active`** — `True` only for `BREAKOUT_RALLY` and
  `NEAR_SUPPORT_BUY` (i.e. "you could act on this today"); `False` for
  everything that's still waiting on a trigger price.

This doesn't predict anything new — it's the same category/level math as
before, just phrased as "what price gets me in" instead of a raw distance
percentage.

## Company info (sector / industry / description)

`company_name` (e.g. "Amazon.com, Inc." next to `AMZN`), `sector`,
`industry`, and a short `description` column are merged into the output
CSV **by default**, pulled from yfinance (`Ticker.info`) per ticker. This
is a separate network call per ticker (no batch endpoint exists for it),
so results are cached locally to `company_info_cache.json` and reused for
`--info-max-age-days` days (default 30) before being re-fetched — this
data barely changes day to day, so there's no reason to re-hit the network
for it on every run.

```bash
python main.py --source file --tickers-file my_watchlist.txt --period 6mo
```

If you want a faster run and don't need sector/description (e.g. a quick
test with `--limit`), skip it with `--no-company-info`:

```bash
python main.py --source file --tickers-file my_watchlist.txt --period 6mo --no-company-info
```

## News

Add `--news` to pull the latest headlines (via Finviz) for the tickers on
your near/below-support watchlist — useful for telling "healthy pullback"
apart from "something broke." Add `--market-news` to also print general
market headlines at the top of the report. News fetching is capped to a
small number of tickers by default (`--news-top-n`, default 15) since it
scrapes Finviz per ticker and shouldn't be run against your whole universe.

## How it works

1. **Ticker universe** comes from Finviz — either your Elite API export, the
   free public screener, or your own watchlist file.
2. **Price history** (daily OHLCV) comes from Yahoo Finance via `yfinance`,
   since Finviz's API doesn't provide full historical daily bars. One
   ~7-month pull per ticker covers all three windows, so you don't re-hit
   the network per period.
3. **Support/resistance** are found by locating swing highs/lows (local
   extrema) in the window, clustering nearby ones into a level, and picking
   the nearest cluster below (support) and above (resistance) the current
   price.
4. **Breakout** = the recent close broke above the resistance that existed
   *before* the last 1–2 days, and volume in that window is at least
   `vol_multiplier` (default 1.5x) the prior 20-day average volume.

## Setup

```bash
pip install -r requirements.txt
```

If you have a Finviz **Elite** subscription and want to use its export API:

```bash
export FINVIZ_API_KEY="your_elite_api_key"
```

(Find your key/token under Finviz → Elite → API.)

## Usage

Run all three windows against the free Finviz screener universe (default
filter: mid-cap+, avg volume > 500k, price > $10):

```bash
python main.py --source free --period all
```

Run just the 6-month window using your Finviz Elite account and a custom filter
(copy the filter string straight from the Finviz screener URL, the part after `f=`):

```bash
python main.py --source elite --filters "cap_midover,sh_avgvol_o500,sh_price_o10" --period 6mo
```

Run against your own watchlist file (one ticker per line), separately for each window:

```bash
python main.py --source file --tickers-file my_watchlist.txt --period 1mo
python main.py --source file --tickers-file my_watchlist.txt --period 3mo
python main.py --source file --tickers-file my_watchlist.txt --period 6mo
```

Quick test run capped to 25 tickers:

```bash
python main.py --source free --limit 25 --period all
```

### Useful flags

| Flag | Default | What it does |
|---|---|---|
| `--period` | `all` | `1mo`, `3mo`, `6mo`, or `all` |
| `--near-pct` | `3.0` | % distance from a level to count as "near" |
| `--below-support-pct` | `15.0` | How far below support (%) to still flag as `BELOW_SUPPORT` rather than dropping to `NEUTRAL` |
| `--vol-multiplier` | `1.5` | Volume spike multiplier required for breakout confirmation |
| `--retest-lookback-days` | `40` | How far back to look for a prior breakout when checking for a `RETEST_BUY` |
| `--retest-undercut-pct` | `2.0` | How far price may have dipped below the retested level and still count as "holding" |
| `--tight-base-window` | `10` | Bars immediately before a breakout/retest used to measure prior-base tightness |
| `--tight-base-pct` | `8.0` | Max High/Low range (% of price) over `--tight-base-window` to flag a base as "tight" |
| `--out` | `scan_results.csv` | Where full results (every ticker × period) are saved |
| `--batch-size` | `50` | Tickers per yfinance download batch |
| `--limit` | none | Cap the universe size, handy for test runs |
| `--no-company-info` | off | Skip sector/industry/description columns (included by default) |
| `--news` | off | Fetch headlines for the near/below-support watchlist |
| `--news-limit` | `3` | Headlines per ticker |
| `--news-top-n` | `15` | Cap on how many watchlist tickers get news fetched |
| `--market-news` | off | Also print general market news headlines |

## Output

- A printed, grouped summary in your terminal (breakout / buy / avoid, per window)
- A full CSV (`scan_results.csv` by default) with every ticker, every period,
  its price, support, resistance, distance to each level, and volume ratio —
  so you can sort/filter further in Excel or pandas.

## Notes & caveats

- This is a mechanical technical screen, not investment advice. Support and
  resistance from swing-point clustering is a simplification — always sanity
  check flagged names against news, earnings dates, and overall market
  conditions before acting.
- The free Finviz screener path scrapes finviz.com — don't run it in a tight
  loop or with very short intervals between runs.
- `yfinance` occasionally rate-limits large universes. If you're scanning
  thousands of tickers, consider narrowing the Finviz filter (e.g. price,
  volume, market cap minimums) rather than pulling the entire market.
- Newly-listed stocks with less than ~3 weeks of history are skipped
  automatically since there isn't enough data to find swing levels.
