"""One commit on the root: append a month's batch to li_raw, li_clean and the mart.

The bad commit loads its batch the run's wrong way: twice over, with the discounts on its first days
dropped, or with lines for orders that were never booked. Every other commit loads its batch cleanly.
A commit only appends, so the state it leaves is exactly the tables as they then stood.
"""

import bauplan

# What every batch table keeps, in the order it keeps it: a read of a parent does not preserve the
# order asked for, and an APPEND has to line up with what earlier builds wrote
COLUMNS = ("l_orderkey", "l_partkey", "l_suppkey", "l_linenumber", "l_extendedprice", "l_discount", "l_shipdate")


def _stamped(lines, batch):
    """The lines a batch table keeps, stamped with the batch this commit is loading.

    The batch number comes from the parameter rather than being worked out again from the ship date:
    one commit loads one batch, and the workload already knows which.

    Money is normalized to decimal below, so a nation's revenue is exact.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    columns = {name: lines.column(name) for name in COLUMNS}
    # Bauplan's lakehouse stores TPC-H money as double where the other backends keep decimal, so it
    # is normalized once, here: the batch tables then hold the same exact values whichever backend
    # built them, and the workload's revenue check can ask for equality rather than a tolerance
    for money in ("l_extendedprice", "l_discount"):
        columns[money] = pc.cast(columns[money], pa.decimal128(15, 2))
    columns["l_shipdate"] = pc.cast(lines.column("l_shipdate"), pa.date32())
    columns["batch_id"] = pa.array([int(batch)] * lines.num_rows, pa.int64())
    return pa.table(columns)


def _revenue(lines, supplier, keys):
    """Revenue per supplier nation, and per whatever else `keys` names, in exact decimal."""
    from decimal import Decimal

    import pyarrow as pa
    import pyarrow.compute as pc

    suppliers = pa.table(
        {
            # The supplier key is matched to the lines' own type: TPC-H keys are int32 in the source
            "l_suppkey": pc.cast(supplier.column("s_suppkey"), lines.column("l_suppkey").type),
            "nation_key": pc.cast(supplier.column("s_nationkey"), pa.int64()),
        }
    )
    joined = lines.join(suppliers, keys="l_suppkey", join_type="inner")
    discount = joined.column("l_discount")
    net = pc.multiply(
        joined.column("l_extendedprice"), pc.subtract(pa.scalar(Decimal("1.00"), discount.type), discount)
    )
    keyed = pa.table({**{key: joined.column(key) for key in keys}, "revenue": net})
    summed = keyed.group_by(keys).aggregate([("revenue", "sum")])
    return pa.table(
        {
            **{key: summed.column(key) for key in keys},
            # Pinned, so the mart this appends to keeps the type the fixture gave it
            "revenue": pc.cast(summed.column("revenue_sum"), pa.decimal128(38, 4)),
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
    batch=bauplan.Parameter("batch"),
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

    lines = _stamped(lineitem, batch)
    shipdate = lines.column("l_shipdate")
    batch_rows = lines.filter(
        pc.and_(
            pc.greater_equal(shipdate, pa.scalar(datetime.date.fromisoformat(start), pa.date32())),
            pc.less(shipdate, pa.scalar(datetime.date.fromisoformat(end), pa.date32())),
        )
    )
    if bad != "1":
        return batch_rows
    if kind == "duplicate":
        return pa.concat_tables([batch_rows, batch_rows])
    if kind == "discount":
        early = pc.less(batch_rows.column("l_shipdate"), pa.scalar(datetime.date.fromisoformat(cut), pa.date32()))
        discount = batch_rows.column("l_discount")
        dropped = pc.if_else(early, pa.scalar(0, discount.type), discount)
        return batch_rows.set_column(batch_rows.column_names.index("l_discount"), "l_discount", dropped)
    # Lines for orders that were never booked: each order's first line again, under a key no order has
    first = batch_rows.filter(pc.equal(batch_rows.column("l_linenumber"), 1))
    unbooked = first.set_column(0, "l_orderkey", pc.negate(first.column("l_orderkey")))
    return pa.concat_tables([batch_rows, unbooked])


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
    import pyarrow as pa

    return pa.table({name: raw.column(name) for name in (*COLUMNS, "batch_id")})


@bauplan.model(name="revenue_mart", materialization_strategy="APPEND")
@bauplan.python("3.12")
def revenue_mart(
    clean=bauplan.Model("li_clean", columns=["l_suppkey", "l_extendedprice", "l_discount", "batch_id"]),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
):
    """The batch's revenue per supplier nation."""
    import pyarrow as pa

    lines = pa.table({name: clean.column(name) for name in ("l_suppkey", "l_extendedprice", "l_discount", "batch_id")})
    return _revenue(lines, supplier, ["nation_key", "batch_id"])
