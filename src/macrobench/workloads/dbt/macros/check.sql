{#
    A step's check, as a dbt test: the SQL inside the call returns one row with a boolean `ok`, the
    same SQL the plain backends run, and the test fails on that row unless it is true — a null `ok`
    fails too, as it does there.

    Every test a build carries runs with it, but only the checks the driver says apply to this step
    judge anything. The rest compile to a query that returns nothing and so pass, the same way a
    Bauplan expectation passes when its id is not among the ones it was handed.
#}

{% macro check(id) %}
{% if id in var('checks', '').split(',') %}
SELECT ok FROM (
{{ caller() }}
) audited
WHERE NOT coalesce(ok, FALSE)
{% else %}
SELECT TRUE AS ok WHERE 1 = 0
{% endif %}
{% endmacro %}
