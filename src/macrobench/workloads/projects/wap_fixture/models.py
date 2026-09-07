"""WAP fixture: the stream batches are read from, and the table they land in.

Both are projections over orders_batched.sql, and both are written the way Bauplan requires: a read
of a parent does not preserve the order of `columns` and a `filter=` on one is not reliably
applied, so columns are picked out by name and filtering happens in the body.
"""

import bauplan


@bauplan.model(name="orders_stream", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def orders_stream(
    src=bauplan.Model(
        "orders_batched",
        columns=["order_key", "cust_key", "order_date", "total_price", "batch_id"],
    ),
):
    """Every order, tagged with its batch. The source each WAP step reads one batch from."""
    import pyarrow as pa

    return pa.table(
        {
            "order_key": src.column("order_key"),
            "cust_key": src.column("cust_key"),
            "order_date": src.column("order_date"),
            "total_price": src.column("total_price"),
            "batch_id": src.column("batch_id"),
        }
    )


@bauplan.model(name="orders_landed", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def orders_landed(
    src=bauplan.Model(
        "orders_batched",
        columns=["order_key", "cust_key", "order_date", "total_price", "batch_id"],
    ),
):
    """Batch 0 only: the published table, pre-seeded so the first append has somewhere to land.

    Its schema is what every appended batch has to match, so it is built from the same parent and
    the same column list as orders_stream.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    rows = src.filter(pc.equal(src.column("batch_id"), 0))
    return pa.table(
        {
            "order_key": rows.column("order_key"),
            "cust_key": rows.column("cust_key"),
            "order_date": rows.column("order_date"),
            "total_price": rows.column("total_price"),
            "batch_id": rows.column("batch_id"),
        }
    )
