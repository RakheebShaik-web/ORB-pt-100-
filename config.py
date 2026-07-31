"""Configuration for the ORB 50% / 100% Yahoo Finance backtest."""

CONFIG = {
    "symbols": ["QQQ"],
    "data": {
        "interval": "1m",
        "period": "30d",
        "prepost": False,
        "auto_adjust": False,
        "cache_dir": "data/cache",
    },
    "session": {
        "timezone": "America/New_York",
        "orb_start": "09:30",
        "orb_end": "09:45",
        "entry_start": "09:45",
        "entry_end": "15:55",
        "force_exit": "15:55",
    },
    "strategy": {
        # Portfolio-wide: across every configured symbol, keep only the earliest
        # valid entry of the trading day.
        "one_trade_total_per_day": True,
        "one_trade_per_symbol_per_day": True,
        "tp1_orb_multiple": 0.50,
        "tp2_orb_multiple": 1.00,
        "tp1_position_pct": 50.0,
        "move_runner_stop_to_breakeven": True,
        # If both stop and target occur inside one 1-minute bar, assume stop first.
        "intrabar_conflict_policy": "stop_first",
    },
    "risk": {
        "initial_capital": 100_000.0,
        # Quantity is sized so the modeled stop loss, adverse entry/exit
        # slippage, and both sides' commissions together do not exceed $10.
        "risk_per_trade_usd": 10.0,
        "max_notional_per_trade": 25_000.0,
        "allow_fractional_shares": False,
        "commission_per_share": 0.0,
        "minimum_commission": 0.0,
        "slippage_bps": 1.0,
    },
    "output_dir": "results",
}
