-- Ingest orders from the corrupted copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_orders AS
SELECT * FROM bad_orders WHERE o_custkey IS NOT NULL
