{{ config(tags=['de_pipeline']) }}

{% call check('orders_unified.matches_gold') %}
{{ matches_gold(staged_columns() ~ ', source', ref('orders_unified'), ref('gold_orders_unified')) }}
{% endcall %}
