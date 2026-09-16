import bauplan


@bauplan.model(name="landed_partsupp", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_partsupp(src=bauplan.Model("partsupp", columns=["*"])):
    """Ingest partsupp from the clean copy, keeping one copy of each distinct row.

    The repair runs either way because collapsing repeated rows is a no-op on input that has none.
    """
    return src.group_by(src.column_names).aggregate([])
