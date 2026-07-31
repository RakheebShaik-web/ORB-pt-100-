# ORB 50% / 100% Yahoo Finance Backtest

Python backtester for the 1-minute opening-range breakout strategy.

## Rules

- Opening range: 09:30–09:45 America/New_York.
- Long: first completed 1-minute candle closing above ORB high.
- Short: first completed 1-minute candle closing below ORB low.
- Entry: signal candle close, including configured adverse slippage.
- Stop: signal candle low for a long; signal candle high for a short.
- TP1: 50% ORB extension; exit 50%.
- After TP1: move the remaining position's stop to the entry price.
- TP2: 100% ORB extension; exit the remainder.
- Exactly one trade total per trading day across all configured symbols; the
  earliest valid breakout is selected. Open positions force-close at 15:55 ET.
- Conservative handling: if a later candle touches a stop and target, stop fills first.
- Position size: whole shares sized so the initial stop loss plus modeled
  adverse entry/exit slippage and commissions does not exceed $10.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
python bot.py
python bot.py --symbols QQQ SPY AAPL --period 30d --refresh
python bot.py --risk 10 --slippage-bps 2 --commission-per-share 0.005
```

Each run creates a timestamped folder under `results/` containing:

- `report.md`
- `summary.json`
- `trades.csv`
- `equity.csv`
- `equity_curve.png`
- `config.json`
- `data_manifest.json`
- `warnings.json`

## Tests

```powershell
python -m pytest -q
```

## Yahoo Finance limitations

Yahoo Finance restricts how much 1-minute history is available and may change
those limits without notice. For a `30d` request, this project automatically
downloads consecutive seven-day chunks, merges them, removes duplicate
timestamps, and caches the combined dataset. Yahoo bars are suitable for
research, but they are not an exchange-grade, quote-level execution feed. The
report records a SHA-256 fingerprint of every downloaded dataset so different
runs can be compared reliably.

## Disclosure

This is a hypothetical historical simulation, not actual trading performance.
Backtested results do not guarantee future results. Results depend on data
quality, fees, slippage, liquidity, taxes, and execution assumptions. This is
for research and educational purposes only and is not investment advice.
