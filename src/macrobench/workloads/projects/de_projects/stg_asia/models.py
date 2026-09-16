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
