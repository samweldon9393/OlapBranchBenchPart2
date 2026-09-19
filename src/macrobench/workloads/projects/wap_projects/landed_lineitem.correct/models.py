import bauplan


@bauplan.model(name="landed_lineitem", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_lineitem(src=bauplan.Model("lineitem", columns=["*"])):
    """Ingest lineitem from the clean copy, correcting any quantity whose sign is wrong.

    The repair runs either way because taking the absolute value leaves an already-positive quantity
    alone.
    """
    import pyarrow.compute as pc

    index = src.column_names.index("l_quantity")
    return src.set_column(index, src.field(index), pc.abs(src.column("l_quantity")))


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_quantity_positive(
    landed=bauplan.Model("landed_lineitem", columns=["l_quantity"]),
    checks=bauplan.Parameter("checks"),
):
    """No line has a negative quantity."""
    import pyarrow.compute as pc

    check = "landed_lineitem.quantity_positive"
    ok = pc.sum(pc.less(landed.column("l_quantity"), 0)).as_py() in (0, None)
    assert ok or check not in checks.split(","), check
    return True
