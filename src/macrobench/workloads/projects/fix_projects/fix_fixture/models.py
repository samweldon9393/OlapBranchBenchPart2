"""The fixing fixture: two years of lineitem batches loaded cleanly, and the mart built over them.

A batch is one month of lineitems by ship date, numbered from the first year the workload counts
from. li_raw keeps every batch as it was loaded and li_clean is what the mart reads. They start out
the same, and only a repair ever makes them differ. The commits made on top of this only append, so
each leaves behind a state the history can go back to exactly.
"""

import bauplan

# What every batch table keeps, in the order it keeps it: a read of a parent does not preserve the
# order asked for, and an APPEND has to line up with what earlier builds wrote
COLUMNS = ("l_orderkey", "l_partkey", "l_suppkey", "l_linenumber", "l_extendedprice", "l_discount", "l_shipdate")


def _batched(lines, first_year):
    """The lines a batch table keeps, with the batch each one belongs to.

    Money is normalized to decimal below, which is what lets the revenue check ask for equality
    rather than for "close enough".
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    shipdate = pc.cast(lines.column("l_shipdate"), pa.date32())
    months = pc.add(
        pc.multiply(pc.subtract(pc.year(shipdate), int(first_year)), 12), pc.subtract(pc.month(shipdate), 1)
    )
    columns = {name: lines.column(name) for name in COLUMNS}
    # Bauplan's lakehouse stores TPC-H money as double where the other backends keep decimal, so it
    # is normalized once, here: the batch tables then hold the same exact values whichever backend
    # built them, and the workload's revenue check can ask for equality rather than a tolerance
    for money in ("l_extendedprice", "l_discount"):
        columns[money] = pc.cast(columns[money], pa.decimal128(15, 2))
    columns["l_shipdate"] = shipdate
    columns["batch_id"] = pc.cast(months, pa.int64())
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
            # Pinned, so the mart an APPEND adds to has the type the fixture gave it
            "revenue": pc.cast(summed.column("revenue_sum"), pa.decimal128(38, 4)),
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
    base_end=bauplan.Parameter("base_end"),
    first_year=bauplan.Parameter("first_year"),
):
    """Every batch the fixture loads, as loaded: the months before the base window ends."""
    import datetime

    import pyarrow as pa
    import pyarrow.compute as pc

    lines = _batched(lineitem, first_year)
    ends = pa.scalar(datetime.date.fromisoformat(base_end), pa.date32())
    return lines.filter(pc.less(lines.column("l_shipdate"), ends))


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
    import pyarrow as pa

    return pa.table({name: raw.column(name) for name in (*COLUMNS, "batch_id")})


@bauplan.model(name="revenue_mart", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def revenue_mart(
    clean=bauplan.Model("li_clean", columns=["l_suppkey", "l_extendedprice", "l_discount", "batch_id"]),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
):
    """Revenue per supplier nation per batch."""
    import pyarrow as pa

    lines = pa.table({name: clean.column(name) for name in ("l_suppkey", "l_extendedprice", "l_discount", "batch_id")})
    return _revenue(lines, supplier, ["nation_key", "batch_id"])
