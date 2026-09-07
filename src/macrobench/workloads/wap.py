"""The WAP (write-audit-publish) workload: batches of orders arrive and are published one by one.

Each step appends one batch on its own branch off the root, audits it there, and merges it into the
root when every audit passes. Several workers run at once, so accepted steps contend on the merge
into that shared root, which is much of what this workload measures.
"""

import random

from src.macrobench.experiment import Action, Fixture, Workload

# Batch ids the fixture splits orders into; see projects/wap_fixture/orders_batched.sql
N_BATCHES = 61


def choose_action(
    workload: Workload, rng: random.Random, parent_state: frozenset[str], step: int, p_correct: float
) -> Action | None:
    """Load the next batch, or None once every batch has been handed out.

    There is no DAG to walk here: every step attempts the same target, and the step counter picks
    which batch it carries. Batch 0 is pre-seeded by the fixture, so step k loads batch k+1.
    """
    batch_id = step + 1
    if batch_id >= N_BATCHES:
        return None
    return Action("orders_landed", rng.random() < p_correct, params=(("batch_id", str(batch_id)),))


# Audits are scoped to the batch just appended, so their cost stays flat as orders_landed grows
AUDITS = {
    "unique_order_key": (
        "SELECT count(*) = count(DISTINCT order_key) AS ok FROM orders_landed WHERE batch_id = {batch_id}"
    ),
    "cust_key_present": (
        "SELECT count(*) = 0 AS ok FROM orders_landed WHERE batch_id = {batch_id} AND cust_key IS NULL"
    ),
    "customer_exists": (
        "SELECT count(*) = 0 AS ok FROM orders_landed o "
        "LEFT JOIN customer c ON c.c_custkey = o.cust_key "
        "WHERE o.batch_id = {batch_id} AND c.c_custkey IS NULL"
    ),
}

WORKLOAD = Workload(
    name="wap",
    fixture=Fixture(name="wap_fixture", tables=("orders_stream", "orders_landed")),
    targets=("orders_landed",),
    dependencies={"orders_landed": frozenset()},
    checks={"orders_landed": AUDITS},
    choose_action=choose_action,
)
