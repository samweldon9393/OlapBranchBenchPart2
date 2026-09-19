{{ config(tags=['wap_fixture']) }}

-- One region appears twice, so r_regionkey is no longer unique.
--
-- A row is corrupt when its primary key is a multiple of the defect modulus, which is the rule the
-- Bauplan project runs too: the same rows are corrupted whichever backend builds the fixture, so the
-- repairs the steps have to do are comparable across them.
SELECT * FROM {{ source('branch', 'region') }}
UNION ALL
SELECT * FROM {{ source('branch', 'region') }} WHERE MOD(r_regionkey, {{ var('defect_modulus', 97) }}) = 0
