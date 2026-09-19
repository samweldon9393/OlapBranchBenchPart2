{{ config(tags=['wap_fixture']) }}

-- Some parts have a negative retail price
SELECT p_partkey, p_name, p_mfgr, p_brand, p_type, p_size, p_container,
       CASE WHEN MOD(p_partkey, {{ var('defect_modulus', 97) }}) = 0
            THEN -p_retailprice ELSE p_retailprice END AS p_retailprice,
       p_comment
FROM {{ source('branch', 'part') }}
