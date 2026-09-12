"""One candidate's attempt: its feature table, then the metrics row the agent scored it with.

Every attempt runs this project; only the parameters differ, naming which features to build and the
score to record. Both tables are written fresh on the branch, so each attempt costs real storage.
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


@bauplan.model(name="ds_metrics", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def ds_metrics(
    # Reading the feature table makes the metrics depend on it, so a row is only written for a
    # feature table that actually built
    built=bauplan.Model("ds_features", columns=["order_key"]),
    features=bauplan.Parameter("features"),
    model=bauplan.Parameter("model"),
    score=bauplan.Parameter("score"),
):
    """The one row the agent scored this candidate with."""
    import pyarrow as pa

    return pa.table({"features": [features], "model": [model], "score": [float(score)]})
