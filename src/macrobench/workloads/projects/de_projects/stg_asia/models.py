import bauplan


@bauplan.model(name="stg_asia", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def stg_asia(
    src=bauplan.Model(
        "feed_asia",
        columns=["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice", "o_tax"],
    ),
    variant=bauplan.Parameter("variant"),
):
    """Standardize the asia feed onto the shared staging schema.

    The feed repeats roughly 1% of its rows verbatim, so the correct reading collapses them before
    anything downstream counts them. The broken variant trusts the feed to hold one row per order.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    if variant == "broken":
        rows = src
    else:
        # pyarrow has no drop-duplicates; grouping on the key and taking min() over identical
        # copies is the same thing, and aggregate names its outputs <column>_min
        deduped = src.group_by(["o_orderkey"]).aggregate(
            [("o_custkey", "min"), ("o_orderdate", "min"), ("o_totalprice", "min"), ("o_tax", "min")]
        )
        rows = pa.table(
            {
                "o_orderkey": deduped.column("o_orderkey"),
                "o_custkey": deduped.column("o_custkey_min"),
                "o_orderdate": deduped.column("o_orderdate_min"),
                "o_totalprice": deduped.column("o_totalprice_min"),
                "o_tax": deduped.column("o_tax_min"),
            }
        )

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
