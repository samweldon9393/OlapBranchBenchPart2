{{ config(tags=['landed_supplier']) }}

{% call check('landed_supplier.nation_exists') %}
SELECT count(*) = 0 AS ok FROM {{ ref('landed_supplier') }} s
LEFT JOIN {{ source('branch', 'nation') }} n ON n.n_nationkey = s.s_nationkey WHERE n.n_nationkey IS NULL
{% endcall %}
