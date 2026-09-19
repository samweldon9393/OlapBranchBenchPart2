{{ config(tags=['landed_customer']) }}

{% call check('landed_customer.name_present') %}
SELECT count(*) = 0 AS ok FROM {{ ref('landed_customer') }} WHERE c_name IS NULL
{% endcall %}
