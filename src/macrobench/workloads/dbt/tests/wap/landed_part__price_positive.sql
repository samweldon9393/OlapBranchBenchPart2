{{ config(tags=['landed_part']) }}

{% call check('landed_part.price_positive') %}
SELECT count(*) = 0 AS ok FROM {{ ref('landed_part') }} WHERE p_retailprice < 0
{% endcall %}
