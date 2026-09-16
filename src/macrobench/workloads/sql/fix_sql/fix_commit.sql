-- One commit on the root: append a month's batch to li_raw, li_clean and the mart.
--
-- The bad commit loads its batch the run's wrong way: twice over, with the discounts on its first
-- days dropped, or with lines for orders that were never booked. Every other commit loads its batch
-- cleanly. A commit only appends, so the state it leaves is exactly the tables as they then stood.
INSERT INTO li_raw
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice,
       CASE WHEN {bad} = 1 AND '{kind}' = 'discount' AND l_shipdate < CAST('{cut}' AS DATE)
            THEN 0 ELSE l_discount END,
       l_shipdate, {batch}
FROM lineitem
WHERE l_shipdate >= CAST('{start}' AS DATE) AND l_shipdate < CAST('{end}' AS DATE)
UNION ALL
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, {batch}
FROM lineitem
WHERE {bad} = 1 AND '{kind}' = 'duplicate'
  AND l_shipdate >= CAST('{start}' AS DATE) AND l_shipdate < CAST('{end}' AS DATE)
UNION ALL
SELECT -l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, {batch}
FROM lineitem
WHERE {bad} = 1 AND '{kind}' = 'unbooked' AND l_linenumber = 1
  AND l_shipdate >= CAST('{start}' AS DATE) AND l_shipdate < CAST('{end}' AS DATE);

INSERT INTO li_clean SELECT * FROM li_raw WHERE batch_id = {batch};

INSERT INTO revenue_mart
SELECT s.s_nationkey, l.batch_id, SUM(l.l_extendedprice * (1 - l.l_discount))
FROM li_clean l JOIN supplier s ON l.l_suppkey = s.s_suppkey
WHERE l.batch_id = {batch}
GROUP BY s.s_nationkey, l.batch_id
