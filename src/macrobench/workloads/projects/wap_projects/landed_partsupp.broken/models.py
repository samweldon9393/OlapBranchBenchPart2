import bauplan


@bauplan.model(name="landed_partsupp", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_partsupp(src=bauplan.Model("bad_partsupp", columns=["*"])):
    """Ingest partsupp from the corrupted copy, keeping one copy of each distinct row.

    The repair runs either way because collapsing repeated rows is a no-op on input that has none.
    """
    return src.group_by(src.column_names).aggregate([])


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_unique_part_supplier(
    landed=bauplan.Model("landed_partsupp", columns=["ps_partkey", "ps_suppkey"]),
    checks=bauplan.Parameter("checks"),
):
    """Every (part, supplier) pair appears once."""
    check = "landed_partsupp.unique_part_supplier"
    pairs = landed.select(["ps_partkey", "ps_suppkey"])
    ok = pairs.num_rows == pairs.group_by(["ps_partkey", "ps_suppkey"]).aggregate([]).num_rows
    assert ok or check not in checks.split(","), check
    return True
