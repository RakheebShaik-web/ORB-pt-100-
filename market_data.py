"""Alpaca/Yahoo historical download, normalization, validation, and caching."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _flatten_columns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame
    first = set(map(str, frame.columns.get_level_values(0)))
    if symbol in first:
        return frame[symbol]
    if symbol in set(map(str, frame.columns.get_level_values(-1))):
        return frame.xs(symbol, axis=1, level=-1)
    frame = frame.copy()
    frame.columns = frame.columns.get_level_values(0)
    return frame


def normalize_bars(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        raise ValueError(f"Yahoo Finance returned no data for {symbol}")
    frame = _flatten_columns(frame, symbol).copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{symbol}: missing OHLCV columns: {sorted(missing)}")
    frame = frame[REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True)
    if frame.index.tz is None:
        # yfinance intraday bars normally arrive tz-aware. UTC is the safest
        # fallback if a future yfinance version returns a naive index.
        frame.index = frame.index.tz_localize("UTC")
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame["volume"] < 0)
    )
    if invalid.any():
        raise ValueError(f"{symbol}: found {int(invalid.sum())} invalid OHLCV candles")
    frame.index.name = "timestamp"
    return frame


def cache_path(
    cache_dir: str | Path,
    symbol: str,
    period: str,
    interval: str,
    source: str,
    feed: str = "",
) -> Path:
    safe_symbol = symbol.replace("^", "INDEX_").replace("/", "_")
    suffix = f"_{feed}" if feed else ""
    return Path(cache_dir) / f"{source}_{safe_symbol}_{period}_{interval}{suffix}.csv"


def download_yahoo_bars(
    symbol: str,
    *,
    period: str,
    interval: str,
    prepost: bool,
    auto_adjust: bool,
    cache_dir: str | Path,
    refresh: bool = False,
) -> pd.DataFrame:
    path = cache_path(cache_dir, symbol, period, interval, "yahoo")
    if path.exists() and not refresh:
        cached = pd.read_csv(path, index_col="timestamp", parse_dates=["timestamp"])
        return normalize_bars(cached, symbol)

    yahoo_cache = Path(cache_dir) / ".yfinance"
    yahoo_cache.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(yahoo_cache))

    # Yahoo restricts each 1-minute request to no more than eight calendar
    # days. yfinance does not automatically split period="30d", so do it here.
    period_match = re.fullmatch(r"(\d+)d", period.strip().lower())
    period_days = int(period_match.group(1)) if period_match else None
    if interval == "1m" and period_days is not None and period_days > 7:
        request_end = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)
        request_start = request_end - pd.Timedelta(days=period_days)
        pieces: list[pd.DataFrame] = []
        chunk_start = request_start
        while chunk_start < request_end:
            chunk_end = min(chunk_start + pd.Timedelta(days=7), request_end)
            piece = yf.download(
                tickers=symbol,
                start=chunk_start.to_pydatetime(),
                end=chunk_end.to_pydatetime(),
                interval=interval,
                prepost=prepost,
                auto_adjust=auto_adjust,
                actions=False,
                progress=False,
                threads=False,
            )
            if not piece.empty:
                pieces.append(piece)
            chunk_start = chunk_end
        if not pieces:
            raise ValueError(
                f"Yahoo Finance returned no 1-minute data for {symbol} across "
                f"{period_days} days. Try --period 7d or retry later."
            )
        raw = pd.concat(pieces).sort_index()
        raw = raw[~raw.index.duplicated(keep="last")]
    else:
        raw = yf.download(
            tickers=symbol,
            period=period,
            interval=interval,
            prepost=prepost,
            auto_adjust=auto_adjust,
            actions=False,
            progress=False,
            threads=False,
        )
    bars = normalize_bars(raw, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_csv(path)
    return bars


def download_alpaca_bars(
    symbol: str,
    *,
    period: str,
    interval: str,
    feed: str,
    adjustment: str,
    cache_dir: str | Path,
    refresh: bool = False,
) -> pd.DataFrame:
    try:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError as exc:
        raise RuntimeError(
            "alpaca-py is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError(
            "Missing Alpaca credentials. Open .env and fill ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY."
        )
    period_match = re.fullmatch(r"(\d+)d", period.strip().lower())
    if not period_match:
        raise ValueError("Alpaca period must use days, for example 30d, 60d, or 90d")
    if interval != "1m":
        raise ValueError("This ORB backtester currently requires interval='1m'")
    feed_map = {"iex": DataFeed.IEX, "sip": DataFeed.SIP}
    if feed not in feed_map:
        raise ValueError("ALPACA_DATA_FEED must be 'iex' or 'sip'")
    adjustment_map = {
        "raw": Adjustment.RAW,
        "split": Adjustment.SPLIT,
        "dividend": Adjustment.DIVIDEND,
        "all": Adjustment.ALL,
    }
    if adjustment not in adjustment_map:
        raise ValueError("ALPACA_ADJUSTMENT must be raw, split, dividend, or all")

    path = cache_path(cache_dir, symbol, period, interval, "alpaca", feed)
    if path.exists() and not refresh:
        cached = pd.read_csv(path, index_col="timestamp", parse_dates=["timestamp"])
        return normalize_bars(cached, symbol)

    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=int(period_match.group(1)))
    client = StockHistoricalDataClient(key, secret)
    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame.Minute,
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        feed=feed_map[feed],
        adjustment=adjustment_map[adjustment],
    )
    raw = client.get_stock_bars(request).df
    if isinstance(raw.index, pd.MultiIndex):
        level = "symbol" if "symbol" in raw.index.names else 0
        raw = raw.xs(symbol, level=level)
    bars = normalize_bars(raw, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_csv(path)
    return bars


def download_bars(
    symbol: str,
    *,
    source: str,
    period: str,
    interval: str,
    prepost: bool,
    auto_adjust: bool,
    alpaca_feed: str,
    alpaca_adjustment: str,
    cache_dir: str | Path,
    refresh: bool = False,
) -> pd.DataFrame:
    if source == "alpaca":
        return download_alpaca_bars(
            symbol,
            period=period,
            interval=interval,
            feed=alpaca_feed,
            adjustment=alpaca_adjustment,
            cache_dir=cache_dir,
            refresh=refresh,
        )
    if source == "yahoo":
        return download_yahoo_bars(
            symbol,
            period=period,
            interval=interval,
            prepost=prepost,
            auto_adjust=auto_adjust,
            cache_dir=cache_dir,
            refresh=refresh,
        )
    raise ValueError("DATA_SOURCE must be 'alpaca' or 'yahoo'")


def data_quality(bars: pd.DataFrame) -> dict[str, Any]:
    local = bars.index.tz_convert("America/New_York")
    trading_dates = pd.Index(local.date)
    expected = 390 * trading_dates.nunique()
    return {
        "bars": int(len(bars)),
        "first_timestamp": bars.index.min().isoformat(),
        "last_timestamp": bars.index.max().isoformat(),
        "trading_days": int(trading_dates.nunique()),
        "expected_regular_session_bars_approx": int(expected),
        "duplicate_timestamps": int(bars.index.duplicated().sum()),
        "zero_volume_bars": int((bars["volume"] == 0).sum()),
    }


def fingerprint(bars: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(bars, index=True).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
