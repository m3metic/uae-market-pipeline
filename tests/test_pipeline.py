"""Tests for the parts where a silent bug would publish wrong numbers."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from uaemkt.checks import business_days_between, run_checks
from uaemkt.config import load_config
from uaemkt.fetch import merge, to_long
from uaemkt.sample import make_prices
from uaemkt.transform import compute_index, compute_metrics

SETTINGS = {"max_staleness_business_days": 3, "max_abs_daily_move": 0.30, "min_ticker_coverage": 0.9}


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def prices(cfg):
    return make_prices(cfg.symbols, start="2024-01-01", end="2026-10-27")


# -- config ---------------------------------------------------------------
def test_config_symbols_are_unique_and_tagged(cfg):
    assert cfg.tickers["symbol"].is_unique
    assert set(cfg.tickers["exchange"]) == {"DFM"}
    assert all(s.endswith(".AE") for s in cfg.symbols)


# -- fetch ----------------------------------------------------------------
def test_to_long_reshapes_yfinance_multiindex():
    dates = pd.to_datetime(["2026-10-26", "2026-10-27"])
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    cols = pd.MultiIndex.from_product([["AAA.AE", "BBB.AD"], fields])
    raw = pd.DataFrame(np.arange(24, dtype=float).reshape(2, 12) + 1, index=dates, columns=cols)
    raw.index.name = "Date"
    raw.loc[dates[1], ("BBB.AD", "Close")] = np.nan  # a missing close is dropped
    out = to_long(raw, ["AAA.AE", "BBB.AD", "MISSING.AE"])
    assert list(out.columns) == ["date", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
    assert len(out) == 3
    assert set(out["symbol"]) == {"AAA.AE", "BBB.AD"}


def test_merge_prefers_new_rows_and_dedupes():
    old = pd.DataFrame(
        {"date": pd.to_datetime(["2026-10-26", "2026-10-27"]), "symbol": "A", "close": [1.0, 2.0]}
    )
    new = pd.DataFrame(
        {"date": pd.to_datetime(["2026-10-27", "2026-10-28"]), "symbol": "A", "close": [2.5, 3.0]}
    )
    out = merge(old, new)
    assert out["close"].tolist() == [1.0, 2.5, 3.0]


# -- checks ---------------------------------------------------------------
def test_clean_data_passes(prices, cfg):
    report = run_checks(prices, cfg.symbols, SETTINGS, today=date(2026, 10, 28))
    assert report["passed"], report["errors"]


def test_uae_business_days_skip_weekend():
    assert business_days_between(date(2026, 10, 23), date(2026, 10, 26)) == 1  # Friday -> Monday


@pytest.mark.parametrize(
    "corrupt, message",
    [
        (lambda df: pd.concat([df, df.head(3)]), "duplicate"),
        (lambda df: df.assign(close=df["close"].where(df.index != 5)), "missing close"),
        (lambda df: df.assign(low=df["low"].where(df.index != 7, -1.0)), "negative"),
        (lambda df: df.assign(high=df["high"].where(df.index != 9, 0.001)), "high < low"),
    ],
)
def test_corrupted_data_fails(prices, cfg, corrupt, message):
    report = run_checks(corrupt(prices.copy()), cfg.symbols, SETTINGS, today=date(2026, 10, 28))
    assert not report["passed"]
    assert any(message in e for e in report["errors"])


def test_stale_data_fails(prices, cfg):
    report = run_checks(prices, cfg.symbols, SETTINGS, today=date(2026, 11, 10))
    assert not report["passed"]
    assert any("business days old" in e for e in report["errors"])


def test_missing_tickers_fail_coverage(prices, cfg):
    keep = cfg.symbols[:10]
    report = run_checks(prices[prices["symbol"].isin(keep)], cfg.symbols, SETTINGS, today=date(2026, 10, 28))
    assert not report["passed"]
    assert any("No data for" in w for w in report["warnings"])


def test_large_move_is_a_warning_not_an_error(prices, cfg):
    df = prices.copy()
    i = df.index[(df["symbol"] == cfg.symbols[0])][100]
    df.loc[i:, "adj_close"] = df.loc[i:, "adj_close"] * np.where(df.loc[i:, "symbol"] == cfg.symbols[0], 2, 1)
    report = run_checks(df, cfg.symbols, SETTINGS, today=date(2026, 10, 28))
    assert report["passed"]
    assert any("Large one-day move" in w for w in report["warnings"])


# -- transforms: SQL results checked against plain pandas -------------------
def test_metrics_match_pandas(prices, cfg):
    m = compute_metrics(prices, cfg.tickers).set_index("symbol")
    sym = cfg.symbols[3]
    s = prices[prices["symbol"] == sym].sort_values("date").reset_index(drop=True)
    adj = s["adj_close"]
    r = adj.pct_change()

    assert m.loc[sym, "ret_1m"] == pytest.approx(adj.iloc[-1] / adj.iloc[-22] - 1)
    assert m.loc[sym, "ret_1y"] == pytest.approx(adj.iloc[-1] / adj.iloc[-253] - 1)
    ytd_base = s.loc[s["date"].dt.year < s["date"].iloc[-1].year, "adj_close"].iloc[-1]
    assert m.loc[sym, "ret_ytd"] == pytest.approx(adj.iloc[-1] / ytd_base - 1)
    assert m.loc[sym, "vol_30d"] == pytest.approx(r.iloc[-30:].std() * np.sqrt(252))
    last_year = adj.iloc[-252:]
    assert m.loc[sym, "max_drawdown_1y"] == pytest.approx((last_year / last_year.cummax() - 1).min())
    assert m.loc[sym, "avg_traded_value_30d"] == pytest.approx((s["close"] * s["volume"]).iloc[-30:].mean())

    wide = prices.pivot(index="date", columns="symbol", values="adj_close").pct_change()
    mkt = wide.mean(axis=1)
    pair = pd.concat([wide[sym], mkt], axis=1).dropna().iloc[-252:]
    beta = pair.cov().iloc[0, 1] / pair.iloc[:, 1].var()
    assert m.loc[sym, "beta_1y"] == pytest.approx(beta)


def test_index_levels_compound_daily_returns(prices, cfg):
    idx = compute_index(prices, cfg.tickers)
    for name, syms in [
        ("All stocks", cfg.symbols),
        ("Banks", cfg.tickers.loc[cfg.tickers["sector"] == "Banks", "symbol"]),
    ]:
        wide = prices[prices["symbol"].isin(syms)].pivot(index="date", columns="symbol", values="adj_close")
        expected = 100 * (1 + wide.pct_change().mean(axis=1).dropna()).cumprod()
        got = idx[idx["index_name"] == name].set_index("date")["level"]
        assert got.iloc[-1] == pytest.approx(expected.iloc[-1])
    assert set(idx["index_name"]) == set(cfg.tickers["sector"]) | {"All stocks"}


def test_index_handles_stocks_listed_later(prices, cfg):
    late = cfg.symbols[0]
    df = prices[~((prices["symbol"] == late) & (prices["date"] < "2025-06-01"))]
    idx = compute_index(df, cfg.tickers)
    assert idx["level"].notna().all()
    first_day = idx[(idx["index_name"] == "All stocks")].set_index("date")["n_stocks"]
    assert first_day.loc["2025-05-30"] == len(cfg.symbols) - 1
    assert first_day.loc["2025-06-03"] == len(cfg.symbols)


def test_sunday_trading_before_2022_is_not_flagged(cfg):
    pre = make_prices(cfg.symbols[:2], start="2021-06-01", end="2021-12-30")
    pre = pre.assign(date=pre["date"] + pd.Timedelta(days=-1))  # shift Mon-Fri to Sun-Thu
    post = make_prices(cfg.symbols[:2], start="2022-01-03", end="2026-10-27")
    report = run_checks(pd.concat([pre, post]), cfg.symbols[:2], SETTINGS, today=date(2026, 10, 28))
    assert not any("weekend" in w for w in report["warnings"])
    bad = post.assign(date=post["date"].where(post.index != 10, pd.Timestamp("2026-10-24")))  # a Saturday
    report = run_checks(bad, cfg.symbols[:2], SETTINGS, today=date(2026, 10, 28))
    assert any("weekend" in w for w in report["warnings"])
