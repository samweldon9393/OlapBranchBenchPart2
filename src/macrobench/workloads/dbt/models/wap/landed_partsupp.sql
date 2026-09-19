{{ config(tags=['landed_partsupp']) }}

-- Ingest partsupp from whichever copy this step drew, collapsing repeated rows.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_partsupp') %}
{% else %}
    {% set source_table = source('branch', 'partsupp') %}
{% endif %}

SELECT DISTINCT * FROM {{ source_table }}
