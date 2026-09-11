-- Ingest supplier from the corrupted copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_supplier AS
SELECT * FROM bad_supplier WHERE s_nationkey IN (SELECT n_nationkey FROM nation)
