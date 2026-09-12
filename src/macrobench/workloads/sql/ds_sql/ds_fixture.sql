-- The data science fixture: the procedure every attempt calls, and the feature catalogue.
--
-- The procedure is created here, once, in untimed setup. A database clone carries its procedures
-- with it, at any depth, so every branch can call it without paying to recreate it — which would
-- otherwise cost several seconds a step and swamp what the step is meant to measure.
--
-- The work runs server-side as Snowpark Python: the join and projections are DataFrame calls that
-- Snowflake compiles and executes in the warehouse, so no data leaves it.
CREATE OR REPLACE PROCEDURE ds_build(features STRING, model STRING, score FLOAT)
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
    candidates = {
        "ship_delay": F.datediff("day", orders["O_ORDERDATE"], lineitem["L_SHIPDATE"]),
        "quantity": lineitem["L_QUANTITY"],
        "discount": lineitem["L_DISCOUNT"],
        "priority": F.substring(orders["O_ORDERPRIORITY"], 1, 1).cast("int"),
    }
    columns = [lineitem["L_ORDERKEY"].alias("order_key")]
    columns += [candidates[feature].alias(feature) for feature in features.split(",")]
    columns.append((lineitem["L_RECEIPTDATE"] > lineitem["L_COMMITDATE"]).alias("late"))
    joined.select(columns).write.save_as_table("ds_features", mode="overwrite")
    session.create_dataframe(
        [[features, model, score]], schema=["features", "model", "score"]
    ).write.save_as_table("ds_metrics", mode="overwrite")
    return "ok"
$$;

-- The catalogue of candidate features every branch draws from, with what each is built from
CREATE OR REPLACE TABLE ds_candidates AS
SELECT column1 AS feature, column2 AS source FROM VALUES
    ('ship_delay', 'days from o_orderdate to l_shipdate'),
    ('quantity', 'l_quantity'),
    ('discount', 'l_discount'),
    ('priority', 'leading digit of o_orderpriority')
