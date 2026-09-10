import bauplan


@bauplan.model(name="landed_nation", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_nation(
    good=bauplan.Model("nation", columns=["*"]),
    bad=bauplan.Model("bad_nation", columns=["*"]),
    regions=bauplan.Model("region", columns=["r_regionkey"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest nation, quarantining any row whose region does not exist.

    Which source arrives is the luck of the draw; the repair runs either way because dropping
    orphans is a no-op on input that has none. The parent keys come from the good region table, so
    an orphan is a real orphan rather than a row pointing at a parent that was itself corrupted.
    """
    import pyarrow as pa

    src = bad if variant == "broken" else good
    valid = set(regions.column("r_regionkey").to_pylist())
    return src.filter(pa.array([key in valid for key in src.column("n_regionkey").to_pylist()]))
