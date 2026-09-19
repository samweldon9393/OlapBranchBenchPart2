{{ config(tags=['wap_fixture']) }}

-- Some suppliers point at a nation that does not exist
SELECT s_suppkey, s_name, s_address,
       CASE WHEN MOD(s_suppkey, {{ var('defect_modulus', 97) }}) = 0
            THEN {{ var('orphan_key', 999) }} ELSE s_nationkey END AS s_nationkey,
       s_phone, s_acctbal, s_comment
FROM {{ source('branch', 'supplier') }}
