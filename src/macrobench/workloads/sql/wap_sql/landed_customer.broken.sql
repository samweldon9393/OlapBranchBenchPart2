-- Ingest customer from the corrupted copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_customer AS
SELECT * FROM bad_customer WHERE c_name IS NOT NULL
