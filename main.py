#!/usr/bin/env python3
"""
main.py
-------
Run a support / resistance / breakout scan across many tickers.

Rules applied (per your spec):
  - Near RESISTANCE            -> AVOID (upside is capped, selling pressure zone)
  - Near SUPPORT (at or above) -> BUY candidate
  - BELOW SUPPORT (by up to --below-support-pct%)
                                -> flagged separately, shown with % below
  - Closed ABOVE resistance in the last 1-2 days on a volume spike
                                -> BREAKOUT / new rally candidate

For your near-support / below-support watchlist specifically, the script
can also pull the latest headlines per ticker (and general market news)
from Finviz, so you can sanity-check WHY something is sitting near or
under support before treating it as a buy.

Examples
--------
# Free Finviz screener universe, all three windows, results to CSV, with news
python main.py --source free --period all --news

# Finviz Elite universe with your own filter string, 6-month window only
python main.py --source elite --api-key YOUR_KEY \
    --filters "cap_midover,sh_avgvol_o500,sh_price_o10" --period 6mo --news

# Your own watchlist file, one ticker per line
python main.py --source file --tickers-file my_watchlist.txt --period 1mo --news

# Just print general market news headlines along with the scan
python main.py --source free --period 6mo --market-news
"""

import argparse
import pandas as pd
from tabulate import tabulate

from finviz_client import (
    get_tickers_from_finviz_elite,
    get_tickers_from_finvizfinance,
    get_tickers_from_file,
)
from price_data import fetch_history_batch
from scanner import scan_ticker, PERIODS
from news_client import get_ticker_news_bulk, get_market_news
from company_info import get_company_info_bulk


def parse_args():
    p = argparse.ArgumentParser(description="Support/Resistance/Breakout scanner (Finviz + Yahoo data)")
    p.add_argument("--period", choices=["1mo", "3mo", "6mo", "all"], default="all",
                   help="Lookback window(s) to analyze (default: all three)")
    p.add_argument("--source", choices=["elite", "free", "file"], default="free",
                   help="Where to pull the ticker universe from (default: free Finviz screener)")
    p.add_argument("--filters", default="cap_midover,sh_avgvol_o500,sh_price_o10",
                   help="Finviz filter string, elite mode only (copy from the finviz.com URL after 'f=')")
    p.add_argument("--tickers-file", default=None,
                   help="Path to a text file, one ticker per line (source=file)")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap number of tickers scanned (handy for a quick test run)")
    p.add_argument("--near-pct", type=float, default=3.0,
                   help="%% distance from a level to count as 'near' (default 3.0)")
    p.add_argument("--below-support-pct", type=float, default=15.0,
                   help="How far below support (%%) to still flag as BELOW_SUPPORT (default 15.0)")
    p.add_argument("--vol-multiplier", type=float, default=1.5,
                   help="Volume spike multiplier required to confirm a breakout (default 1.5x 20-day avg)")
    p.add_argument("--retest-lookback-days", type=int, default=40,
                   help="How far back to look for a prior breakout when checking for a RETEST (default 40)")
    p.add_argument("--retest-undercut-pct", type=float, default=2.0,
                   help="How far price is allowed to have dipped below the retested level and still "
                        "count as 'holding' (default 2.0%%)")
    p.add_argument("--tight-base-window", type=int, default=10,
                   help="Number of bars immediately before a breakout/retest used to measure "
                        "prior-base tightness (default 10)")
    p.add_argument("--tight-base-pct", type=float, default=8.0,
                   help="Max High-Low range (%% of price) over --tight-base-window for a base to be "
                        "flagged 'tight' (default 8.0%%)")
    p.add_argument("--out", default="scan_results.csv", help="CSV file for full results")
    p.add_argument("--api-key", default=None, help="Finviz Elite API key (or set FINVIZ_API_KEY env var)")
    p.add_argument("--batch-size", type=int, default=50, help="Tickers per yfinance batch download")
    p.add_argument("--news", action="store_true",
                   help="Fetch recent headlines for tickers in the near/below-support watchlist")
    p.add_argument("--news-limit", type=int, default=3, help="Headlines per ticker (default 3)")
    p.add_argument("--news-top-n", type=int, default=15,
                   help="Cap how many tickers get news fetched, to avoid hammering Finviz (default 15, "
                        "takes the ones closest to/furthest below support)")
    p.add_argument("--market-news", action="store_true",
                   help="Also print general market news headlines (not ticker-specific)")
    p.add_argument("--no-company-info", dest="company_info", action="store_false",
                   help="Skip merging sector / industry / description columns into the output "
                        "(they're included by default, via yfinance)")
    p.set_defaults(company_info=True)
    p.add_argument("--info-max-age-days", type=int, default=30,
                   help="Reuse cached sector/industry/description if fetched within this many days (default 30)")
    return p.parse_args()


def get_universe(args):
    if args.source == "elite":
        return get_tickers_from_finviz_elite(filters=args.filters, api_key=args.api_key)
    elif args.source == "file":
        if not args.tickers_file:
            raise ValueError("--tickers-file is required when --source file")
        return get_tickers_from_file(args.tickers_file)
    else:
        return get_tickers_from_finvizfinance(limit=args.limit)


def print_news_block(ticker_news: dict):
    for ticker, headlines in ticker_news.items():
        print(f"\n  {ticker} news:")
        if not headlines:
            print("    (no recent headlines found)")
            continue
        for h in headlines:
            date = h.get("date", "")
            title = h.get("title", "")
            source = h.get("source", "")
            tail = f" ({source})" if source else ""
            print(f"    [{date}] {title}{tail}")


