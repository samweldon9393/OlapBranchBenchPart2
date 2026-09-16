import json
import random
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import polars as pl
import typer

from src.common.backend import Backend
from src.common.results import append_results
from src.macrobench.backends.protocol import BACKENDS, MacroBackend
from src.macrobench.experiment import Action, Fixture, MacrobenchConfig, Workload, timed
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


def _try(op: object, *args: object) -> Exception | None:
    """Run an operation, handing back the failure instead of raising it.

    Publishing is timed whether or not it works: a merge that loses a race is a real cost of
    contention, and a run should record it rather than disappear into a traceback.
    """
    try:
        op(*args)  # type: ignore[operator]
    except Exception as error:  # noqa: BLE001 - the backend's exception types are its own
        return error
    return None


def _checks(workload: Workload, built: frozenset[str], params: Mapping[str, str]) -> dict[str, str]:
    """Everything judging this branch, by id, with the action's parameters filled in.

    A target's checks are qualified with the target, so two targets naming a check the same way stay
    two checks and a failure says which target's check it was. Invariants judge the branch whatever
    it built and are named on their own.
    """
    checks = {
        f"{target}.{name}": sql
        for target in sorted(built)
        for name, sql in workload.checks.get(target, {}).items()
    }
    return {name: sql.format(**params) for name, sql in (checks | dict(workload.invariants)).items()}


def _evaluate(
    ops: MacroBackend, client: object, branch: str, namespace: str, checks: Mapping[str, str], cache: bool
) -> frozenset[str]:
    """Run each check on the branch and return the ones that passed.

    The workload supplies the SQL and this only reads the boolean it returns, so what counts as
    correct never has to be known here. A check that cannot run at all — a target that never
    materialized, or SQL that will not typecheck against what was built — counts as not passing
    rather than as a benchmark failure.
    """
    passing = set()
    for name, statement in checks.items():
        try:
            rows = ops.query(client, branch, namespace, statement, cache)
        except Exception as error:  # noqa: BLE001 - the backend's exception types are its own
            _note("check", f"{name} on {branch}: {str(error).splitlines()[0]}")
            continue
        if rows and rows[0].get("ok"):
            passing.add(name)
    return frozenset(passing)


def _step_branch(root: str, step: int, attempt: int) -> str:
    """Where a step's work goes: the root's name, the step, and the attempt if it is not the first.

    Minted here rather than by a backend, so every backend has to accept its own root name with a
    suffix on it. The cleanup instructions in CLAUDE.md work off the same shape.
    """
    suffix = "" if attempt == 1 else f"_a{attempt}"
    return f"{root}_s{step}{suffix}"


@dataclass
class Attempt:
    """What one step left behind, however many attempts it took."""

    rows: list[dict] = field(default_factory=list)
    child: Node | None = None
    accepted: bool = False
    passing: frozenset[str] = frozenset()
    attempts: int = 0


def _attempt(
    tree: Tree,
    ops: MacroBackend,
    config: MacrobenchConfig,
    client: object,
    parent: Node,
    action: Action,
    step: int,
    source: str,
    checks: Mapping[str, str],
) -> Attempt:
    """Branch, build, check, and then keep, publish or discard — retrying only a lost merge race.

    A retry is a fresh branch off the parent as it now stands: the branch that lost is anchored to a
    commit the parent has moved past, so its work has to be redone rather than merged again.
    """
    result = Attempt()
    attempts = _max_attempts(config)
    origin = f"snapshot {action.from_snapshot}" if action.from_snapshot is not None else (
        "the root" if parent.depth == 0 else f"step {parent.step + 1}"
    )

    for attempt in range(1, attempts + 1):
        result.attempts = attempt
        branch = _step_branch(tree.root.branch, step, attempt)
        started = time.perf_counter()
        _step_note(step, config, action, "start", f"off {origin}")

        row, _ = timed(
            "create_branch", step, action.target, branch, partial(ops.create_branch, client, branch, source)
        )
        result.rows.append(row)
        tree.opened(branch)

        row, built = timed(
            "run", step, action.target, branch, partial(ops.run, client, branch, config.namespace, action, config.cache)
        )
        result.rows.append(row)
        # The checks decide whether a step is kept, so a build that did not run is left to fail them
        # like any other bad attempt — but it is worth saying so, since "the check could not run" and
        # "the check found something wrong" look identical in the results otherwise
        if not built:
            _note("build", f"{action.build} did not build on {branch.rsplit('_', 1)[-1]}")

        row, result.passing = timed(
            "evaluate",
            step,
            action.target,
            branch,
            partial(_evaluate, ops, client, branch, config.namespace, checks, config.cache),
        )
        result.rows.append(row)
        result.accepted = result.passing == frozenset(checks)

        if result.accepted and not config.merge_on_commit:
            # The branch stays, and later steps can build on top of it
            result.child = Node(branch, parent, parent.depth + 1, parent.state | {action.target}, step)
            _step_note(step, config, action, "kept", f"{time.perf_counter() - started:.1f}s")
            return result

        conflict = None
        if result.accepted:
            # The work lands on the parent, so the branch never joins the tree
            row, conflict = timed(
                "merge_branch",
                step,
                action.target,
                branch,
                partial(_try, ops.merge_branch, client, branch, parent.branch),
            )
            row["merge_attempt"] = attempt
            result.rows.append(row)

        row, _ = timed("delete_branch", step, action.target, branch, partial(ops.delete_branch, client, branch))
        result.rows.append(row)
        tree.closed(branch)

        took = f"{time.perf_counter() - started:.1f}s"
        if not result.accepted:
            failed = ", ".join(sorted(frozenset(checks) - result.passing))
            _step_note(step, config, action, "rejected", f"{took}  failed: {failed}")
            return result
        if conflict is None:
            _step_note(step, config, action, "published", took)
            return result
        _step_note(step, config, action, "conflict", f"{took}  retrying, attempt {attempt + 1}/{attempts}")

    raise RuntimeError(f"step {step} lost the race {attempts} times running")


