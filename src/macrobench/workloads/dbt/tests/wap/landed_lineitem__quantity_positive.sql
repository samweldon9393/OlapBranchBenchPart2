{{ config(tags=['landed_lineitem']) }}

{% call check('landed_lineitem.quantity_positive') %}
SELECT count(*) = 0 AS ok FROM {{ ref('landed_lineitem') }} WHERE l_quantity < 0
{% endcall %}
