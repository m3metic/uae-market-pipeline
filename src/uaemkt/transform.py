"""Compute metrics and index series with DuckDB SQL (see sql/*.sql)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def _run(sql_file: str, prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("prices", prices)
    con.register("universe", universe[["symbol", "name", "exchange", "sector"]])
    out = con.execute((SQL_DIR / sql_file).read_text(encoding="utf-8")).df()
    con.close()
    return out


def compute_metrics(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    metrics = _run("metrics.sql", prices, universe)
    return universe[["symbol", "name", "exchange", "sector"]].merge(metrics, on="symbol", how="inner")


def compute_index(prices: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    return _run("index.sql", prices, universe)
