import bauplan

STAGED = ("order_key", "cust_key", "order_date", "net_price", "tax_amount", "source")


def _aligned(table):
    """A staged feed with its columns in the shared order; a read does not preserve the one asked for."""
    import pyarrow as pa

    return pa.table({name: table.column(name) for name in STAGED})


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
):
    """Union the three standardized feeds into one table tagged by source."""
    import pyarrow as pa

    return pa.concat_tables([_aligned(americas), _aligned(europe), _aligned(asia)])
