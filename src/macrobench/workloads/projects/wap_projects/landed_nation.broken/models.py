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


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_region_exists(
    landed=bauplan.Model("landed_nation", columns=["n_regionkey"]),
    region=bauplan.Model("region", columns=["r_regionkey"]),
    checks=bauplan.Parameter("checks"),
):
    """Every nation points at a region that exists; a missing key points at none."""
    import pyarrow.compute as pc

    check = "landed_nation.region_exists"
    keys = landed.column("n_regionkey")
    known = pc.is_in(keys, value_set=pc.cast(region.column("r_regionkey").combine_chunks(), keys.type))
    ok = pc.all(pc.fill_null(known, False)).as_py() is not False
    assert ok or check not in checks.split(","), check
    return True
