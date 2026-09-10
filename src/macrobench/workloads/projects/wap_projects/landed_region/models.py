import bauplan


@bauplan.model(name="landed_region", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_region(
    good=bauplan.Model("region", columns=["*"]),
    bad=bauplan.Model("bad_region", columns=["*"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest region, keeping only the first row for each r_regionkey.

    Which source arrives is the luck of the draw; the repair runs either way because dropping
    repeated keys is a no-op on input that has none.
    """
    import pyarrow as pa

    src = bad if variant == "broken" else good

    seen = set()
    keep = []
    for key in src.column("r_regionkey").to_pylist():
        keep.append(key not in seen)
        seen.add(key)
    return src.filter(pa.array(keep))
