-- Ingest part from the corrupted copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_part AS
SELECT * REPLACE (ABS(p_retailprice) AS p_retailprice) FROM bad_part
