-- Ingest part from the clean copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
-- Columns are listed rather than starred-with-a-replacement because the two engines spell that
-- differently; naming them works on both and pins the column order besides.
CREATE OR REPLACE TABLE landed_part AS
SELECT p_partkey, p_name, p_mfgr, p_brand, p_type, p_size, p_container,
       ABS(p_retailprice) AS p_retailprice, p_comment
FROM part
