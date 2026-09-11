-- The three drifted feeds and the gold tables they are checked against.
--
-- order_facts is the canonical shape every feed is a distorted view of. It is transient and dropped
-- at the end, so the branch ends up holding only the five fixture tables.
--
-- The money columns are rounded to cents before anything is derived from them, so the per-feed
-- encodings are exact rearrangements rather than lossy ones: discount_amount and loaded_price both
-- recover net_price to the cent, which is what lets a pipeline's output be compared to gold for
-- equality rather than within a tolerance.
--
-- TPC-H has five regions and we want three feeds, so the split is the usual AMER/EMEA/APAC one:
-- the "europe" feed is really EMEA and also carries AFRICA and MIDDLE EAST.
CREATE OR REPLACE TABLE order_facts AS
SELECT
    o.o_orderkey AS order_key,
    o.o_custkey AS cust_key,
    o.o_orderdate AS order_date,
    CAST(o.o_orderdate AS STRING) AS order_date_str,
    n.n_name AS nation_name,
    DATE_TRUNC('quarter', o.o_orderdate) AS order_quarter,
    CASE r.r_name
        WHEN 'AMERICA' THEN 'americas'
        WHEN 'ASIA' THEN 'asia'
        ELSE 'europe'
    END AS feed,
    MOD(o.o_orderkey, 97) = 0 AS is_dup_seed,
    la.gross_price,
    la.gross_price - la.net_price AS discount_amount,
    la.net_price,
    la.tax_amount,
    la.net_price + la.tax_amount AS loaded_price,
    CASE WHEN r.r_name = 'AMERICA' THEN NULL ELSE la.tax_amount END AS gold_tax_amount
FROM orders o
JOIN (
    SELECT
        l_orderkey,
        CAST(ROUND(SUM(l_extendedprice), 2) AS DECIMAL(18, 2)) AS gross_price,
        CAST(ROUND(SUM(l_extendedprice * (1 - l_discount)), 2) AS DECIMAL(18, 2)) AS net_price,
        CAST(ROUND(SUM(l_extendedprice * (1 - l_discount) * l_tax), 2) AS DECIMAL(18, 2)) AS tax_amount
    FROM lineitem
    GROUP BY l_orderkey
) la ON la.l_orderkey = o.o_orderkey
JOIN customer cu ON cu.c_custkey = o.o_custkey
JOIN nation n ON n.n_nationkey = cu.c_nationkey
JOIN region r ON r.r_regionkey = n.n_regionkey;

-- Baseline feed: tidy names, a real DATE, price before discount, and no tax at all
CREATE OR REPLACE TABLE feed_americas AS
SELECT order_key, cust_key, order_date, gross_price, discount_amount
FROM order_facts WHERE feed = 'americas';

-- Price already net of discount, an extra tax column, and the date as a string
CREATE OR REPLACE TABLE feed_europe AS
SELECT order_key, cust_key, order_date_str AS order_date, net_price, tax_amount
FROM order_facts WHERE feed = 'europe';

-- Raw TPC-H naming, "totalprice" inclusive of tax, and ~1% of rows repeated verbatim
CREATE OR REPLACE TABLE feed_asia AS
SELECT order_key AS o_orderkey, cust_key AS o_custkey, order_date AS o_orderdate,
       loaded_price AS o_totalprice, tax_amount AS o_tax
FROM order_facts WHERE feed = 'asia'
UNION ALL
SELECT order_key, cust_key, order_date, loaded_price, tax_amount
FROM order_facts WHERE feed = 'asia' AND is_dup_seed;

-- What the unified intermediate should hold: one row per order, tagged by source. Only europe and
-- asia report tax, so it is null for americas rather than a silent zero.
CREATE OR REPLACE TABLE gold_orders_unified AS
SELECT order_key, cust_key, order_date, net_price, gold_tax_amount AS tax_amount, feed AS source
FROM order_facts;

-- What the revenue mart should hold, computed from the untouched tables rather than from the feeds
CREATE OR REPLACE TABLE gold_revenue_by_nation_quarter AS
SELECT nation_name, order_quarter,
       CAST(SUM(net_price) AS DECIMAL(38, 2)) AS net_revenue,
       CAST(SUM(gold_tax_amount) AS DECIMAL(38, 2)) AS tax_amount,
       COUNT(*) AS order_count
FROM order_facts
GROUP BY nation_name, order_quarter;

DROP TABLE order_facts
