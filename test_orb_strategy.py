"""Deterministic unit tests that do not require network access."""

from __future__ import annotations

import pandas as pd

from orb_strategy import backtest_symbol

SESSION = {
    "timezone": "America/New_York",
    "orb_start": "09:30",
    "orb_end": "09:45",
    "entry_start": "09:45",
    "entry_end": "15:55",
    "force_exit": "15:55",
}
STRATEGY = {
    "one_trade_per_symbol_per_day": True,
    "tp1_orb_multiple": 0.5,
    "tp2_orb_multiple": 1.0,
    "tp1_position_pct": 50.0,
    "move_runner_stop_to_breakeven": False,
    "intrabar_conflict_policy": "stop_first",
}
RISK = {
    "risk_per_trade_usd": 100.0,
    "max_notional_per_trade": 100_000.0,
    "allow_fractional_shares": False,
    "commission_per_share": 0.0,
    "minimum_commission": 0.0,
    "slippage_bps": 0.0,
}


def synthetic_day(exit_case: str) -> pd.DataFrame:
    index = pd.date_range("2026-07-15 09:30", "2026-07-15 15:55", freq="1min", tz="America/New_York")
    frame = pd.DataFrame({"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.5, "volume": 1000}, index=index)
    # ORB = 100–101. Breakout close 101.20, stop 100.90, targets 101.50/102.00.
    frame.loc["2026-07-15 09:45", ["open", "high", "low", "close"]] = [100.9, 101.3, 100.9, 101.2]
    if exit_case == "targets":
        frame.loc["2026-07-15 09:46", ["open", "high", "low", "close"]] = [101.2, 101.6, 101.1, 101.5]
        frame.loc["2026-07-15 09:47", ["open", "high", "low", "close"]] = [101.5, 102.1, 101.4, 102.0]
    elif exit_case == "conflict":
        frame.loc["2026-07-15 09:46", ["open", "high", "low", "close"]] = [101.2, 101.7, 100.8, 101.3]
    return frame.tz_convert("UTC")


def test_partial_targets() -> None:
    trades, warnings = backtest_symbol("TEST", synthetic_day("targets"), SESSION, STRATEGY, RISK)
    assert not warnings
    assert len(trades) == 1
    assert bool(trades.iloc[0]["tp1_hit"])
    assert trades.iloc[0]["exit_reason"] == "TP2"
    assert trades.iloc[0]["net_pnl"] > 0


def test_intrabar_conflict_is_stop_first() -> None:
    trades, _ = backtest_symbol("TEST", synthetic_day("conflict"), SESSION, STRATEGY, RISK)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "STOP"
    assert not bool(trades.iloc[0]["tp1_hit"])
    assert trades.iloc[0]["net_pnl"] < 0

