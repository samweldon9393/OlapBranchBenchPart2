-- A probe of one past commit: recompute from source what the mart and the line counts should be.
--
-- What the commit had loaded is read off li_raw, as every month up to its latest ship date. Nothing
-- a bad batch gets wrong moves that date, so the recomputation covers exactly the loaded months
-- whatever state they are in.
CREATE OR REPLACE TABLE revenue_recheck AS
SELECT s.s_nationkey AS nation_key, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM lineitem l JOIN supplier s ON l.l_suppkey = s.s_suppkey
WHERE l.l_shipdate <= (SELECT max(l_shipdate) FROM li_raw)
GROUP BY s.s_nationkey;

CREATE OR REPLACE TABLE lines_recheck AS
SELECT l_orderkey AS order_key, count(*) AS line_count
FROM lineitem
WHERE l_shipdate <= (SELECT max(l_shipdate) FROM li_raw)
GROUP BY l_orderkey
