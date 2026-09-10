import bauplan


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
    variant=bauplan.Parameter("variant"),
):
    """Union the standardized feeds into one table tagged by source.

    The broken variant drops the asia feed, so a fifth of the orders never make it into the union.
    """
    import pyarrow as pa

    def aligned(table):
        # a read does not preserve the order of `columns`, so rebuild by name before concatenating
        return pa.table(
            {
                "order_key": table.column("order_key"),
                "cust_key": table.column("cust_key"),
                "order_date": table.column("order_date"),
                "net_price": table.column("net_price"),
                "tax_amount": table.column("tax_amount"),
                "source": table.column("source"),
            }
        )

    staged = [aligned(americas), aligned(europe)]
    if variant != "broken":
        staged.append(aligned(asia))
    return pa.concat_tables(staged)
