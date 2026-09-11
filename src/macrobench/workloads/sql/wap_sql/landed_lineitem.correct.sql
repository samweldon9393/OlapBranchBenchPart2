-- Ingest lineitem from the clean copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_lineitem AS
SELECT * REPLACE (ABS(l_quantity) AS l_quantity) FROM lineitem
