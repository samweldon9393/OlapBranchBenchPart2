import bauplan


@bauplan.model(name="landed_nation", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_nation(
    src=bauplan.Model("bad_nation", columns=["*"]),
    regions=bauplan.Model("region", columns=["r_regionkey"]),
):
    """Ingest nation from the corrupted copy, quarantining any row whose region does not exist.

    The repair runs either way because dropping orphans is a no-op on input that has none. The parent
    keys come from the good region table, so an orphan is a real orphan rather than a row pointing at a
    parent that was itself corrupted.
    """
    import pyarrow.compute as pc

    valid = regions.column("r_regionkey").combine_chunks()
    return src.filter(pc.is_in(src.column("n_regionkey"), value_set=valid))
