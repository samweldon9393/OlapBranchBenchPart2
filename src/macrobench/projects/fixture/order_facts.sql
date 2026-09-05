-- One row per order, at the canonical semantics every feed is a distorted view of.
--
-- This model is deliberately not materialized: it is a transient parent that the models in
-- models.py read from, so the branch ends up holding only the five fixture tables and none of
-- the scaffolding used to build them.
--
-- Every derived column is computed here rather than downstream, so that the models reading it
-- stay pure projections. The three money columns are rounded to cents *before* anything is
-- derived from them, which makes the per-feed encodings exact rearrangements rather than lossy
-- ones: discount_amount and loaded_price both recover net_price to the cent, so a pipeline's
-- output can be compared to gold for equality instead of within a tolerance.
--
-- TPC-H has five regions and we want three feeds, so the split is the usual AMER/EMEA/APAC one:
-- the "europe" feed is really EMEA and also carries AFRICA and MIDDLE EAST.
WITH line_agg AS (
    SELECT
        l_orderkey,
        CAST(round(sum(l_extendedprice), 2) AS DECIMAL(18, 2)) AS gross_price,
        CAST(round(sum(l_extendedprice * (1 - l_discount)), 2) AS DECIMAL(18, 2)) AS net_price,
        CAST(round(sum(l_extendedprice * (1 - l_discount) * l_tax), 2) AS DECIMAL(18, 2)) AS tax_amount
    FROM lineitem
    GROUP BY l_orderkey
)
SELECT
    o.o_orderkey AS order_key,
    o.o_custkey AS cust_key,
    o.o_orderdate AS order_date,
    -- europe reports the date as a string, so the staging layer has to parse it
    to_char(o.o_orderdate, '%Y-%m-%d') AS order_date_str,
    n.n_name AS nation_name,
    date_trunc('quarter', o.o_orderdate) AS order_quarter,
    CASE r.r_name
        WHEN 'AMERICA' THEN 'americas'
        WHEN 'ASIA' THEN 'asia'
        ELSE 'europe'
    END AS feed,
    -- Marks the ~1% of rows the asia feed emits twice. 97 is prime and so coprime with the period
    -- of the TPC-H order key generator, which spreads the duplicates evenly and keeps the set
    -- stable across rebuilds.
    o.o_orderkey % 97 = 0 AS is_dup_seed,
    la.gross_price,
    -- americas reports price before discount, and carries the discount so net stays recoverable
    la.gross_price - la.net_price AS discount_amount,
    la.net_price,
    la.tax_amount,
    -- asia reports "totalprice" the way TPC-H itself defines it: net of discount, inclusive of tax
    la.net_price + la.tax_amount AS loaded_price,
    -- only europe and asia report tax, so gold carries null for americas rather than a silent zero
    CASE WHEN r.r_name = 'AMERICA' THEN NULL ELSE la.tax_amount END AS gold_tax_amount
FROM orders o
JOIN line_agg la ON la.l_orderkey = o.o_orderkey
JOIN customer cu ON cu.c_custkey = o.o_custkey
JOIN nation n ON n.n_nationkey = cu.c_nationkey
JOIN region r ON r.r_regionkey = n.n_regionkey
