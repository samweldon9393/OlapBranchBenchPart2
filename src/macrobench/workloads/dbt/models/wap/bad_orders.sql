{{ config(tags=['wap_fixture']) }}

-- Some orders have no customer
SELECT o_orderkey,
       CASE WHEN MOD(o_orderkey, {{ var('defect_modulus', 97) }}) = 0 THEN NULL ELSE o_custkey END AS o_custkey,
       o_orderstatus, o_totalprice, o_orderdate, o_orderpriority, o_clerk, o_shippriority, o_comment
FROM {{ source('branch', 'orders') }}
