"""Data quality checks, run on every pipeline run before anything is saved.

Errors stop the pipeline (the previous good data is kept). Warnings are
recorded in the quality report and shown on the dashboard.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

UAE_WEEKMASK = "Mon Tue Wed Thu Fri"  # UAE markets trade Monday to Friday since 2022
WEEKEND_CHANGE = pd.Timestamp("2022-01-01")


def business_days_between(start: date, end: date) -> int:
    return int(np.busday_count(start, end, weekmask=UAE_WEEKMASK))


def run_checks(prices: pd.DataFrame, symbols: list[str], settings: dict, today: date) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Schema and emptiness
    required = {"date", "symbol", "open", "high", "low", "close", "adj_close", "volume"}
    missing = required - set(prices.columns)
    if missing:
        return _report(False, [f"Missing columns: {sorted(missing)}"], [], {})
    if prices.empty:
        return _report(False, ["No price rows at all"], [], {})

    df = prices.copy()
    df["date"] = pd.to_datetime(df["date"])

    # 2. Keys
    dupes = int(df.duplicated(subset=["symbol", "date"]).sum())
    if dupes:
        errors.append(f"{dupes} duplicate (symbol, date) rows")

    # 3. Values
    nulls = int(df["close"].isna().sum())
    if nulls:
        errors.append(f"{nulls} rows with missing close price")
    nonpos = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    if nonpos:
        errors.append(f"{nonpos} rows with zero or negative prices")
    bad_range = int((df["high"] < df["low"]).sum())
    if bad_range:
        errors.append(f"{bad_range} rows where high < low")
    neg_vol = int((df["volume"] < 0).sum())
    if neg_vol:
        errors.append(f"{neg_vol} rows with negative volume")
    # The UAE weekend was Friday-Saturday until the end of 2021 and Saturday-Sunday since 2022,
    # so Sunday trading before 2022 is normal.
    dow = df["date"].dt.day_of_week  # Monday = 0
    new_week = df["date"] >= WEEKEND_CHANGE
    off_day = (new_week & dow.isin([5, 6])) | (~new_week & dow.isin([4, 5]))
    if int(off_day.sum()):
        warnings.append(f"{int(off_day.sum())} rows dated on a UAE weekend day")

    # 4. Suspicious jumps (possible split, bad tick or corporate action)
    df = df.sort_values(["symbol", "date"])
    moves = df.groupby("symbol")["adj_close"].pct_change().abs()
    big = df.loc[moves > settings.get("max_abs_daily_move", 0.30), ["symbol", "date"]]
    for _, row in big.tail(10).iterrows():
        warnings.append(f"Large one-day move: {row.symbol} on {row.date.date()}")

    # 5. Coverage and freshness per symbol
    latest = df.groupby("symbol")["date"].max()
    present = [s for s in symbols if s in latest.index]
    absent = [s for s in symbols if s not in latest.index]
    coverage = len(present) / len(symbols) if symbols else 1.0
    if absent:
        warnings.append(f"No data for: {', '.join(absent)}")
    if coverage < settings.get("min_ticker_coverage", 0.9):
        errors.append(f"Only {coverage:.0%} of tickers have data")

    max_stale = settings.get("max_staleness_business_days", 3)
    newest = latest.max().date()
    lag = business_days_between(newest, today)
    if lag > max_stale:
        errors.append(f"Newest price is {newest}, {lag} business days old (limit {max_stale})")
    stale_syms = [s for s, d in latest.items() if business_days_between(d.date(), newest) > max_stale]
    if stale_syms:
        warnings.append(f"Stale tickers (behind the rest of the market): {', '.join(stale_syms)}")

    stats = {
        "rows": int(len(df)),
        "symbols_with_data": len(present),
        "symbols_expected": len(symbols),
        "first_date": str(df["date"].min().date()),
        "latest_date": str(newest),
        "business_days_since_latest": lag,
    }
    return _report(not errors, errors, warnings, stats)


def _report(passed: bool, errors: list[str], warnings: list[str], stats: dict) -> dict:
    return {"passed": passed, "errors": errors, "warnings": warnings, "stats": stats}
