{{ config(tags=['wap_fixture']) }}

-- Some customers have no name
SELECT c_custkey,
       CASE WHEN MOD(c_custkey, {{ var('defect_modulus', 97) }}) = 0 THEN NULL ELSE c_name END AS c_name,
       c_address, c_nationkey, c_phone, c_acctbal, c_mktsegment, c_comment
FROM {{ source('branch', 'customer') }}
