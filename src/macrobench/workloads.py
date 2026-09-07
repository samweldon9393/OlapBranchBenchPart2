import random
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import polars as pl
import typer

from src.branch.cli import Backend
from src.common.results import append_results
from src.macrobench.backends import resolve
from src.macrobench.experiment import MacrobenchConfig, timed
from src.macrobench.spec import Workload, choose_action


def run_workload(
    workload: Workload,
    backend: Backend,
    base_branch: str,
    config: MacrobenchConfig,
    results_path: str | Path = "results/macrobench.parquet",
) -> pl.DataFrame:
    """Run one workload end to end: branch, mutate, evaluate, keep or prune.

    The agent walks up the workload's DAG, and each step is one attempt at one target. A step that
    improves the set of passing targets becomes the new head, so the successful attempts form a
    single deep chain; a step that does not is deleted, and the next attempt starts from the last
    good state. The run ends when every target passes or the agent runs out of steps.

    Nothing below is specific to a workload: what to build and how it is judged all come off the
    Workload, so the four of them share this loop.
    """
    ops = resolve(backend)
    exp_id = str(uuid.uuid4())
    rng = random.Random(config.seed)
    rows: list[dict] = []
    targets = workload.targets

    # ---- setup, untimed ----
    client = ops.connect()
    root_branch = ops.create_root_branch(client, base_branch)
    ops.materialize_fixture(client, root_branch, config.namespace, workload.fixture)
    typer.echo(f"root branch {root_branch} ready with {len(workload.fixture.tables)} fixture tables")

    head, matching, built = root_branch, frozenset(), frozenset()
    live_branches = [root_branch]

    # ---- timed loop ----
    workload_started_at = datetime.now(tz=UTC)
    workload_perf_start = time.perf_counter()
    try:
        for step in range(config.max_steps):
            action = choose_action(workload, rng, matching, built, config.p_correct)
            if action is None:
                break

            # Branch name is built outside the measured region, the way part 1 does it
            step_branch = f"{root_branch}_s{step}"
            row, branch = timed(
                "create_branch",
                step,
                action.target,
                step_branch,
                partial(ops.create_branch, client, step_branch, head),
            )
            rows.append(row)
            live_branches.append(branch)

            row, _ = timed(
                "mutate",
                step,
                action.target,
                branch,
                partial(ops.mutate, client, branch, config.namespace, action),
            )
            rows.append(row)

            candidate_built = built | {action.target}
            # Only what has been built can pass, so the check set follows the chain up the DAG
            candidate_checks = {target: workload.checks[target] for target in candidate_built}
            row, new_matching = timed(
                "evaluate",
                step,
                action.target,
                branch,
                partial(ops.evaluate, client, branch, config.namespace, candidate_checks),
            )
            rows.append(row)

            if len(new_matching) > len(matching):
                head, matching, built = branch, new_matching, candidate_built
            else:
                row, _ = timed(
                    "delete_branch",
                    step,
                    action.target,
                    branch,
                    partial(ops.delete_branch, client, branch),
                )
                rows.append(row)
                live_branches.remove(branch)

            typer.echo(
                f"step {step}: {action.target} ({action.variant}) -> "
                f"{len(matching)}/{len(targets)} matching, head {head}"
            )

            if len(matching) == len(targets):
                break

        # Publishing the finished chain is part of the workload, so it is timed like the rest
        if head != root_branch:
            row, _ = timed(
                "merge_branch",
                config.max_steps,
                "",
                head,
                partial(ops.merge_branch, client, head, root_branch),
            )
            rows.append(row)

        workload_duration_s = time.perf_counter() - workload_perf_start
        workload_ended_at = datetime.now(tz=UTC)
        # The whole timed region as one row, so a run's end-to-end cost is queryable without
        # having to re-add the per-operation durations and the gaps between them
        rows.append(
            {
                "step": -1,
                "operation": "workload",
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
        for branch in reversed(live_branches):
            ops.delete_branch(client, branch)

    config_struct = asdict(config)
    df = pl.DataFrame(
        [
            {
                "backend": str(backend),
                "workload": workload.name,
                "exp_id": exp_id,
                **row,
                "matched": len(matching),
                "targets": len(targets),
                "config": config_struct,
            }
            for row in rows
        ]
    )

    return append_results(df, results_path)
