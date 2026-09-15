-- One repair: off the last good state, replay the culprit and every commit after it, fixing as it goes.
--
-- The replay loads each batch from source exactly as its commit did, the culprit's defect included,
-- and appends it to li_raw. Into li_clean it applies one strategy to the batches in scope and passes
-- the rest through as they were loaded:
--   dedupe     keep one copy of each line
--   rederive   load the batches again from source
--   filter     drop lines whose order, part or supplier does not exist
--   restore    take each line's discount from source
-- The mart and the recomputations are then rebuilt, and fix_metrics records how many rows outside
-- the culprit the strategy rewrote.
CREATE OR REPLACE TABLE replay_raw AS
WITH replayed AS (
    SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
           CAST((EXTRACT(YEAR FROM l_shipdate) - 1992) * 12 + EXTRACT(MONTH FROM l_shipdate) - 1 AS INT) AS batch_id
    FROM lineitem
    WHERE l_shipdate >= CAST('{start}' AS DATE) AND l_shipdate < CAST('{end}' AS DATE)
)
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice,
       CASE WHEN batch_id = {culprit} AND '{kind}' = 'discount' AND l_shipdate < CAST('{cut}' AS DATE)
            THEN 0 ELSE l_discount END AS l_discount,
       l_shipdate, batch_id
FROM replayed
UNION ALL
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, batch_id
FROM replayed
WHERE batch_id = {culprit} AND '{kind}' = 'duplicate'
UNION ALL
SELECT -l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, batch_id
FROM replayed
WHERE batch_id = {culprit} AND '{kind}' = 'unbooked' AND l_linenumber = 1;

INSERT INTO li_raw SELECT * FROM replay_raw;

INSERT INTO li_clean
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, batch_id
FROM replay_raw
WHERE batch_id < {scope_lo} OR batch_id > {scope_hi}
UNION ALL
SELECT DISTINCT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, batch_id
FROM replay_raw
WHERE '{strategy}' = 'dedupe' AND batch_id BETWEEN {scope_lo} AND {scope_hi}
UNION ALL
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST((EXTRACT(YEAR FROM l_shipdate) - 1992) * 12 + EXTRACT(MONTH FROM l_shipdate) - 1 AS INT)
FROM lineitem
WHERE '{strategy}' = 'rederive'
  AND l_shipdate >= CAST('{start}' AS DATE) AND l_shipdate < CAST('{scope_end}' AS DATE)
UNION ALL
SELECT r.l_orderkey, r.l_partkey, r.l_suppkey, r.l_linenumber, r.l_extendedprice, r.l_discount, r.l_shipdate,
       r.batch_id
FROM replay_raw r
JOIN orders o ON r.l_orderkey = o.o_orderkey
JOIN part p ON r.l_partkey = p.p_partkey
JOIN supplier s ON r.l_suppkey = s.s_suppkey
WHERE '{strategy}' = 'filter' AND r.batch_id BETWEEN {scope_lo} AND {scope_hi}
UNION ALL
SELECT r.l_orderkey, r.l_partkey, r.l_suppkey, r.l_linenumber, r.l_extendedprice,
       coalesce(s.l_discount, r.l_discount), r.l_shipdate, r.batch_id
FROM replay_raw r
LEFT JOIN lineitem s ON s.l_orderkey = r.l_orderkey AND s.l_linenumber = r.l_linenumber
WHERE '{strategy}' = 'restore' AND r.batch_id BETWEEN {scope_lo} AND {scope_hi};

INSERT INTO revenue_mart
SELECT s.s_nationkey, l.batch_id, SUM(l.l_extendedprice * (1 - l.l_discount))
FROM li_clean l JOIN supplier s ON l.l_suppkey = s.s_suppkey
WHERE l.batch_id >= {culprit}
GROUP BY s.s_nationkey, l.batch_id;

CREATE OR REPLACE TABLE revenue_recheck AS
SELECT s.s_nationkey AS nation_key, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM lineitem l JOIN supplier s ON l.l_suppkey = s.s_suppkey
WHERE l.l_shipdate <= (SELECT max(l_shipdate) FROM li_raw)
GROUP BY s.s_nationkey;

CREATE OR REPLACE TABLE lines_recheck AS
SELECT l_orderkey AS order_key, count(*) AS line_count
FROM lineitem
WHERE l_shipdate <= (SELECT max(l_shipdate) FROM li_raw)
GROUP BY l_orderkey;

-- Every row in scope is rewritten, as a partition rewrite does, so the rows disturbed are the ones
-- in scope that belong to batches the culprit never touched
CREATE OR REPLACE TABLE fix_metrics AS
SELECT '{strategy}' AS repair_strategy, '{scope}' AS repair_scope,
       count(*) AS disturbed_rows, -count(*) AS score
FROM replay_raw
WHERE batch_id BETWEEN {scope_lo} AND {scope_hi} AND batch_id <> {culprit};

DROP TABLE replay_raw
