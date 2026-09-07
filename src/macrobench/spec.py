"""What a workload is, in terms the backends and the loop can both work with.

The four workloads differ in what they set up, what they build, and how they know they are done,
but they all run the same branch/mutate/evaluate/prune loop. Everything that differs is data in a
Workload, so the loop and the backend adapters stay written once.
"""

import random
from collections.abc import Mapping
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
    """One rewrite the agent can attempt: a target to build, and which version of it to write.

    How a backend turns this into work is its own business; all the loop needs to know is what the
    attempt was aimed at and whether it was meant to be a good one.
    """

    target: str
    correct: bool

    @property
    def variant(self) -> str:
        """Which version of the rewrite to apply."""
        return "correct" if self.correct else "broken"


@dataclass(frozen=True)
class Workload:
    """A workload the benchmark can run end to end.

    `checks` maps each target to SQL returning a single row with one boolean `ok` column; a backend
    runs it and reads that column, so deciding what "correct" means stays with the workload and
    never leaks into the backend adapters.
    """

    name: str
    fixture: Fixture
    targets: tuple[str, ...]
    dependencies: Mapping[str, frozenset[str]]
    checks: Mapping[str, str]


def choose_action(workload: Workload, rng: random.Random, matching: frozenset[str], built: frozenset[str], p_correct: float) -> Action | None:
    """Pick the next rewrite to attempt, or None when nothing is currently attemptable.

    The agent only reaches for targets whose inputs already exist and that are not already known
    good, which is what keeps a run walking up the DAG instead of thrashing. Whether it gets the
    rewrite right is a coin flip weighted by p_correct, so a lower value means more dead ends and a
    longer walk to the same finished state.
    """
    attemptable = [
        target for target in workload.targets if target not in matching and workload.dependencies[target] <= built
    ]
    if not attemptable:
        return None
    return Action(target=rng.choice(attemptable), correct=rng.random() < p_correct)
