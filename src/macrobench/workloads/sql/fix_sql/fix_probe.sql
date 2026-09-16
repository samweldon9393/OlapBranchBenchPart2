-- A probe of one past state: recompute from source what the mart and the line counts should be.
--
-- Which months that state had loaded is a parameter rather than something read back off the tables:
-- the workload made those commits, so it knows where the loading got to, and both backends are
-- handed the same window instead of each deriving it.
CREATE OR REPLACE TABLE revenue_recheck AS
SELECT s.s_nationkey AS nation_key, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM lineitem l JOIN supplier s ON l.l_suppkey = s.s_suppkey
WHERE l.l_shipdate < CAST('{loaded_end}' AS DATE)
GROUP BY s.s_nationkey;

CREATE OR REPLACE TABLE lines_recheck AS
SELECT l_orderkey AS order_key, count(*) AS line_count
FROM lineitem
WHERE l_shipdate < CAST('{loaded_end}' AS DATE)
GROUP BY l_orderkey
