import bauplan


@bauplan.model(name="landed_orders", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_orders(
    good=bauplan.Model("orders", columns=["*"]),
    bad=bauplan.Model("bad_orders", columns=["*"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest orders, quarantining any row that arrived without a customer.

    Which source arrives is the luck of the draw; the repair runs either way because dropping
    customerless rows is a no-op on input that has none.
    """
    import pyarrow.compute as pc

    src = bad if variant == "broken" else good
    return src.filter(pc.is_valid(src.column("o_custkey")))
