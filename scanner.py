"""
scanner.py
----------
Runs the support/resistance/breakout model across one or more lookback
windows (1mo, 3mo, 6mo) for a single ticker's price history.
"""

import pandas as pd
from levels import find_support_resistance, classify

PERIODS = ["1mo", "3mo", "6mo"]

# Approximate trading days per window
_DAYS_MAP = {"1mo": 21, "3mo": 63, "6mo": 126}


def trim_to_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    n = _DAYS_MAP.get(period, 126)
    return df.tail(n)


def scan_ticker(df: pd.DataFrame, periods=None, near_pct=3.0, vol_multiplier=1.5, breakout_days=2,
                 below_support_pct=15.0, retest_lookback_days=40, retest_undercut_pct=2.0,
                 tight_base_window=10, tight_base_pct=8.0):
    """
    df: full ~7mo daily OHLCV history for one ticker.
    Returns {period_label: classification_dict} for each requested period
    that has enough data.

    Levels are computed excluding the last `breakout_days` bars, so a
    breakout is measured against the resistance that existed BEFORE the
    move - not a level that already includes the move itself.

    retest_lookback_days / retest_undercut_pct control how far back and
    how loosely a "retest" of a broken-resistance-turned-support level is
    detected (see levels.detect_retest). tight_base_window / tight_base_pct
    control what counts as a "tight prior base" before a breakout or
    retest (see levels._base_tightness).
    """
    periods = periods or PERIODS
    out = {}
    for period in periods:
        sub = trim_to_period(df, period)
        if sub is None or len(sub) < 15:
            continue
        levels = find_support_resistance(sub, exclude_last_n=breakout_days)
        out[period] = classify(sub, levels, near_pct=near_pct, vol_multiplier=vol_multiplier,
                                breakout_days=breakout_days, below_support_pct=below_support_pct,
                                retest_lookback_days=retest_lookback_days,
                                retest_undercut_pct=retest_undercut_pct,
                                tight_base_window=tight_base_window, tight_base_pct=tight_base_pct)
    return out