def _steps(
    tree: Tree, ops: MacroBackend, workload: Workload, config: MacrobenchConfig, client: object, snapshots: list[str]
) -> list[dict]:
    """Claim and run steps until the tree says the run is done.

    `snapshots` are the states setup recorded on the root, for a step that branches from one of them
    rather than from its parent.
    """
    rows: list[dict] = []

    while (claim := tree.claim()) is not None:
        parent, action, step = claim
        params = dict(action.params)
        # Everything the parent already had, plus what this step is attempting
        built = parent.state | {action.target}
        checks = _checks(workload, built, params)
        source = parent.branch if action.from_snapshot is None else snapshots[action.from_snapshot]

        attempt = Attempt()
        try:
            attempt = _attempt(tree, ops, config, client, parent, action, step, source, checks)
        finally:
            # Every claim is released, even one that raised: a slot still held is a worker blocked
            # forever on the tree's condition, and a run that hangs instead of failing
            tree.finish(parent, attempt.child)

        for row in attempt.rows:
            row.update(
                parent=parent.branch,
                depth=parent.depth + 1,
                accepted=attempt.accepted,
                variant=action.variant,
                params=json.dumps(params),
                failed_checks=sorted(frozenset(checks) - attempt.passing),
                # How many tries the step took, on every row so a step's cost can be read off any of them
                attempts=attempt.attempts,
            )
        rows.extend(attempt.rows)

    return rows


def _worker(
    tree: Tree, ops: MacroBackend, workload: Workload, config: MacrobenchConfig, snapshots: list[str]
) -> list[dict]:
    """Run steps until the tree says the run is done, returning this worker's result rows.

    The worker owns its client — connectors are not thread safe, and building one must never land
    inside a measured region — and touches shared state only through claim and finish.
    """
    client = ops.connect()
    try:
        return _steps(tree, ops, workload, config, client, snapshots)
    finally:
        # A worker's client outlives every step it runs but nothing beyond that; left open, it is
        # still being torn down as the interpreter exits
        ops.close(client)


def _setup(
    ops: MacroBackend, client: object, root_branch: str, config: MacrobenchConfig, fixture: Fixture
) -> list[str]:
    """Build the fixture on the root branch, returning the state after each build.

    This is setup, not measurement: once it has run, the root holds whatever the workload needs to
    start from, so every timed step can branch off it and inherit the lot. Each build runs exactly
    the way a step's does, so a workload with a history to go back through only has to list it, and
    the snapshots are what an action's `from_snapshot` indexes into.
    """
    snapshots: list[str] = []
    for build in fixture.builds:
        if not ops.run(client, root_branch, config.namespace, build, config.cache):
            raise RuntimeError(f"fixture build {build.build} failed on {root_branch}")
        snapshots.append(ops.snapshot(client, root_branch))

    missing = {table.lower() for table in fixture.tables} - ops.tables(client, root_branch, config.namespace)
    if missing:
        raise RuntimeError(f"fixture left {root_branch}.{config.namespace} without: {', '.join(sorted(missing))}")
    _note("setup", f"fixture ready: {len(fixture.tables)} tables, {len(snapshots)} snapshot(s)")
    return snapshots


