"""One repair: off the last good state, replay the culprit and every commit after it, fixing as it goes.

The replay loads each batch from source exactly as its commit did, the culprit's defect included, and
appends it to li_raw. Into li_clean it applies one strategy to the batches in scope and passes the
rest through as they were loaded:
    dedupe     keep one copy of each line
    rederive   load the batches again from source
    filter     drop lines whose order, part or supplier does not exist
    restore    take each line's discount from source
The mart and the recomputations are then rebuilt, and fix_metrics records how many rows outside the
culprit the strategy rewrote.
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


def _shipped(lines, start, end):
    """The lines shipped from one date up to, but not including, another."""
    import datetime

    import pyarrow as pa
    import pyarrow.compute as pc

    shipdate = lines.column("l_shipdate")
    return lines.filter(
        pc.and_(
            pc.greater_equal(shipdate, pa.scalar(datetime.date.fromisoformat(start), pa.date32())),
            pc.less(shipdate, pa.scalar(datetime.date.fromisoformat(end), pa.date32())),
        )
    )


def _in_scope(lines, low, high):
    """Which lines belong to a batch in scope."""
    import pyarrow.compute as pc

    batch = lines.column("batch_id")
    return pc.and_(pc.greater_equal(batch, int(low)), pc.less_equal(batch, int(high)))


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


def _revenue(lines, supplier, keys):
    """Revenue per supplier nation, and per whatever else `keys` names."""
    import pyarrow as pa
    import pyarrow.compute as pc

    suppliers = pa.table(
        {
            "l_suppkey": pc.cast(supplier.column("s_suppkey"), pa.int64()),
            "nation_key": pc.cast(supplier.column("s_nationkey"), pa.int64()),
        }
    )
    joined = lines.join(suppliers, keys="l_suppkey", join_type="inner")
    keyed = pa.table(
        {
            **{key: joined.column(key) for key in keys},
            "revenue": pc.multiply(joined.column("l_extendedprice"), pc.subtract(1.0, joined.column("l_discount"))),
        }
    )
    summed = keyed.group_by(keys).aggregate([("revenue", "sum")])
    return pa.table({**{key: summed.column(key) for key in keys}, "revenue": summed.column("revenue_sum")})


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
    culprit=bauplan.Parameter("culprit"),
    start=bauplan.Parameter("start"),
    end=bauplan.Parameter("end"),
    cut=bauplan.Parameter("cut"),
    kind=bauplan.Parameter("kind"),
):
    """The culprit's batch and every one after it, loaded exactly as their commits loaded them."""
    import datetime

    import pyarrow as pa
    import pyarrow.compute as pc

    replayed = _shipped(_typed(lineitem), start, end)
    is_culprit = pc.equal(replayed.column("batch_id"), int(culprit))
    if kind == "discount":
        early = pc.and_(
            is_culprit,
            pc.less(replayed.column("l_shipdate"), pa.scalar(datetime.date.fromisoformat(cut), pa.date32())),
        )
        dropped = pc.if_else(early, 0.0, replayed.column("l_discount"))
        return replayed.set_column(replayed.column_names.index("l_discount"), "l_discount", dropped)
    batch = replayed.filter(is_culprit)
    if kind == "duplicate":
        return pa.concat_tables([replayed, batch])
    first = batch.filter(pc.equal(batch.column("l_linenumber"), 1))
    unbooked = first.set_column(0, "l_orderkey", pc.negate(first.column("l_orderkey")))
    return pa.concat_tables([replayed, unbooked])


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
    orders=bauplan.Model("orders", columns=["o_orderkey"]),
    part=bauplan.Model("part", columns=["p_partkey"]),
    supplier=bauplan.Model("supplier", columns=["s_suppkey"]),
    strategy=bauplan.Parameter("strategy"),
    scope_lo=bauplan.Parameter("scope_lo"),
    scope_hi=bauplan.Parameter("scope_hi"),
    scope_end=bauplan.Parameter("scope_end"),
    start=bauplan.Parameter("start"),
):
    """The replayed batches with the strategy applied to those in scope."""
    import pyarrow as pa
    import pyarrow.compute as pc

    replayed = _typed(raw)
    scoped = _in_scope(replayed, scope_lo, scope_hi)
    outside, inside = replayed.filter(pc.invert(scoped)), replayed.filter(scoped)

    if strategy == "dedupe":
        inside = inside.group_by(inside.column_names).aggregate([])
    elif strategy == "rederive":
        inside = _shipped(_typed(lineitem), start, scope_end)
    elif strategy == "filter":

        def known(column, keys):
            return pc.is_in(inside.column(column), value_set=pc.cast(keys, pa.int64()).combine_chunks())

        exists = pc.and_(
            pc.and_(known("l_orderkey", orders.column("o_orderkey")), known("l_partkey", part.column("p_partkey"))),
            known("l_suppkey", supplier.column("s_suppkey")),
        )
        inside = inside.filter(exists)
    else:
        source = _typed(lineitem)
        discounts = pa.table(
            {
                "l_orderkey": source.column("l_orderkey"),
                "l_linenumber": source.column("l_linenumber"),
                "source_discount": source.column("l_discount"),
            }
        )
        joined = inside.join(discounts, keys=["l_orderkey", "l_linenumber"], join_type="left outer")
        restored = pc.coalesce(joined.column("source_discount"), joined.column("l_discount"))
        inside = joined.set_column(joined.column_names.index("l_discount"), "l_discount", restored)

    return pa.concat_tables([_typed(outside), _typed(inside)])


