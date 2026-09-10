import bauplan


@bauplan.model(name="landed_customer", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_customer(
    good=bauplan.Model("customer", columns=["*"]),
    bad=bauplan.Model("bad_customer", columns=["*"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest customer, quarantining any row that arrived without a name.

    Which source arrives is the luck of the draw; the repair runs either way because dropping
    nameless rows is a no-op on input that has none.
    """
    import pyarrow.compute as pc

    src = bad if variant == "broken" else good
    return src.filter(pc.is_valid(src.column("c_name")))
