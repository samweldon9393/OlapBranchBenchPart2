{{ config(tags=['de_pipeline']) }}

{% call check('stg_asia.matches_gold') %}
{{ matches_gold(staged_columns(), ref('stg_asia'), ref('gold_orders_unified') ~ " WHERE source = 'asia'") }}
{% endcall %}
