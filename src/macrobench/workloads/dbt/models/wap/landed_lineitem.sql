{{ config(tags=['landed_lineitem']) }}

-- Ingest lineitem from whichever copy this step drew, bringing any negative quantity back positive.
-- The repair runs either way because it is a no-op on input that has nothing wrong with it.
--
-- Columns are listed rather than starred-with-a-replacement because the two engines spell that
-- differently; naming them works on both and pins the column order besides.
{% if var('variant', 'correct') == 'broken' %}
    {% set source_table = ref('bad_lineitem') %}
{% else %}
    {% set source_table = source('branch', 'lineitem') %}
{% endif %}

SELECT l_orderkey, l_partkey, l_suppkey, l_linenumber, ABS(l_quantity) AS l_quantity,
       l_extendedprice, l_discount, l_tax, l_returnflag, l_linestatus,
       l_shipdate, l_commitdate, l_receiptdate, l_shipinstruct, l_shipmode, l_comment
FROM {{ source_table }}
