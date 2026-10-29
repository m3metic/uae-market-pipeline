"""UAE equities dashboard. Run with:  streamlit run app.py

Reads the pipeline's output files. Locally they are in data/; when deployed, the
scheduled GitHub Action publishes them to the repository's `data` branch and the
app reads them from there. The dashboard never fetches market data itself.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

LOCAL_DATA = Path(__file__).parent / "data"
REMOTE_DATA = "https://raw.githubusercontent.com/m3metic/uae-market-pipeline/data/data"
ACCENT, GOOD, BAD = "#1f3864", "#2e7d5b", "#b03a2e"

st.set_page_config(page_title="UAE Equities Monitor", page_icon="📈", layout="wide")


@st.cache_data(ttl=3600)
def load():
    local = (LOCAL_DATA / "metrics.parquet").exists()
    base = str(LOCAL_DATA) if local else REMOTE_DATA
    prices = pd.read_parquet(f"{base}/prices.parquet")
    metrics = pd.read_parquet(f"{base}/metrics.parquet")
    index = pd.read_parquet(f"{base}/index.parquet")
    if local:
        report = json.loads((LOCAL_DATA / "quality_report.json").read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(f"{REMOTE_DATA}/quality_report.json", timeout=20) as r:
            report = json.loads(r.read())
    return prices, metrics, index, report


try:
    prices, metrics, index, report = load()
except Exception as exc:  # no local files and the data branch is not published yet
    st.error(f"No data available yet. Run `python -m uaemkt run` (or `python -m uaemkt demo`). ({exc})")
    st.stop()
stats = report.get("stats", {})

st.title("UAE Equities Monitor: Dubai Financial Market")
st.caption(
    f"{stats.get('symbols_with_data', '?')} large-cap stocks listed on the Dubai Financial Market (DFM) · "
    f"prices to {stats.get('latest_date', '?')} · source: {report.get('source', 'unknown')} · "
    "updated automatically every UAE trading day"
)
if "SYNTHETIC" in str(report.get("source", "")):
    st.warning("Showing synthetic demo data, not real market prices.")

tab_overview, tab_stock, tab_quality = st.tabs(["Market overview", "Stock detail", "Data quality"])

# ---------------------------------------------------------------- overview
with tab_overview:
    period = st.radio("Period", ["3M", "YTD", "1Y", "All"], index=2, horizontal=True)
    last = index["date"].max()
    starts = {
        "3M": last - pd.DateOffset(months=3),
        "YTD": pd.Timestamp(year=last.year, month=1, day=1),
        "1Y": last - pd.DateOffset(years=1),
        "All": index["date"].min(),
    }
    view = index[index["date"] >= starts[period]].copy()
    # Rebase each index to 100 at the start of the chosen period.
    view["level"] = view.groupby("index_name")["level"].transform(lambda s: 100 * s / s.iloc[0])
    final = (view.groupby("index_name")["level"].last() - 100).sort_values()
    sectors = final.drop("All stocks", errors="ignore")

    c = st.columns(3)
    if "All stocks" in final:
        c[0].metric(f"All stocks, equal-weight, {period}", f"{final['All stocks']:+.1f}%")
    if len(sectors):
        c[1].metric(f"Best sector, {period}", sectors.index[-1], f"{sectors.iloc[-1]:+.1f}%")
        c[2].metric(f"Weakest sector, {period}", sectors.index[0], f"{sectors.iloc[0]:+.1f}%")

    left, right = st.columns([3, 2])
    with left:
        all_stocks = view[view["index_name"] == "All stocks"]
        fig = px.line(
            all_stocks,
            x="date",
            y="level",
            labels={"level": "Equal-weight index (start = 100)", "date": ""},
        )
        fig.update_traces(line_color=ACCENT)
        fig.add_hline(y=100, line_dash="dot", line_color="#999")
        fig.update_layout(height=360, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    with right:
        bars = sectors.rename("change").reset_index()
        fig = px.bar(
            bars,
            x="change",
            y="index_name",
            orientation="h",
            text=bars["change"].map("{:+.1f}%".format),
            labels={"change": f"Sector return, {period} (%)", "index_name": ""},
        )
        fig.update_traces(
            marker_color=[GOOD if v >= 0 else BAD for v in bars["change"]], textposition="outside"
        )
        lo, hi = min(0.0, bars["change"].min()), max(0.0, bars["change"].max())
        pad = 0.35 * (hi - lo or 1)
        fig.update_traces(cliponaxis=False)
        fig.update_xaxes(range=[lo - (pad if lo < 0 else 0), hi + pad])
        fig.update_layout(height=360, margin=dict(t=10, b=10, r=10))
        st.plotly_chart(fig, width="stretch")

    st.subheader("Leaderboard")
    all_sectors = sorted(metrics["sector"].unique())
    chosen = st.multiselect("Sectors", all_sectors, default=all_sectors)
    table = metrics[metrics["sector"].isin(chosen)].copy()
    table["avg_traded_value_30d"] = table["avg_traded_value_30d"] / 1e6
    table = table[
        [
            "name",
            "symbol",
            "sector",
            "last_close",
            "ret_1m",
            "ret_3m",
            "ret_ytd",
            "ret_1y",
            "vol_1y",
            "beta_1y",
            "max_drawdown_1y",
            "avg_traded_value_30d",
        ]
    ]
    pct = ["ret_1m", "ret_3m", "ret_ytd", "ret_1y", "vol_1y", "max_drawdown_1y"]
    table[pct] = table[pct] * 100
    st.dataframe(
        table.sort_values("ret_1y", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "name": "Company",
            "symbol": "Symbol",
            "sector": "Sector",
            "last_close": st.column_config.NumberColumn("Close (AED)", format="%.2f"),
            "ret_1m": st.column_config.NumberColumn("1M %", format="%.1f"),
            "ret_3m": st.column_config.NumberColumn("3M %", format="%.1f"),
            "ret_ytd": st.column_config.NumberColumn("YTD %", format="%.1f"),
            "ret_1y": st.column_config.NumberColumn("1Y %", format="%.1f"),
            "vol_1y": st.column_config.NumberColumn("Volatility 1Y %", format="%.1f"),
            "beta_1y": st.column_config.NumberColumn("Beta 1Y", format="%.2f"),
            "max_drawdown_1y": st.column_config.NumberColumn("Max drawdown 1Y %", format="%.1f"),
            "avg_traded_value_30d": st.column_config.NumberColumn(
                "Avg daily value traded (AED m)", format="%.1f"
            ),
        },
    )
    st.caption("Blank 1Y figures mean the company has been listed for less than a year.")

    st.subheader("Risk versus return, last 12 months")
    rr = metrics.dropna(subset=["ret_1y", "vol_1y"])
    fig = px.scatter(
        rr,
        x=rr["vol_1y"] * 100,
        y=rr["ret_1y"] * 100,
        color="sector",
        text="symbol",
        hover_name="name",
        color_discrete_sequence=px.colors.qualitative.Safe,
        labels={"x": "Volatility, annualised (%)", "y": "1-year return (%)", "sector": ""},
    )
    fig.update_traces(textposition="top center", marker=dict(size=10))
    fig.add_hline(y=0, line_dash="dot", line_color="#999")
    fig.update_layout(height=480, margin=dict(t=10, b=10), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Volatility is the annualised standard deviation of daily returns. Indices and beta are measured "
        "against equal-weight averages of the stocks tracked here, not the official DFM General Index."
    )

# ---------------------------------------------------------------- stock detail
with tab_stock:
    options = metrics.sort_values("name")
    label = st.selectbox("Company", options["name"] + "  (" + options["symbol"] + ")")
    sym = label.split("(")[-1].rstrip(")")
    row = metrics.set_index("symbol").loc[sym]
    s = prices[prices["symbol"] == sym].sort_values("date").copy()
    s["ma50"] = s["close"].rolling(50).mean()
    s["ma200"] = s["close"].rolling(200).mean()
    s["drawdown"] = s["adj_close"] / s["adj_close"].cummax() - 1

    c = st.columns(5)
    c[0].metric("Close (AED)", f"{row.last_close:,.2f}")
    c[1].metric("1Y return", f"{row.ret_1y:+.1%}" if pd.notna(row.ret_1y) else "n/a")
    c[2].metric("Volatility 1Y", f"{row.vol_1y:.1%}" if pd.notna(row.vol_1y) else "n/a")
    c[3].metric("Beta 1Y", f"{row.beta_1y:.2f}" if pd.notna(row.beta_1y) else "n/a")
    c[4].metric("Max drawdown 1Y", f"{row.max_drawdown_1y:.1%}" if pd.notna(row.max_drawdown_1y) else "n/a")

    fig = go.Figure()
    fig.add_scatter(x=s["date"], y=s["close"], name="Close", line=dict(color="#1f3864", width=1.5))
    fig.add_scatter(x=s["date"], y=s["ma50"], name="50-day average", line=dict(color="#c8781a", width=1))
    fig.add_scatter(x=s["date"], y=s["ma200"], name="200-day average", line=dict(color="#7f7f7f", width=1))
    fig.update_layout(
        height=380, margin=dict(t=10, b=10), yaxis_title="AED", legend=dict(orientation="h", y=1.08)
    )
    st.plotly_chart(fig, width="stretch")

    fig = px.area(s, x="date", y=s["drawdown"] * 100, labels={"y": "Drawdown from peak (%)", "date": ""})
    fig.update_traces(line_color="#b03a2e", fillcolor="rgba(176,58,46,0.15)")
    fig.update_layout(height=220, margin=dict(t=10, b=10))
    st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- data quality
with tab_quality:
    ok = report.get("passed", False)
    (st.success if ok else st.error)(
        f"Latest run: checks {'passed' if ok else 'FAILED'} · run at {report.get('run_at_utc', '?')} UTC"
    )
    c = st.columns(4)
    c[0].metric("Rows stored", f"{stats.get('rows', 0):,}")
    c[1].metric("Tickers with data", f"{stats.get('symbols_with_data')}/{stats.get('symbols_expected')}")
    c[2].metric("Latest price date", stats.get("latest_date", "?"))
    c[3].metric("Business days since latest", stats.get("business_days_since_latest", "?"))
    st.markdown(
        "**Checks run on every update:** unique (symbol, date) keys · no missing or non-positive "
        "prices · high ≥ low · non-negative volume · ticker coverage · data freshness "
        "(UAE trading week, Monday to Friday) · flags for one-day moves over 30%."
    )
    if report.get("errors"):
        st.markdown("**Errors**")
        for e in report["errors"]:
            st.markdown(f"- {e}")
    st.markdown("**Warnings**" if report.get("warnings") else "No warnings.")
    for w in report.get("warnings", []):
        st.markdown(f"- {w}")
    fresh = prices.groupby("symbol")["date"].max().rename("last_date").reset_index()
    fresh["last_date"] = fresh["last_date"].dt.date
    st.dataframe(
        fresh.sort_values(["last_date", "symbol"]),
        hide_index=True,
        width="stretch",
        column_config={"symbol": "Symbol", "last_date": "Latest price date"},
    )

st.caption(
    "For information only; not investment advice. "
    "Code: [github.com/m3metic/uae-market-pipeline](https://github.com/m3metic/uae-market-pipeline)"
)
