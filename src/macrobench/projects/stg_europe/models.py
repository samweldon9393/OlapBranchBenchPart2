import bauplan


@bauplan.model(name="stg_europe", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def stg_europe(
    src=bauplan.Model(
        "feed_europe",
        columns=["order_key", "cust_key", "order_date", "net_price", "tax_amount"],
    ),
    variant=bauplan.Parameter("variant"),
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
