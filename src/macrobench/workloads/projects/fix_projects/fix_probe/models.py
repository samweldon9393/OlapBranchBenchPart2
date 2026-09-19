"""A probe of one past state: recompute from source what the mart and the line counts should be.

Which months that state had loaded is a parameter rather than something read back off the tables:
the workload made those commits, so it knows where the loading got to, and both backends are handed
the same window instead of each deriving it.
"""

import bauplan


def _loaded(lineitem, judged_from, loaded_end):
    """Source lines shipped in the months being judged, typed the way the batch tables are."""
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
    return lines.filter(
        pc.and_(
            pc.greater_equal(shipdate, pa.scalar(datetime.date.fromisoformat(judged_from), pa.date32())),
            pc.less(shipdate, pa.scalar(datetime.date.fromisoformat(loaded_end), pa.date32())),
        )
    )


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
    judged_from=bauplan.Parameter("judged_from"),
    loaded_end=bauplan.Parameter("loaded_end"),
):
    """Revenue per supplier nation over the loaded months, from source."""
    return _revenue(_loaded(lineitem, judged_from, loaded_end), supplier, ["nation_key"])


@bauplan.model(name="lines_recheck", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def lines_recheck(
    lineitem=bauplan.Model(
        "lineitem", columns=["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"]
    ),
    judged_from=bauplan.Parameter("judged_from"),
    loaded_end=bauplan.Parameter("loaded_end"),
):
    """Lines per order over the loaded months, from source."""
    import pyarrow as pa

    counted = _loaded(lineitem, judged_from, loaded_end).group_by("l_orderkey").aggregate([("l_orderkey", "count")])
    return pa.table({"order_key": counted.column("l_orderkey"), "line_count": counted.column("l_orderkey_count")})


# The invariants, run inside the same run as the rechecks they compare against. Each is named after
# the check it is and judges only when the driver says that check applies; a strict run then fails on
# its assertion, lands nothing, and reports the check's id as the reason.
#
# They judge the batches from `judged_batch` on. In a probe that is everything, read off the branch;
# in a repair it is what the repair replayed, since a run hands an expectation only the rows the run
# appended — which is why every backend judges that same window.


def _judged(table, judged_batch):
    """The rows of the batches being judged."""
    import pyarrow.compute as pc

    return table.filter(pc.greater_equal(table.column("batch_id"), int(judged_batch)))


@bauplan.expectation()
@bauplan.python("3.12")
def expect_revenue(
    mart=bauplan.Model("revenue_mart", columns=["nation_key", "batch_id", "revenue"]),
    recheck=bauplan.Model("revenue_recheck", columns=["nation_key", "revenue"]),
    judged_batch=bauplan.Parameter("judged_batch"),
    checks=bauplan.Parameter("checks"),
):
    """The mart's revenue per nation is exactly what source says, to the last decimal place."""
    from collections import defaultdict
    from decimal import Decimal

    check = "revenue"
    judged = _judged(mart, judged_batch)
    actual = defaultdict(Decimal)
    for nation, revenue in zip(judged.column("nation_key").to_pylist(), judged.column("revenue").to_pylist()):
        actual[nation] += revenue
    expected = dict(zip(recheck.column("nation_key").to_pylist(), recheck.column("revenue").to_pylist()))
    ok = all(actual.get(nation, 0) == expected.get(nation, 0) for nation in actual.keys() | expected.keys())
    assert ok or check not in checks.split(","), check
    return True


@bauplan.expectation()
@bauplan.python("3.12")
def expect_line_counts(
    clean=bauplan.Model("li_clean", columns=["l_orderkey", "batch_id"]),
    recheck=bauplan.Model("lines_recheck", columns=["order_key", "line_count"]),
    judged_batch=bauplan.Parameter("judged_batch"),
    checks=bauplan.Parameter("checks"),
):
    """Every order has as many lines as source says: no batch loaded twice, no order made up."""
    import pyarrow as pa
    import pyarrow.compute as pc

    check = "line_counts"
    counted = _judged(clean, judged_batch).group_by("l_orderkey").aggregate([("l_orderkey", "count")])

    def by_order(keys, counts):
        return pa.table({"key": pc.cast(keys, pa.int64()), "count": pc.cast(counts, pa.int64())}).sort_by("key")

    actual = by_order(counted.column("l_orderkey"), counted.column("l_orderkey_count"))
    expected = by_order(recheck.column("order_key"), recheck.column("line_count"))
    ok = actual.combine_chunks().equals(expected.combine_chunks())
    assert ok or check not in checks.split(","), check
    return True


@bauplan.expectation()
@bauplan.python("3.12")
def expect_ref_integrity(
    clean=bauplan.Model("li_clean", columns=["l_orderkey", "l_partkey", "l_suppkey", "batch_id"]),
    orders=bauplan.Model("orders", columns=["o_orderkey"]),
    part=bauplan.Model("part", columns=["p_partkey"]),
    supplier=bauplan.Model("supplier", columns=["s_suppkey"]),
    judged_batch=bauplan.Parameter("judged_batch"),
    checks=bauplan.Parameter("checks"),
):
    """Every line points at an order, a part and a supplier that exist."""
    import pyarrow.compute as pc

    check = "ref_integrity"
    judged = _judged(clean, judged_batch)

    def known(column, keys):
        # The parent keys are matched to the lines' own type: TPC-H keys are int32 in the source
        values = pc.cast(keys, judged.column(column).type).combine_chunks()
        return pc.all(pc.is_in(judged.column(column), value_set=values)).as_py() is not False

    ok = (
        known("l_orderkey", orders.column("o_orderkey"))
        and known("l_partkey", part.column("p_partkey"))
        and known("l_suppkey", supplier.column("s_suppkey"))
    )
    assert ok or check not in checks.split(","), check
    return True
