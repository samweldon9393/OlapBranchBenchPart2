{{ config(tags=['orders_unified']) }}

{#-
    The three staging models are built by earlier steps, on the branch this one runs on, so `ref`
    names them without this invocation building them.
-#}

SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM {{ ref('stg_americas') }}
UNION ALL
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM {{ ref('stg_europe') }}

{% if var('variant', 'correct') != 'broken' %}
{#- The broken variant drops the asia feed, so a fifth of the orders never make it into the union -#}
UNION ALL
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM {{ ref('stg_asia') }}
{% endif %}
