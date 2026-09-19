{{ config(tags=['fix_probe', 'fix_repair']) }}

{#-
    What the mart's revenue should be, recomputed from source over the months being judged.

    The window is a parameter rather than something read back off the tables: the workload made the
    commits, so it knows where the loading got to, and every backend is handed the same window —
    everything a probed state had loaded, or the months a repair replayed.
-#}

SELECT s.s_nationkey AS nation_key,
       SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM {{ source('branch', 'lineitem') }} l
JOIN {{ source('branch', 'supplier') }} s ON l.l_suppkey = s.s_suppkey
WHERE l.l_shipdate >= CAST('{{ var('judged_from') }}' AS DATE)
  AND l.l_shipdate < CAST('{{ var('loaded_end') }}' AS DATE)
GROUP BY s.s_nationkey
