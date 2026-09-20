"""
finviz_client.py
-----------------
Pulls the ticker universe to scan from Finviz.

Two modes:
1. Elite API (source="elite") - uses your Finviz Elite export endpoint + API key.
   Set FINVIZ_API_KEY as an environment variable, or pass --api-key on the CLI.
2. Free screener (source="free") - uses the open-source `finvizfinance` package,
   which scrapes the public Finviz screener. No API key needed, slower, and
   should not be hammered with very frequent requests.
3. File (source="file") - just read tickers from a plain text file, one per line.
   Useful if you already keep a watchlist.
"""

import io
import os
import requests
import pandas as pd

FINVIZ_EXPORT_URL = "https://elite.finviz.com/export.ashx"


def get_tickers_from_finviz_elite(filters: str = "", api_key: str = None, view: str = "111") -> list:
    """
    Pull a ticker list from Finviz Elite's CSV export endpoint.

    filters: Finviz screener filter string, e.g.
             "cap_midover,sh_avgvol_o500,sh_price_o10"
             (see https://finviz.com/screener.ashx for filter codes -
              the string in your browser URL after 'f=' is exactly this)
    api_key: Finviz Elite API auth token (Finviz account -> Elite -> API)
    """
    api_key = api_key or os.environ.get("FINVIZ_API_KEY")
    if not api_key:
        raise ValueError(
            "No Finviz API key found. Set the FINVIZ_API_KEY environment "
            "variable, or pass --api-key on the command line."
        )
    params = {"v": view, "auth": api_key}
    if filters:
        params["f"] = filters

    resp = requests.get(FINVIZ_EXPORT_URL, params=params, timeout=30)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))
    ticker_col = "Ticker" if "Ticker" in df.columns else df.columns[1]
    return df[ticker_col].dropna().unique().tolist()


def get_tickers_from_finvizfinance(filters: dict = None, limit: int = None) -> list:
    """
    Free fallback: uses the finvizfinance package (pip install finvizfinance).
    No API key required, but it scrapes finviz.com so don't call it too often
    or with huge screener pulls in a tight loop.
    """
    from finvizfinance.screener.overview import Overview

    fo = Overview()
    fo.set_filter(filters_dict=filters or {})
    df = fo.screener_view()
    tickers = df["Ticker"].tolist()
    return tickers[:limit] if limit else tickers


def get_tickers_from_file(path: str) -> list:
    with open(path) as f:
        return [line.strip().upper() for line in f if line.strip()]
