"""The candidate's fitted model: least squares, or the single split that best separates the label.

Fitted with numpy on every row that is not held out, inside the procedure Snowflake runs the model
as. The fitting code is the Bauplan project's _learn.py written out again — a dbt Python model cannot
import a module of the project's — so keep the two alike. A fitted model is rows of (kind, name,
value), which the metrics model reads back.
"""

import numpy as np

# Rows whose order key is a multiple of this are held out: scored, never fitted on
HOLDOUT_MODULUS = 5
# Where the tree looks for its split: these quantiles of each feature
SPLIT_QUANTILES = 19


def _fit(kind_of_model, X, y, names):  # noqa: ANN001, ANN202, N803 - numpy arrays, named the way the maths names them
    """Fit a model to the features X (one column per name) and the label y."""
    if kind_of_model == "regression":
        design = np.column_stack([np.ones(len(y)), X])
        coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
        return [("coef", "intercept", float(coefficients[0]))] + [
            ("coef", name, float(value)) for name, value in zip(names, coefficients[1:], strict=True)
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


def model(dbt, session):  # noqa: ANN001, ANN201 - dbt calls this; its arguments are not ours to annotate
    dbt.config(materialized="table", packages=["numpy"])

    names = dbt.config.meta_get("features").split(",")
    frame = dbt.ref("ds_features").to_pandas()
    X = np.column_stack([frame[name.upper()].to_numpy(dtype=np.float64) for name in names])  # noqa: N806
    y = frame["LATE"].to_numpy(dtype=np.float64)
    train = frame["ORDER_KEY"].to_numpy(dtype=np.int64) % HOLDOUT_MODULUS != 0

    terms = _fit(dbt.config.meta_get("model"), X[train], y[train], names)
    return session.create_dataframe([list(term) for term in terms], schema=["term_kind", "term_name", "value"])
