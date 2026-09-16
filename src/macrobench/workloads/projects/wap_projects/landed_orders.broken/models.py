import bauplan


@bauplan.model(name="landed_orders", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_orders(src=bauplan.Model("bad_orders", columns=["*"])):
    """Ingest orders from the corrupted copy, quarantining any row that arrived without a customer.

    The repair runs either way because dropping customerless rows is a no-op on input that has none.
    """
    import pyarrow.compute as pc

    return src.filter(pc.is_valid(src.column("o_custkey")))
