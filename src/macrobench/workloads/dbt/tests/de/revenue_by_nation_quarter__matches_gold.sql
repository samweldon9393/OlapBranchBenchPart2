{{ config(tags=['de_pipeline']) }}

{% call check('revenue_by_nation_quarter.matches_gold') %}
{{ matches_gold(revenue_columns(), ref('revenue_by_nation_quarter'), ref('gold_revenue_by_nation_quarter')) }}
{% endcall %}
