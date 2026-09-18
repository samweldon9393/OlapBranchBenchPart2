{{ config(tags=['de_fixture']) }}

-- Raw TPC-H naming, "totalprice" inclusive of tax, and ~1% of rows repeated verbatim
SELECT order_key AS o_orderkey, cust_key AS o_custkey, order_date AS o_orderdate,
       loaded_price AS o_totalprice, tax_amount AS o_tax
FROM {{ ref('order_facts') }} WHERE feed = 'asia'
UNION ALL
SELECT order_key, cust_key, order_date, loaded_price, tax_amount
FROM {{ ref('order_facts') }} WHERE feed = 'asia' AND is_dup_seed
