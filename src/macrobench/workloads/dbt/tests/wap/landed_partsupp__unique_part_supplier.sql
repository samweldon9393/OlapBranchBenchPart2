{{ config(tags=['landed_partsupp']) }}

{% call check('landed_partsupp.unique_part_supplier') %}
SELECT (SELECT count(*) FROM {{ ref('landed_partsupp') }})
     = (SELECT count(*) FROM (SELECT DISTINCT ps_partkey, ps_suppkey FROM {{ ref('landed_partsupp') }}) pairs) AS ok
{% endcall %}
