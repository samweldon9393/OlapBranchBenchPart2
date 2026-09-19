{{ config(tags=['landed_region']) }}

{% call check('landed_region.unique_region_key') %}
SELECT count(*) = count(DISTINCT r_regionkey) AS ok FROM {{ ref('landed_region') }}
{% endcall %}
