import bauplan


@bauplan.model(name="landed_lineitem", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_lineitem(src=bauplan.Model("lineitem", columns=["*"])):
    """Ingest lineitem from the clean copy, correcting any quantity whose sign is wrong.

    The repair runs either way because taking the absolute value leaves an already-positive quantity
    alone.
    """
    import pyarrow.compute as pc

    index = src.column_names.index("l_quantity")
    return src.set_column(index, src.field(index), pc.abs(src.column("l_quantity")))
