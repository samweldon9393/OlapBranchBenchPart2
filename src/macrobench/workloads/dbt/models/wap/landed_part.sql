{{ config(tags=['landed_part']) }}

-- Ingest part from whichever copy this step drew, bringing any negative price back positive.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
--
-- Columns are listed rather than starred-with-a-replacement because the two engines spell that
-- differently; naming them works on both and pins the column order besides.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_part') %}
{% else %}
    {% set source_table = source('branch', 'part') %}
{% endif %}

SELECT p_partkey, p_name, p_mfgr, p_brand, p_type, p_size, p_container,
       ABS(p_retailprice) AS p_retailprice, p_comment
FROM {{ source_table }}
