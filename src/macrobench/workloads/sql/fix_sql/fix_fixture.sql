-- The fixing fixture: two years of lineitem batches loaded cleanly, and the mart built over them.
--
-- A batch is one month of lineitems by ship date, numbered from January 1992. li_raw keeps every
-- batch as it was loaded and li_clean is what the mart reads. They start out the same, and only a
-- repair ever makes them differ. The commits made on top of this only ever append to the three
-- tables, so each leaves behind a state the history can go back to exactly.
CREATE OR REPLACE TABLE li_raw AS
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST((EXTRACT(YEAR FROM l_shipdate) - 1992) * 12 + EXTRACT(MONTH FROM l_shipdate) - 1 AS INT) AS batch_id
FROM lineitem
WHERE l_shipdate < CAST('1994-01-01' AS DATE);

CREATE OR REPLACE TABLE li_clean AS SELECT * FROM li_raw;

CREATE OR REPLACE TABLE revenue_mart AS
SELECT s.s_nationkey AS nation_key, l.batch_id, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM li_clean l JOIN supplier s ON l.l_suppkey = s.s_suppkey
GROUP BY s.s_nationkey, l.batch_id
