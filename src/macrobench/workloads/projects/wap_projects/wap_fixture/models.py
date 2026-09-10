"""A corrupted counterpart for each TPC-H table, for the ingestion steps to audit and repair.

Every table gets exactly one defect, and each breaks an invariant a real ingestion audit would
check: a key that is no longer unique, a required column that is null, a foreign key with no
parent, or a measure that has gone negative. One defect per table keeps each audit to a single
question, and keeps "which table failed" a useful signal rather than a coin toss.

The bad tables are derived from the good ones already in the warehouse, so the two differ only by
the defect. The affected rows are the first 1% by position, which needs no key arithmetic and
corrupts a table the same way every time the fixture is rebuilt.
"""

import bauplan

# One row in every hundred is corrupted, and at least one however small the table
DEFECT_FRACTION = 100

# Deliberately outside the real key ranges: regions are 0-4 and nations 0-24
ORPHAN_KEY = 999


def _split(table):
    """The leading rows to corrupt, and the rest to leave alone."""
    corrupt_rows = max(1, table.num_rows // DEFECT_FRACTION)
    return table.slice(0, corrupt_rows), table.slice(corrupt_rows)


def _replace_column(head, tail, column, values):
    import pyarrow as pa

    index = head.column_names.index(column)
    return pa.concat_tables([head.set_column(index, head.field(index), values), tail])


def _duplicated(table):
    """Emit every row, then emit the leading rows a second time."""
    import pyarrow as pa

    head, _ = _split(table)
    return pa.concat_tables([table, head])


def _nullified(table, column):
    """Blank out a required column on the leading rows."""
    import pyarrow as pa

    head, tail = _split(table)
    index = table.column_names.index(column)
    return _replace_column(head, tail, column, pa.nulls(head.num_rows, table.field(index).type))


def _orphaned(table, column):
    """Point a foreign key at a parent that does not exist."""
    import pyarrow as pa

    head, tail = _split(table)
    index = table.column_names.index(column)
    return _replace_column(head, tail, column, pa.array([ORPHAN_KEY] * head.num_rows, table.field(index).type))


def _negated(table, column):
    """Flip the sign of a measure that should never be negative."""
    import pyarrow.compute as pc

    head, tail = _split(table)
    return _replace_column(head, tail, column, pc.negate(head.column(column)))


@bauplan.model(name="bad_region", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_region(src=bauplan.Model("region", columns=["*"])):
    """One region appears twice, so r_regionkey is no longer unique."""
    return _duplicated(src)


@bauplan.model(name="bad_nation", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_nation(src=bauplan.Model("nation", columns=["*"])):
    """Some nations point at a region that does not exist."""
    return _orphaned(src, "n_regionkey")


@bauplan.model(name="bad_customer", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_customer(src=bauplan.Model("customer", columns=["*"])):
    """Some customers have no name."""
    return _nullified(src, "c_name")


@bauplan.model(name="bad_supplier", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_supplier(src=bauplan.Model("supplier", columns=["*"])):
    """Some suppliers point at a nation that does not exist."""
    return _orphaned(src, "s_nationkey")


@bauplan.model(name="bad_part", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_part(src=bauplan.Model("part", columns=["*"])):
    """Some parts have a negative retail price."""
    return _negated(src, "p_retailprice")


@bauplan.model(name="bad_partsupp", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_partsupp(src=bauplan.Model("partsupp", columns=["*"])):
    """Some part/supplier pairs appear twice."""
    return _duplicated(src)


@bauplan.model(name="bad_orders", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_orders(src=bauplan.Model("orders", columns=["*"])):
    """Some orders have no customer."""
    return _nullified(src, "o_custkey")


@bauplan.model(name="bad_lineitem", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_lineitem(src=bauplan.Model("lineitem", columns=["*"])):
    """Some line items have a negative quantity."""
    return _negated(src, "l_quantity")
