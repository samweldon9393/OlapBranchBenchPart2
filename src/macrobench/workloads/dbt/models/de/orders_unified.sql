{{ config(tags=['de_pipeline']) }}

{#-
    The union of the three staging models the same run has just built: every step reruns the whole
    pipeline, so this reads whatever implementation of each the step's vars chose.
-#}

SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM {{ ref('stg_americas') }}
UNION ALL
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM {{ ref('stg_europe') }}

{% if var('variant_orders_unified', 'broken') != 'broken' %}
{#- The broken variant drops the asia feed, so a fifth of the orders never make it into the union -#}
UNION ALL
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM {{ ref('stg_asia') }}
{% endif %}
