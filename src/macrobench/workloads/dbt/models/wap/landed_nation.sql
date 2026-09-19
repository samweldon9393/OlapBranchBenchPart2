{{ config(tags=['landed_nation']) }}

-- Ingest nation from whichever copy this step drew, dropping rows whose region does not exist.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_nation') %}
{% else %}
    {% set source_table = source('branch', 'nation') %}
{% endif %}

SELECT * FROM {{ source_table }}
WHERE n_regionkey IN (SELECT r_regionkey FROM {{ source('branch', 'region') }})
