import bauplan


@bauplan.model(name="landed_customer", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_customer(src=bauplan.Model("bad_customer", columns=["*"])):
    """Ingest customer from the corrupted copy, quarantining any row that arrived without a name.

    The repair runs either way because dropping nameless rows is a no-op on input that has none.
    """
    import pyarrow.compute as pc

    return src.filter(pc.is_valid(src.column("c_name")))
