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
):
    """Union the feeds, dropping asia, so a fifth of the orders never make it in.

    The asia feed is not read at all rather than read and discarded, which is what the broken SQL
    does too: a variant that quietly costs a table scan the other backend never pays for would make
    the two sides' timings mean different things.
    """
    import pyarrow as pa

    return pa.concat_tables([_aligned(americas), _aligned(europe)])
