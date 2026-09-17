{{ config(tags=['wap_fixture']) }}

-- Some part/supplier pairs appear twice. A partsupp row is keyed by the pair, but the defect keys
-- off ps_partkey alone: every supplier of a corrupt part is duplicated, which is one predicate
-- rather than one per key column.
SELECT * FROM {{ source('branch', 'partsupp') }}
UNION ALL
SELECT * FROM {{ source('branch', 'partsupp') }} WHERE MOD(ps_partkey, {{ var('defect_modulus', 97) }}) = 0
