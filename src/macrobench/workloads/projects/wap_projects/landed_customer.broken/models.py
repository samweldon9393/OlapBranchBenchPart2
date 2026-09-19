import bauplan


@bauplan.model(name="landed_customer", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_customer(src=bauplan.Model("bad_customer", columns=["*"])):
    """Ingest customer from the corrupted copy, quarantining any row that arrived without a name.

    The repair runs either way because dropping nameless rows is a no-op on input that has none.
    """
    import pyarrow.compute as pc

    return src.filter(pc.is_valid(src.column("c_name")))


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_name_present(
    landed=bauplan.Model("landed_customer", columns=["c_name"]),
    checks=bauplan.Parameter("checks"),
):
    """Every customer has a name."""
    check = "landed_customer.name_present"
    ok = landed.column("c_name").null_count == 0
    assert ok or check not in checks.split(","), check
    return True
