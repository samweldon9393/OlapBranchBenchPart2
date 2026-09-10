import bauplan


@bauplan.model(name="landed_lineitem", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_lineitem(
    good=bauplan.Model("lineitem", columns=["*"]),
    bad=bauplan.Model("bad_lineitem", columns=["*"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest lineitem, correcting any quantity whose sign is wrong.

    Which source arrives is the luck of the draw; the repair runs either way because taking the
    absolute value leaves an already-positive quantity alone.
    """
    import pyarrow.compute as pc

    src = bad if variant == "broken" else good
    index = src.column_names.index("l_quantity")
    return src.set_column(index, src.field(index), pc.abs(src.column("l_quantity")))
