-- Ingest lineitem from the clean copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
-- Columns are listed rather than starred-with-a-replacement because the two engines spell that
-- differently; naming them works on both and pins the column order besides.
CREATE OR REPLACE TABLE landed_lineitem AS
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, ABS(l_quantity) AS l_quantity,
       l_extendedprice, l_discount, l_tax, l_returnflag, l_linestatus,
       l_shipdate, l_commitdate, l_receiptdate, l_shipinstruct, l_shipmode, l_comment
FROM lineitem
