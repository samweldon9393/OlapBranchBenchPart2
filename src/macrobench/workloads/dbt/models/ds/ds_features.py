"""One candidate's feature table, built server-side as Snowpark Python.

This is the model the workload exists to compare: dbt ships the code with the run and Snowflake
executes it in the warehouse as a stored procedure, which is what the hand-written backend does with
an anonymous procedure and what Bauplan does with a project of Python models. No data leaves the
warehouse either way.

A Python model cannot be templated, so which features to build arrives as the model's `meta`, which
the project's YAML fills in from the run's vars.
"""

from snowflake.snowpark import functions as F


def model(dbt, session):  # noqa: ANN001, ANN201 - dbt calls this; its arguments are not ours to annotate
    dbt.config(materialized="table")

    lineitem = dbt.source("branch", "lineitem")
    orders = dbt.source("branch", "orders")
    joined = lineitem.join(orders, lineitem["L_ORDERKEY"] == orders["O_ORDERKEY"])
    candidates = {
        "ship_delay": F.datediff("day", orders["O_ORDERDATE"], lineitem["L_SHIPDATE"]),
        "quantity": lineitem["L_QUANTITY"],
        "discount": lineitem["L_DISCOUNT"],
        "priority": F.substring(orders["O_ORDERPRIORITY"], 1, 1).cast("int"),
    }
    columns = [lineitem["L_ORDERKEY"].alias("order_key")]
    columns += [candidates[feature].alias(feature) for feature in dbt.config.meta_get("features").split(",")]
    columns.append((lineitem["L_RECEIPTDATE"] > lineitem["L_COMMITDATE"]).alias("late"))
    return joined.select(columns)
