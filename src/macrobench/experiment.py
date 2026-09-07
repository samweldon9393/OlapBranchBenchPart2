"""What one experiment is made of: the workload it runs, its knobs, and how operations are timed.

The workloads differ in what they set up, what they build, how they choose what to try next, and
how they know a step was good. All of that is data in a Workload, so the driver and the backend
adapters stay written once.
"""

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Fixture:
    """The setup a workload needs on the root branch before any timed step runs.

    The name identifies the fixture to the backend, which knows how it builds one; the tables are
    what has to exist afterwards, and are checked so a half-built fixture fails setup loudly rather
    than showing up later as a workload that can never finish.
    """

    name: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    """One attempt the agent can make: a target to build, which version of it, and any parameters.

    How a backend turns this into work is its own business; all the driver needs to know is what
    the attempt was aimed at and whether it was meant to be a good one. `params` is a tuple of
    pairs rather than a dict so the dataclass stays hashable; it names the thing the attempt works
    on — the batch a WAP step loads, say — and is passed to the backend and interpolated into the
    workload's check SQL.
    """

    target: str
    correct: bool
    params: tuple[tuple[str, str], ...] = ()

    @property
    def variant(self) -> str:
        """Which version of the rewrite to apply."""
        return "correct" if self.correct else "broken"


# Picking the next attempt is the one thing that genuinely differs per workload, so it is a
# callable on the Workload rather than a hook system. `parent_state` is the set of targets already
# built and passing on the branch being extended, and `step` is the run-wide step counter. Return
# None when there is nothing to attempt from this parent.
type ChooseAction = Callable[["Workload", random.Random, frozenset[str], int, float], "Action | None"]


@dataclass(frozen=True)
class Workload:
    """A workload the benchmark can run end to end.

    `checks` is two levels: each target maps to the checks that judge it, by name. Data engineering
    has one check per target, keyed by the target's own name; WAP runs three audits over its single
    target. Each check is SQL returning a single row with one boolean `ok` column, and may contain
    `{name}` placeholders that the driver fills from the action's params. A step is accepted when
    every check run on it passes, which is the same rule for every workload.
    """

    name: str
    fixture: Fixture
    targets: tuple[str, ...]
    dependencies: Mapping[str, frozenset[str]]
    checks: Mapping[str, Mapping[str, str]]
    choose_action: ChooseAction


@dataclass(frozen=True)
class MacrobenchConfig:
    """Knobs for one end-to-end workload run.

    The seed makes a run reproducible: it drives both which model the agent rewrites at each step
    and whether that rewrite is a correct one, so the same seed replays the same sequence of
    successes and dead ends.

    Caching is off by default and always passed explicitly, never left to the platform or the
    profile to resolve. The workload repeats identical work constantly — the same correct rewrite
    of a model gets built on many branches, across steps and across seeds — so a warm cache would
    time a lookup instead of the build, and how warm it was would depend on what had been run
    before, on that account, from that machine. Turning it on is a legitimate thing to measure, but
    it has to be a recorded choice rather than a default nobody set.

    The three fanout numbers are the whole topology: a chain is root_fanout=1, inner_fanout=1; a
    star is max_depth=1 with inner_fanout=0; anything bushier is a bigger root_fanout and a
    non-zero inner_fanout.
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
