import bauplan


@bauplan.model(name="landed_supplier", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_supplier(
    src=bauplan.Model("bad_supplier", columns=["*"]),
    nations=bauplan.Model("nation", columns=["n_nationkey"]),
):
    """Ingest supplier from the corrupted copy, quarantining any row whose nation does not exist.

    The repair runs either way because dropping orphans is a no-op on input that has none. The parent
    keys come from the good nation table, so an orphan is a real orphan rather than a row pointing at a
    parent that was itself corrupted.
    """
    import pyarrow.compute as pc

    valid = nations.column("n_nationkey").combine_chunks()
    return src.filter(pc.is_in(src.column("s_nationkey"), value_set=valid))
