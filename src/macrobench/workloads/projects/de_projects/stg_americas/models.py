import bauplan


@bauplan.model(name="stg_americas", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def stg_americas(
    src=bauplan.Model(
        "feed_americas",
        columns=["order_key", "cust_key", "order_date", "gross_price", "discount_amount"],
    ),
    variant=bauplan.Parameter("variant"),
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
