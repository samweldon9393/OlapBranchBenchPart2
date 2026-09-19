"""The two models the agent compares, fitted and scored with numpy.

Deterministic on purpose: the same feature set gives the same score on every backend and every run,
so whether a candidate survives is down to the data rather than to a draw. A fitted model is kept as
rows of (kind, name, value), which is a table any backend can store and read back.

    regression  least squares on every chosen feature, plus an intercept
    tree        a single split: the one threshold, on the one feature, that best separates the label

The same code is written into the Snowflake procedure and the dbt Python models; a project cannot
share a module with them, so keep the three alike.
"""

# Rows whose order key is a multiple of this are held out: scored, never fitted on
HOLDOUT_MODULUS = 5

# Where the tree looks for its split: these quantiles of each feature
SPLIT_QUANTILES = 19


def fit(model, X, y, names):
    """Fit a model to the features X (one column per name) and the label y."""
    import numpy as np

    if model == "regression":
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
        # No feature splits the rows at all, so the best a split can do is predict the mean
        return [("split", names[0], float("inf")), ("left", "", float(y.mean())), ("right", "", float(y.mean()))]
    _, name, threshold, left_mean, right_mean = best
    return [("split", name, float(threshold)), ("left", "", float(left_mean)), ("right", "", float(right_mean))]


def predict(terms, X, names):
    """What a fitted model says for the features X."""
    import numpy as np

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
    residual = ((y - predicted) ** 2).sum()
    total = ((y - y.mean()) ** 2).sum()
    return round(float(1 - residual / total), 6)
