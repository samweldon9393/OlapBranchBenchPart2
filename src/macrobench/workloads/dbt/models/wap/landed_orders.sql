{{ config(tags=['landed_orders']) }}

-- Ingest orders from whichever copy this step drew, dropping rows with no customer.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_orders') %}
{% else %}
    {% set source_table = source('branch', 'orders') %}
{% endif %}

SELECT * FROM {{ source_table }} WHERE o_custkey IS NOT NULL
