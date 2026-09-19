{{ config(tags=['fix_probe', 'fix_repair']) }}

{#- What each order's line count should be, over the same months. -#}

SELECT l_orderkey AS order_key, count(*) AS line_count
FROM {{ source('branch', 'lineitem') }}
WHERE l_shipdate >= CAST('{{ var('judged_from') }}' AS DATE)
  AND l_shipdate < CAST('{{ var('loaded_end') }}' AS DATE)
GROUP BY l_orderkey
