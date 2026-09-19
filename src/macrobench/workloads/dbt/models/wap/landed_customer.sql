{{ config(tags=['landed_customer']) }}

-- Ingest customer from whichever copy this step drew, dropping rows with no name.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_customer') %}
{% else %}
    {% set source_table = source('branch', 'customer') %}
{% endif %}

SELECT * FROM {{ source_table }} WHERE c_name IS NOT NULL
