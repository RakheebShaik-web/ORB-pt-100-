"""Main executable for the QQQ ORB 50% / 100% Yahoo backtest."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from config import CONFIG
from market_data import data_quality, download_bars, fingerprint, write_manifest
from orb_strategy import backtest_symbol
from performance import build_equity, calculate_metrics, save_chart, write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest ORB 50% / 100% using Yahoo Finance 1-minute bars.")
    parser.add_argument("--symbols", nargs="+", help="Symbols, for example QQQ SPY AAPL")
    parser.add_argument("--period", help="Yahoo period, typically 7d or 30d for 1-minute bars")
    parser.add_argument("--risk", type=float, help="Dollar risk per trade")
    parser.add_argument("--capital", type=float, help="Initial portfolio capital")
    parser.add_argument("--slippage-bps", type=float, help="Adverse slippage per fill in basis points")
    parser.add_argument("--commission-per-share", type=float, help="Commission per share")
    parser.add_argument("--move-stop-to-breakeven", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Ignore local Yahoo data cache")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = deepcopy(CONFIG)
    if args.symbols:
        config["symbols"] = [symbol.upper() for symbol in args.symbols]
    if args.period:
        config["data"]["period"] = args.period
    if args.risk is not None:
        config["risk"]["risk_per_trade_usd"] = args.risk
    if args.capital is not None:
        config["risk"]["initial_capital"] = args.capital
    if args.slippage_bps is not None:
        config["risk"]["slippage_bps"] = args.slippage_bps
    if args.commission_per_share is not None:
        config["risk"]["commission_per_share"] = args.commission_per_share
    if args.move_stop_to_breakeven:
        config["strategy"]["move_runner_stop_to_breakeven"] = True

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(config["output_dir"]) / run_stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    all_trades: list[pd.DataFrame] = []
    all_warnings: list[str] = []
    manifest: dict[str, object] = {"source": "Yahoo Finance via yfinance", "symbols": {}}

    for symbol in config["symbols"]:
        print(f"Downloading/loading {symbol}...")
        bars = download_bars(symbol, refresh=args.refresh, **config["data"])
        symbol_trades, warnings = backtest_symbol(
            symbol, bars, config["session"], config["strategy"], config["risk"]
        )
        all_trades.append(symbol_trades)
        all_warnings.extend(warnings)
        manifest["symbols"][symbol] = {
            "sha256": fingerprint(bars),
            "quality": data_quality(bars),
        }
        print(f"{symbol}: {len(symbol_trades)} completed trades from {len(bars)} bars")

    nonempty = [frame for frame in all_trades if not frame.empty]
    trades = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()
    if not trades.empty:
        trades = trades.sort_values(["entry_time", "symbol"]).reset_index(drop=True)
        if config["strategy"].get("one_trade_total_per_day", True):
            before = len(trades)
            trades = (
                trades.groupby("trade_date", sort=False, as_index=False, group_keys=False)
                .head(1)
                .reset_index(drop=True)
            )
            removed = before - len(trades)
            if removed:
                all_warnings.append(
                    f"Portfolio one-trade-per-day rule removed {removed} later same-day symbol trades."
                )
    equity = build_equity(trades, float(config["risk"]["initial_capital"]))
    metrics = calculate_metrics(trades, equity, float(config["risk"]["initial_capital"]))

    trades.to_csv(run_dir / "trades.csv", index=False)
    equity.to_csv(run_dir / "equity.csv", index=False)
    (run_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(metrics, indent=2, allow_nan=False), encoding="utf-8")
    (run_dir / "warnings.json").write_text(json.dumps(all_warnings, indent=2), encoding="utf-8")
    write_manifest(run_dir / "data_manifest.json", manifest)
    write_report(run_dir / "report.md", metrics, config, all_warnings)
    save_chart(equity, run_dir / "equity_curve.png")

    print(json.dumps(metrics, indent=2))
    print(f"Artifacts: {run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
