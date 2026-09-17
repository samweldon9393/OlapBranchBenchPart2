{{ config(tags=['landed_region']) }}

-- Ingest region from whichever copy this step drew, then repair whatever the audit would object to.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
--
-- Which copy is a Jinja choice rather than a second model: two models cannot write the same table,
-- and the Bauplan side needs a project per variant only because its SQL models do not template.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_region') %}
{% else %}
    {% set source_table = source('branch', 'region') %}
{% endif %}

SELECT DISTINCT * FROM {{ source_table }}
