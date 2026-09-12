-- One candidate's attempt: build its feature table and record its score, both on this branch.
-- Every attempt runs this; only the parameters differ.
--
-- The build is an anonymous procedure, so its code travels with every call and nothing is kept in
-- the database between them, the way a Bauplan run uploads its project each time. The work runs
-- server-side as Snowpark Python: the join and projections are DataFrame calls that Snowflake
-- compiles and executes in the warehouse, so no data leaves it.
--
-- The script is filled in with str.format, so the braces in the Python are doubled.
WITH ds_build AS PROCEDURE (features STRING, model STRING, score FLOAT)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
AS
$$
from snowflake.snowpark import functions as F


def run(session, features, model, score):
    lineitem = session.table("lineitem")
    orders = session.table("orders")
    joined = lineitem.join(orders, lineitem["L_ORDERKEY"] == orders["O_ORDERKEY"])
    candidates = {{
        "ship_delay": F.datediff("day", orders["O_ORDERDATE"], lineitem["L_SHIPDATE"]),
        "quantity": lineitem["L_QUANTITY"],
        "discount": lineitem["L_DISCOUNT"],
        "priority": F.substring(orders["O_ORDERPRIORITY"], 1, 1).cast("int"),
    }}
    columns = [lineitem["L_ORDERKEY"].alias("order_key")]
    columns += [candidates[feature].alias(feature) for feature in features.split(",")]
    columns.append((lineitem["L_RECEIPTDATE"] > lineitem["L_COMMITDATE"]).alias("late"))
    joined.select(columns).write.save_as_table("ds_features", mode="overwrite")
    session.create_dataframe(
        [[features, model, score]], schema=["features", "model", "score"]
    ).write.save_as_table("ds_metrics", mode="overwrite")
    return "ok"
$$
CALL ds_build('{features}', '{model}', {score})
