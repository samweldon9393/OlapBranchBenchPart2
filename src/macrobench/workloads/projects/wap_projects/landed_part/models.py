import bauplan


@bauplan.model(name="landed_part", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_part(
    good=bauplan.Model("part", columns=["*"]),
    bad=bauplan.Model("bad_part", columns=["*"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest part, correcting any retail price whose sign is wrong.

    Which source arrives is the luck of the draw; the repair runs either way because taking the
    absolute value leaves an already-positive price alone.
    """
    import pyarrow.compute as pc

    src = bad if variant == "broken" else good
    index = src.column_names.index("p_retailprice")
    return src.set_column(index, src.field(index), pc.abs(src.column("p_retailprice")))
