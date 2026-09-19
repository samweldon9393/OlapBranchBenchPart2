{{ config(tags=['landed_nation']) }}

{% call check('landed_nation.region_exists') %}
SELECT count(*) = 0 AS ok FROM {{ ref('landed_nation') }} n
LEFT JOIN {{ source('branch', 'region') }} r ON r.r_regionkey = n.n_regionkey WHERE r.r_regionkey IS NULL
{% endcall %}
