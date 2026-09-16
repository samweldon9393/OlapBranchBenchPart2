"""What one experiment is made of: the workload it runs, its knobs, and how operations are timed.

The workloads differ in what they set up, what they build, how they choose what to try next, and
how they know a step was good. All of that is data in a Workload, so the driver and the backend
adapters stay written once.
"""

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class Action:
    """One build: what it produces, what builds it, which version of it, and what it is given.

    `builder` names what does the building when that is not named after the target — a workload
    whose every step runs the same thing with different parameters names it once here. `variant`
    picks between implementations where a build has more than one, and empty means it has only one.
    `params` is a tuple of pairs rather than a dict so the dataclass stays hashable; it reaches the
    build and is interpolated into the workload's check SQL.
    """

    target: str
    builder: str = ""
    variant: str = ""
    params: tuple[tuple[str, str], ...] = ()
    # Where the attempt branches from, when that is not its parent as it stands: the index of one of
    # the snapshots setup recorded, for a workload that goes back through the root's history
    from_snapshot: int | None = None

    @property
    def build(self) -> str:
        """What the backend builds this attempt with."""
        return self.builder or self.target


@dataclass(frozen=True)
class Fixture:
    """What setup builds on the root branch, in order, before any timed step runs.

    Every build runs exactly the way a step's does, and the state after each is recorded, so a
    workload with a history to go back through lists that history here and most name a single build.
    `tables` is what has to exist once setup is done; it is checked so a half-built fixture fails
    setup loudly rather than showing up later as a workload that can never finish.
    """

    builds: tuple[Action, ...]
    tables: tuple[str, ...]


# Picking the next attempt is the one thing that genuinely differs per workload, so it is a
# callable on the Workload rather than a hook system. `parent_state` is the set of targets already
# built and passing on the branch being extended; `tried` is every target already attempted off that
# same parent, kept or not, so a workload can avoid handing two siblings the same candidate; and
# `step` is the run-wide step counter. Return None when there is nothing to attempt from this parent.
type ChooseAction = Callable[[random.Random, frozenset[str], frozenset[str], int, float], "Action | None"]


@dataclass(frozen=True)
class Workload:
    """A workload the benchmark can run end to end.

    `checks` judge what a branch built: each target maps to the checks that judge it, by name, and
    they run for every target the branch carries, so a step has to leave its ancestors' work intact
    as well as land its own. `invariants` judge the branch whatever it built, and run once per step;
    a workload whose every step is judged the same way says so here instead of mapping every target
    to the same checks. Both are SQL returning a single row with one boolean `ok` column, and may
    contain `{name}` placeholders the driver fills from the action's params. A step is accepted when
    everything run on it passes, which is the same rule for every workload.
    """

    name: str
    fixture: Fixture
    choose_action: ChooseAction
    checks: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    invariants: Mapping[str, str] = field(default_factory=dict)
    # How to pick the branch a run publishes, for a workload whose leaves are not ranked by how much
    # they built: a (table, column) read off every surviving leaf at once, the highest value winning
    rank_by: tuple[str, str] | None = None
    # Publish the chosen leaf by making the root's tables match it rather than by merging it. For a
    # workload whose leaves are built off a past commit: the root has changed the same tables since,
    # so a merge conflicts by construction, and taking the fix means overwriting them
    overwrite_on_publish: bool = False


@dataclass(frozen=True)
class MacrobenchConfig:
    """Knobs for one end-to-end workload run.

    The seed makes a single-worker run reproducible: it drives what the agent attempts at each step
    and how well that attempt turns out. `p_correct` is the chance any one attempt is a good one —
    a coin flip where a workload builds a correct or a broken version, the same probability
    expressed as a score to beat where a workload scores its attempts, and nothing at all to a
    workload whose steps are all deliberate.

    Caching is off by default and always passed explicitly, never left to the platform or the
    profile to resolve. The workload repeats identical work constantly — the same correct rewrite
    of a model gets built on many branches, across steps and across seeds — so a warm cache would
    time a lookup instead of the build, and how warm it was would depend on what had been run
    before, on that account, from that machine. Turning it on is a legitimate thing to measure, but
    it has to be a recorded choice rather than a default nobody set.

    The three fanout numbers are the whole topology: a chain is root_fanout=1, inner_fanout=1; a
    star is max_depth=1 with inner_fanout=0; anything bushier is a bigger root_fanout and a
    non-zero inner_fanout.

    The namespace default here is only a fallback for building a config by hand. Each backend keeps
    the tables somewhere different, so the CLI fills this in from the backend being run against.
    """

    seed: int = 0
    namespace: str = "tpch_1"
    cache: bool = False
    p_correct: float = 0.7
    # tree shape
    root_fanout: int = 1
    inner_fanout: int = 1
    max_depth: int = 50
    max_steps: int = 20
    # execution
    n_workers: int = 1
    merge_on_commit: bool = False


def timed[R](operation: str, step: int, target: str, branch_name: str, op: Callable[[], R]) -> tuple[dict, R]:
    """Run one operation, returning its result row and the operation's value.

    Only the call itself sits between the two clock reads; naming, bookkeeping and the decision of
    what to do next all stay outside, the same way part 1 keeps them out of the measured region.
    """
    started_at = datetime.now(tz=UTC)
    perf_start = time.perf_counter()
    result = op()
    duration_s = time.perf_counter() - perf_start
    ended_at = datetime.now(tz=UTC)
    row = {
        "step": step,
        "operation": operation,
        "target": target,
        "branch_name": branch_name,
        "duration_s": duration_s,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    return row, result
