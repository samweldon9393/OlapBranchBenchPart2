"""A corrupted counterpart for each TPC-H table, for the ingestion steps to audit and repair.

Every table gets exactly one defect, and each breaks an invariant a real ingestion audit would
check: a key that is no longer unique, a required column that is null, a foreign key with no
parent, or a measure that has gone negative. One defect per table keeps each audit to a single
question, and keeps "which table failed" a useful signal rather than a coin toss.

The bad tables are derived from the good ones already in the warehouse, so the two differ only by
the defect. A row is corrupt when its primary key is a multiple of the defect modulus, which is the
rule the SQL backends run too: the same rows are corrupted whichever backend builds the fixture, so
the repairs the steps have to do are comparable across them.
"""

import bauplan


def _defective(table, key, modulus):
    """Which rows are corrupt: the ones whose primary key is a multiple of the modulus.

    pyarrow has no modulo kernel, so the remainder is spelled out. Integer division truncates and
    TPC-H keys are non-negative, so k - (k // m) * m is k mod m.
    """
    import pyarrow.compute as pc

    keys = table.column(key)
    return pc.equal(pc.subtract(keys, pc.multiply(pc.divide(keys, modulus), modulus)), 0)


def _partition(table, key, modulus):
    """The corrupt rows and the rest, so a defect is built over only the rows it applies to."""
    import pyarrow.compute as pc

    defective = _defective(table, key, modulus)
    return table.filter(defective), table.filter(pc.invert(defective))


def _replace_column(bad, good, column, values):
    import pyarrow as pa

    index = bad.column_names.index(column)
    return pa.concat_tables([bad.set_column(index, bad.field(index), values), good])


def _duplicated(table, key, modulus):
    """Emit every row, then emit the corrupt ones a second time."""
    import pyarrow as pa

    return pa.concat_tables([table, table.filter(_defective(table, key, modulus))])


def _nullified(table, key, modulus, column):
    """Blank out a required column on the corrupt rows."""
    import pyarrow as pa

    bad, good = _partition(table, key, modulus)
    index = table.column_names.index(column)
    return _replace_column(bad, good, column, pa.nulls(bad.num_rows, table.field(index).type))


def _orphaned(table, key, modulus, column, orphan_key):
    """Point a foreign key at a parent that does not exist."""
    import pyarrow as pa

    bad, good = _partition(table, key, modulus)
    index = table.column_names.index(column)
    return _replace_column(bad, good, column, pa.array([orphan_key] * bad.num_rows, table.field(index).type))


def _negated(table, key, modulus, column):
    """Flip the sign of a measure that should never be negative."""
    import pyarrow.compute as pc

    bad, good = _partition(table, key, modulus)
    return _replace_column(bad, good, column, pc.negate(bad.column(column)))


@bauplan.model(name="bad_region", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_region(
    src=bauplan.Model("region", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
):
    """One region appears twice, so r_regionkey is no longer unique."""
    return _duplicated(src, "r_regionkey", int(defect_modulus))


@bauplan.model(name="bad_nation", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_nation(
    src=bauplan.Model("nation", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
    orphan_key=bauplan.Parameter("orphan_key"),
):
    """Some nations point at a region that does not exist."""
    return _orphaned(src, "n_nationkey", int(defect_modulus), "n_regionkey", int(orphan_key))


@bauplan.model(name="bad_customer", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_customer(
    src=bauplan.Model("customer", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
):
    """Some customers have no name."""
    return _nullified(src, "c_custkey", int(defect_modulus), "c_name")


@bauplan.model(name="bad_supplier", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_supplier(
    src=bauplan.Model("supplier", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
    orphan_key=bauplan.Parameter("orphan_key"),
):
    """Some suppliers point at a nation that does not exist."""
    return _orphaned(src, "s_suppkey", int(defect_modulus), "s_nationkey", int(orphan_key))


@bauplan.model(name="bad_part", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_part(
    src=bauplan.Model("part", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
):
    """Some parts have a negative retail price."""
    return _negated(src, "p_partkey", int(defect_modulus), "p_retailprice")


@bauplan.model(name="bad_partsupp", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_partsupp(
    src=bauplan.Model("partsupp", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
):
    """Some part/supplier pairs appear twice.

    A partsupp row is keyed by the pair, but the defect keys off ps_partkey alone: every supplier of
    a corrupt part is duplicated, which is one rule the SQL side can spell as a single predicate.
    """
    return _duplicated(src, "ps_partkey", int(defect_modulus))


@bauplan.model(name="bad_orders", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_orders(
    src=bauplan.Model("orders", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
):
    """Some orders have no customer."""
    return _nullified(src, "o_orderkey", int(defect_modulus), "o_custkey")


@bauplan.model(name="bad_lineitem", materialization_strategy="REPLACE")
@bauplan.python("3.12")
def bad_lineitem(
    src=bauplan.Model("lineitem", columns=["*"]),
    defect_modulus=bauplan.Parameter("defect_modulus"),
):
    """Some line items have a negative quantity.

    A line is keyed by its order and line number, and the defect keys off l_orderkey: every line of
    a corrupt order goes negative, which keeps this the same rule as the one bad_orders runs.
    """
    return _negated(src, "l_orderkey", int(defect_modulus), "l_quantity")
