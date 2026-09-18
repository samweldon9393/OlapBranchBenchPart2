{{ config(tags=['ds_fixture']) }}

{#-
    The catalogue of candidate features every branch draws from, with what each is built from.

    Written as a union of literal rows rather than a VALUES list, whose column names each platform
    spells its own way — the project is one project, and only the Snowflake target ever runs this.
-#}

SELECT 'ship_delay' AS feature, 'days from o_orderdate to l_shipdate' AS source
UNION ALL SELECT 'quantity', 'l_quantity'
UNION ALL SELECT 'discount', 'l_discount'
UNION ALL SELECT 'priority', 'leading digit of o_orderpriority'
