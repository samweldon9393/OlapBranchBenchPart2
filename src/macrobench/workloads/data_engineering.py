"""The data engineering workload: debug a pipeline that consolidates three drifted feeds into a mart.

The pipeline is one DAG of five models, and every step runs all of it, the way a pipeline is run: the
agent rewrites one model on a branch, reruns the whole pipeline, and keeps the branch if the models
it has fixed so far all match gold. The pipeline starts out with every model broken, so the agent
fixes them one at a time, walking up the DAG — a model is only worth fixing once everything it reads
is right.

Everything specific to this workload lives here — what the fixture leaves on the root branch, the
DAG the agent walks, and how each model is judged against gold. The loop and the backend adapters
read it through the Workload interface and know none of it.
"""

import random

from src.macrobench.experiment import Action, Fixture, Workload

# The drifted feeds the agent has to standardize, and the gold tables it is judged against. Gold is
# computed from the untouched TPC-H tables rather than from the feeds, so reproducing it means the
# drift was genuinely undone rather than agreed with.
FIXTURE = Fixture(
    builds=(Action(target="de_fixture"),),
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

# What every step runs: the whole pipeline, as one Bauplan project, one dbt tag, or the SQL scripts
# de_pipeline.pipeline lists
PIPELINE = "de_pipeline"

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
# comparison. Both matter: sums widen decimal precision, and whether one null equals another in a
# set difference is something engines disagree on, so gold's null tax on the americas rows could
# otherwise report every one of them as a mismatch. The broken model variants all get values wrong
# rather than types, so normalizing types here does not hide them. The SQL backends run this SQL;
# the dbt tests (macros/matches_gold.sql) and the Bauplan pipeline's expectations make the same
# comparison their own way.
_STAGED_COLUMNS = """
    order_key, cust_key, order_date,
    CAST(net_price AS DECIMAL(18,2)) AS net_price,
    coalesce(CAST(tax_amount AS DECIMAL(18,2)), CAST(-1 AS DECIMAL(18,2))) AS tax_amount
"""

_UNIFIED_COLUMNS = f"{_STAGED_COLUMNS}, source"

_REVENUE_COLUMNS = """
    nation_name,
    CAST(order_quarter AS DATE) AS order_quarter,
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


def choose_action(
    rng: random.Random,
    parent_state: frozenset[str],
    tried: frozenset[str],
    step: int,
    p_correct: float,
) -> Action | None:
    """Pick the next model to rewrite, or None when nothing is attemptable from this parent.

    A target is attemptable when it is not already passing on the parent and everything it reads
    is, so the agent walks up the DAG instead of thrashing and never builds on top of a broken
    parent. Whether it gets the rewrite right is a coin flip weighted by p_correct, so a lower
    value means more dead ends and a longer walk to the same finished state. The step counter is
    unused here; this workload's choice depends only on what the parent already has.

    The step runs the whole pipeline, so the action says how every model is written: the ones the
    parent has fixed stay correct, the one being rewritten takes the drawn variant, and the rest are
    still broken. The branch's checks are the fixed models' plus the rewritten one's, so a model not
    yet touched is never what a step is judged on.
    """
    attemptable = [
        target for target in TARGETS if target not in parent_state and DEPENDENCIES[target] <= parent_state
    ]
    if not attemptable:
        return None
    target = rng.choice(attemptable)
    variant = "correct" if rng.random() < p_correct else "broken"
    variants = {model: "correct" if model in parent_state else "broken" for model in TARGETS} | {target: variant}
    return Action(
        target=target,
        builder=PIPELINE,
        variant=variant,
        params=tuple((f"variant_{model}", written) for model, written in variants.items()),
    )


WORKLOAD = Workload(
    name="data_engineering",
    fixture=FIXTURE,
    # One check per target: whether it reproduces its gold table exactly
    checks={target: {"matches_gold": _comparison_sql(target)} for target in TARGETS},
    choose_action=choose_action,
)
