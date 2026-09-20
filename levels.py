"""
levels.py
---------
Support/resistance detection (swing-point clustering, same idea used for
the manual SNDK analysis) and the buy / avoid / breakout classification.
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def _cluster_levels(prices, tolerance_pct=1.5):
    """
    Cluster a list of swing price points into levels. Points within
    tolerance_pct of each other are merged into one level. Returns a list
    of (level_price, touch_count) tuples - touch_count is how many times
    price reacted near that level, which is a rough proxy for strength.
    """
    if len(prices) == 0:
        return []
    prices = sorted(prices)
    clusters = []
    current = [prices[0]]
    for p in prices[1:]:
        center = np.mean(current)
        if center > 0 and abs(p - center) / center * 100 <= tolerance_pct:
            current.append(p)
        else:
            clusters.append((float(np.mean(current)), len(current)))
            current = [p]
    clusters.append((float(np.mean(current)), len(current)))
    return clusters


def find_support_resistance(df: pd.DataFrame, order: int = 3, tolerance_pct: float = 1.5,
                             exclude_last_n: int = 0):
    """
    df must have High, Low, Close, Volume columns (daily bars), already
    trimmed to the lookback window you want (1mo / 3mo / 6mo).

    exclude_last_n: number of most-recent bars to leave OUT of the swing
    high/low detection. This matters for breakout detection - if today's
    surge is included in the swing-high scan, it gets counted as "the
    resistance" instead of being compared against the PRIOR resistance it
    just broke through. Pass breakout_days here when you specifically want
    to test for a breakout; pass 0 when you just want the current levels.

    Finds local swing highs/lows, clusters them into levels, then picks:
      - support    = nearest cluster below the current price
      - resistance = nearest cluster above the current price
    Falls back to the period's min/max if no cluster exists on one side
    (e.g. the stock is at a new all-time high or low for the window).
    """
    current_price = float(df["Close"].iloc[-1])

    hist = df.iloc[:-exclude_last_n] if exclude_last_n > 0 and len(df) > exclude_last_n else df
    lows = hist["Low"].values
    highs = hist["High"].values

    min_idx = argrelextrema(lows, np.less_equal, order=order)[0]
    max_idx = argrelextrema(highs, np.greater_equal, order=order)[0]

    support_points = lows[min_idx]
    resistance_points = highs[max_idx]

    support_clusters = _cluster_levels(support_points, tolerance_pct)
    resistance_clusters = _cluster_levels(resistance_points, tolerance_pct)

    below = [c for c in support_clusters if c[0] < current_price]
    above = [c for c in resistance_clusters if c[0] > current_price]

    support = max(below, key=lambda c: c[0])[0] if below else float(hist["Low"].min())
    resistance = min(above, key=lambda c: c[0])[0] if above else float(hist["High"].max())

    return {
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "support_clusters": support_clusters,
        "resistance_clusters": resistance_clusters,
        "current_price": round(current_price, 2),
    }


def _base_tightness(df: pd.DataFrame, end_idx: int, window: int = 10):
    """
    Range tightness (as % of price) of the `window` bars immediately BEFORE
    end_idx (exclusive) - i.e. the "base" a breakout launched from. Smaller
    % = tighter, lower-volatility consolidation right before the move,
    which is generally a higher-quality launch pad (same idea as a
    "VCP"/tight-flag base: the tighter the coil, the cleaner the move that
    tends to follow). Returns None if there isn't enough history before
    end_idx to measure a full window.
    """
    start_idx = end_idx - window
    if start_idx < 0:
        return None
    base = df.iloc[start_idx:end_idx]
    if base.empty:
        return None
    hi = base["High"].max()
    lo = base["Low"].min()
    mid = base["Close"].mean()
    if mid <= 0:
        return None
    return round(float((hi - lo) / mid * 100), 2)


def detect_retest(df: pd.DataFrame, support: float, vol_multiplier: float, near_pct: float,
                   vol_lookback: int = 20, retest_lookback_days: int = 40,
                   undercut_tolerance_pct: float = 2.0, level_tolerance_pct: float = 1.5,
                   base_window: int = 10):
    """
    Checks whether the CURRENT support level used to be resistance that
    price broke through on a volume spike within the last
    retest_lookback_days, and whether price has since pulled back to that
    same level and is holding it. That's a "retest": the breakout already
    happened and got confirmed, and price coming back to touch (not break)
    the old resistance-turned-support is usually a safer, better
    risk/reward entry than chasing the original breakout candle.

    Returns None if no qualifying retest is found, otherwise a dict with
    the breakout level, how long ago it broke out, how far price dipped
    below the level since (worst_undercut_pct), how close price is to it
    right now, and whether the base immediately before that breakout was
    "tight" (see _base_tightness).
    """
    if not support or support <= 0 or len(df) < 5:
        return None

    n = len(df)
    search_start = max(0, n - retest_lookback_days)

    breakout_idx = None
    for i in range(search_start, n):
        if i < vol_lookback:
            continue
        close = df["Close"].iloc[i]
        # require a close meaningfully above the level (i.e. an actual
        # break, not just noise sitting right on top of it)
        if close <= support * (1 + level_tolerance_pct / 100):
            continue
        vol_window = df["Volume"].iloc[i - vol_lookback:i]
        avg_vol = vol_window.mean() if len(vol_window) > 0 else 0
        if avg_vol <= 0:
            continue
        vol_ratio = df["Volume"].iloc[i] / avg_vol
        if vol_ratio >= vol_multiplier:
            breakout_idx = i  # keep the most recent qualifying bar

    if breakout_idx is None:
        return None

    since = df.iloc[breakout_idx + 1:]
    if since.empty:
        return None

    low_since = float(since["Low"].min())
    last_close = float(df["Close"].iloc[-1])
    pct_from_level = round((last_close - support) / support * 100, 2)
    worst_undercut_pct = round((support - low_since) / support * 100, 2)

    is_near = abs(pct_from_level) <= near_pct
    holding = worst_undercut_pct <= undercut_tolerance_pct
    if not (is_near and holding):
        return None

    base_pct = _base_tightness(df, breakout_idx, window=base_window)

    return {
        "retest_level": round(support, 2),
        "days_since_breakout": n - 1 - breakout_idx,
        "retest_low": round(low_since, 2),
        "pct_from_level": pct_from_level,
        "worst_undercut_pct": worst_undercut_pct,
        "prior_base_range_pct": base_pct,
        "tight_prior_base": base_pct is not None and base_pct <= 8.0,
    }


def classify(df: pd.DataFrame, levels: dict, near_pct: float = 3.0,
             vol_multiplier: float = 1.5, vol_lookback: int = 20, breakout_days: int = 2,
             below_support_pct: float = 15.0, retest_lookback_days: int = 40,
             retest_undercut_pct: float = 2.0, tight_base_window: int = 10,
             tight_base_pct: float = 8.0):
    """
    Classify a stock using the rule set you described:
      - close to resistance             -> AVOID
      - close to support (at or above)  -> BUY candidate
      - a pullback to a level that was recently broken out of on volume,
        still holding it               -> RETEST (higher-conviction buy,
                                           see detect_retest)
      - BELOW support by up to below_support_pct%
                                         -> BELOW_SUPPORT (watch / possible deep-value
                                            buy, flagged separately since a broken
                                            support often means something changed)
      - closed ABOVE resistance in the last 1-2 days on above-average
        volume                          -> BREAKOUT / new rally candidate
      - otherwise                       -> NEUTRAL

    dist_to_support_pct is signed: positive means price is above support,
    negative means price has fallen below it (e.g. -8.0 = 8% below support).

    tight_prior_base flags BREAKOUT_RALLY / RETEST_BUY rows where the bars
    immediately before the breakout were a low-volatility, tight
    consolidation (prior_base_range_pct <= tight_base_pct) rather than a
    wide, choppy range - generally read as a cleaner, higher-quality setup.
    """
    price = levels["current_price"]
    support = levels["support"]
    resistance = levels["resistance"]

    dist_to_support_pct = (price - support) / support * 100 if support else None
    dist_to_resistance_pct = (resistance - price) / price * 100 if price else None

    vol_window = df["Volume"].iloc[-(vol_lookback + breakout_days):-breakout_days]
    avg_vol = vol_window.mean() if len(vol_window) > 0 else 0
    recent_vol = df["Volume"].iloc[-breakout_days:].max()
    vol_ratio = round(float(recent_vol / avg_vol), 2) if avg_vol > 0 else 0.0

    recent_close_max = df["Close"].iloc[-breakout_days:].max()
    is_breakout = (recent_close_max > resistance) and (vol_ratio >= vol_multiplier)

    tight_prior_base = None
    prior_base_range_pct = None
    retest_info = None

    if is_breakout:
        category = "BREAKOUT_RALLY"
        trailing = df["Close"].iloc[-breakout_days:]
        breakout_bar_idx = len(df) - breakout_days + int(np.argmax(trailing.values))
        prior_base_range_pct = _base_tightness(df, breakout_bar_idx, window=tight_base_window)
        tight_prior_base = prior_base_range_pct is not None and prior_base_range_pct <= tight_base_pct
    else:
        retest_info = detect_retest(
            df, support, vol_multiplier, near_pct, vol_lookback=vol_lookback,
            retest_lookback_days=retest_lookback_days,
            undercut_tolerance_pct=retest_undercut_pct, base_window=tight_base_window,
        )
        if retest_info is not None:
            category = "RETEST_BUY"
            prior_base_range_pct = retest_info["prior_base_range_pct"]
            tight_prior_base = retest_info["tight_prior_base"]
        elif dist_to_resistance_pct is not None and 0 <= dist_to_resistance_pct <= near_pct:
            category = "NEAR_RESISTANCE_AVOID"
        elif dist_to_support_pct is not None and 0 <= dist_to_support_pct <= near_pct:
            category = "NEAR_SUPPORT_BUY"
        elif dist_to_support_pct is not None and -below_support_pct <= dist_to_support_pct < 0:
            category = "BELOW_SUPPORT"
        else:
            category = "NEUTRAL"

    # --- Entry trigger / signal ---
    # This turns the category into a concrete "what price gets me in" answer,
    # e.g. for a stock sitting under resistance at 172, entry_trigger=172 and
    # entry_signal tells you to wait for a close above it; once BREAKOUT_RALLY
    # fires (close above 172 on volume), signal_active flips to True and
    # entry_signal says the trigger already happened.
    if category == "BREAKOUT_RALLY":
        entry_trigger = resistance
        base_note = " (tight prior base)" if tight_prior_base else ""
        entry_signal = f"ENTER - closed above {resistance} resistance on {vol_ratio}x volume{base_note}"
        signal_active = True
    elif category == "RETEST_BUY":
        entry_trigger = retest_info["retest_level"]
        base_note = " (tight prior base)" if tight_prior_base else ""
        entry_signal = (f"ENTER - retest of {entry_trigger} breakout level "
                         f"({retest_info['days_since_breakout']}d ago), holding{base_note}")
        signal_active = True
    elif category == "NEAR_SUPPORT_BUY":
        entry_trigger = support
        entry_signal = f"ENTER - holding support at {support}"
        signal_active = True
    elif category == "NEAR_RESISTANCE_AVOID":
        entry_trigger = resistance
        entry_signal = f"WAIT - buy trigger is a close above {resistance}"
        signal_active = False
    elif category == "BELOW_SUPPORT":
        entry_trigger = support
        entry_signal = f"WAIT - needs to reclaim {support} before entry"
        signal_active = False
    else:
        entry_trigger = resistance
        entry_signal = f"NO SIGNAL - next trigger is a close above {resistance}"
        signal_active = False

    return {
        "category": category,
        "price": price,
        "support": support,
        "resistance": resistance,
        "dist_to_support_pct": round(dist_to_support_pct, 2) if dist_to_support_pct is not None else None,
        "dist_to_resistance_pct": round(dist_to_resistance_pct, 2) if dist_to_resistance_pct is not None else None,
        "volume_ratio": vol_ratio,
        "entry_trigger": entry_trigger,
        "entry_signal": entry_signal,
        "signal_active": signal_active,
        "is_retest": category == "RETEST_BUY",
        "retest_level": retest_info["retest_level"] if retest_info else None,
        "days_since_breakout": retest_info["days_since_breakout"] if retest_info else None,
        "retest_worst_undercut_pct": retest_info["worst_undercut_pct"] if retest_info else None,
        "tight_prior_base": tight_prior_base,
        "prior_base_range_pct": prior_base_range_pct,
    }
