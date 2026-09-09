-- Every order, tagged with the batch it arrives in.
--
-- This model is deliberately not materialized: it is a transient parent the models in models.py
-- read from, so the branch ends up holding only the two fixture tables.
--
-- The batch count is 61 rather than a round 64 because the TPC-H order key generator only uses the
-- first 8 keys of every 32, so any modulus sharing a factor with 32 leaves most batches empty --
-- `% 64` fills only 16 of its 64 ids, and an empty batch would make the audits pass trivially, a
-- duplicated empty batch included. 61 is prime, so every id is used and the batches come out within
-- a few rows of the same size.
SELECT
    o_orderkey AS order_key,
    o_custkey AS cust_key,
    o_orderdate AS order_date,
    o_totalprice AS total_price,
    o_orderkey % 61 AS batch_id
FROM orders
