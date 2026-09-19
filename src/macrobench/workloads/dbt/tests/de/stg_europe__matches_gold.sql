{{ config(tags=['de_pipeline']) }}

{% call check('stg_europe.matches_gold') %}
{{ matches_gold(staged_columns(), ref('stg_europe'), ref('gold_orders_unified') ~ " WHERE source = 'europe'") }}
{% endcall %}
