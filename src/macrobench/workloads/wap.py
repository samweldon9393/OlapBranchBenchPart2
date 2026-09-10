"""The WAP (write-audit-publish) workload: eight tables ingested, audited and published at once.

Each step takes one TPC-H table, ingests it onto its own branch off the root, audits what landed,
repairs anything the audit would object to, and merges into the root once the audit passes. Which
source a step draws is the luck of p_correct: a clean table, or the corrupted counterpart the
fixture built, in which case the audit finds real problems and the step has real repair work to do.

Every step owns a different table, so no two publish the same key and the merges cannot conflict.
"""

import random

from src.macrobench.experiment import Action, Fixture, Workload

# The TPC-H tables, one per worker. A run hands each out exactly once, so eight is the most workers
# that can be busy at a time.
TABLES = ("region", "nation", "customer", "supplier", "part", "partsupp", "orders", "lineitem")

TARGETS = tuple(f"landed_{table}" for table in TABLES)


def choose_action(
    workload: Workload, rng: random.Random, parent_state: frozenset[str], step: int, p_correct: float
) -> Action | None:
    """Hand out the next table, or None once every table has been claimed.

    The step counter picks the table, which is what keeps two workers off the same one: steps are
    numbered under the tree's lock, so each number — and so each table — is handed out once. The
    draw that is left to chance is which copy of the table arrives, clean or corrupted.
    """
    if step >= len(TABLES):
        return None
    return Action(target=f"landed_{TABLES[step]}", correct=rng.random() < p_correct)


# One audit per table, each asking the single question that table's defect would fail. They run
# against what the step landed, after any repair, so passing means the table is fit to publish.
# Foreign keys are checked against the good parent tables, so an orphan is a real orphan.
AUDITS: dict[str, dict[str, str]] = {
    "landed_region": {
        "unique_region_key": "SELECT count(*) = count(DISTINCT r_regionkey) AS ok FROM landed_region",
    },
    "landed_nation": {
        "region_exists": (
            "SELECT count(*) = 0 AS ok FROM landed_nation n "
            "LEFT JOIN region r ON r.r_regionkey = n.n_regionkey WHERE r.r_regionkey IS NULL"
        ),
    },
    "landed_customer": {
        "name_present": "SELECT count(*) = 0 AS ok FROM landed_customer WHERE c_name IS NULL",
    },
    "landed_supplier": {
        "nation_exists": (
            "SELECT count(*) = 0 AS ok FROM landed_supplier s "
            "LEFT JOIN nation n ON n.n_nationkey = s.s_nationkey WHERE n.n_nationkey IS NULL"
        ),
    },
    "landed_part": {
        "price_positive": "SELECT count(*) = 0 AS ok FROM landed_part WHERE p_retailprice < 0",
    },
    "landed_partsupp": {
        "unique_part_supplier": (
            "SELECT (SELECT count(*) FROM landed_partsupp) "
            "= (SELECT count(*) FROM (SELECT DISTINCT ps_partkey, ps_suppkey FROM landed_partsupp)) AS ok"
        ),
    },
    "landed_orders": {
        "customer_present": "SELECT count(*) = 0 AS ok FROM landed_orders WHERE o_custkey IS NULL",
    },
    "landed_lineitem": {
        "quantity_positive": "SELECT count(*) = 0 AS ok FROM landed_lineitem WHERE l_quantity < 0",
    },
}

WORKLOAD = Workload(
    name="wap",
    # The fixture leaves a corrupted counterpart for every table, so a step has something to draw
    # when its luck runs out
    fixture=Fixture(name="wap_fixture", tables=tuple(f"bad_{table}" for table in TABLES)),
    targets=TARGETS,
    # Every table is ingested on its own, so no step waits on another
    dependencies=dict.fromkeys(TARGETS, frozenset()),
    checks=AUDITS,
    choose_action=choose_action,
)
