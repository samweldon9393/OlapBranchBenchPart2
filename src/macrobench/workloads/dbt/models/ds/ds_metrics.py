"""How well the candidate's model predicts the rows it never saw: the one row it is ranked by.

The scoring code is the Bauplan project's _learn.py written out again — a dbt Python model cannot
import a module of the project's — so keep the two alike.
"""

import numpy as np

# Rows whose order key is a multiple of this are held out: scored, never fitted on
HOLDOUT_MODULUS = 5


def _predict(terms, X, names):  # noqa: ANN001, ANN202, N803 - numpy arrays, named the way the maths names them
    """What a fitted model says for the features X."""
    by_kind: dict = {}
    for kind, name, value in terms:
        by_kind.setdefault(kind, {})[name] = value
    if "coef" in by_kind:
        coefficients = by_kind["coef"]
        return coefficients["intercept"] + sum(coefficients[name] * X[:, j] for j, name in enumerate(names))
    ((name, threshold),) = by_kind["split"].items()
    return np.where(X[:, names.index(name)] <= threshold, by_kind["left"][""], by_kind["right"][""])


def model(dbt, session):  # noqa: ANN001, ANN201 - dbt calls this; its arguments are not ours to annotate
    dbt.config(materialized="table", packages=["numpy"])

    features = dbt.config.meta_get("features")
    names = features.split(",")
    frame = dbt.ref("ds_features").to_pandas()
    held_out = frame[frame["ORDER_KEY"].to_numpy(dtype=np.int64) % HOLDOUT_MODULUS == 0]
    X = np.column_stack([held_out[name.upper()].to_numpy(dtype=np.float64) for name in names])  # noqa: N806
    y = held_out["LATE"].to_numpy(dtype=np.float64)

    fitted = dbt.ref("ds_model").to_pandas()
    terms = list(zip(fitted["TERM_KIND"], fitted["TERM_NAME"], fitted["VALUE"], strict=True))
    predicted = _predict(terms, X, names)
    # Rounded so backends agree to the digit whatever order they summed in
    score = round(float(1 - ((y - predicted) ** 2).sum() / ((y - y.mean()) ** 2).sum()), 6)
    return session.create_dataframe(
        [[features, dbt.config.meta_get("model"), score]], schema=["features", "model", "score"]
    )
