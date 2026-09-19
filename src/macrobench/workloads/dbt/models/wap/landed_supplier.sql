{{ config(tags=['landed_supplier']) }}

-- Ingest supplier from whichever copy this step drew, dropping rows whose nation does not exist.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_supplier') %}
{% else %}
    {% set source_table = source('branch', 'supplier') %}
{% endif %}

SELECT * FROM {{ source_table }}
WHERE s_nationkey IN (SELECT n_nationkey FROM {{ source('branch', 'nation') }})
