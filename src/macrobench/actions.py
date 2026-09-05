import random
from dataclasses import dataclass
from pathlib import Path

PROJECTS = Path(__file__).parent / "projects"

# The DAG the agent is building: three staging models over the drifted feeds, a union on top of
# them, and a mart on top of that. Each is checked against a gold table, so "done" means every one
# of them matches.
TARGETS = ("stg_americas", "stg_europe", "stg_asia", "orders_unified", "revenue_by_nation_quarter")

# What has to already be on the branch before a model can be rewritten. The staging models read
# fixture tables, which the root branch always carries, so only the upper layers have prerequisites.
DEPENDENCIES: dict[str, frozenset[str]] = {
    "stg_americas": frozenset(),
    "stg_europe": frozenset(),
    "stg_asia": frozenset(),
    "orders_unified": frozenset({"stg_americas", "stg_europe", "stg_asia"}),
    "revenue_by_nation_quarter": frozenset({"orders_unified"}),
}


@dataclass(frozen=True)
class Action:
    """One rewrite the agent can attempt: a model, and which version of it to write."""

    target: str
    correct: bool

    @property
    def project_dir(self) -> Path:
        """The Bauplan project that materializes this model."""
        return PROJECTS / self.target

    @property
    def variant(self) -> str:
        """The run parameter selecting the correct or the broken version of the model."""
        return "correct" if self.correct else "broken"


def choose_action(rng: random.Random, matching: frozenset[str], built: frozenset[str], p_correct: float) -> Action | None:
    """Pick the next rewrite to attempt, or None when nothing is currently attemptable.

    The agent only reaches for models whose inputs already exist and that are not already known
    good, which is what keeps a run walking up the DAG instead of thrashing. Whether it gets the
    rewrite right is a coin flip weighted by p_correct, so a lower value means more dead ends and
    a longer walk to the same finished state.
    """
    attemptable = [target for target in TARGETS if target not in matching and DEPENDENCIES[target] <= built]
    if not attemptable:
        return None
    return Action(target=rng.choice(attemptable), correct=rng.random() < p_correct)
