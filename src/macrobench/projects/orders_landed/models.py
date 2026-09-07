import bauplan


@bauplan.model(name="orders_landed", materialization_strategy="APPEND")
@bauplan.python("3.12")
def orders_landed(
    src=bauplan.Model(
        "orders_stream",
        columns=["order_key", "cust_key", "order_date", "total_price", "batch_id"],
    ),
    variant=bauplan.Parameter("variant"),
    batch_id=bauplan.Parameter("batch_id"),
):
    """Append one batch of orders to the published table.

    The batch is selected in the body rather than with a `filter=` on the read: a filter that were
    silently not applied would append the whole stream instead of one batch, which is a failure
    this workload would otherwise only notice as strange numbers.

    The broken variant appends the batch twice, so the same order keys land twice — the defect the
    uniqueness audit exists to catch.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    rows = src.filter(pc.equal(src.column("batch_id"), int(batch_id)))
    batch = pa.table(
        {
            "order_key": rows.column("order_key"),
            "cust_key": rows.column("cust_key"),
            "order_date": rows.column("order_date"),
            "total_price": rows.column("total_price"),
            "batch_id": rows.column("batch_id"),
        }
    )
    if variant == "broken":
        return pa.concat_tables([batch, batch])
    return batch
