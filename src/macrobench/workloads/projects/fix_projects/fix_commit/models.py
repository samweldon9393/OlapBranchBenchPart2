"""One commit on the root: append a month's batch to li_raw, li_clean and the mart.

The bad commit loads its batch the run's wrong way: twice over, with the discounts on its first days
dropped, or with lines for orders that were never booked. Every other commit loads its batch cleanly.
A commit only appends, so the state it leaves is exactly the tables as they then stood.
"""

import bauplan


def _typed(lines):
    """Lines as every batch table keeps them: fixed types, so appends line up, and each batch.

    Columns are picked out by name, since a read of a parent does not preserve the order asked for.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    shipdate = pc.cast(lines.column("l_shipdate"), pa.date32())
    batch = pc.add(pc.multiply(pc.subtract(pc.year(shipdate), 1992), 12), pc.subtract(pc.month(shipdate), 1))
    return pa.table(
        {
            "l_orderkey": pc.cast(lines.column("l_orderkey"), pa.int64()),
            "l_partkey": pc.cast(lines.column("l_partkey"), pa.int64()),
            "l_suppkey": pc.cast(lines.column("l_suppkey"), pa.int64()),
            "l_linenumber": pc.cast(lines.column("l_linenumber"), pa.int64()),
            "l_extendedprice": pc.cast(lines.column("l_extendedprice"), pa.float64()),
            "l_discount": pc.cast(lines.column("l_discount"), pa.float64()),
            "l_shipdate": shipdate,
            "batch_id": pc.cast(batch, pa.int64()),
        }
    )


@bauplan.model(name="li_raw", materialization_strategy="APPEND")
@bauplan.python("3.12")
def li_raw(
    lineitem=bauplan.Model(
        "lineitem",
        columns=[
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_extendedprice",
            "l_discount",
            "l_shipdate",
        ],
    ),
    start=bauplan.Parameter("start"),
    end=bauplan.Parameter("end"),
    cut=bauplan.Parameter("cut"),
    kind=bauplan.Parameter("kind"),
    bad=bauplan.Parameter("bad"),
):
    """The month's batch, loaded the way this commit loads it."""
    import datetime

    import pyarrow as pa
    import pyarrow.compute as pc

    lines = _typed(lineitem)
    shipdate = lines.column("l_shipdate")
    batch = lines.filter(
        pc.and_(
            pc.greater_equal(shipdate, pa.scalar(datetime.date.fromisoformat(start), pa.date32())),
            pc.less(shipdate, pa.scalar(datetime.date.fromisoformat(end), pa.date32())),
        )
    )
    if bad != "1":
        return batch
    if kind == "duplicate":
        return pa.concat_tables([batch, batch])
    if kind == "discount":
        early = pc.less(batch.column("l_shipdate"), pa.scalar(datetime.date.fromisoformat(cut), pa.date32()))
        dropped = pc.if_else(early, 0.0, batch.column("l_discount"))
        return batch.set_column(batch.column_names.index("l_discount"), "l_discount", dropped)
    # Lines for orders that were never booked: each order's first line again, under a key no order has
    first = batch.filter(pc.equal(batch.column("l_linenumber"), 1))
    unbooked = first.set_column(0, "l_orderkey", pc.negate(first.column("l_orderkey")))
    return pa.concat_tables([batch, unbooked])


@bauplan.model(name="li_clean", materialization_strategy="APPEND")
@bauplan.python("3.12")
def li_clean(
    raw=bauplan.Model(
        "li_raw",
        columns=[
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_extendedprice",
            "l_discount",
            "l_shipdate",
            "batch_id",
        ],
    ),
):
    """The batch as the mart will read it, which is as it was loaded until something repairs it."""
    return _typed(raw)


@bauplan.model(name="revenue_mart", materialization_strategy="APPEND")
@bauplan.python("3.12")
def revenue_mart(
    clean=bauplan.Model(
        "li_clean",
        columns=["l_suppkey", "l_extendedprice", "l_discount", "batch_id"],
    ),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
):
    """The batch's revenue per supplier nation."""
    import pyarrow as pa
    import pyarrow.compute as pc

    suppliers = pa.table(
        {
            "l_suppkey": pc.cast(supplier.column("s_suppkey"), pa.int64()),
            "nation_key": pc.cast(supplier.column("s_nationkey"), pa.int64()),
        }
    )
    lines = pa.table({name: clean.column(name) for name in ["l_suppkey", "l_extendedprice", "l_discount", "batch_id"]})
    joined = lines.join(suppliers, keys="l_suppkey", join_type="inner")
    keyed = pa.table(
        {
            "nation_key": joined.column("nation_key"),
            "batch_id": joined.column("batch_id"),
            "revenue": pc.multiply(joined.column("l_extendedprice"), pc.subtract(1.0, joined.column("l_discount"))),
        }
    )
    summed = keyed.group_by(["nation_key", "batch_id"]).aggregate([("revenue", "sum")])
    return pa.table(
        {
            "nation_key": summed.column("nation_key"),
            "batch_id": summed.column("batch_id"),
            "revenue": summed.column("revenue_sum"),
        }
    )
