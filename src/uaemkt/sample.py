"""Synthetic prices for tests and offline demos. Clearly fake: never mixed with real data."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_prices(
    symbols: list[str], start: str = "2023-01-02", end: str = "2026-10-27", seed: int = 7
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)  # Monday-Friday, matching UAE trading days
    market = rng.normal(0.0003, 0.008, len(dates))
    frames = []
    for i, sym in enumerate(symbols):
        beta = 0.6 + 0.08 * i
        own = rng.normal(0.0001 * (i % 5 - 2), 0.012, len(dates))
        rets = beta * market + own
        close = (2 + 3 * rng.random()) * np.exp(np.cumsum(rets))
        spread = np.abs(rng.normal(0, 0.006, len(dates)))
        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": sym,
                    "open": close * (1 + rng.normal(0, 0.003, len(dates))),
                    "high": close * (1 + spread),
                    "low": close * (1 - spread),
                    "close": close,
                    "adj_close": close,
                    "volume": rng.integers(200_000, 8_000_000, len(dates)),
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df["open"] = df[["open", "high"]].min(axis=1).clip(lower=df["low"])
    return df
