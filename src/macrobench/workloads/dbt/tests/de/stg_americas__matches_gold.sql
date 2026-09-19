{{ config(tags=['de_pipeline']) }}

{% call check('stg_americas.matches_gold') %}
{{ matches_gold(staged_columns(), ref('stg_americas'), ref('gold_orders_unified') ~ " WHERE source = 'americas'") }}
{% endcall %}
