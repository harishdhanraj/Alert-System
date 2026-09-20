"""
news_client.py
--------------
Pulls recent headlines for a ticker (and general market news) from Finviz,
via the free `finvizfinance` package. This is scraped from finviz.com's
quote page / news page, so:
  - don't call it in a tight loop across thousands of tickers - it's meant
    to be used on your short "near support / below support / breakout"
    lists, not the entire scanned universe.
  - failures (rate limiting, a ticker with no news, network hiccup) are
    caught and simply return an empty list rather than crashing the scan.
"""

import time


def get_ticker_news(ticker: str, limit: int = 3, pause: float = 0.5) -> list:
    """
    Returns up to `limit` recent headlines for a ticker as a list of dicts:
      {"date": ..., "title": ..., "source": ..., "link": ...}
    Returns [] on any failure (bad ticker, rate limit, no news available).
    """
    try:
        from finvizfinance.quote import finvizfinance
        stock = finvizfinance(ticker)
        news_df = stock.ticker_news()
        if news_df is None or news_df.empty:
            return []
        news_df = news_df.head(limit)
        out = []
        for _, row in news_df.iterrows():
            out.append({
                "date": str(row.get("Date", "")),
                "title": str(row.get("Title", "")),
                "source": str(row.get("Source", "")) if "Source" in news_df.columns else "",
                "link": str(row.get("Link", "")),
            })
        time.sleep(pause)  # be polite - this hits finviz.com per ticker
        return out
    except Exception:
        return []


def get_ticker_news_bulk(tickers: list, limit_per_ticker: int = 3, pause: float = 0.5) -> dict:
    """
    Fetch news for a short list of tickers (e.g. your near-support or
    below-support watchlist, NOT the whole scanned universe). Returns
    {ticker: [headline_dicts]}.
    """
    out = {}
    for t in tickers:
        out[t] = get_ticker_news(t, limit=limit_per_ticker, pause=pause)
    return out


def get_market_news(limit: int = 10) -> list:
    """
    General market news headlines (not ticker-specific), from Finviz's
    news homepage feed. Returns a list of {"date", "title", "source", "link"}.
    """
    try:
        from finvizfinance.news import News
        fnews = News()
        news_dict = fnews.get_news()
        # finvizfinance returns a dict with keys like 'news' and 'blogs',
        # each a DataFrame with Date/Title/Link/Source-ish columns.
        df = news_dict.get("news")
        if df is None or df.empty:
            return []
        df = df.head(limit)
        out = []
        for _, row in df.iterrows():
            out.append({
                "date": str(row.get("Date", "")),
                "title": str(row.get("Title", "")),
                "source": str(row.get("Source", "")) if "Source" in df.columns else "",
                "link": str(row.get("Link", "")),
            })
        return out
    except Exception:
        return []
