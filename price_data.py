"""
price_data.py
--------------
Downloads daily OHLCV history for a list of tickers in batches, using
yfinance. We always pull ~7 months of daily bars in one shot, then trim
down to the 1mo / 3mo / 6mo windows locally, so you only hit the network
once per ticker regardless of how many periods you want to analyze.
"""

import time
import pandas as pd
import yfinance as yf

# Fetch a little more than needed so indicators have warm-up room.
MAX_FETCH_PERIOD = "7mo"


def fetch_history_batch(tickers, batch_size=50, pause=1.0, period=MAX_FETCH_PERIOD):
    """
    Download historical daily OHLCV for a list of tickers in batches.
    Returns a dict {ticker: DataFrame} with columns Open, High, Low, Close, Volume.
    """
    results = {}
    total = len(tickers)

    for i in range(0, total, batch_size):
        batch = tickers[i:i + batch_size]
        print(f"  fetching {i + 1}-{min(i + batch_size, total)} of {total}...")
        try:
            data = yf.download(
                tickers=batch,
                period=period,
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            print(f"  [WARN] batch starting at {i} failed: {e}")
            continue

        if len(batch) == 1:
            t = batch[0]
            df = data.dropna()
            if not df.empty:
                results[t] = df
        else:
            for t in batch:
                try:
                    df = data[t].dropna()
                    if not df.empty and len(df) >= 15:
                        results[t] = df
                except (KeyError, Exception):
                    continue

        time.sleep(pause)  # be polite to Yahoo's endpoint

    return results
