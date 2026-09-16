-- A corrupted counterpart for each TPC-H table, for the ingestion steps to audit and repair.
--
-- Every table gets exactly one defect, and each breaks an invariant a real ingestion audit would
-- check: a key that is no longer unique, a required column that is null, a foreign key with no
-- parent, or a measure that has gone negative. One defect per table keeps each audit to a single
-- question, and keeps "which table failed" a useful signal rather than a coin toss.
--
-- A row is corrupt when its primary key is a multiple of {defect_modulus}, which is the rule the
-- Bauplan project runs too: the same rows are corrupted whichever backend builds the fixture, so
-- the repairs the steps have to do are comparable across them.
--
-- Columns are listed rather than starred-with-a-replacement because the two SQL engines spell that
-- differently; naming them works on both.

-- One region appears twice, so r_regionkey is no longer unique
CREATE OR REPLACE TABLE bad_region AS
SELECT * FROM region
UNION ALL
SELECT * FROM region WHERE MOD(r_regionkey, {defect_modulus}) = 0;

-- Some nations point at a region that does not exist
CREATE OR REPLACE TABLE bad_nation AS
SELECT n_nationkey, n_name,
       CASE WHEN MOD(n_nationkey, {defect_modulus}) = 0 THEN {orphan_key} ELSE n_regionkey END AS n_regionkey,
       n_comment
FROM nation;

-- Some customers have no name
CREATE OR REPLACE TABLE bad_customer AS
SELECT c_custkey,
       CASE WHEN MOD(c_custkey, {defect_modulus}) = 0 THEN NULL ELSE c_name END AS c_name,
       c_address, c_nationkey, c_phone, c_acctbal, c_mktsegment, c_comment
FROM customer;

-- Some suppliers point at a nation that does not exist
CREATE OR REPLACE TABLE bad_supplier AS
SELECT s_suppkey, s_name, s_address,
       CASE WHEN MOD(s_suppkey, {defect_modulus}) = 0 THEN {orphan_key} ELSE s_nationkey END AS s_nationkey,
       s_phone, s_acctbal, s_comment
FROM supplier;

-- Some parts have a negative retail price
CREATE OR REPLACE TABLE bad_part AS
SELECT p_partkey, p_name, p_mfgr, p_brand, p_type, p_size, p_container,
       CASE WHEN MOD(p_partkey, {defect_modulus}) = 0 THEN -p_retailprice ELSE p_retailprice END AS p_retailprice,
       p_comment
FROM part;

-- Some part/supplier pairs appear twice. A partsupp row is keyed by the pair, but the defect keys
-- off ps_partkey alone: every supplier of a corrupt part is duplicated, which is one predicate
-- rather than one per key column.
CREATE OR REPLACE TABLE bad_partsupp AS
SELECT * FROM partsupp
UNION ALL
SELECT * FROM partsupp WHERE MOD(ps_partkey, {defect_modulus}) = 0;

-- Some orders have no customer
CREATE OR REPLACE TABLE bad_orders AS
SELECT o_orderkey,
       CASE WHEN MOD(o_orderkey, {defect_modulus}) = 0 THEN NULL ELSE o_custkey END AS o_custkey,
       o_orderstatus, o_totalprice, o_orderdate, o_orderpriority, o_clerk, o_shippriority, o_comment
FROM orders;

-- Some line items have a negative quantity. A line is keyed by its order and line number, and the
-- defect keys off l_orderkey: every line of a corrupt order goes negative, which keeps this the
-- same rule bad_orders runs.
CREATE OR REPLACE TABLE bad_lineitem AS
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber,
       CASE WHEN MOD(l_orderkey, {defect_modulus}) = 0 THEN -l_quantity ELSE l_quantity END AS l_quantity,
       l_extendedprice, l_discount, l_tax, l_returnflag, l_linestatus,
       l_shipdate, l_commitdate, l_receiptdate, l_shipinstruct, l_shipmode, l_comment
FROM lineitem
