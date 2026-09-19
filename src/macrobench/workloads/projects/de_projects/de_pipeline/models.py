"""The data engineering pipeline: three drifted feeds standardized, unioned, and rolled up into a mart.

    feed_americas ─→ stg_americas ─┐
    feed_europe   ─→ stg_europe   ─┼─→ orders_unified ─→ revenue_by_nation_quarter
    feed_asia     ─→ stg_asia     ─┘

One project, run whole on every step, the way a pipeline is: a step rewrites one model and reruns the
lot, and everything downstream of the rewrite is rebuilt from it. Each model has a correct and a
broken implementation, chosen by its own `variant_<model>` parameter; the pipeline starts out with
every model broken, and the agent fixes them one at a time.

Every model is audited by an expectation comparing it to gold. Only the ones the driver names in
`checks` judge anything — a model the agent has not fixed yet is broken by design, and is not what
the step is being judged on — and the run is strict, so one that fails stops the run and nothing it
built lands.
"""

import bauplan

STAGED = ("order_key", "cust_key", "order_date", "net_price", "tax_amount", "source")


def _aligned(table):
    """A staged feed with its columns in the shared order; a read does not preserve the one asked for."""
    import pyarrow as pa

    return pa.table({name: table.column(name) for name in STAGED})


@bauplan.model(name="stg_americas", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def stg_americas(
    src=bauplan.Model(
        "feed_americas",
        columns=["order_key", "cust_key", "order_date", "gross_price", "discount_amount"],
    ),
    variant=bauplan.Parameter("variant_stg_americas"),
):
    """Standardize the americas feed onto the shared staging schema.

    The feed reports price before discount, so the correct reading subtracts it to reach the
    canonical net revenue. The broken variant takes the reported price as if it were already net.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    gross_price = src.column("gross_price")
    if variant == "broken":
        net_price = gross_price
    else:
        net_price = pc.subtract(gross_price, src.column("discount_amount"))

    return pa.table(
        {
            "order_key": src.column("order_key"),
            "cust_key": src.column("cust_key"),
            "order_date": src.column("order_date"),
            "net_price": pc.cast(net_price, pa.decimal128(18, 2)),
            # americas reports no tax at all, so the column is carried but never filled
            "tax_amount": pa.nulls(src.num_rows, pa.decimal128(18, 2)),
            "source": pa.array(["americas"] * src.num_rows, pa.string()),
        }
    )


@bauplan.model(name="stg_europe", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def stg_europe(
    src=bauplan.Model(
        "feed_europe",
        columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount"],
    ),
    variant=bauplan.Parameter("variant_stg_europe"),
):
    """Standardize the europe feed onto the shared staging schema.

    The feed already reports price net of discount, so the correct reading carries it straight
    through. The broken variant folds tax into revenue, double counting what the tax column
    already reports separately.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    tax_amount = pc.cast(src.column("tax_amount"), pa.decimal128(18, 2))
    if variant == "broken":
        net_price = pc.add(src.column("net_price"), src.column("tax_amount"))
    else:
        net_price = src.column("net_price")

    return pa.table(
        {
            "order_key": src.column("order_key"),
            "cust_key": src.column("cust_key"),
            # the feed carries the date as a string, so it has to be parsed before the union lines up
            "order_date": pc.cast(pc.strptime(src.column("order_date"), format="%Y-%m-%d", unit="s"), pa.date32()),
            "net_price": pc.cast(net_price, pa.decimal128(18, 2)),
            "tax_amount": tax_amount,
            "source": pa.array(["europe"] * src.num_rows, pa.string()),
        }
    )


@bauplan.model(name="stg_asia", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def stg_asia(
    src=bauplan.Model(
        "feed_asia",
        columns=["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice", "o_tax"],
    ),
    variant=bauplan.Parameter("variant_stg_asia"),
):
    """Standardize the asia feed onto the shared staging schema.

    The feed repeats roughly 1% of its rows verbatim, so the correct reading collapses them before
    anything downstream counts them. The broken variant trusts the feed to hold one row per order.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    # The feed repeats rows verbatim, so the correct reading collapses identical rows of the feed
    # before anything downstream counts them — grouping on every column with no aggregate is
    # pyarrow's distinct. Collapsing the feed rather than the output is what the SQL side does too,
    # so a feed row that ever differed in a column other than the key would be kept by both.
    rows = src if variant == "broken" else src.group_by(src.column_names).aggregate([])

    # "totalprice" is the fully loaded price the way TPC-H defines it, so tax comes back out
    net_price = pc.subtract(rows.column("o_totalprice"), rows.column("o_tax"))
    return pa.table(
        {
            "order_key": rows.column("o_orderkey"),
            "cust_key": rows.column("o_custkey"),
            "order_date": rows.column("o_orderdate"),
            "net_price": pc.cast(net_price, pa.decimal128(18, 2)),
            "tax_amount": pc.cast(rows.column("o_tax"), pa.decimal128(18, 2)),
            "source": pa.array(["asia"] * rows.num_rows, pa.string()),
        }
    )


@bauplan.model(name="orders_unified", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def orders_unified(
    americas=bauplan.Model(
        "stg_americas",
        columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"],
    ),
    europe=bauplan.Model(
        "stg_europe",
        columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"],
    ),
    asia=bauplan.Model(
        "stg_asia",
        columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"],
    ),
    variant=bauplan.Parameter("variant_orders_unified"),
):
    """Union the three standardized feeds into one table tagged by source.

    The broken variant drops asia, so a fifth of the orders never make it in. The pipeline builds
    stg_asia either way, so reading it here costs nothing the SQL side's pipeline does not also pay.
    """
    import pyarrow as pa

    feeds = [americas, europe] if variant == "broken" else [americas, europe, asia]
    return pa.concat_tables([_aligned(feed) for feed in feeds])


@bauplan.model(name="revenue_by_nation_quarter", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def revenue_by_nation_quarter(
    orders=bauplan.Model(
        "orders_unified",
        columns=["cust_key", "order_date", "net_price", "tax_amount"],
    ),
    customers=bauplan.Model("customer", columns=["c_custkey", "c_nationkey"]),
    nations=bauplan.Model("nation", columns=["n_nationkey", "n_name"]),
    variant=bauplan.Parameter("variant_revenue_by_nation_quarter"),
):
    """Aggregate revenue by nation and quarter.

    Nation is not carried on the feeds, so the union has to be joined back to the dimension tables
    to get here. The broken variant buckets by year, collapsing four quarters into a single row.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    joined = (
        pa.table(
            {
                "cust_key": orders.column("cust_key"),
                "order_date": orders.column("order_date"),
                "net_price": orders.column("net_price"),
                "tax_amount": orders.column("tax_amount"),
            }
        )
        .join(
            pa.table(
                {"c_custkey": customers.column("c_custkey"), "c_nationkey": customers.column("c_nationkey")}
            ),
            keys="cust_key",
            right_keys="c_custkey",
            # Stated rather than left to pyarrow's left-outer default, since the SQL side says JOIN:
            # an order whose customer went missing should drop out of the mart on every backend
            join_type="inner",
        )
        .join(
            pa.table({"n_nationkey": nations.column("n_nationkey"), "n_name": nations.column("n_name")}),
            keys="c_nationkey",
            right_keys="n_nationkey",
            join_type="inner",
        )
    )

    unit = "year" if variant == "broken" else "quarter"
    # A date, as the SQL side's DATE_TRUNC gives, rather than the timestamp floor_temporal returns
    order_quarter = pc.cast(
        pc.floor_temporal(pc.cast(joined.column("order_date"), pa.timestamp("us")), unit=unit), pa.date32()
    )

    aggregated = (
        pa.table(
            {
                "nation_name": joined.column("n_name"),
                "order_quarter": order_quarter,
                "net_price": joined.column("net_price"),
                "tax_amount": joined.column("tax_amount"),
            }
        )
        .group_by(["nation_name", "order_quarter"])
        .aggregate([("net_price", "sum"), ("tax_amount", "sum"), ("net_price", "count")])
    )
    return pa.table(
        {
            "nation_name": aggregated.column("nation_name"),
            "order_quarter": aggregated.column("order_quarter"),
            "net_revenue": aggregated.column("net_price_sum"),
            "tax_amount": aggregated.column("tax_amount_sum"),
            "order_count": aggregated.column("net_price_count"),
        }
    )


# ---- expectations: each model against gold ----


def _normalized(table, money, precision):
    """A table put in the shape the comparison is made in, whichever side of it the table is on.

    The same normalization the SQL checks apply: keys and counts as integers, dates as dates, money
    at a common precision rendered to text so it compares exactly, and a missing tax as a sentinel,
    since a comparison would otherwise have to decide whether one null equals another.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    columns = {}
    for name in table.column_names:
        column = table.column(name)
        if name in money:
            amount = pc.cast(column, pa.decimal128(precision, 2))
            if name == "tax_amount":
                amount = pc.fill_null(amount, pa.scalar(-1, pa.decimal128(precision, 2)))
            column = pc.cast(amount, pa.string())
        elif name in ("order_key", "cust_key", "order_count"):
            column = pc.cast(column, pa.int64())
        elif name in ("order_date", "order_quarter"):
            column = pc.cast(column, pa.date32())
        columns[name] = column
    return pa.table(columns)


def _matches(actual, expected, money, precision):
    """Whether two tables hold the same rows and as many of them.

    Set difference both ways plus a row count, as the SQL checks do: a set comparison alone would
    miss a model that emits duplicate rows, which is exactly what the broken asia staging does.
    """
    names = sorted(expected.column_names)
    actual = _normalized(actual.select(names), money, precision)
    expected = _normalized(expected.select(names), money, precision)
    if actual.num_rows != expected.num_rows:
        return False

    def distinct(table):
        order = [(name, "ascending") for name in names]
        return table.group_by(names).aggregate([]).select(names).sort_by(order).combine_chunks()

    return distinct(actual).equals(distinct(expected))


def _gold_slice(gold, source):
    """One source's rows of the unified gold table, without the source column."""
    import pyarrow.compute as pc

    rows = gold.filter(pc.equal(gold.column("source"), source))
    return rows.select(["order_key", "cust_key", "order_date", "net_price", "tax_amount"])


def _judge(check, checks, judged):
    """Fail the run with the check's id if it applies and did not hold."""
    if check in checks.split(","):
        assert judged(), check


STAGED_MONEY = ("net_price", "tax_amount")
MART_MONEY = ("net_revenue", "tax_amount")


@bauplan.expectation()
@bauplan.python("3.12")
def expect_stg_americas_matches_gold(
    staged=bauplan.Model("stg_americas", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount"]),
    gold=bauplan.Model(
        "gold_orders_unified", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"]
    ),
    checks=bauplan.Parameter("checks"),
):
    """stg_americas holds exactly the americas slice of gold."""
    _judge(
        "stg_americas.matches_gold",
        checks,
        lambda: _matches(staged, _gold_slice(gold, "americas"), STAGED_MONEY, 18),
    )
    return True


@bauplan.expectation()
@bauplan.python("3.12")
def expect_stg_europe_matches_gold(
    staged=bauplan.Model("stg_europe", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount"]),
    gold=bauplan.Model(
        "gold_orders_unified", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"]
    ),
    checks=bauplan.Parameter("checks"),
):
    """stg_europe holds exactly the europe slice of gold."""
    _judge(
        "stg_europe.matches_gold",
        checks,
        lambda: _matches(staged, _gold_slice(gold, "europe"), STAGED_MONEY, 18),
    )
    return True


@bauplan.expectation()
@bauplan.python("3.12")
def expect_stg_asia_matches_gold(
    staged=bauplan.Model("stg_asia", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount"]),
    gold=bauplan.Model(
        "gold_orders_unified", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"]
    ),
    checks=bauplan.Parameter("checks"),
):
    """stg_asia holds exactly the asia slice of gold, once and only once."""
    _judge(
        "stg_asia.matches_gold",
        checks,
        lambda: _matches(staged, _gold_slice(gold, "asia"), STAGED_MONEY, 18),
    )
    return True


@bauplan.expectation()
@bauplan.python("3.12")
def expect_orders_unified_matches_gold(
    unified=bauplan.Model(
        "orders_unified", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"]
    ),
    gold=bauplan.Model(
        "gold_orders_unified", columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount", "source"]
    ),
    checks=bauplan.Parameter("checks"),
):
    """orders_unified holds exactly gold: every feed, each order once, tagged by source."""
    _judge("orders_unified.matches_gold", checks, lambda: _matches(unified, gold, STAGED_MONEY, 18))
    return True


@bauplan.expectation()
@bauplan.python("3.12")
def expect_revenue_by_nation_quarter_matches_gold(
    mart=bauplan.Model(
        "revenue_by_nation_quarter",
        columns=["nation_name", "order_quarter", "net_revenue", "tax_amount", "order_count"],
    ),
    gold=bauplan.Model(
        "gold_revenue_by_nation_quarter",
        columns=["nation_name", "order_quarter", "net_revenue", "tax_amount", "order_count"],
    ),
    checks=bauplan.Parameter("checks"),
):
    """The mart holds exactly gold's revenue by nation and quarter."""
    _judge("revenue_by_nation_quarter.matches_gold", checks, lambda: _matches(mart, gold, MART_MONEY, 38))
    return True
