"""The data science pipeline: build a candidate's features, fit a model to them, score it on held-out rows.

    lineitem ⋈ orders ─→ ds_features ─→ ds_model ─→ ds_metrics
                                   └──────────────────┘

Every attempt runs the whole pipeline; only the parameters differ, naming which features to build and
which kind of model to fit. All three tables are written fresh on the branch, so each attempt costs
real storage, and the score is whatever the data gives — the expectation at the end is what decides
whether the candidate survives.
"""

import bauplan


@bauplan.model(name="ds_features", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def ds_features(
    lineitem=bauplan.Model(
        "lineitem",
        columns=["l_orderkey", "l_shipdate", "l_commitdate", "l_receiptdate", "l_quantity", "l_discount"],
    ),
    orders=bauplan.Model("orders", columns=["o_orderkey", "o_orderdate", "o_orderpriority"]),
    features=bauplan.Parameter("features"),
):
    """The chosen features for every line item, and the label: whether it arrived late.

    Columns are picked out by name, since a read of a parent does not preserve the order asked for.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    joined = pa.table(
        {name: lineitem.column(name) for name in lineitem.column_names}
    ).join(
        pa.table({name: orders.column(name) for name in orders.column_names}),
        keys="l_orderkey",
        right_keys="o_orderkey",
        # Stated rather than left to pyarrow's left-outer default, since the Snowflake side joins
        # inner: a line whose order went missing should drop out on both backends
        join_type="inner",
    )

    candidates = {
        "ship_delay": lambda t: pc.days_between(t.column("o_orderdate"), t.column("l_shipdate")),
        "quantity": lambda t: t.column("l_quantity"),
        "discount": lambda t: t.column("l_discount"),
        "priority": lambda t: pc.cast(pc.utf8_slice_codeunits(t.column("o_orderpriority"), 0, 1), pa.int32()),
    }

    columns = {"order_key": joined.column("l_orderkey")}
    for feature in features.split(","):
        columns[feature] = candidates[feature](joined)
    columns["late"] = pc.greater(joined.column("l_receiptdate"), joined.column("l_commitdate"))
    return pa.table(columns)


def _split(table, features):
    """The features as a matrix, the label as a vector, and which rows are held out."""
    import numpy as np
    from _learn import HOLDOUT_MODULUS

    names = features.split(",")
    X = np.column_stack([table.column(name).to_numpy().astype(np.float64) for name in names])
    y = table.column("late").to_numpy(zero_copy_only=False).astype(np.float64)
    holdout = table.column("order_key").to_numpy() % HOLDOUT_MODULUS == 0
    return X, y, holdout, names


@bauplan.model(name="ds_model", materialization_strategy="REPLACE")
@bauplan.python("3.12", pip={"numpy": "2.2.4"})
def ds_model(
    data=bauplan.Model("ds_features", columns=["*"]),
    features=bauplan.Parameter("features"),
    model=bauplan.Parameter("model"),
):
    """The fitted model, fitted on every row that is not held out."""
    import pyarrow as pa
    from _learn import fit

    X, y, holdout, names = _split(data, features)
    terms = fit(model, X[~holdout], y[~holdout], names)
    return pa.table(
        {
            "term_kind": [kind for kind, _, _ in terms],
            "term_name": [name for _, name, _ in terms],
            "value": pa.array([value for _, _, value in terms], pa.float64()),
        }
    )


@bauplan.model(name="ds_metrics", materialization_strategy="REPLACE")
@bauplan.python("3.12", pip={"numpy": "2.2.4"})
def ds_metrics(
    data=bauplan.Model("ds_features", columns=["*"]),
    fitted=bauplan.Model("ds_model", columns=["term_kind", "term_name", "value"]),
    features=bauplan.Parameter("features"),
    model=bauplan.Parameter("model"),
):
    """How well the model predicts the rows it never saw, as the one row the candidate is ranked by."""
    import pyarrow as pa
    from _learn import predict, r_squared

    X, y, holdout, names = _split(data, features)
    terms = list(
        zip(
            fitted.column("term_kind").to_pylist(),
            fitted.column("term_name").to_pylist(),
            fitted.column("value").to_pylist(),
        )
    )
    score = r_squared(y[holdout], predict(terms, X[holdout], names))
    return pa.table({"features": [features], "model": [model], "score": pa.array([score], pa.float64())})


@bauplan.expectation()
@bauplan.python("3.12")
def expect_score(
    metrics=bauplan.Model("ds_metrics", columns=["features", "score"]),
    features=bauplan.Parameter("features"),
    threshold=bauplan.Parameter("threshold"),
    checks=bauplan.Parameter("checks"),
):
    """The candidate explains enough of the label to be worth refining.

    The feature set is checked too, so the score is this candidate's rather than one left behind.
    """
    check = "score"
    ok = metrics.column("score")[0].as_py() >= float(threshold) and metrics.column("features")[0].as_py() == features
    assert ok or check not in checks.split(","), check
    return True
