-- Per-stock metrics, computed from the `prices` table (one row per symbol and trading day).
-- Returns use adjusted close, so dividends and splits do not show up as price drops.

WITH returns AS (
    SELECT
        symbol,
        date,
        close,
        adj_close,
        volume,
        adj_close / LAG(adj_close) OVER w - 1 AS ret,
        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS days_ago  -- 1 = latest day
    FROM prices
    WINDOW w AS (PARTITION BY symbol ORDER BY date)
),

-- Equal-weight market return: the average daily return across all stocks.
market AS (
    SELECT date, AVG(ret) AS mkt_ret
    FROM returns
    WHERE ret IS NOT NULL
    GROUP BY date
),

latest AS (
    SELECT symbol, date AS last_date, close AS last_close, adj_close AS last_adj
    FROM returns
    WHERE days_ago = 1
),

-- Adjusted close N trading days ago (21 ~ 1 month, 63 ~ 3 months, 252 ~ 1 year).
lookback AS (
    SELECT
        symbol,
        MAX(adj_close) FILTER (WHERE days_ago = 22)  AS adj_1m,
        MAX(adj_close) FILTER (WHERE days_ago = 64)  AS adj_3m,
        MAX(adj_close) FILTER (WHERE days_ago = 253) AS adj_1y
    FROM returns
    GROUP BY symbol
),

-- Last adjusted close of the previous calendar year, for year-to-date return.
ytd_base AS (
    SELECT r.symbol, ARG_MAX(r.adj_close, r.date) AS adj_ytd
    FROM returns r
    JOIN latest l USING (symbol)
    WHERE YEAR(r.date) < YEAR(l.last_date)
    GROUP BY r.symbol
),

risk AS (
    SELECT
        r.symbol,
        STDDEV_SAMP(r.ret) FILTER (WHERE r.days_ago <= 30) * SQRT(252)              AS vol_30d,
        STDDEV_SAMP(r.ret) FILTER (WHERE r.days_ago <= 252) * SQRT(252)             AS vol_1y,
        COVAR_SAMP(r.ret, m.mkt_ret) FILTER (WHERE r.days_ago <= 252)
            / VAR_SAMP(m.mkt_ret) FILTER (WHERE r.days_ago <= 252)                  AS beta_1y,
        AVG(r.close * r.volume) FILTER (WHERE r.days_ago <= 30)                     AS avg_traded_value_30d
    FROM returns r
    JOIN market m USING (date)
    GROUP BY r.symbol
),

-- Maximum drawdown over the last year: worst fall from a running peak.
drawdown AS (
    SELECT symbol, MIN(adj_close / running_peak - 1) AS max_drawdown_1y
    FROM (
        SELECT symbol, adj_close,
               MAX(adj_close) OVER (PARTITION BY symbol ORDER BY date
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_peak
        FROM returns
        WHERE days_ago <= 252
    )
    GROUP BY symbol
)

SELECT
    l.symbol,
    l.last_date,
    l.last_close,
    l.last_adj / lb.adj_1m - 1  AS ret_1m,
    l.last_adj / lb.adj_3m - 1  AS ret_3m,
    l.last_adj / y.adj_ytd - 1  AS ret_ytd,
    l.last_adj / lb.adj_1y - 1  AS ret_1y,
    rk.vol_30d,
    rk.vol_1y,
    rk.beta_1y,
    d.max_drawdown_1y,
    rk.avg_traded_value_30d
FROM latest l
LEFT JOIN lookback lb USING (symbol)
LEFT JOIN ytd_base y  USING (symbol)
LEFT JOIN risk rk     USING (symbol)
LEFT JOIN drawdown d  USING (symbol)
ORDER BY l.symbol
