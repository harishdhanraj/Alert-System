# Favorites Watchlist Email Alerts (free, hourly, 9:30am-5pm ET)

This adds three things to the scanner:

- **`favorites.txt`** - your short list of tickers to actively watch (one per line). Separate from `my_watchlist.txt`/`my_watchlist_top1000.txt`, which stay as the bulk scan universe for `main.py`.
- **`run_favorites_alert.py`** + **`email_alert.py`** - scans just `favorites.txt` and emails you a digest **only when a ticker's signal newly becomes actionable or changes** (BREAKOUT, RETEST BUY, NEAR SUPPORT/BUY, NEAR RESISTANCE/AVOID, BELOW SUPPORT). This avoids getting the same "still near support" email every hour forever - you're told once when it starts, and again if it changes.
- **`.github/workflows/stock_alerts.yml`** - a free GitHub Actions workflow that runs the script every hour, 9:30am-5pm ET, Monday-Friday.

## 1. Put this project on GitHub

If it isn't already:
```bash
cd stock-scanner
git init
git add .
git commit -m "Add favorites alerting"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
Public or private both work. Public repos get **unlimited free** Actions minutes; private repos get 2,000 free minutes/month on GitHub's free plan, which is far more than 1 run/hour needs.

## 2. Get an email account you can send FROM

Easiest: a Gmail account with an **App Password** (works even if you send to any email address, not just Gmail).

1. Turn on 2-Step Verification on that Google account (required for App Passwords).
2. Go to https://myaccount.google.com/apppasswords, create one for "Mail", copy the 16-character password.

(Any other SMTP provider - Outlook, a work email, SendGrid, etc. - works too; you'll just use its host/port instead of Gmail's.)

## 3. Add repo secrets

In your GitHub repo: **Settings -> Secrets and variables -> Actions -> New repository secret**, add:

| Secret name | Example value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | `youraddress@gmail.com` |
| `SMTP_PASS` | the 16-char App Password |
| `ALERT_TO` | `you@example.com` (comma-separate for multiple recipients) |

## 4. Edit your watchlist

Edit `favorites.txt` to whatever tickers you actually want alerts on, commit, and push:
```bash
echo -e "AAPL\nNVDA\nMSFT" > favorites.txt
git add favorites.txt && git commit -m "Update favorites" && git push
```

## 5. That's it

The workflow now runs automatically every hour, 9:30am-5pm ET, Mon-Fri, for free. You can also trigger it manually any time from the repo's **Actions** tab -> "Favorites Stock Alert" -> **Run workflow** (handy for testing your email setup right now instead of waiting for the next scheduled hour).

The first run will likely email you a full digest since there's no prior state to compare against yet - that's expected and only happens once. After that, you'll only get emailed on an actual new/changed signal, but every email always includes a full snapshot table of all your favorites for context.

### Notes & caveats
- GitHub disables scheduled workflows automatically after **60 days with no commits** to the repo - just push anything (even editing `favorites.txt`) to reactivate it.
- Scheduled times on GitHub Actions are "best effort" and can occasionally run a few minutes late during high load - fine for this use case.
- Want a different alert period (1mo/6mo instead of the default 3mo) or to skip the market-hours guard for testing? Edit the `run` line in `.github/workflows/stock_alerts.yml`:
  ```
  run: python run_favorites_alert.py --period 6mo
  run: python run_favorites_alert.py --ignore-market-hours --force   # test email right now
  ```
- This is a mechanical technical screen, not investment advice - same caveat as the rest of the scanner.
