{{ config(tags=['wap_fixture']) }}

-- Some nations point at a region that does not exist
SELECT n_nationkey, n_name,
       CASE WHEN MOD(n_nationkey, {{ var('defect_modulus', 97) }}) = 0
            THEN {{ var('orphan_key', 999) }} ELSE n_regionkey END AS n_regionkey,
       n_comment
FROM {{ source('branch', 'nation') }}
