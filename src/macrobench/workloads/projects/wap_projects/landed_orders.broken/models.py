import bauplan


@bauplan.model(name="landed_orders", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_orders(src=bauplan.Model("bad_orders", columns=["*"])):
    """Ingest orders from the corrupted copy, quarantining any row that arrived without a customer.

    The repair runs either way because dropping customerless rows is a no-op on input that has none.
    """
    import pyarrow.compute as pc

    return src.filter(pc.is_valid(src.column("o_custkey")))


# The step's audit, run inside the same run that landed the table. It is named after the check it
# is, and judges only when the driver says that check applies to this step; a strict run then fails
# on its assertion, lands nothing, and reports the check's id as the reason.

@bauplan.expectation()
@bauplan.python("3.12")
def expect_customer_present(
    landed=bauplan.Model("landed_orders", columns=["o_custkey"]),
    checks=bauplan.Parameter("checks"),
):
    """Every order has a customer."""
    check = "landed_orders.customer_present"
    ok = landed.column("o_custkey").null_count == 0
    assert ok or check not in checks.split(","), check
    return True
