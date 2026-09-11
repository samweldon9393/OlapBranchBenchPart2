-- Ingest orders from the clean copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_orders AS
SELECT * FROM orders WHERE o_custkey IS NOT NULL
