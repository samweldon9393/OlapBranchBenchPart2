{{ config(tags=['fix_probe', 'fix_repair']) }}

{% call check('ref_integrity') %}
WITH judged AS (
    SELECT l_orderkey, l_partkey, l_suppkey FROM {{ ref('li_clean') }}
    WHERE batch_id >= {{ var('judged_batch') }}
)
SELECT (SELECT count(*) FROM judged l LEFT JOIN {{ source('branch', 'orders') }} o ON l.l_orderkey = o.o_orderkey
        WHERE o.o_orderkey IS NULL) = 0
   AND (SELECT count(*) FROM judged l LEFT JOIN {{ source('branch', 'part') }} p ON l.l_partkey = p.p_partkey
        WHERE p.p_partkey IS NULL) = 0
   AND (SELECT count(*) FROM judged l LEFT JOIN {{ source('branch', 'supplier') }} s ON l.l_suppkey = s.s_suppkey
        WHERE s.s_suppkey IS NULL) = 0 AS ok
{% endcall %}
