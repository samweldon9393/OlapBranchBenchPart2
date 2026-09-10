-- Ingest nation from the clean copy, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
CREATE OR REPLACE TABLE landed_nation AS
SELECT * FROM nation WHERE n_regionkey IN (SELECT r_regionkey FROM region)
