"""Download daily prices from Yahoo Finance and merge them into the local store.

Runs are incremental: on an existing store, only the last few weeks are
re-downloaded (to pick up late corrections), then merged with history.
"""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PRICE_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
REFETCH_DAYS = 21  # overlap window re-downloaded on every incremental run


def download(symbols: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """Daily OHLCV for `symbols` as a long table (one row per symbol and date)."""
    import yfinance as yf  # imported here so tests and the dashboard don't need it

    with warnings.catch_warnings():
        # yfinance emits pandas deprecation warnings on every call; they are not ours to fix.
        warnings.simplefilter("ignore", category=FutureWarning)
        warnings.simplefilter("ignore", category=DeprecationWarning)
        if hasattr(pd.errors, "Pandas4Warning"):
            warnings.simplefilter("ignore", category=pd.errors.Pandas4Warning)
        raw = yf.download(
            symbols,
            start=start,
            end=end,
            group_by="ticker",
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=True,
        )
    return to_long(raw, symbols)


def to_long(raw: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Reshape yfinance's wide (ticker, field) columns into PRICE_COLUMNS."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    frames = []
    for sym in symbols:
        if isinstance(raw.columns, pd.MultiIndex):
            if sym not in raw.columns.get_level_values(0):
                continue
            part = raw[sym]
        else:  # a single ticker can come back with flat columns
            part = raw
        part = part.rename(columns=str.lower).rename(columns={"adj close": "adj_close"})
        part = part.dropna(subset=["close"])
        if part.empty:
            continue
        part = part.reset_index().rename(columns={"Date": "date", "index": "date"})
        part["symbol"] = sym
        frames.append(part)
    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    if "adj_close" not in out:
        out["adj_close"] = out["close"]
    return out[PRICE_COLUMNS].sort_values(["symbol", "date"]).reset_index(drop=True)


def merge(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Combine stored and freshly downloaded rows; new rows win on overlap."""
    if existing is None or existing.empty:
        combined = new
    else:
        combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
    return combined.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_prices(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=PRICE_COLUMNS)


def incremental_start(existing: pd.DataFrame, history_start: str) -> str:
    if existing.empty:
        return history_start
    last = pd.to_datetime(existing["date"]).max().date()
    return str(last - timedelta(days=REFETCH_DAYS))


def update(
    symbols: list[str], history_start: str, path: Path, today: date | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (merged prices, newly downloaded rows). Does not write anything."""
    existing = load_prices(path)
    start = incremental_start(existing, history_start)
    end = str((today or datetime.now(ZoneInfo("Asia/Dubai")).date()) + timedelta(days=1))
    new = download(symbols, start=start, end=end)
    return merge(existing, new), new
