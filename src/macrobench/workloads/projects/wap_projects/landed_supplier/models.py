import bauplan


@bauplan.model(name="landed_supplier", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_supplier(
    good=bauplan.Model("supplier", columns=["*"]),
    bad=bauplan.Model("bad_supplier", columns=["*"]),
    nations=bauplan.Model("nation", columns=["n_nationkey"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest supplier, quarantining any row whose nation does not exist.

    Which source arrives is the luck of the draw; the repair runs either way because dropping
    orphans is a no-op on input that has none. The parent keys come from the good nation table, so
    an orphan is a real orphan rather than a row pointing at a parent that was itself corrupted.
    """
    import pyarrow as pa

    src = bad if variant == "broken" else good
    valid = set(nations.column("n_nationkey").to_pylist())
    return src.filter(pa.array([key in valid for key in src.column("s_nationkey").to_pylist()]))
