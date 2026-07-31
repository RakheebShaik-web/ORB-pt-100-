
"""Pure ORB strategy logic and deterministic one-minute trade simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
import math
from typing import Any

import pandas as pd


@dataclass
class Position:
    symbol: str
    side: str
    trade_date: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    orb_high: float
    orb_low: float
    initial_qty: float
    remaining_qty: float
    tp1_qty: float
    entry_fee: float
    realized_pnl: float = 0.0
    exit_fees: float = 0.0
    tp1_hit: bool = False
    exit_reason: str = ""
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None


def parse_clock(value: str) -> time:
    return pd.Timestamp(value).time()


def adverse_fill(price: float, side: str, bps: float, is_entry: bool) -> float:
    rate = bps / 10_000.0
    buy = (side == "long" and is_entry) or (side == "short" and not is_entry)
    return price * (1.0 + rate if buy else 1.0 - rate)


def commission(qty: float, per_share: float, minimum: float) -> float:
    if qty <= 0 or per_share <= 0:
        return 0.0
    return max(qty * per_share, minimum)


def position_size(entry: float, stop: float, risk: dict[str, Any]) -> float:
    distance = abs(entry - stop)
    if distance <= 0:
        return 0.0
    risk_qty = float(risk["risk_per_trade_usd"]) / distance
    notional_qty = float(risk["max_notional_per_trade"]) / entry
    qty = min(risk_qty, notional_qty)
    if not risk["allow_fractional_shares"]:
        qty = math.floor(qty)
    return max(float(qty), 0.0)


def pnl_for_exit(position: Position, price: float, qty: float) -> float:
    direction = 1.0 if position.side == "long" else -1.0
    return direction * (price - position.entry_price) * qty


def _close_piece(
    position: Position,
    raw_price: float,
    qty: float,
    timestamp: pd.Timestamp,
    reason: str,
    risk: dict[str, Any],
) -> None:
    qty = min(qty, position.remaining_qty)
    fill = adverse_fill(raw_price, position.side, float(risk["slippage_bps"]), False)
    fee = commission(qty, float(risk["commission_per_share"]), float(risk["minimum_commission"]))
    position.realized_pnl += pnl_for_exit(position, fill, qty) - fee
    position.exit_fees += fee
    position.remaining_qty -= qty
    position.exit_time = timestamp
    position.exit_price = fill
    position.exit_reason = reason


def _record(position: Position) -> dict[str, Any]:
    row = asdict(position)
    row["gross_pnl_before_fees"] = position.realized_pnl + position.entry_fee + position.exit_fees
    row["net_pnl"] = position.realized_pnl - position.entry_fee
    row["total_fees"] = position.entry_fee + position.exit_fees
    row["return_on_notional_pct"] = (
        row["net_pnl"] / (position.entry_price * position.initial_qty) * 100.0
        if position.initial_qty else 0.0
    )
    return row


def backtest_symbol(
    symbol: str,
    bars: pd.DataFrame,
    session: dict[str, Any],
    strategy: dict[str, Any],
    risk: dict[str, Any],
) -> tuple[pd.DataFrame, list[str]]:
    timezone = session["timezone"]
    local = bars.tz_convert(timezone).copy()
    local = local.between_time("09:30", "16:00", inclusive="left")
    orb_start = parse_clock(session["orb_start"])
    orb_end = parse_clock(session["orb_end"])
    entry_start = parse_clock(session["entry_start"])
    entry_end = parse_clock(session["entry_end"])
    force_exit = parse_clock(session["force_exit"])
    warnings: list[str] = []
    completed: list[dict[str, Any]] = []

    for trade_date, day in local.groupby(local.index.date):
        day = day.sort_index()
        orb = day[(day.index.time >= orb_start) & (day.index.time < orb_end)]
        expected_orb_bars = int(
            (pd.Timestamp.combine(trade_date, orb_end) - pd.Timestamp.combine(trade_date, orb_start))
            / pd.Timedelta(minutes=1)
        )
        if len(orb) != expected_orb_bars:
            warnings.append(f"{symbol} {trade_date}: skipped; ORB has {len(orb)}/{expected_orb_bars} bars")
            continue
        orb_high = float(orb["high"].max())
        orb_low = float(orb["low"].min())
        orb_range = orb_high - orb_low
        if orb_range <= 0:
            warnings.append(f"{symbol} {trade_date}: skipped; non-positive ORB range")
            continue

        position: Position | None = None
        trades_today = 0
        eligible = day[(day.index.time >= entry_start) & (day.index.time <= force_exit)]

        for timestamp, bar in eligible.iterrows():
            clock = timestamp.time()

            if position is not None:
                stop = position.stop_price
                if position.tp1_hit and strategy["move_runner_stop_to_breakeven"]:
                    stop = position.entry_price
                stop_hit = bar["low"] <= stop if position.side == "long" else bar["high"] >= stop
                tp1_hit = (
                    not position.tp1_hit
                    and (bar["high"] >= position.tp1_price if position.side == "long" else bar["low"] <= position.tp1_price)
                )
                tp2_hit = bar["high"] >= position.tp2_price if position.side == "long" else bar["low"] <= position.tp2_price

                # OHLC bars do not reveal event order. A conservative stop-first
                # policy prevents optimistic results when both levels are touched.
                if stop_hit:
                    _close_piece(position, stop, position.remaining_qty, timestamp, "STOP", risk)
                else:
                    if tp1_hit:
                        _close_piece(position, position.tp1_price, position.tp1_qty, timestamp, "TP1", risk)
                        position.tp1_hit = True
                    if position.remaining_qty > 0 and tp2_hit:
                        _close_piece(position, position.tp2_price, position.remaining_qty, timestamp, "TP2", risk)

                if position.remaining_qty <= 1e-12:
                    completed.append(_record(position))
                    position = None

            if position is None and clock < entry_end:
                can_reenter = not strategy["one_trade_per_symbol_per_day"] or trades_today == 0
                side = "long" if bar["close"] > orb_high else "short" if bar["close"] < orb_low else None
                if can_reenter and side:
                    raw_entry = float(bar["close"])
                    entry = adverse_fill(raw_entry, side, float(risk["slippage_bps"]), True)
                    stop = float(bar["low"] if side == "long" else bar["high"])
                    # Skip a signal when adverse slippage would place the stop on
                    # the wrong side of the simulated fill.
                    if (side == "long" and stop >= entry) or (side == "short" and stop <= entry):
                        warnings.append(f"{symbol} {timestamp}: skipped; invalid stop after slippage")
                        continue
                    qty = position_size(entry, stop, risk)
                    if qty <= 0:
                        warnings.append(f"{symbol} {timestamp}: skipped; position size is zero")
                        continue
                    tp1 = orb_high + orb_range * float(strategy["tp1_orb_multiple"]) if side == "long" else orb_low - orb_range * float(strategy["tp1_orb_multiple"])
                    tp2 = orb_high + orb_range * float(strategy["tp2_orb_multiple"]) if side == "long" else orb_low - orb_range * float(strategy["tp2_orb_multiple"])
                    tp1_qty = qty * float(strategy["tp1_position_pct"]) / 100.0
                    if not risk["allow_fractional_shares"]:
                        tp1_qty = math.floor(tp1_qty)
                    tp1_qty = min(max(tp1_qty, 0.0), qty)
                    entry_fee = commission(qty, float(risk["commission_per_share"]), float(risk["minimum_commission"]))
                    position = Position(
                        symbol=symbol,
                        side=side,
                        trade_date=str(trade_date),
                        entry_time=timestamp,
                        entry_price=entry,
                        stop_price=stop,
                        tp1_price=tp1,
                        tp2_price=tp2,
                        orb_high=orb_high,
                        orb_low=orb_low,
                        initial_qty=qty,
                        remaining_qty=qty,
                        tp1_qty=tp1_qty,
                        entry_fee=entry_fee,
                    )
                    trades_today += 1

            if position is not None and clock >= force_exit:
                _close_piece(position, float(bar["close"]), position.remaining_qty, timestamp, "EOD", risk)
                completed.append(_record(position))
                position = None

        if position is not None:
            timestamp = day.index[-1]
            _close_piece(position, float(day.iloc[-1]["close"]), position.remaining_qty, timestamp, "LAST_BAR", risk)
            completed.append(_record(position))

    trades = pd.DataFrame(completed)
    if not trades.empty:
        trades = trades.sort_values(["entry_time", "symbol"]).reset_index(drop=True)
    return trades, warnings

