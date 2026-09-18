{{ config(
    materialized='incremental',
    incremental_strategy='append',
    on_schema_change='fail',
    tags=['fix_fixture', 'fix_commit', 'fix_repair'],
) }}

{#-
    Every batch of lineitems as it was loaded, whichever build is doing the loading.

    A batch is one month by ship date, numbered from the first year the workload counts from. The
    fixture lays down the base months and is invoked with --full-refresh; a commit adds one month;
    a repair replays the culprit's month and every one after it. All three only ever add rows, which
    is what lets the history be branched from at any point.

    Which build is running is a Jinja choice, so only the arm that was asked for compiles at all —
    the `if` the Bauplan project writes in Python, rather than a guard left for the engine to fold.
-#}

{% set build = var('build', 'fix_fixture') %}
{% set batched %}
    CAST((EXTRACT(YEAR FROM l_shipdate) - {{ var('first_year', 1992) }}) * 12
         + EXTRACT(MONTH FROM l_shipdate) - 1 AS INT)
{% endset %}

{#-
    A build that knows its batch says so as a literal, and a literal carries only as much precision
    as its digits need. dbt compares the column types of what it is about to append against the table
    it is appending to, so a bare 24 is a schema change where the same INSERT by hand would coerce.
    Every batch_id is therefore cast, whichever build wrote it.
-#}

{% if build == 'fix_fixture' %}

SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       {{ batched }} AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_shipdate < CAST('{{ var('base_end') }}' AS DATE)

{% elif build == 'fix_commit' %}

{#- The bad commit loads its batch the run's wrong way; every other commit loads it cleanly -#}
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice,
       {% if var('bad') == '1' and var('kind') == 'discount' %}
       CASE WHEN l_shipdate < CAST('{{ var('cut') }}' AS DATE) THEN 0 ELSE l_discount END AS l_discount,
       {% else %}
       l_discount,
       {% endif %}
       l_shipdate, CAST({{ var('batch') }} AS INT) AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_shipdate >= CAST('{{ var('start') }}' AS DATE) AND l_shipdate < CAST('{{ var('end') }}' AS DATE)

{% if var('bad') == '1' and var('kind') == 'duplicate' %}
UNION ALL
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST({{ var('batch') }} AS INT) AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_shipdate >= CAST('{{ var('start') }}' AS DATE) AND l_shipdate < CAST('{{ var('end') }}' AS DATE)
{% endif %}

{% if var('bad') == '1' and var('kind') == 'unbooked' %}
UNION ALL
{# Lines for orders that were never booked: each order's first line again, under a key no order has #}
SELECT -l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST({{ var('batch') }} AS INT) AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_linenumber = 1
  AND l_shipdate >= CAST('{{ var('start') }}' AS DATE) AND l_shipdate < CAST('{{ var('end') }}' AS DATE)
{% endif %}

{% else %}

{#- The replay: each batch loaded exactly as its commit loaded it, the culprit's defect included -#}
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice,
       {% if var('kind') == 'discount' %}
       CASE WHEN batch_id = {{ var('culprit') }} AND l_shipdate < CAST('{{ var('cut') }}' AS DATE)
            THEN 0 ELSE l_discount END AS l_discount,
       {% else %}
       l_discount,
       {% endif %}
       l_shipdate, batch_id
FROM (
    SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
           {{ batched }} AS batch_id
    FROM {{ source('branch', 'lineitem') }}
    WHERE l_shipdate >= CAST('{{ var('start') }}' AS DATE) AND l_shipdate < CAST('{{ var('end') }}' AS DATE)
) replayed

{% if var('kind') == 'duplicate' %}
UNION ALL
{# The culprit's batch is the first month replayed, so its defects are a plain date range #}
SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST({{ var('culprit') }} AS INT) AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_shipdate >= CAST('{{ var('start') }}' AS DATE)
  AND l_shipdate < CAST('{{ var('culprit_end') }}' AS DATE)
{% endif %}

{% if var('kind') == 'unbooked' %}
UNION ALL
SELECT -l_orderkey, l_partkey, l_suppkey, l_linenumber, l_extendedprice, l_discount, l_shipdate,
       CAST({{ var('culprit') }} AS INT) AS batch_id
FROM {{ source('branch', 'lineitem') }}
WHERE l_linenumber = 1
  AND l_shipdate >= CAST('{{ var('start') }}' AS DATE)
  AND l_shipdate < CAST('{{ var('culprit_end') }}' AS DATE)
{% endif %}

{% endif %}
