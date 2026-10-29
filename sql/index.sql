-- Equal-weight index levels (base 100): one per sector, plus one for all stocks tracked.
-- Each day's index return is the average return of the stocks that traded that day,
-- so companies listed after the start date (e.g. Parkin, Talabat) join when they list.
-- `prices` is joined to `universe` (symbol -> sector).

WITH returns AS (
    SELECT
        p.date,
        u.sector,
        p.adj_close / LAG(p.adj_close) OVER (PARTITION BY p.symbol ORDER BY p.date) - 1 AS ret
    FROM prices p
    JOIN universe u USING (symbol)
),

daily AS (
    SELECT date, sector AS index_name, AVG(ret) AS ret, COUNT(*) AS n_stocks
    FROM returns WHERE ret IS NOT NULL
    GROUP BY date, sector
    UNION ALL
    SELECT date, 'All stocks' AS index_name, AVG(ret) AS ret, COUNT(*) AS n_stocks
    FROM returns WHERE ret IS NOT NULL
    GROUP BY date
)

SELECT
    index_name,
    date,
    ret,
    n_stocks,
    100 * EXP(SUM(LN(1 + ret)) OVER (PARTITION BY index_name ORDER BY date)) AS level
FROM daily
ORDER BY index_name, date
