"""Portfolio aggregation, metrics, report, and chart generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DISCLOSURE = (
    "This backtest is a hypothetical historical simulation and does not represent actual "
    "trading performance. Backtested results do not guarantee future results. Results depend "
    "on market-data quality, corporate actions, fees, slippage, liquidity, taxes, execution "
    "assumptions, and implementation details. This is for research and educational purposes "
    "only and is not investment advice. All investments involve risk and may lose value."
)


def build_equity(trades: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame([{"date": pd.NaT, "daily_pnl": 0.0, "equity": initial_capital}])
    closed = trades.copy()
    closed["date"] = pd.to_datetime(closed["exit_time"]).dt.tz_localize(None).dt.normalize()
    daily = closed.groupby("date", as_index=False)["net_pnl"].sum().rename(columns={"net_pnl": "daily_pnl"})
    all_days = pd.DataFrame({"date": pd.date_range(daily["date"].min(), daily["date"].max(), freq="B")})
    equity = all_days.merge(daily, how="left", on="date").fillna({"daily_pnl": 0.0})
    equity["equity"] = initial_capital + equity["daily_pnl"].cumsum()
    equity["daily_return"] = equity["equity"].pct_change().fillna(equity["daily_pnl"] / initial_capital)
    equity["peak"] = equity["equity"].cummax()
    equity["drawdown_pct"] = (equity["equity"] / equity["peak"] - 1.0) * 100.0
    return equity


def calculate_metrics(trades: pd.DataFrame, equity: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    daily_returns = equity["daily_return"] if "daily_return" in equity else pd.Series(dtype=float)
    std = daily_returns.std(ddof=1)
    sharpe = float(np.sqrt(252) * daily_returns.mean() / std) if len(daily_returns) > 1 and std > 0 else 0.0
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    final_equity = float(equity["equity"].iloc[-1])
    return {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_profit": float(pnl.sum()),
        "total_return_pct": (final_equity / initial_capital - 1.0) * 100.0,
        "max_drawdown_pct": float(equity.get("drawdown_pct", pd.Series([0.0])).min()),
        "trades": int(len(trades)),
        "wins": int((pnl > 0).sum()),
        "losses": int((pnl < 0).sum()),
        "breakeven_trades": int((pnl == 0).sum()),
        "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "average_trade": float(pnl.mean()) if len(pnl) else 0.0,
        "largest_win": float(pnl.max()) if len(pnl) else 0.0,
        "largest_loss": float(pnl.min()) if len(pnl) else 0.0,
        "sharpe_daily": sharpe,
        "fees_paid": float(trades["total_fees"].sum()) if not trades.empty else 0.0,
        "tp1_hit_rate_pct": float(trades["tp1_hit"].mean() * 100.0) if not trades.empty else 0.0,
    }


def save_chart(equity: pd.DataFrame, path: Path) -> None:
    if equity["date"].isna().all():
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(equity["date"], equity["equity"], color="#2563eb", linewidth=1.8)
    axes[0].set_title("ORB 50% / 100% Backtest")
    axes[0].set_ylabel("Equity ($)")
    axes[0].grid(alpha=0.25)
    axes[1].fill_between(equity["date"], equity["drawdown_pct"], 0, color="#dc2626", alpha=0.4)
    axes[1].set_ylabel("Drawdown %")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_report(path: Path, metrics: dict[str, Any], config: dict[str, Any], warnings: list[str]) -> None:
    pf = "∞" if metrics["profit_factor"] is None and metrics["net_profit"] > 0 else (
        "N/A" if metrics["profit_factor"] is None else f'{metrics["profit_factor"]:.2f}'
    )
    text = f"""# ORB 50% / 100% Backtest Report

| Metric | Result |
|---|---:|
| Total return | {metrics['total_return_pct']:.2f}% |
| Net profit | ${metrics['net_profit']:.2f} |
| Max drawdown | {metrics['max_drawdown_pct']:.2f}% |
| Trades | {metrics['trades']} |
| Win rate | {metrics['win_rate_pct']:.2f}% |
| Profit factor | {pf} |
| Daily Sharpe | {metrics['sharpe_daily']:.2f} |
| TP1 hit rate | {metrics['tp1_hit_rate_pct']:.2f}% |
| Fees | ${metrics['fees_paid']:.2f} |

## Execution assumptions

- Signal: first completed 1-minute close above/below the 09:30–09:45 ET ORB.
- Fill: signal close with configured adverse slippage.
- Stop: signal candle low for longs; signal candle high for shorts.
- Targets: 50% and 100% of ORB range beyond the broken boundary.
- Same-bar entry exits are prohibited; management begins on the next bar.
- Intrabar stop/target ambiguity uses conservative stop-first ordering.
- Yahoo bars are used as supplied; no quote-level spread or order-book model.
- Configuration: `{json.dumps(config, sort_keys=True)}`

## Data warnings

{chr(10).join(f"- {warning}" for warning in warnings) if warnings else "- None"}

## Important disclosure

{DISCLOSURE}
"""
    path.write_text(text, encoding="utf-8")

