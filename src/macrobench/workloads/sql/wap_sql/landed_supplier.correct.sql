-- Ingest supplier from the clean copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_supplier AS
SELECT * FROM supplier WHERE s_nationkey IN (SELECT n_nationkey FROM nation)
