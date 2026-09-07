"""What a workload is, in terms the backends and the driver can both work with.

The workloads differ in what they set up, what they build, how they choose what to try next, and
how they know a step was good. All of that is data in a Workload, so the driver and the backend
adapters stay written once.
"""

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass


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