def _publish(
    ops: MacroBackend,
    client: object,
    workload: Workload,
    config: MacrobenchConfig,
    leaves: list[Node],
    root_branch: str,
) -> list[dict]:
    """Pick the branch a run publishes and land it on the root.

    Only leaves are candidates: a node with children is an ancestor of a branch that carries
    strictly more work, so publishing it would throw that work away. Among the leaves the highest
    score wins and how much a leaf built breaks the tie, so a workload that names no score leaves
    every leaf tied and the rule becomes "whichever built the most" — for a chain, its head. A leaf
    that never wrote the ranked table scores lowest rather than failing the run.
    """
    rows: list[dict] = []
    scores: dict[str, float] = {}

    if workload.rank_by is not None:
        # Every surviving leaf is scored off a table it wrote, read across all of them at once. That
        # read is timed like any other operation: how a backend reaches many branches in one go is
        # part of what a bushy workload measures.
        table, column = workload.rank_by
        row, readings = timed(
            "aggregate",
            -1,
            "",
            root_branch,
            partial(
                ops.read_across, client, [leaf.branch for leaf in leaves], config.namespace, table, config.cache
            ),
        )
        rows.append(row)
        scores = {
            branch: max((reading[column] for reading in readings), default=float("-inf"))
            for branch, readings in readings.items()
        }

    best = max(leaves, key=lambda node: (scores.get(node.branch, float("-inf")), len(node.state)))

    # A leaf built off a past commit cannot be merged, because the root has changed the same tables
    # since; such a workload publishes by overwriting them instead. Either way it is the publish,
    # timed and recorded the same way.
    publish = (
        partial(ops.overwrite_branch, client, best.branch, root_branch, config.namespace)
        if workload.overwrite_on_publish
        else partial(ops.merge_branch, client, best.branch, root_branch)
    )
    row, failure = timed("merge_branch", -1, "", best.branch, partial(_try, publish))
    rows.append(row)
    if failure is not None:
        raise RuntimeError(f"publishing {best.branch} into {root_branch} failed: {failure}") from failure
    return rows


def _teardown(ops: MacroBackend, client: object, tree: Tree) -> None:
    """Delete every branch the run still has open, children before parents.

    This works off the branches rather than the committed nodes so that a step which died mid-flight
    does not leave its branch behind, and it keeps going on failure so one undeletable branch does
    not strand all the others.
    """
    leftover = tree.remaining()
    _note("teardown", f"deleting {len(leftover)} branch(es)")
    for branch in leftover:
        try:
            ops.delete_branch(client, branch)
        except Exception as error:  # noqa: BLE001 - the backend's exception types are its own
            _note("teardown", f"could not delete {branch}: {error}")
    ops.close(client)


def run_workload(
    workload: Workload,
    backend: Backend,
    base_branch: str,
    config: MacrobenchConfig,
    results_path: str | Path = "results/macrobench.parquet",
) -> pl.DataFrame:
    """Run one workload end to end: branch, build, check, keep or prune.

    Each step branches off a committed node — or off a state setup recorded, for a workload that
    goes back through the root's history — attempts one target on it, and checks the result. A step
    whose every check passes is committed: merged into its parent right away, or kept as a branch
    others can build on; anything else is deleted and its parent's slot freed. The tree the
    committed steps form is whatever the fanout numbers say: a chain, a star, or something bushier.

    Nothing here is specific to a workload or a backend: what to build, how it is judged, and what
    to try next all come off the Workload, and the operations come off the backend adapter.
    """
    ops = BACKENDS[backend]
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
        snapshots = _setup(ops, client, root_branch, config, workload.fixture)

        # ---- timed region ----
        workload_started_at = datetime.now(tz=UTC)
        workload_perf_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=config.n_workers) as pool:
            per_worker = list(
                pool.map(lambda _: _worker(tree, ops, workload, config, snapshots), range(config.n_workers))
            )
        rows = [row for worker_rows in per_worker for row in worker_rows]

        # When steps merge as they go there is nothing left to publish; the root already has it all
        if not config.merge_on_commit and (leaves := tree.leaves()):
            rows.extend(_publish(ops, client, workload, config, leaves, root_branch))

        workload_duration_s = time.perf_counter() - workload_perf_start
        workload_ended_at = datetime.now(tz=UTC)
        retries = sum(1 for row in rows if row["operation"] == "run") - tree.step
        _note("done", f"{tree.step} steps, {len(tree.nodes) - 1} kept, {retries} redone in {workload_duration_s:.1f}s")
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
        _teardown(ops, client, tree)

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
