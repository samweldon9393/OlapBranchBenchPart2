{{ config(
    materialized='incremental',
    incremental_strategy='append',
    on_schema_change='fail',
    tags=['fix_fixture', 'fix_commit', 'fix_repair'],
) }}

{#-
    What the mart reads. It matches li_raw until a repair makes them differ.

    The fixture and a commit take the rows as they were loaded; a repair applies one strategy to the
    batches in scope and passes the rest through. Reading li_raw rather than staging the replay
    somewhere of its own means dbt orders the two, which the hand-written script had to do itself.
-#}

{% set build = var('build', 'fix_fixture') %}
{% set columns %}
    l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate, batch_id
{% endset %}

{% if build == 'fix_fixture' %}

SELECT {{ columns }} FROM {{ ref('li_raw') }}

{% elif build == 'fix_commit' %}

SELECT {{ columns }} FROM {{ ref('li_raw') }} WHERE batch_id = {{ var('batch') }}

{% else %}

{#- Everything the replay added that the strategy does not touch -#}
SELECT {{ columns }}
FROM {{ ref('li_raw') }}
WHERE batch_id >= {{ var('culprit') }}
  AND (batch_id < {{ var('scope_lo') }} OR batch_id > {{ var('scope_hi') }})
UNION ALL

{% if var('strategy') == 'dedupe' %}
{#- Keep one copy of each line -#}
SELECT DISTINCT {{ columns }}
FROM {{ ref('li_raw') }}
WHERE batch_id BETWEEN {{ var('scope_lo') }} AND {{ var('scope_hi') }}

{% elif var('strategy') == 'rederive' %}
{#- Load the batches in scope again from source -#}
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST((EXTRACT(YEAR FROM l_shipdate) - {{ var('first_year', 1992) }}) * 12
            + EXTRACT(MONTH FROM l_shipdate) - 1 AS INT) AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_shipdate >= CAST('{{ var('start') }}' AS DATE)
  AND l_shipdate < CAST('{{ var('scope_end') }}' AS DATE)

{% elif var('strategy') == 'filter' %}
{#- Drop lines whose order, part or supplier does not exist -#}
SELECT {{ columns }}
FROM {{ ref('li_raw') }}
WHERE batch_id BETWEEN {{ var('scope_lo') }} AND {{ var('scope_hi') }}
  AND l_orderkey IN (SELECT o_orderkey FROM {{ source('branch', 'orders') }})
  AND l_partkey IN (SELECT p_partkey FROM {{ source('branch', 'part') }})
  AND l_suppkey IN (SELECT s_suppkey FROM {{ source('branch', 'supplier') }})

{% else %}
{#- Take each line's discount from source -#}
SELECT r.l_orderkey, r.l_partkey, r.l_suppkey, r.l_linenumber, r.l_extendedprice,
       coalesce(s.l_discount, r.l_discount) AS l_discount, r.l_shipdate, r.batch_id
FROM {{ ref('li_raw') }} r
LEFT JOIN {{ source('branch', 'lineitem') }} s
       ON s.l_orderkey = r.l_orderkey AND s.l_linenumber = r.l_linenumber
WHERE r.batch_id BETWEEN {{ var('scope_lo') }} AND {{ var('scope_hi') }}
{% endif %}

{% endif %}
