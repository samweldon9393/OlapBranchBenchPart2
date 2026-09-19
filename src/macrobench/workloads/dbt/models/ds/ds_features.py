"""One candidate's feature table, built server-side as Snowpark Python — the first stage of the pipeline.

dbt ships the code with the run and Snowflake executes it in the warehouse as a stored procedure,
which is what the hand-written backend does with an anonymous procedure and what Bauplan does with a
project of Python models. No data leaves the warehouse either way.

A Python model cannot be templated, so which features to build arrives as the model's `meta`, which
the project's YAML fills in from the run's vars. Features are stored as doubles, which is what the
fitting downstream reads them as.
"""

from snowflake.snowpark import functions as F
from snowflake.snowpark.types import DoubleType


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
    names = dbt.config.meta_get("features").split(",")
    columns = [lineitem["L_ORDERKEY"].alias("order_key")]
    columns += [candidates[name].cast(DoubleType()).alias(name) for name in names]
    columns.append((lineitem["L_RECEIPTDATE"] > lineitem["L_COMMITDATE"]).alias("late"))
    return joined.select(columns)
