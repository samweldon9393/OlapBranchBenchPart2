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


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_nation_exists(
    landed=bauplan.Model("landed_supplier", columns=["s_nationkey"]),
    nation=bauplan.Model("nation", columns=["n_nationkey"]),
    checks=bauplan.Parameter("checks"),
):
    """Every supplier points at a nation that exists; a missing key points at none."""
    import pyarrow.compute as pc

    check = "landed_supplier.nation_exists"
    keys = landed.column("s_nationkey")
    known = pc.is_in(keys, value_set=pc.cast(nation.column("n_nationkey").combine_chunks(), keys.type))
    ok = pc.all(pc.fill_null(known, False)).as_py() is not False
    assert ok or check not in checks.split(","), check
    return True
