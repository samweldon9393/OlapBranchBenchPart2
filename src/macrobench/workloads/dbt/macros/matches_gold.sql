{#
    Whether a data engineering model reproduces its gold table exactly: the same comparison the
    workload's SQL makes for the plain backends, and the Bauplan pipeline's expectations make in
    pyarrow. Money is cast to a common precision and a missing tax to a sentinel before comparing,
    and the row counts are compared too, since a set difference hides duplicates.
#}

{% macro staged_columns() %}
    order_key, cust_key, order_date,
    CAST(net_price AS DECIMAL(18,2)) AS net_price,
    coalesce(CAST(tax_amount AS DECIMAL(18,2)), CAST(-1 AS DECIMAL(18,2))) AS tax_amount
{% endmacro %}

{% macro revenue_columns() %}
    nation_name,
    CAST(order_quarter AS DATE) AS order_quarter,
    CAST(net_revenue AS DECIMAL(38,2)) AS net_revenue,
    coalesce(CAST(tax_amount AS DECIMAL(38,2)), CAST(-1 AS DECIMAL(38,2))) AS tax_amount,
    order_count
{% endmacro %}

{% macro matches_gold(columns, actual, expected) %}
WITH expected AS (SELECT {{ columns }} FROM {{ expected }}),
     actual AS (SELECT {{ columns }} FROM {{ actual }}),
     missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
     unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected),
     summary AS (
         SELECT (SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected) AS diff,
                (SELECT count(*) FROM actual) AS n_actual,
                (SELECT count(*) FROM expected) AS n_expected
     )
SELECT diff = 0 AND n_actual = n_expected AS ok FROM summary
{% endmacro %}
