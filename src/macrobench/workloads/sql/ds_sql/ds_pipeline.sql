-- One candidate's attempt: build its features, fit a model to them, and score it on held-out rows,
-- all on this branch. Every attempt runs this; only the parameters differ.
--
-- The pipeline is an anonymous procedure, so its code travels with every call and nothing is kept in
-- the database between them, the way a Bauplan run uploads its project each time. It runs
-- server-side as Snowpark Python: the features are DataFrame calls Snowflake compiles and executes in
-- the warehouse, and the fitting pulls them into the procedure's own sandbox, so no data leaves it.
--
-- The fitting code is the Bauplan project's _learn.py, written out again: a script cannot import it.
-- Keep the two alike.
WITH ds_pipeline AS PROCEDURE (features STRING, model STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'numpy')
HANDLER = 'run'
AS
$$
import numpy as np
from snowflake.snowpark import functions as F
from snowflake.snowpark.types import DoubleType

# Rows whose order key is a multiple of this are held out: scored, never fitted on
HOLDOUT_MODULUS = 5
# Where the tree looks for its split: these quantiles of each feature
SPLIT_QUANTILES = 19


def build_features(session, names):
    """The chosen features for every line item, and the label: whether it arrived late."""
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
    columns += [candidates[name].cast(DoubleType()).alias(name) for name in names]
    columns.append((lineitem["L_RECEIPTDATE"] > lineitem["L_COMMITDATE"]).alias("late"))
    joined.select(columns).write.save_as_table("ds_features", mode="overwrite")


def split(session, names):
    """The features as a matrix, the label as a vector, and which rows are held out."""
    frame = session.table("ds_features").to_pandas()
    X = np.column_stack([frame[name.upper()].to_numpy(dtype=np.float64) for name in names])
    y = frame["LATE"].to_numpy(dtype=np.float64)
    holdout = frame["ORDER_KEY"].to_numpy(dtype=np.int64) % HOLDOUT_MODULUS == 0
    return X, y, holdout


def fit(kind_of_model, X, y, names):
    """Least squares with an intercept, or the single split that best separates the label."""
    if kind_of_model == "regression":
        design = np.column_stack([np.ones(len(y)), X])
        coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
        return [("coef", "intercept", float(coefficients[0]))] + [
            ("coef", name, float(value)) for name, value in zip(names, coefficients[1:])
        ]
    best = None
    for j, name in enumerate(names):
        for threshold in np.unique(np.quantile(X[:, j], np.linspace(0.05, 0.95, SPLIT_QUANTILES))):
            left = X[:, j] <= threshold
            if left.all() or not left.any():
                continue
            left_mean, right_mean = y[left].mean(), y[~left].mean()
            error = ((y[left] - left_mean) ** 2).sum() + ((y[~left] - right_mean) ** 2).sum()
            if best is None or error < best[0]:
                best = (error, name, threshold, left_mean, right_mean)
    if best is None:
        return [("split", names[0], float("inf")), ("left", "", float(y.mean())), ("right", "", float(y.mean()))]
    _, name, threshold, left_mean, right_mean = best
    return [("split", name, float(threshold)), ("left", "", float(left_mean)), ("right", "", float(right_mean))]


def predict(terms, X, names):
    """What a fitted model says for the features X."""
    by_kind = {}
    for kind, name, value in terms:
        by_kind.setdefault(kind, {})[name] = value
    if "coef" in by_kind:
        coefficients = by_kind["coef"]
        return coefficients["intercept"] + sum(coefficients[name] * X[:, j] for j, name in enumerate(names))
    ((name, threshold),) = by_kind["split"].items()
    return np.where(X[:, names.index(name)] <= threshold, by_kind["left"][""], by_kind["right"][""])


def r_squared(y, predicted):
    """How much of the label's variance the model explains, rounded so backends agree to the digit."""
    return round(float(1 - ((y - predicted) ** 2).sum() / ((y - y.mean()) ** 2).sum()), 6)


def run(session, features, model):
    names = features.split(",")
    build_features(session, names)

    X, y, holdout = split(session, names)
    terms = fit(model, X[~holdout], y[~holdout], names)
    session.create_dataframe(
        [list(term) for term in terms], schema=["term_kind", "term_name", "value"]
    ).write.save_as_table("ds_model", mode="overwrite")

    score = r_squared(y[holdout], predict(terms, X[holdout], names))
    session.create_dataframe(
        [[features, model, score]], schema=["features", "model", "score"]
    ).write.save_as_table("ds_metrics", mode="overwrite")
    return "ok"
$$
CALL ds_pipeline('{features}', '{model}')
