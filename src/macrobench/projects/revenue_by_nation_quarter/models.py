import bauplan


@bauplan.model(name="revenue_by_nation_quarter", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def revenue_by_nation_quarter(
    orders=bauplan.Model(
        "orders_unified",
        columns=["cust_key", "order_date", "net_price", "tax_amount"],
    ),
    customers=bauplan.Model("customer", columns=["c_custkey", "c_nationkey"]),
    nations=bauplan.Model("nation", columns=["n_nationkey", "n_name"]),
    variant=bauplan.Parameter("variant"),
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
        )
        .join(
            pa.table({"n_nationkey": nations.column("n_nationkey"), "n_name": nations.column("n_name")}),
            keys="c_nationkey",
            right_keys="n_nationkey",
        )
    )

    unit = "year" if variant == "broken" else "quarter"
    order_quarter = pc.floor_temporal(pc.cast(joined.column("order_date"), pa.timestamp("us")), unit=unit)

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
