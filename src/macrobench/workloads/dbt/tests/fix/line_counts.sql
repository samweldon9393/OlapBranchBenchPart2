{{ config(tags=['fix_probe', 'fix_repair']) }}

{% call check('line_counts') %}
WITH actual AS (
         SELECT l_orderkey AS order_key, count(*) AS line_count FROM {{ ref('li_clean') }}
         WHERE batch_id >= {{ var('judged_batch') }} GROUP BY l_orderkey
     ),
     mismatched AS (
         SELECT 1 AS mismatch
         FROM actual a FULL OUTER JOIN {{ ref('lines_recheck') }} e ON a.order_key = e.order_key
         WHERE a.line_count IS NULL OR e.line_count IS NULL OR a.line_count <> e.line_count
     )
SELECT count(*) = 0 AS ok FROM mismatched
{% endcall %}
