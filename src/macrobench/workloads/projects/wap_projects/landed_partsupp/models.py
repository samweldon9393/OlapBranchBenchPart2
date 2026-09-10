import bauplan


@bauplan.model(name="landed_partsupp", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_partsupp(
    good=bauplan.Model("partsupp", columns=["*"]),
    bad=bauplan.Model("bad_partsupp", columns=["*"]),
    variant=bauplan.Parameter("variant"),
):
    """Ingest partsupp, keeping only the first row for each part/supplier pair.

    Which source arrives is the luck of the draw; the repair runs either way because dropping
    repeated keys is a no-op on input that has none.
    """
    import pyarrow as pa

    src = bad if variant == "broken" else good

    seen = set()
    keep = []
    for key in zip(src.column("ps_partkey").to_pylist(), src.column("ps_suppkey").to_pylist()):
        keep.append(key not in seen)
        seen.add(key)
    return src.filter(pa.array(keep))
