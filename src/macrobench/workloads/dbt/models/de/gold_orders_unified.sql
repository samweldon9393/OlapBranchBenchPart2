{{ config(tags=['de_fixture']) }}

-- What the unified intermediate should hold: one row per order, tagged by source. Only europe and
-- asia report tax, so it is null for americas rather than a silent zero.
SELECT order_key, cust_key, order_date, net_price, gold_tax_amount AS tax_amount, feed AS source
FROM {{ ref('order_facts') }}
