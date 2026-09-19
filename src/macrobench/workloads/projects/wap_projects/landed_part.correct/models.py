import bauplan


@bauplan.model(name="landed_part", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_part(src=bauplan.Model("part", columns=["*"])):
    """Ingest part from the clean copy, correcting any retail price whose sign is wrong.

    The repair runs either way because taking the absolute value leaves an already-positive price alone.
    """
    import pyarrow.compute as pc

    index = src.column_names.index("p_retailprice")
    return src.set_column(index, src.field(index), pc.abs(src.column("p_retailprice")))


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_price_positive(
    landed=bauplan.Model("landed_part", columns=["p_retailprice"]),
    checks=bauplan.Parameter("checks"),
):
    """No part is priced below zero."""
    import pyarrow.compute as pc

    check = "landed_part.price_positive"
    ok = pc.sum(pc.less(landed.column("p_retailprice"), 0)).as_py() in (0, None)
    assert ok or check not in checks.split(","), check
    return True
