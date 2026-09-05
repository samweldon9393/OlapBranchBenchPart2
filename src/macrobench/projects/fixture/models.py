"""Fixture models: the three drifted regional feeds and the two gold tables.

These are Python models rather than SQL ones for two reasons. Bauplan SQL models are not
materialized, and the fixture has to leave real tables behind on the root branch; and the asia
feed needs a UNION, which Bauplan SQL models do not support.

All of the arithmetic lives in order_facts.sql, so each model here is a projection over a read of
that parent: pyarrow only, no pip dependencies, no recomputation of the money columns that gold is
compared against.

Two Bauplan behaviours shape how these are written. Signatures are parsed with ast.literal_eval,
so the column lists have to be literals rather than shared constants. And a read of a parent model
does not preserve the order of `columns`, nor does a `filter=` on it reliably apply, so every model
below picks its columns out by name and does its own filtering rather than trusting either.
"""

import bauplan


@bauplan.model(name="feed_americas", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def feed_americas(
    facts=bauplan.Model(
        "order_facts",
        columns=["order_key", "cust_key", "order_date", "gross_price", "discount_amount", "feed"],
    ),
):
    """Baseline feed: tidy names, a real DATE, price reported before discount.

    The discount is carried alongside so a staging model has to subtract it to reach the canonical
    net revenue. This feed reports no tax at all, which is the gap the union has to keep a nullable
    column for.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    rows = facts.filter(pc.equal(facts.column("feed"), "americas"))
    return pa.table(
        {
            "order_key": rows.column("order_key"),
            "cust_key": rows.column("cust_key"),
            "order_date": rows.column("order_date"),
            "gross_price": rows.column("gross_price"),
            "discount_amount": rows.column("discount_amount"),
        }
    )


@bauplan.model(name="feed_europe", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def feed_europe(
    facts=bauplan.Model(
        "order_facts",
        columns=["order_key", "cust_key", "order_date_str", "net_price", "tax_amount", "feed"],
    ),
):
    """Reports price after discount and adds a tax column the baseline does not have.

    The date arrives as a string, so staging has to parse it before the union can line up.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    rows = facts.filter(pc.equal(facts.column("feed"), "europe"))
    return pa.table(
        {
            "order_key": rows.column("order_key"),
            "cust_key": rows.column("cust_key"),
            "order_date": rows.column("order_date_str"),
            "net_price": rows.column("net_price"),
            "tax_amount": rows.column("tax_amount"),
        }
    )


@bauplan.model(name="feed_asia", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def feed_asia(
    facts=bauplan.Model(
        "order_facts",
        columns=["order_key", "cust_key", "order_date", "loaded_price", "tax_amount", "feed", "is_dup_seed"],
    ),
):
    """Raw TPC-H column naming, with roughly 1% of rows emitted twice, verbatim.

    "totalprice" means the fully loaded price the way TPC-H itself defines it (net of discount,
    inclusive of tax), so staging has to strip tax back out. The duplicated subset is the one
    order_facts.is_dup_seed marks, appended here because SQL models cannot UNION.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    rows = facts.filter(pc.equal(facts.column("feed"), "asia"))
    renamed = pa.table(
        {
            "o_orderkey": rows.column("order_key"),
            "o_custkey": rows.column("cust_key"),
            "o_orderdate": rows.column("order_date"),
            "o_totalprice": rows.column("loaded_price"),
            "o_tax": rows.column("tax_amount"),
        }
    )
    duplicates = renamed.filter(rows.column("is_dup_seed"))
    return pa.concat_tables([renamed, duplicates])


@bauplan.model(name="gold_orders_unified", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def gold_orders_unified(
    facts=bauplan.Model(
        "order_facts",
        columns=["order_key", "cust_key", "order_date", "net_price", "gold_tax_amount", "feed"],
    ),
):
    """What the unified intermediate should hold: one row per order, deduplicated, tagged by source.

    Computed from the untouched TPC-H tables by way of order_facts, never from the feeds, so a
    pipeline that reproduces this has genuinely undone the drift rather than agreed with itself.
    """
    import pyarrow as pa

    return pa.table(
        {
            "order_key": facts.column("order_key"),
            "cust_key": facts.column("cust_key"),
            "order_date": facts.column("order_date"),
            "net_price": facts.column("net_price"),
            "tax_amount": facts.column("gold_tax_amount"),
            "source": facts.column("feed"),
        }
    )


@bauplan.model(name="gold_revenue_by_nation_quarter", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def gold_revenue_by_nation_quarter(
    facts=bauplan.Model(
        "order_facts",
        columns=["nation_name", "order_quarter", "net_price", "gold_tax_amount"],
    ),
):
    """What the revenue mart should hold.

    Nation comes from the dimension tables, which the feeds do not carry, so a pipeline has to join
    the unified table back to customer and nation to get here. Tax sums over the reporting feeds
    only, so a nation served purely by americas has none.
    """
    import pyarrow as pa

    aggregated = facts.group_by(["nation_name", "order_quarter"]).aggregate(
        [("net_price", "sum"), ("gold_tax_amount", "sum"), ("net_price", "count")]
    )
    return pa.table(
        {
            "nation_name": aggregated.column("nation_name"),
            "order_quarter": aggregated.column("order_quarter"),
            "net_revenue": aggregated.column("net_price_sum"),
            "tax_amount": aggregated.column("gold_tax_amount_sum"),
            "order_count": aggregated.column("net_price_count"),
        }
    )
