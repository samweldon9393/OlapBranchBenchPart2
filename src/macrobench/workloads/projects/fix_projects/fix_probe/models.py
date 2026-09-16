"""A probe of one past state: recompute from source what the mart and the line counts should be.

Which months that state had loaded is a parameter rather than something read back off the tables:
the workload made those commits, so it knows where the loading got to, and both backends are handed
the same window instead of each deriving it.
"""

import bauplan


def _loaded(lineitem, loaded_end):
    """Source lines shipped before the loading got this far, typed the way the batch tables are."""
    import datetime

    import pyarrow as pa
    import pyarrow.compute as pc

    shipdate = pc.cast(lineitem.column("l_shipdate"), pa.date32())
    lines = pa.table(
        {
            "l_orderkey": lineitem.column("l_orderkey"),
            "l_suppkey": lineitem.column("l_suppkey"),
            # Money is normalized to decimal, as it is where a batch table is written
            "l_extendedprice": pc.cast(lineitem.column("l_extendedprice"), pa.decimal128(15, 2)),
            "l_discount": pc.cast(lineitem.column("l_discount"), pa.decimal128(15, 2)),
            "l_shipdate": shipdate,
        }
    )
    return lines.filter(pc.less(shipdate, pa.scalar(datetime.date.fromisoformat(loaded_end), pa.date32())))


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
            "revenue": pc.cast(summed.column("revenue_sum"), pa.decimal128(38, 4)),
        }
    )


@bauplan.model(name="revenue_recheck", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def revenue_recheck(
    lineitem=bauplan.Model(
        "lineitem", columns=["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"]
    ),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
    loaded_end=bauplan.Parameter("loaded_end"),
):
    """Revenue per supplier nation over the loaded months, from source."""
    return _revenue(_loaded(lineitem, loaded_end), supplier, ["nation_key"])


@bauplan.model(name="lines_recheck", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def lines_recheck(
    lineitem=bauplan.Model(
        "lineitem", columns=["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"]
    ),
    loaded_end=bauplan.Parameter("loaded_end"),
):
    """Lines per order over the loaded months, from source."""
    import pyarrow as pa

    counted = _loaded(lineitem, loaded_end).group_by("l_orderkey").aggregate([("l_orderkey", "count")])
    return pa.table({"order_key": counted.column("l_orderkey"), "line_count": counted.column("l_orderkey_count")})
