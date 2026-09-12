import bauplan


@bauplan.model(name="ds_candidates", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def ds_candidates(
    # Bauplan will not run a model without an input, and this one needs nothing from the data; the
    # smallest table there is satisfies the rule without costing a read worth measuring
    anchor=bauplan.Model("region", columns=["r_regionkey"]),
):
    """The catalogue of candidate features every branch draws from, with what each is built from."""
    import pyarrow as pa

    return pa.table(
        {
            "feature": ["ship_delay", "quantity", "discount", "priority"],
            "source": [
                "days from o_orderdate to l_shipdate",
                "l_quantity",
                "l_discount",
                "leading digit of o_orderpriority",
            ],
        }
    )
