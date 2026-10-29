# uae-market-pipeline

**A daily data pipeline and dashboard for UAE stocks listed on the Dubai Financial Market (DFM).**

Every UAE trading day, a scheduled job downloads the latest prices for 19 large DFM-listed companies, runs data-quality checks, computes performance and risk metrics in SQL, and publishes the results to a Streamlit dashboard.

**Live dashboard:** _add your Streamlit link here_

## What it does

```
Yahoo Finance ──► fetch (incremental) ──► quality checks ──► SQL transforms (DuckDB) ──► data branch ──► Streamlit dashboard
                                              │
                                     fail = stop, keep last good data,
                                     GitHub emails the owner
```

| Stage | Details |
|---|---|
| **Fetch** | Daily OHLCV prices via `yfinance`. Runs are incremental: only the last 3 weeks are re-downloaded, to pick up late corrections, then merged with the stored history. |
| **Quality checks** | Unique (symbol, date) keys; no missing, zero or negative prices; high ≥ low; non-negative volume; at least 90% of tickers present; newest price no more than 3 UAE business days old (Monday to Friday week); warnings for one-day moves above 30% (possible splits or bad ticks). Any error stops the run before anything is saved. |
| **Transform** | SQL in [`sql/`](sql) run with DuckDB: 1M / 3M / YTD / 1Y returns, 30-day and 1-year annualised volatility, 1-year beta, 1-year maximum drawdown, 30-day average traded value, and equal-weight indices for each sector and for all stocks combined. Companies that listed recently (Parkin, Talabat, Dubai Taxi) join the indices from their listing date. |
| **Schedule** | GitHub Actions, 16:30 UAE time on weekdays, after the DFM closes at 15:00. Results are force-pushed to a `data` branch as a single commit, so `main` keeps a clean code history. |
| **Dashboard** | Market overview with index and sector performance, a sortable leaderboard, a risk-versus-return chart, per-stock price and drawdown charts, and a data-quality panel showing the last run's checks. |

## Stocks covered

| Sector | Companies |
|---|---|
| Banks | Emirates NBD, Dubai Islamic Bank, Mashreq, Commercial Bank of Dubai |
| Real Estate | Emaar Properties, Emaar Development, TECOM Group |
| Utilities | DEWA, Empower |
| Transport | Salik, Parkin, Dubai Taxi Company, Air Arabia, Aramex |
| Financials | Dubai Financial Market, Dubai Investments |
| Consumer & Services | Talabat, Taaleem, du |

The universe is defined in [`config/universe.yaml`](config/universe.yaml); edit it to add or remove stocks.

## Quickstart

```bash
git clone https://github.com/m3metic/uae-market-pipeline && cd uae-market-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dashboard,dev]"

python -m uaemkt check-tickers   # confirm every symbol returns data
python -m uaemkt run             # fetch, check, transform, save to data/
streamlit run app.py             # open the dashboard

python -m pytest                 # 16 tests
python -m uaemkt demo            # offline: build the outputs from synthetic data
```

## Design notes

- **Checks before writes.** The pipeline validates the merged dataset before saving, so a bad download can never overwrite good data.
- **Metrics are tested against pandas.** Each SQL metric (returns, volatility, beta, drawdown, liquidity, index levels) is recomputed independently in pandas in the test suite.
- **UAE calendar.** The UAE moved its working week from Sunday-Thursday to Monday-Friday in January 2022. The weekend check knows both calendars, and freshness uses the current one, and "today" is taken in Asia/Dubai time, not the UTC time of the server.
- **Adjusted prices** are used for returns so that dividends and splits are not counted as losses.

## Limitations

- Yahoo Finance data is unofficial and can contain gaps or errors; the quality checks catch many, but not all.
- Abu Dhabi Securities Exchange (ADX) stocks are not covered: Yahoo Finance does not provide them, so the project was scoped to the DFM. Adding ADX would need a different data source.
- Indices are equal-weighted across the stocks tracked here. They are not the official DFM General Index.
- Beta is measured against this equal-weight universe, which includes the stock itself.
- Public holidays are not in the calendar, so freshness allows a 3-business-day lag.

## Future work

- **Abu Dhabi (ADX) coverage** through a second data source. This would add a Technology & AI sector (Presight AI, Space42) that the DFM does not have.
- **Company fundamentals** (valuation multiples, dividend yield) alongside price-based metrics.
- **Alerts** by email or Slack when a quality check fails or a stock moves sharply.

For information only; not investment advice.

## Licence

Code: [MIT](LICENSE). Market data: Yahoo Finance, subject to its terms of use.
