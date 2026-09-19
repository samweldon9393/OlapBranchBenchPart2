{{ config(tags=['landed_orders']) }}

{% call check('landed_orders.customer_present') %}
SELECT count(*) = 0 AS ok FROM {{ ref('landed_orders') }} WHERE o_custkey IS NULL
{% endcall %}
