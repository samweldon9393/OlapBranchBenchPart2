"""Comparing what the agent built against the gold tables the fixture put on the root branch."""

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
    "revenue_by_nation_quarter": (
        _REVENUE_COLUMNS,
        "revenue_by_nation_quarter",
        "gold_revenue_by_nation_quarter",
    ),
}


def comparison_sql(target: str) -> str:
    """SQL returning the symmetric difference against gold, plus both row counts.

    The counts are not redundant: EXCEPT is a set operation, so a model that emits duplicate rows
    has a symmetric difference of zero while holding more rows than gold. That is exactly what the
    broken asia variant does, and the row counts are what catch it.
    """
    columns, actual_table, expected_table = _COMPARISONS[target]
    return f"""
        WITH expected AS (SELECT {columns} FROM {expected_table}),
             actual AS (SELECT {columns} FROM {actual_table}),
             missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
             unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        SELECT (SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected) AS diff,
               (SELECT count(*) FROM actual) AS n_actual,
               (SELECT count(*) FROM expected) AS n_expected
    """


def matches_gold(result: dict) -> bool:
    """Whether a comparison_sql result says the model reproduces its gold table exactly."""
    return result["diff"] == 0 and result["n_actual"] == result["n_expected"]
