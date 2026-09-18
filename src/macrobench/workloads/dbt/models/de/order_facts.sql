{{ config(tags=['de_fixture']) }}

{#-
    The canonical shape every feed is a distorted view of, and the only thing the fixture's other
    five models read.

    It is scaffolding rather than a fixture table, so the project drops it once the fixture has run
    (the on-run-end hook in dbt_project.yml) and the branch is left holding the five tables the
    workload names. Materializing it is what keeps it cheap: as an ephemeral model its five-table
    join would be inlined into each of the five models below and computed five times over.

    The money columns are rounded to cents before anything is derived from them, so the per-feed
    encodings are exact rearrangements rather than lossy ones: discount_amount and loaded_price both
    recover net_price to the cent, which is what lets a pipeline's output be compared to gold for
    equality rather than within a tolerance.

    TPC-H has five regions and we want three feeds, so the split is the usual AMER/EMEA/APAC one:
    the "europe" feed is really EMEA and also carries AFRICA and MIDDLE EAST.
-#}

SELECT
    o.o_orderkey AS order_key,
    o.o_custkey AS cust_key,
    o.o_orderdate AS order_date,
    CAST(o.o_orderdate AS STRING) AS order_date_str,
    n.n_name AS nation_name,
    DATE_TRUNC('quarter', o.o_orderdate) AS order_quarter,
    CASE r.r_name
        WHEN 'AMERICA' THEN 'americas'
        WHEN 'ASIA' THEN 'asia'
        ELSE 'europe'
    END AS feed,
    MOD(o.o_orderkey, 97) = 0 AS is_dup_seed,
    la.gross_price,
    la.gross_price - la.net_price AS discount_amount,
    la.net_price,
    la.tax_amount,
    la.net_price + la.tax_amount AS loaded_price,
    CASE WHEN r.r_name = 'AMERICA' THEN NULL ELSE la.tax_amount END AS gold_tax_amount
FROM {{ source('branch', 'orders') }} o
JOIN (
    SELECT
        l_orderkey,
        CAST(ROUND(SUM(l_extendedprice), 2) AS DECIMAL(18, 2)) AS gross_price,
        CAST(ROUND(SUM(l_extendedprice * (1 - l_discount)), 2) AS DECIMAL(18, 2)) AS net_price,
        CAST(ROUND(SUM(l_extendedprice * (1 - l_discount) * l_tax), 2) AS DECIMAL(18, 2)) AS tax_amount
    FROM {{ source('branch', 'lineitem') }}
    GROUP BY l_orderkey
) la ON la.l_orderkey = o.o_orderkey
JOIN {{ source('branch', 'customer') }} cu ON cu.c_custkey = o.o_custkey
JOIN {{ source('branch', 'nation') }} n ON n.n_nationkey = cu.c_nationkey
JOIN {{ source('branch', 'region') }} r ON r.r_regionkey = n.n_regionkey
