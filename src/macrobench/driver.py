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
from src.macrobench.backends.protocol import MacroBackend, resolve
from src.macrobench.experiment import Action, MacrobenchConfig, Workload, timed
from src.macrobench.tree import Node, Tree


def _max_attempts(config: MacrobenchConfig) -> int:
    """How many times a step may be tried before the run gives up on it.

    Merges are resolved per key, so of several workers publishing into the same parent only the
    first wins; the losers' branches are anchored to a commit the parent has moved past and cannot
    be merged again at all, however many times they are asked, so the step is redone instead.

    A loser does not simply queue behind the other n_workers - 1: while it redoes its step, the
    others claim fresh steps and publish those too, so it can keep losing. Against a backend that
    conflicts the same way, the unluckiest step needed 14 attempts at 4 workers and 21 at 8 —
    around three and a half times the worker count. The bound is set well above that, generous
    enough not to fail a run that is merely unlucky while still ending one that is going nowhere.
    """
    return max(8, 6 * config.n_workers)


def _note(label: str, message: str) -> None:
    """A line about the run as a whole.

    Every log line is written in one call, so lines from workers running at once do not interleave.
    """
    typer.echo(f"{label:<8} {message}")


def _step_note(step: int, config: MacrobenchConfig, action: Action, state: str, detail: str = "") -> None:
    """A line about one step, so a long run visibly makes progress instead of just sitting there."""
    where = f"{step + 1:>3}/{config.max_steps}"
    typer.echo(f"{'step':<8} {where:<8} {action.target:<26} {action.variant:<8} {state:<10} {detail}".rstrip())


def _try_merge(ops: MacroBackend, client: object, source_ref: str, into_branch: str) -> Exception | None:
    """Merge, handing back the failure instead of raising so a losing attempt can still be timed."""
    try:
        ops.merge_branch(client, source_ref, into_branch)
    except Exception as error:  # noqa: BLE001 - the backend's exception types are its own
        return error
    return None


def _worker(tree: Tree, ops: MacroBackend, workload: Workload, config: MacrobenchConfig) -> list[dict]:
    """Run steps until the tree says the run is done, returning this worker's result rows.

    The worker owns its client — connectors are not thread safe, and building one must never land
    inside a measured region — and touches shared state only through claim and finish.
    """
    client = ops.connect()
    rows: list[dict] = []

    try:
        rows = _steps(tree, ops, workload, config, client)
    finally:
        # A worker's client outlives every step it runs but nothing beyond that; left open, it is
        # still being torn down as the interpreter exits
        ops.close(client)
    return rows