def main():
    args = parse_args()
    periods = PERIODS if args.period == "all" else [args.period]

    if args.market_news:
        print("=" * 70)
        print("GENERAL MARKET NEWS")
        print("=" * 70)
        for h in get_market_news(limit=10):
            date = h.get("date", "")
            title = h.get("title", "")
            source = h.get("source", "")
            tail = f" ({source})" if source else ""
            print(f"  [{date}] {title}{tail}")
        print()

    print("Fetching ticker universe from Finviz...")
    tickers = get_universe(args)
    if args.limit:
        tickers = tickers[:args.limit]
    print(f"{len(tickers)} tickers to scan.")

    print("Downloading price history (one pass covers all requested windows)...")
    history = fetch_history_batch(tickers, batch_size=args.batch_size)
    print(f"Got usable data for {len(history)} of {len(tickers)} tickers.")

    rows = []
    for ticker, df in history.items():
        try:
            results = scan_ticker(df, periods=periods, near_pct=args.near_pct,
                                   vol_multiplier=args.vol_multiplier,
                                   below_support_pct=args.below_support_pct,
                                   retest_lookback_days=args.retest_lookback_days,
                                   retest_undercut_pct=args.retest_undercut_pct,
                                   tight_base_window=args.tight_base_window,
                                   tight_base_pct=args.tight_base_pct)
        except Exception as e:
            print(f"  [WARN] {ticker} failed: {e}")
            continue
        for period, r in results.items():
            rows.append({"ticker": ticker, "period": period, **r})

    if not rows:
        print("No results produced.")
        return

    result_df = pd.DataFrame(rows)

    if args.company_info:
        unique_tickers = result_df["ticker"].unique().tolist()
        print(f"\nFetching sector/industry/description for {len(unique_tickers)} tickers "
              f"(cached up to {args.info_max_age_days} days)...")
        info = get_company_info_bulk(unique_tickers, max_age_days=args.info_max_age_days)
        info_df = pd.DataFrame.from_dict(info, orient="index").reset_index().rename(columns={"index": "ticker"})
        result_df = result_df.merge(info_df, on="ticker", how="left")

    result_df.to_csv(args.out, index=False)
    print(f"\nFull results for every ticker/period saved to: {args.out}\n")

    cols = ["ticker", "price", "support", "resistance",
            "dist_to_support_pct", "dist_to_resistance_pct", "volume_ratio", "entry_signal"]
    if args.company_info:
        cols = ["ticker", "company_name", "sector", "price", "support", "resistance",
                "dist_to_support_pct", "dist_to_resistance_pct", "volume_ratio", "entry_signal"]

    # breakout/retest tables get an extra tight_prior_base column
    setup_cols = cols[:-1] + ["tight_prior_base", "entry_signal"]

    for period in periods:
        sub = result_df[result_df["period"] == period]
        print(f"\n{'=' * 70}\n{period.upper()} WINDOW\n{'=' * 70}")

        # --- Breakout / rally candidates ---
        breakout = sub[sub["category"] == "BREAKOUT_RALLY"].sort_values("volume_ratio", ascending=False)
        print(f"\n--- BREAKOUT \u2014 new rally candidates (high volume above resistance) ({len(breakout)}) ---")
        print(tabulate(breakout[setup_cols], headers="keys", showindex=False, tablefmt="simple") if not breakout.empty else "  (none)")

        # --- Retest candidates ---
        retest = sub[sub["category"] == "RETEST_BUY"].sort_values("days_since_breakout")
        print(f"\n--- RETEST \u2014 pullback to a recent breakout level, still holding ({len(retest)}) ---")
        print(tabulate(retest[setup_cols], headers="keys", showindex=False, tablefmt="simple") if not retest.empty else "  (none)")

        # --- Near resistance / avoid ---
        avoid = sub[sub["category"] == "NEAR_RESISTANCE_AVOID"].sort_values("dist_to_resistance_pct")
        print(f"\n--- NEAR RESISTANCE \u2014 avoid for now ({len(avoid)}) ---")
        print(tabulate(avoid[cols], headers="keys", showindex=False, tablefmt="simple") if not avoid.empty else "  (none)")

        # --- Near support OR below support, combined, as requested ---
        watch = sub[sub["category"].isin(["NEAR_SUPPORT_BUY", "BELOW_SUPPORT"])].copy()
        watch = watch.sort_values("dist_to_support_pct")  # most-below-support first, then near-support
        print(f"\n--- NEAR OR BELOW SUPPORT \u2014 buy watch / breakdown risk ({len(watch)}) ---")
        if not watch.empty:
            display = watch.copy()
            watch_cols = ["ticker", "price", "support", "resistance",
                          "dist_to_support_pct", "volume_ratio", "entry_signal"]
            if args.company_info:
                watch_cols[1:1] = ["company_name", "sector"]
            print(tabulate(display[watch_cols],
                           headers="keys", showindex=False, tablefmt="simple"))

            if args.news:
                watch_tickers = watch["ticker"].head(args.news_top_n).tolist()
                print(f"\n  Fetching news for top {len(watch_tickers)} tickers on this list "
                      f"(--news-top-n={args.news_top_n})...")
                ticker_news = get_ticker_news_bulk(watch_tickers, limit_per_ticker=args.news_limit)
                print_news_block(ticker_news)
        else:
            print("  (none)")


if __name__ == "__main__":
    main()
