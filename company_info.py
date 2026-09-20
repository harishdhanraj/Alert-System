"""
company_info.py
----------------
Fetches company description, sector, and industry for a list of tickers,
so the scan output can be filtered/grouped by sector or skimmed with a
one-line description instead of just a bare ticker symbol.

yfinance has no batch endpoint for this (unlike price history), so each
ticker is a separate network call via yf.Ticker(t).info. To keep that
reasonably fast and polite:
  - calls are spread across a small thread pool (info requests, not heavy
    downloads, so this is safe at a modest concurrency)
  - results are cached to a local JSON file (company_info_cache.json by
    default) so re-running the scanner doesn't re-fetch tickers whose
    sector/industry/description you already have. Cache entries older
    than max_age_days are refreshed (this data barely changes day to day).
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

CACHE_FILE = "company_info_cache.json"
CACHE_MAX_AGE_DAYS_DEFAULT = 30
DESCRIPTION_MAX_CHARS = 400


def _load_cache(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache, path):
    try:
        with open(path, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _fetch_one(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        description = (info.get("longBusinessSummary") or "")[:DESCRIPTION_MAX_CHARS]
        # shortName is the display name yfinance itself uses (e.g. "Amazon.com, Inc.");
        # longName is sometimes missing, shortName rarely is.
        name = info.get("shortName") or info.get("longName") or ""
        return ticker, {
            "company_name": name,
            "sector": info.get("sector", "") or "",
            "industry": info.get("industry", "") or "",
            "description": description,
            "fetched_at": time.time(),
        }
    except Exception:
        return ticker, {"company_name": "", "sector": "", "industry": "", "description": "", "fetched_at": time.time()}


def get_company_info_bulk(tickers, max_workers=10, cache_path=CACHE_FILE,
                           max_age_days=CACHE_MAX_AGE_DAYS_DEFAULT, use_cache=True):
    """
    Returns {ticker: {"sector": ..., "industry": ..., "description": ...}}
    for every ticker in `tickers`. Cache hits younger than max_age_days are
    reused as-is; everything else (new tickers or stale entries) is fetched
    fresh from yfinance in parallel.
    """
    cache = _load_cache(cache_path) if use_cache else {}
    now = time.time()
    max_age_sec = max_age_days * 86400

    need_fetch = [
        t for t in tickers
        if not cache.get(t) or (now - cache[t].get("fetched_at", 0)) > max_age_sec
    ]

    if need_fetch:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_fetch_one, t): t for t in need_fetch}
            for fut in as_completed(futures):
                t, data = fut.result()
                cache[t] = data
        _save_cache(cache, cache_path)

    return {
        t: {"company_name": cache.get(t, {}).get("company_name", ""),
            "sector": cache.get(t, {}).get("sector", ""),
            "industry": cache.get(t, {}).get("industry", ""),
            "description": cache.get(t, {}).get("description", "")}
        for t in tickers
    }
