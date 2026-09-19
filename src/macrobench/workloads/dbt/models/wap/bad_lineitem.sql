{{ config(tags=['wap_fixture']) }}

-- Some line items have a negative quantity. A line is keyed by its order and line number, and the
-- defect keys off l_orderkey: every line of a corrupt order goes negative, which keeps this the same
-- rule bad_orders runs.
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber,
       CASE WHEN MOD(l_orderkey, {{ var('defect_modulus', 97) }}) = 0
            THEN -l_quantity ELSE l_quantity END AS l_quantity,
       l_extendedprice, l_discount, l_tax, l_returnflag, l_linestatus,
       l_shipdate, l_commitdate, l_receiptdate, l_shipinstruct, l_shipmode, l_comment
FROM {{ source('branch', 'lineitem') }}
