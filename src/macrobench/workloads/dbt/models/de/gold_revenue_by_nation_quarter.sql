{{ config(tags=['de_fixture']) }}

-- What the revenue mart should hold, computed from the untouched tables rather than from the feeds
SELECT nation_name, order_quarter,
       CAST(SUM(net_price) AS DECIMAL(38, 2)) AS net_revenue,
       CAST(SUM(gold_tax_amount) AS DECIMAL(38, 2)) AS tax_amount,
       COUNT(*) AS order_count
FROM {{ ref('order_facts') }}
GROUP BY nation_name, order_quarter