@bauplan.model(name="revenue_mart", materialization_strategy="APPEND")
@bauplan.python("3.12")
def revenue_mart(
    clean=bauplan.Model(
        "li_clean",
        columns=["l_suppkey", "l_extendedprice", "l_discount", "batch_id"],
    ),
    supplier=bauplan.Model("supplier", columns=["s_suppkey", "s_nationkey"]),
):
    """Revenue per supplier nation for each replayed batch."""
    import pyarrow as pa

    lines = pa.table({name: clean.column(name) for name in ["l_suppkey", "l_extendedprice", "l_discount", "batch_id"]})
    return _revenue(lines, supplier, ["nation_key", "batch_id"])


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
    """Revenue per supplier nation over every loaded month, from source.

    The replay is the newest thing loaded, so its latest ship date is the whole table's.
    """
    return _revenue(_loaded(lineitem, raw), supplier, ["nation_key"])


@bauplan.model(name="lines_recheck", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def lines_recheck(
    lineitem=bauplan.Model(
        "lineitem",
        columns=["l_orderkey", "l_suppkey", "l_extendedprice", "l_discount", "l_shipdate"],
    ),
    raw=bauplan.Model("li_raw", columns=["l_shipdate"]),
):
    """Lines per order over every loaded month, from source."""
    import pyarrow as pa

    counted = _loaded(lineitem, raw).group_by("l_orderkey").aggregate([("l_orderkey", "count")])
    return pa.table({"order_key": counted.column("l_orderkey"), "line_count": counted.column("l_orderkey_count")})


@bauplan.model(name="fix_metrics", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def fix_metrics(
    raw=bauplan.Model("li_raw", columns=["batch_id"]),
    strategy=bauplan.Parameter("strategy"),
    scope=bauplan.Parameter("scope"),
    culprit=bauplan.Parameter("culprit"),
    scope_lo=bauplan.Parameter("scope_lo"),
    scope_hi=bauplan.Parameter("scope_hi"),
):
    """How many rows outside the culprit the repair rewrote.

    Every row in scope is rewritten, as a partition rewrite does, so the rows disturbed are the ones in
    scope that belong to batches the culprit never touched.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    batch = raw.column("batch_id")
    disturbed = pc.and_(_in_scope(raw, scope_lo, scope_hi), pc.not_equal(batch, int(culprit)))
    rows = pc.sum(pc.cast(disturbed, pa.int64())).as_py() or 0
    return pa.table(
        {
            "repair_strategy": [strategy],
            "repair_scope": [scope],
            "disturbed_rows": pa.array([rows], pa.int64()),
            "score": pa.array([-rows], pa.int64()),
        }
    )
