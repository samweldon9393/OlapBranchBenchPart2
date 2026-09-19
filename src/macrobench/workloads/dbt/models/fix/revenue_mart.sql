{{ config(
    materialized='incremental',
    incremental_strategy='append',
    on_schema_change='fail',
    tags=['fix_fixture', 'fix_commit', 'fix_repair'],
) }}

{#-
    Revenue per supplier nation per batch: the mart the workload's whole story is about overstating.

    Each build aggregates only the batches it just landed, because the model appends to what is
    already there rather than rebuilding it.
-#}

{% set build = var('build', 'fix_fixture') %}

SELECT s.s_nationkey AS nation_key, l.batch_id,
       SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM {{ ref('li_clean') }} l
JOIN {{ source('branch', 'supplier') }} s ON l.l_suppkey = s.s_suppkey
{% if build == 'fix_commit' %}
WHERE l.batch_id = {{ var('batch') }}
{% elif build == 'fix_repair' %}
WHERE l.batch_id >= {{ var('culprit') }}
{% endif %}
GROUP BY s.s_nationkey, l.batch_id
