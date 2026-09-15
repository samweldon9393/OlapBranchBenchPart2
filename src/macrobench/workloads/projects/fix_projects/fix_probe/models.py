"""A probe of one past commit: recompute from source what the mart and the line counts should be.

What the commit had loaded is read off li_raw, as every month up to its latest ship date. Nothing a
bad batch gets wrong moves that date, so the recomputation covers exactly the loaded months whatever
state they are in.
"""

import bauplan


def _loaded(lineitem, raw):
    """Source lines shipped by the latest ship date loaded, typed the way the batch tables are."""
    import pyarrow as pa
    import pyarrow.compute as pc

    last = pc.max(pc.cast(raw.column("l_shipdate"), pa.date32()))
    shipdate = pc.cast(lineitem.column("l_shipdate"), pa.date32())
    lines = pa.table(
        {
            "l_orderkey": pc.cast(lineitem.column("l_orderkey"), pa.int64()),
            "l_suppkey": pc.cast(lineitem.column("l_suppkey"), pa.int64()),
            "l_extendedprice": pc.cast(lineitem.column("l_extendedprice"), pa.float64()),
            "l_discount": pc.cast(lineitem.column("l_discount"), pa.float64()),
            "l_shipdate": shipdate,
        }
    )
    return lines.filter(pc.less_equal(shipdate, last))


@bauplan.model(name="revenue_recheck", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def revenue_recheck(
    lineitem=bauplan.Model(
        "lineitem",
        columns=["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"],
    ),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
    raw=bauplan.Model("li_raw", columns=["l_shipdate"]),
):
    """Revenue per supplier nation over the loaded months, from source."""
    import pyarrow as pa
    import pyarrow.compute as pc

    lines = _loaded(lineitem, raw)
    suppliers = pa.table(
        {
            "l_suppkey": pc.cast(supplier.column("s_suppkey"), pa.int64()),
            "nation_key": pc.cast(supplier.column("s_nationkey"), pa.int64()),
        }
    )
    joined = lines.join(suppliers, keys="l_suppkey", join_type="inner")
    keyed = pa.table(
        {
            "nation_key": joined.column("nation_key"),
            "revenue": pc.multiply(joined.column("l_extendedprice"), pc.subtract(1.0, joined.column("l_discount"))),
        }
    )
    summed = keyed.group_by("nation_key").aggregate([("revenue", "sum")])
    return pa.table({"nation_key": summed.column("nation_key"), "revenue": summed.column("revenue_sum")})


@bauplan.model(name="lines_recheck", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def lines_recheck(
    lineitem=bauplan.Model(
        "lineitem",
        columns=["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"],
    ),
    raw=bauplan.Model("li_raw", columns=["l_shipdate"]),
):
    """Lines per order over the loaded months, from source."""
    import pyarrow as pa

    counted = _loaded(lineitem, raw).group_by("l_orderkey").aggregate([("l_orderkey", "count")])
    return pa.table({"order_key": counted.column("l_orderkey"), "line_count": counted.column("l_orderkey_count")})
