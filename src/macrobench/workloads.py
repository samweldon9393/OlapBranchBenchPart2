import json
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import polars as pl
import typer

from src.branch.cli import Backend
from src.common.results import append_results
from src.macrobench.backends import MacroBackend, resolve
from src.macrobench.experiment import MacrobenchConfig, timed
from src.macrobench.spec import Workload
from src.macrobench.tree import Node, Tree

# Merge contention on a shared parent is one of the things these workloads exist to measure, so a
# merge that loses a race is retried rather than failing the run
MERGE_ATTEMPTS = 3
MERGE_RETRY_S = 0.5


def _merge_with_retry(ops: MacroBackend, client: object, source_ref: str, into_branch: str) -> int:
    """Merge, retrying a losing race a couple of times. Returns how many attempts it took."""
    for attempt in range(1, MERGE_ATTEMPTS + 1):
        try:
            ops.merge_branch(client, source_ref, into_branch)
        except Exception:
            if attempt == MERGE_ATTEMPTS:
                raise
            time.sleep(MERGE_RETRY_S)
        else:
            return attempt
    raise AssertionError("unreachable")


def _worker(tree: Tree, ops: MacroBackend, workload: Workload, config: MacrobenchConfig) -> list[dict]:
    """Run steps until the tree says the run is done, returning this worker's result rows.

    The worker owns its client — connectors are not thread safe, and building one must never land
    inside a measured region — and touches shared state only through claim and finish.
    """
    client = ops.connect()
    rows: list[dict] = []

    while (claim := tree.claim()) is not None:
        parent, action, step = claim
        branch = f"{tree.root.branch}_s{step}"
        params = dict(action.params)
        step_rows = []

        row, _ = timed(
            "create_branch",
            step,
            action.target,
            branch,
            partial(ops.create_branch, client, branch, parent.branch),
        )
        step_rows.append(row)

        row, _ = timed(
            "mutate",
            step,
            action.target,
            branch,
            partial(ops.mutate, client, branch, config.namespace, action, config.cache),
        )
        step_rows.append(row)

        # Everything the parent already had, plus what this step just attempted
        built = parent.state | {action.target}
        checks = {name: sql.format(**params) for target in built for name, sql in workload.checks[target].items()}
        row, passing = timed(
            "evaluate",
            step,
            action.target,
            branch,
            partial(ops.evaluate, client, branch, config.namespace, checks, config.cache),
        )
        step_rows.append(row)

        accepted = passing == frozenset(checks)
        merge_attempts = None
        child = None
        if accepted and config.merge_on_commit:
            # The work lands on the parent and the branch is done with, so it never joins the tree
            row, merge_attempts = timed(
                "merge_branch",
                step,
                action.target,
                branch,
                partial(_merge_with_retry, ops, client, branch, parent.branch),
            )
            step_rows.append(row)
        elif accepted:
            child = Node(branch, parent, parent.depth + 1, built)

        if child is None:
            row, _ = timed(
                "delete_branch",
                step,
                action.target,
                branch,
                partial(ops.delete_branch, client, branch),
            )
            step_rows.append(row)

        tree.finish(parent, child)

        for step_row in step_rows:
            step_row.update(
                parent=parent.branch,
                depth=parent.depth + 1,
                accepted=accepted,
                correct=action.correct,
                params=json.dumps(params),
                failed_checks=sorted(frozenset(checks) - passing),
                merge_attempts=merge_attempts if step_row["operation"] == "merge_branch" else None,
            )
        rows.extend(step_rows)

    return rows


def run_workload(
    workload: Workload,
    backend: Backend,
    base_branch: str,
    config: MacrobenchConfig,
    results_path: str | Path = "results/macrobench.parquet",
) -> pl.DataFrame:
    """Run one workload end to end: branch, mutate, evaluate, keep or prune.

    Each step branches off a committed node, attempts one target on it, and checks the result. A
    step whose every check passes is committed — merged into its parent right away, or kept as a
    branch others can build on; anything else is deleted and its parent's slot freed. The tree the
    committed steps form is whatever the fanout numbers say: a chain, a star, or something bushier.

    Nothing here is specific to a workload or a backend: what to build, how it is judged, and what
    to try next all come off the Workload, and the operations come off the backend adapter.
    """
    ops = resolve(backend)
    exp_id = str(uuid.uuid4())

    # ---- setup, untimed ----
    client = ops.connect()
    root_branch = ops.create_root_branch(client, base_branch)
    ops.materialize_fixture(client, root_branch, config.namespace, workload.fixture, config.cache)
    typer.echo(f"root branch {root_branch} ready with {len(workload.fixture.tables)} fixture tables")

    tree = Tree(Node(root_branch, None, 0, frozenset()), workload, config, random.Random(config.seed))
    rows: list[dict] = []

    # ---- timed region ----
    workload_started_at = datetime.now(tz=UTC)
    workload_perf_start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=config.n_workers) as pool:
            per_worker = list(pool.map(lambda _: _worker(tree, ops, workload, config), range(config.n_workers)))
        rows = [row for worker_rows in per_worker for row in worker_rows]

        # When steps merge as they go there is nothing left to publish; the root already has it all.
        # Otherwise the run ends holding a tree of committed branches and has to pick one to publish.
        # Only leaves are candidates — a node with children is an ancestor of a branch that carries
        # strictly more work, so publishing it would throw that work away. Among the leaves the best
        # one is whichever carries the most targets built and passing, since state only grows down a
        # path. For a chain that is just the head, the single deepest branch. Ties (two paths that
        # got equally far) are broken arbitrarily, which only arises once a run is bushy.
        if not config.merge_on_commit and (leaves := tree.leaves()):
            best = max(leaves, key=lambda node: len(node.state))
            row, _ = timed(
                "merge_branch",
                -1,
                "",
                best.branch,
                partial(ops.merge_branch, client, best.branch, root_branch),
            )
            rows.append(row)

        workload_duration_s = time.perf_counter() - workload_perf_start
        workload_ended_at = datetime.now(tz=UTC)
        # The whole timed region as one row, so a run's end-to-end cost is queryable without
        # having to re-add the per-operation durations and the gaps between them
        rows.append(
            {
                "step": -1,
                "operation": f"{workload.name}_workload",
                "target": "",
                "branch_name": root_branch,
                "duration_s": workload_duration_s,
                "started_at": workload_started_at,
                "ended_at": workload_ended_at,
            }
        )
    finally:
        # ---- teardown, untimed ----
        # Children before parents, so a branch is never deleted while another still points at it
        for node in reversed(tree.nodes):
            ops.delete_branch(client, node.branch)

    committed = len(tree.nodes) - 1
    config_struct = asdict(config)
    df = pl.DataFrame(
        [
            {
                "backend": str(backend),
                "workload": workload.name,
                "exp_id": exp_id,
                **row,
                "committed": committed,
                "steps": tree.step,
                "config": config_struct,
            }
            for row in rows
        ]
    )

    return append_results(df, results_path)
