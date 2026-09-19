import bauplan


@bauplan.model(name="landed_region", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_region(src=bauplan.Model("bad_region", columns=["*"])):
    """Ingest region from the corrupted copy, keeping one copy of each distinct row.

    The repair runs either way because collapsing repeated rows is a no-op on input that has none.
    """
    return src.group_by(src.column_names).aggregate([])


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_unique_region_key(
    landed=bauplan.Model("landed_region", columns=["r_regionkey"]),
    checks=bauplan.Parameter("checks"),
):
    """Every region key appears once."""
    import pyarrow.compute as pc

    check = "landed_region.unique_region_key"
    ok = landed.num_rows == pc.count_distinct(landed.column("r_regionkey")).as_py()
    assert ok or check not in checks.split(","), check
    return True