def _steps(
    tree: Tree, ops: MacroBackend, workload: Workload, config: MacrobenchConfig, client: object
) -> list[dict]:
    """Claim and run steps until the tree says the run is done."""
    rows: list[dict] = []

    while (claim := tree.claim()) is not None:
        parent, action, step = claim
        params = dict(action.params)
        # Everything the parent already had, plus what this step is attempting
        built = parent.state | {action.target}
        checks = {name: sql.format(**params) for target in built for name, sql in workload.checks[target].items()}

        step_rows: list[dict] = []
        child = None
        accepted = False
        passing: frozenset[str] = frozenset()
        conflict: Exception | None = None
        attempts = _max_attempts(config)

        for attempt in range(1, attempts + 1):
            # A retry is a fresh branch off the parent as it now stands. The branch that lost the
            # race is anchored to a commit the parent has moved past, so its work has to be redone
            # rather than merged again.
            suffix = "" if attempt == 1 else f"_a{attempt}"
            branch = f"{tree.root.branch}_s{step}{suffix}"
            attempt_start = time.perf_counter()
            _step_note(step, config, action, "start", f"off {parent.branch.rsplit('.', 1)[-1]}")

            row, _ = timed(
                "create_branch",
                step,
                action.target,
                branch,
                partial(ops.create_branch, client, branch, parent.branch),
            )
            step_rows.append(row)
            tree.opened(branch)

            row, _ = timed(
                "run",
                step,
                action.target,
                branch,
                partial(ops.run, client, branch, config.namespace, action, config.cache),
            )
            step_rows.append(row)

            row, passing = timed(
                "evaluate",
                step,
                action.target,
                branch,
                partial(ops.evaluate, client, branch, config.namespace, checks, config.cache),
            )
            step_rows.append(row)
            accepted = passing == frozenset(checks)

            if accepted and not config.merge_on_commit:
                # The branch stays, and later steps can build on top of it
                child = Node(branch, parent, parent.depth + 1, built)
                _step_note(step, config, action, "kept", f"{time.perf_counter() - attempt_start:.1f}s")
                break

            if accepted:
                # The work lands on the parent, so the branch never joins the tree
                row, conflict = timed(
                    "merge_branch",
                    step,
                    action.target,
                    branch,
                    partial(_try_merge, ops, client, branch, parent.branch),
                )
                row["merge_attempt"] = attempt
                step_rows.append(row)

            row, _ = timed(
                "delete_branch",
                step,
                action.target,
                branch,
                partial(ops.delete_branch, client, branch),
            )
            step_rows.append(row)
            tree.closed(branch)

            took = f"{time.perf_counter() - attempt_start:.1f}s"
            if not accepted:
                failed = ", ".join(sorted(frozenset(checks) - passing))
                _step_note(step, config, action, "rejected", f"{took}  failed: {failed}")
            elif conflict is None:
                _step_note(step, config, action, "published", took)
            else:
                _step_note(step, config, action, "conflict", f"{took}  retrying, attempt {attempt + 1}/{attempts}")

            # Rejected, or published: either way this step is done. Only a lost race goes round again.
            if not accepted or conflict is None:
                break
        else:
            raise RuntimeError(f"step {step} lost the race {attempts} times running") from conflict

        tree.finish(parent, child)

        for step_row in step_rows:
            step_row.update(
                parent=parent.branch,
                depth=parent.depth + 1,
                accepted=accepted,
                correct=action.correct,
                params=json.dumps(params),
                failed_checks=sorted(frozenset(checks) - passing),
                # How many tries the step took, on every row so a step's cost can be read off any of them
                attempts=attempt,
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
    """Run one workload end to end: branch, run, evaluate, keep or prune.

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
    _note("setup", f"{workload.name} on {backend}, {config.n_workers} worker(s), up to {config.max_steps} steps")
    client = ops.connect()
    root_branch = ops.create_root_branch(client, base_branch)
    _note("setup", f"root branch {root_branch} off {base_branch}")

    # The tree is built before the fixture so that the root branch is already something teardown
    # knows to clean up. Building a fixture is the most failure-prone part of a run, and on a
    # backend where a branch is a real database, an orphaned root is a bill rather than a stray ref.
    tree = Tree(Node(root_branch, None, 0, frozenset()), workload, config, random.Random(config.seed))
    rows: list[dict] = []

    try:
        _note("setup", f"building fixture {workload.fixture.name}")
        ops.materialize_fixture(client, root_branch, config.namespace, workload.fixture, config.cache)
        _note("setup", f"fixture ready with {len(workload.fixture.tables)} tables")

        # ---- timed region ----
        workload_started_at = datetime.now(tz=UTC)
        workload_perf_start = time.perf_counter()
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
        retries = sum(1 for row in rows if row["operation"] == "run") - tree.step
        _note(
            "done",
            f"{tree.step} steps, {len(tree.nodes) - 1} kept, {retries} redone "
            f"in {workload_duration_s:.1f}s",
        )
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
        # Every branch the run still has open, children before parents so one is never deleted
        # while another still points at it. This works off the branches rather than the committed
        # nodes so that a step which died mid-flight does not leave its branch behind, and it keeps
        # going on failure so one undeletable branch does not strand all the others.
        leftover = tree.remaining()
        _note("teardown", f"deleting {len(leftover)} branch(es)")
        for branch in leftover:
            try:
                ops.delete_branch(client, branch)
            except Exception as error:  # noqa: BLE001 - the backend's exception types are its own
                _note("teardown", f"could not delete {branch}: {error}")
        ops.close(client)

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
