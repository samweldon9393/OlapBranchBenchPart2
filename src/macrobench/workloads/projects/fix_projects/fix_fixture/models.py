"""The fixing fixture: two years of lineitem batches loaded cleanly, and the mart built over them.

A batch is one month of lineitems by ship date, numbered from January 1992. li_raw keeps every batch
as it was loaded and li_clean is what the mart reads. They start out the same, and only a repair ever
makes them differ. The commits made on top of this only append, so each leaves behind a state the
history can go back to exactly.
"""

import bauplan


def _typed(lines):
    """Lines as every batch table keeps them: fixed types, so later appends line up, and each batch.

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


@bauplan.model(name="li_raw", materialization_strategy="REPLACE")
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
):
    """The first two years of batches, as loaded."""
    import pyarrow.compute as pc

    lines = _typed(lineitem)
    return lines.filter(pc.less(lines.column("batch_id"), 24))


@bauplan.model(name="li_clean", materialization_strategy="REPLACE")
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
    """What the mart reads: the same batches, since nothing has needed repairing yet."""
    return _typed(raw)


@bauplan.model(name="revenue_mart", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def revenue_mart(
    clean=bauplan.Model(
        "li_clean",
        columns=["l_suppkey", "l_extendedprice", "l_discount", "batch_id"],
    ),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
):
    """Revenue per supplier nation per batch."""
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
