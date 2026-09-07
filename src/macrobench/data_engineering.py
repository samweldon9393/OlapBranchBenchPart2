"""The data engineering workload: consolidate three drifted feeds and reconcile a mart on top.

Everything specific to this workload lives here — what the fixture leaves on the root branch, the
DAG the agent walks, and how each model is judged against gold. The loop and the backend adapters
read it through the Workload interface and know none of it.
"""

from src.macrobench.spec import Fixture, Workload

# The drifted feeds the agent has to standardize, and the gold tables it is judged against. Gold is
# computed from the untouched TPC-H tables rather than from the feeds, so reproducing it means the
# drift was genuinely undone rather than agreed with.
FIXTURE = Fixture(
    name="de_fixture",
    tables=(
        "feed_americas",
        "feed_europe",
        "feed_asia",
        "gold_orders_unified",
        "gold_revenue_by_nation_quarter",
    ),
)

# Three staging models over the feeds, a union on top of them, and a mart on top of that
TARGETS = ("stg_americas", "stg_europe", "stg_asia", "orders_unified", "revenue_by_nation_quarter")

# The staging models read fixture tables, which the root branch always carries, so only the upper
# layers have prerequisites
DEPENDENCIES: dict[str, frozenset[str]] = {
    "stg_americas": frozenset(),
    "stg_europe": frozenset(),
    "stg_asia": frozenset(),
    "orders_unified": frozenset({"stg_americas", "stg_europe", "stg_asia"}),
    "revenue_by_nation_quarter": frozenset({"orders_unified"}),
}

# Money columns are cast to a common decimal type and nulls are coalesced to a sentinel before the
# comparison. Both matter: sums widen decimal precision, and DataFusion's EXCEPT treats null as
# distinct from null, so gold's null tax on the americas rows would otherwise report every one of
# them as a mismatch. The broken model variants all get values wrong rather than types, so
# normalizing types here does not hide them.
_STAGED_COLUMNS = """
    order_key, cust_key, order_date,
    CAST(net_price AS DECIMAL(18,2)) AS net_price,
    coalesce(CAST(tax_amount AS DECIMAL(18,2)), CAST(-1 AS DECIMAL(18,2))) AS tax_amount
"""

_UNIFIED_COLUMNS = f"{_STAGED_COLUMNS}, source"

_REVENUE_COLUMNS = """
    nation_name, order_quarter,
    CAST(net_revenue AS DECIMAL(38,2)) AS net_revenue,
    coalesce(CAST(tax_amount AS DECIMAL(38,2)), CAST(-1 AS DECIMAL(38,2))) AS tax_amount,
    order_count
"""

# For each target: the columns to compare, the table the agent built, and the gold it must match.
# A staging model owns one source's slice of the unified gold table.
_COMPARISONS: dict[str, tuple[str, str, str]] = {
    "stg_americas": (_STAGED_COLUMNS, "stg_americas", "gold_orders_unified WHERE source = 'americas'"),
    "stg_europe": (_STAGED_COLUMNS, "stg_europe", "gold_orders_unified WHERE source = 'europe'"),
    "stg_asia": (_STAGED_COLUMNS, "stg_asia", "gold_orders_unified WHERE source = 'asia'"),
    "orders_unified": (_UNIFIED_COLUMNS, "orders_unified", "gold_orders_unified"),
    "revenue_by_nation_quarter": (_REVENUE_COLUMNS, "revenue_by_nation_quarter", "gold_revenue_by_nation_quarter"),
}


def _comparison_sql(target: str) -> str:
    """SQL deciding whether a target reproduces its gold table exactly.

    The row counts are not redundant next to the symmetric difference: EXCEPT is a set operation, so
    a model that emits duplicate rows differs from gold by nothing while holding more rows than it.
    That is exactly what the broken asia variant does, and the counts are what catch it.
    """
    columns, actual_table, expected_table = _COMPARISONS[target]
    return f"""
        WITH expected AS (SELECT {columns} FROM {expected_table}),
             actual AS (SELECT {columns} FROM {actual_table}),
             missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
             unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected),
             summary AS (
                 SELECT (SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected) AS diff,
                        (SELECT count(*) FROM actual) AS n_actual,
                        (SELECT count(*) FROM expected) AS n_expected
             )
        SELECT diff = 0 AND n_actual = n_expected AS ok FROM summary
    """


WORKLOAD = Workload(
    name="data_engineering",
    fixture=FIXTURE,
    targets=TARGETS,
    dependencies=DEPENDENCIES,
    checks={target: _comparison_sql(target) for target in TARGETS},
)
