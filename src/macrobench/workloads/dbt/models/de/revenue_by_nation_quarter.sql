{{ config(tags=['de_pipeline']) }}

{#- The broken variant buckets by year, collapsing four quarters into a single row -#}
{% set bucket = 'year' if var('variant_revenue_by_nation_quarter', 'broken') == 'broken' else 'quarter' %}

-- Nation is not carried on the feeds, so the union is joined back to the dimension tables
SELECT n.n_name AS nation_name,
       DATE_TRUNC('{{ bucket }}', u.order_date) AS order_quarter,
       CAST(SUM(u.net_price) AS DECIMAL(38, 2)) AS net_revenue,
       CAST(SUM(u.tax_amount) AS DECIMAL(38, 2)) AS tax_amount,
       COUNT(*) AS order_count
FROM {{ ref('orders_unified') }} u
JOIN {{ source('branch', 'customer') }} c ON c.c_custkey = u.cust_key
JOIN {{ source('branch', 'nation') }} n ON n.n_nationkey = c.c_nationkey
GROUP BY 1, 2
