{{ config(tags=['fix_probe', 'fix_repair']) }}

{% call check('revenue') %}
WITH mart AS (
         SELECT nation_key, SUM(revenue) AS revenue FROM {{ ref('revenue_mart') }}
         WHERE batch_id >= {{ var('judged_batch') }} GROUP BY nation_key
     ),
     gaps AS (
         SELECT abs(coalesce(m.revenue, 0) - coalesce(r.revenue, 0)) AS gap
         FROM mart m FULL OUTER JOIN {{ ref('revenue_recheck') }} r ON m.nation_key = r.nation_key
     )
SELECT coalesce(max(gap), 0) = 0 AS ok FROM gaps
{% endcall %}
