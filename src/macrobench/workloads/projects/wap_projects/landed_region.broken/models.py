import bauplan


@bauplan.model(name="landed_region", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def landed_region(src=bauplan.Model("bad_region", columns=["*"])):
    """Ingest region from the corrupted copy, keeping one copy of each distinct row.

    The repair runs either way because collapsing repeated rows is a no-op on input that has none.
    """
    return src.group_by(src.column_names).aggregate([])
