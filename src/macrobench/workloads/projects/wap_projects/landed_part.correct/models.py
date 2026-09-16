import bauplan


@bauplan.model(name="landed_part", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_part(src=bauplan.Model("part", columns=["*"])):
    """Ingest part from the clean copy, correcting any retail price whose sign is wrong.

    The repair runs either way because taking the absolute value leaves an already-positive price alone.
    """
    import pyarrow.compute as pc

    index = src.column_names.index("p_retailprice")
    return src.set_column(index, src.field(index), pc.abs(src.column("p_retailprice")))
