{{ config(tags=['fix_repair']) }}

{#-
    How many rows outside the culprit this repair rewrote, which is how the fixes are ranked.

    Every row in scope is rewritten, as a partition rewrite does, so the rows disturbed are the ones
    in scope belonging to batches the culprit never touched.
-#}

SELECT '{{ var('strategy') }}' AS repair_strategy,
       '{{ var('scope') }}' AS repair_scope,
       count(*) AS disturbed_rows,
       -count(*) AS score
FROM {{ ref('li_raw') }}
WHERE batch_id BETWEEN {{ var('scope_lo') }} AND {{ var('scope_hi') }}
  AND batch_id <> {{ var('culprit') }}
