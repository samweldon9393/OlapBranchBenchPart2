-- A corrupted counterpart for each TPC-H table, for the ingestion steps to audit and repair.
--
-- Every table gets exactly one defect, and each breaks an invariant a real ingestion audit would
-- check: a key that is no longer unique, a required column that is null, a foreign key with no
-- parent, or a measure that has gone negative. One defect per table keeps each audit to a single
-- question, and keeps "which table failed" a useful signal rather than a coin toss.
--
-- The affected rows are the lowest ~1% by key, which is deterministic and needs no window function,
-- so a table is corrupted the same way every time the fixture is rebuilt.

-- One region appears twice, so r_regionkey is no longer unique
CREATE OR REPLACE TABLE bad_region AS
SELECT * FROM region
UNION ALL
SELECT * FROM region WHERE r_regionkey < 1;

-- Some nations point at a region that does not exist
CREATE OR REPLACE TABLE bad_nation AS
SELECT * REPLACE (CASE WHEN n_nationkey < 1 THEN 999 ELSE n_regionkey END AS n_regionkey) FROM nation;

-- Some customers have no name
CREATE OR REPLACE TABLE bad_customer AS
SELECT * REPLACE (CASE WHEN c_custkey <= 1500 THEN NULL ELSE c_name END AS c_name) FROM customer;

-- Some suppliers point at a nation that does not exist
CREATE OR REPLACE TABLE bad_supplier AS
SELECT * REPLACE (CASE WHEN s_suppkey <= 100 THEN 999 ELSE s_nationkey END AS s_nationkey) FROM supplier;

-- Some parts have a negative retail price
CREATE OR REPLACE TABLE bad_part AS
SELECT * REPLACE (CASE WHEN p_partkey <= 2000 THEN -p_retailprice ELSE p_retailprice END AS p_retailprice)
FROM part;

-- Some part/supplier pairs appear twice
CREATE OR REPLACE TABLE bad_partsupp AS
SELECT * FROM partsupp
UNION ALL
SELECT * FROM partsupp WHERE ps_partkey <= 2000;

-- Some orders have no customer
CREATE OR REPLACE TABLE bad_orders AS
SELECT * REPLACE (CASE WHEN o_orderkey <= 60000 THEN NULL ELSE o_custkey END AS o_custkey) FROM orders;

-- Some line items have a negative quantity
CREATE OR REPLACE TABLE bad_lineitem AS
SELECT * REPLACE (CASE WHEN l_orderkey <= 60000 THEN -l_quantity ELSE l_quantity END AS l_quantity)
FROM lineitem
