#!/usr/bin/env python3
"""
run_favorites_alert.py
-----------------------
Scans ONLY your favorites list (favorites.txt) and emails you a digest
whenever a ticker enters or changes into an actionable signal:
  BREAKOUT_RALLY, RETEST_BUY, NEAR_SUPPORT_BUY, NEAR_RESISTANCE_AVOID,
  BELOW_SUPPORT.

Meant to run on a schedule (e.g. hourly during market hours) via
GitHub Actions - see .github/workflows/stock_alerts.yml. To avoid an
email every single hour for a signal that hasn't changed, results are
compared against the previous run's state (alert_state.json) and ONLY
new/changed signals trigger an email. Every email still includes a full
snapshot table of all watched tickers for context, with changed rows
marked.

Usage:
    python run_favorites_alert.py
    python run_favorites_alert.py --favorites-file my_favorites.txt --period 6mo
    python run_favorites_alert.py --force                 # email even with no changes
    python run_favorites_alert.py --ignore-market-hours    # skip the ET 9:30-5pm guard (testing)
"""

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from finviz_client import get_tickers_from_file
from price_data import fetch_history_batch
from scanner import scan_ticker
from email_alert import send_alert_email

STATE_FILE = "alert_state.json"
ACTIONABLE = {"BREAKOUT_RALLY", "RETEST_BUY", "NEAR_SUPPORT_BUY",
              "NEAR_RESISTANCE_AVOID", "BELOW_SUPPORT"}

CATEGORY_LABEL = {
    "BREAKOUT_RALLY": "BREAKOUT",
    "RETEST_BUY": "RETEST BUY",
    "NEAR_SUPPORT_BUY": "NEAR SUPPORT (BUY)",
    "NEAR_RESISTANCE_AVOID": "NEAR RESISTANCE (AVOID)",
    "BELOW_SUPPORT": "BELOW SUPPORT",
    "NEUTRAL": "NEUTRAL",
}


def parse_args():
    p = argparse.ArgumentParser(description="Email alert digest for your favorites list")
    p.add_argument("--favorites-file", default="favorites.txt")
    p.add_argument("--period", default="3mo", choices=["1mo", "3mo", "6mo"],
                   help="Single lookback window to alert on (default 3mo). Keeping this to "
                        "one period keeps the digest and change-tracking simple; run "
                        "main.py separately if you want the full multi-period CSV.")
    p.add_argument("--state-file", default=STATE_FILE)
    p.add_argument("--force", action="store_true",
                   help="Send the digest even if nothing changed since the last run")
    p.add_argument("--ignore-market-hours", action="store_true",
                   help="Skip the 9:30am-5pm ET, weekday-only guard (useful for manual testing)")
    return p.parse_args()


def in_market_window(now=None):
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    end = now.replace(hour=17, minute=0, second=0, microsecond=0)
    return start <= now <= end


def load_state(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state, path):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def build_email(period, rows, changes):
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p %Z")
    changed_tickers = {c["ticker"] for c in changes}

    def row_html(r):
        label = CATEGORY_LABEL.get(r["category"], r["category"])
        mark = " &#9733; NEW/CHANGED" if r["ticker"] in changed_tickers else ""
        return (f"<tr><td>{r['ticker']}</td><td>{label}{mark}</td>"
                f"<td>{r['price']}</td><td>{r['support']}</td><td>{r['resistance']}</td>"
                f"<td>{r['entry_signal']}</td></tr>")

    body_rows = "".join(row_html(r) for r in rows)
    html = f"""
    <h2>Favorites Watchlist Alert - {period} window</h2>
    <p>Run at {now_str}</p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
      <tr><th>Ticker</th><th>Signal</th><th>Price</th><th>Support</th>
          <th>Resistance</th><th>Entry Signal</th></tr>
      {body_rows}
    </table>
    <p style="color:#666;font-size:12px">Mechanical technical screen, not investment advice.</p>
    """

    text_lines = [f"Favorites Watchlist Alert - {period} window ({now_str})", ""]
    for r in rows:
        label = CATEGORY_LABEL.get(r["category"], r["category"])
        mark = " (NEW/CHANGED)" if r["ticker"] in changed_tickers else ""
        text_lines.append(f"{r['ticker']}: {label}{mark} | price {r['price']} "
                           f"| support {r['support']} | resistance {r['resistance']} "
                           f"| {r['entry_signal']}")

    return html, "\n".join(text_lines)


def main():
    args = parse_args()

    if not args.ignore_market_hours and not in_market_window():
        print("Outside 9:30am-5pm ET market window (or it's a weekend) - skipping this run.")
        return

    tickers = get_tickers_from_file(args.favorites_file)
    if not tickers:
        print(f"No tickers found in {args.favorites_file}")
        return
    print(f"Scanning {len(tickers)} favorite tickers: {', '.join(tickers)}")

    history = fetch_history_batch(tickers, batch_size=50)
    state = load_state(args.state_file)

    rows, changes = [], []
    new_state = dict(state)

    for ticker, df in history.items():
        try:
            results = scan_ticker(df, periods=[args.period])
        except Exception as e:
            print(f"  [WARN] {ticker} failed: {e}")
            continue
        r = results.get(args.period)
        if not r:
            continue
        rows.append({"ticker": ticker, **r})

        key = f"{ticker}:{args.period}"
        prev_category = state.get(key)
        category = r["category"]
        new_state[key] = category

        if category in ACTIONABLE and category != prev_category:
            changes.append({"ticker": ticker, "from": prev_category, "to": category})

    rows.sort(key=lambda r: r["ticker"])

    if changes:
        print(f"{len(changes)} new/changed signal(s): "
              + ", ".join(f"{c['ticker']} {c['from']}->{c['to']}" for c in changes))
    else:
        print("No new/changed signals since last run.")

    if changes or args.force:
        html, text = build_email(args.period, rows, changes)
        subject_bits = [f"{c['ticker']} {CATEGORY_LABEL.get(c['to'], c['to'])}" for c in changes[:5]]
        subject = ("Stock Alert: " + ", ".join(subject_bits)) if subject_bits else "Stock Watchlist Digest"
        send_alert_email(subject, html, text)
        print("Email sent.")
    else:
        print("Nothing to email.")

    save_state(new_state, args.state_file)


if __name__ == "__main__":
    main()
