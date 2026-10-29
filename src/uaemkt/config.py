"""Load the stock universe and pipeline settings from config/universe.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "universe.yaml"
DATA_DIR = ROOT / "data"

PRICES_PATH = DATA_DIR / "prices.parquet"
METRICS_PATH = DATA_DIR / "metrics.parquet"
INDEX_PATH = DATA_DIR / "index.parquet"
REPORT_PATH = DATA_DIR / "quality_report.json"


@dataclass
class Config:
    history_start: str
    currency: str
    tickers: pd.DataFrame  # columns: symbol, name, exchange, sector
    checks: dict = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return self.tickers["symbol"].tolist()


def load_config(path: str | Path = DEFAULT_CONFIG) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    tickers = pd.DataFrame(raw["tickers"])
    if tickers["symbol"].duplicated().any():
        raise ValueError("Duplicate symbols in config")
    return Config(
        history_start=str(raw.get("history_start", "2021-01-01")),
        currency=raw.get("currency", "AED"),
        tickers=tickers,
        checks=raw.get("checks", {}),
    )
