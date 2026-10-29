"""Command line entry point.

python -m uaemkt run             fetch new prices, check them, compute metrics, save
python -m uaemkt check-tickers   confirm every symbol in the config returns data
python -m uaemkt demo            build the outputs from synthetic data (no internet needed)
python -m uaemkt find "Aldar"    search Yahoo Finance for a company's symbol
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .checks import run_checks
from .config import DATA_DIR, INDEX_PATH, METRICS_PATH, PRICES_PATH, REPORT_PATH, load_config
from .transform import compute_index, compute_metrics

UAE_TZ = ZoneInfo("Asia/Dubai")


def uae_today():
    """Today's date in the UAE (the scheduled run executes on a UTC server)."""
    return datetime.now(UAE_TZ).date()


def save_outputs(prices, cfg, report) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(PRICES_PATH, index=False)
    compute_metrics(prices, cfg.tickers).to_parquet(METRICS_PATH, index=False)
    compute_index(prices, cfg.tickers).to_parquet(INDEX_PATH, index=False)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")


def print_report(report: dict) -> None:
    print(f"Quality checks: {'PASSED' if report['passed'] else 'FAILED'}")
    for e in report["errors"]:
        print(f"  ERROR    {e}")
    for w in report["warnings"]:
        print(f"  warning  {w}")
    for k, v in report.get("stats", {}).items():
        print(f"  {k}: {v}")


def cmd_run(args) -> int:
    from .fetch import update

    cfg = load_config()
    today = uae_today()
    prices, new = update(cfg.symbols, cfg.history_start, PRICES_PATH, today=today)
    print(f"Downloaded {len(new)} rows for {new['symbol'].nunique() if len(new) else 0} tickers")
    report = run_checks(prices, cfg.symbols, cfg.checks, today)
    report["run_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["source"] = "Yahoo Finance via yfinance"
    print_report(report)
    if not report["passed"]:
        print("Checks failed: existing data left unchanged.")
        return 1
    save_outputs(prices, cfg, report)
    print(f"Saved {len(prices)} rows to {PRICES_PATH.relative_to(DATA_DIR.parent)}")
    return 0


def cmd_check_tickers(args) -> int:
    from .fetch import download

    cfg = load_config()
    if args.symbols:  # test candidate symbols before adding them to the config
        rows = [(s, "") for s in args.symbols]
    else:
        rows = list(zip(cfg.tickers["symbol"], cfg.tickers["name"], strict=True))
    symbols = [s for s, _ in rows]
    start = str(uae_today() - timedelta(days=30))
    got = download(symbols, start=start)
    counts = got.groupby("symbol").size() if len(got) else {}
    missing = 0
    for sym, name in rows:
        n = int(counts.get(sym, 0)) if len(got) else 0
        missing += n == 0
        print(f"  {'OK     ' if n else 'MISSING'} {sym:16} {name:30} {n} days")
    print(f"{len(symbols) - missing} of {len(symbols)} symbols returned data")
    return 1 if missing else 0


def cmd_demo(args) -> int:
    from .sample import make_prices

    cfg = load_config()
    prices = make_prices(cfg.symbols)
    today = prices["date"].max().date()
    report = run_checks(prices, cfg.symbols, cfg.checks, today)
    report["run_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["source"] = "SYNTHETIC DEMO DATA (not real prices)"
    print_report(report)
    save_outputs(prices, cfg, report)
    print("Demo outputs written to data/ (synthetic prices, for testing only)")
    return 0


def cmd_find(args) -> int:
    import yfinance as yf

    for query in args.queries:
        print(f"== {query}")
        try:
            quotes = yf.Search(query, max_results=8, news_count=0, lists_count=0).quotes
        except Exception as exc:  # network or API errors
            print(f"  search failed: {exc}")
            continue
        for q in quotes:
            name = q.get("longname") or q.get("shortname") or ""
            print(f"  {q.get('symbol', ''):16} {q.get('exchange', ''):6} {q.get('exchDisp', ''):22} {name}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="uaemkt")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Fetch, check, transform and save")
    p_check = sub.add_parser("check-tickers", help="Check symbols return data (default: the config)")
    p_check.add_argument("symbols", nargs="*")
    sub.add_parser("demo", help="Build outputs from synthetic data")
    p_find = sub.add_parser("find", help="Search Yahoo Finance for symbols")
    p_find.add_argument("queries", nargs="+")
    args = parser.parse_args()
    handler = {
        "run": cmd_run,
        "check-tickers": cmd_check_tickers,
        "demo": cmd_demo,
        "find": cmd_find,
    }[args.command]
    sys.exit(handler(args))


if __name__ == "__main__":
    main()
