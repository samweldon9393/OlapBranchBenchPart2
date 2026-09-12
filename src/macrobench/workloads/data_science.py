"""The data science workload: an agent searches for features that predict late deliveries.

The label is whether a line item arrived after its committed date. The agent tries a batch of
candidate feature sets, scores each, keeps the promising ones, and refines those further by adding a
feature at a time — so the tree is bushy and a few levels deep rather than a single chain.

Every attempt builds its own feature table and its own metrics table on its own branch, so nothing
is shared between siblings: this is the workload that makes storage grow, and that has to clean up
after itself. The winner is decided at the end by reading every surviving branch's metrics at once.

The "model" is simulated. A score is drawn from the run's seeded RNG and written to the branch's
metrics table as if a model had produced it: the point is the branching and the storage, not the
statistics, and a score drawn inside a warehouse would make a run impossible to reproduce.
"""

import random

from src.macrobench.experiment import Action, Fixture, Workload

# The candidate features, all derivable from lineitem joined to orders
FEATURES = ("ship_delay", "quantity", "discount", "priority")

# The two kinds of model the agent compares. Chosen once, off the root, and kept down a lineage.
MODELS = ("tree", "regression")

# Off the root, a candidate is a model and a first feature: 2 x 4 = 8 branches. Below that, each
# refinement adds one more feature, so a target there is just the feature it adds.
ROOTS = tuple(f"{model}:{feature}" for model in MODELS for feature in FEATURES)
TARGETS = ROOTS + FEATURES

# Every attempt builds the same way — a feature table and a metrics row — and only its parameters
# differ, so all of them run one builder rather than a project or script per target
BUILDER = "ds_features"


def _lineage(state: frozenset[str]) -> tuple[str, list[str]]:
    """The model and the features a branch already carries."""
    model = ""
    features = []
    for token in state:
        if ":" in token:
            model, first = token.split(":", 1)
            features.append(first)
        else:
            features.append(token)
    return model, features


def choose_action(
    workload: Workload,
    rng: random.Random,
    parent_state: frozenset[str],
    tried: frozenset[str],
    step: int,
    p_correct: float,
) -> Action | None:
    """Pick the next candidate off this parent, or None once every one has been tried.

    Off the root that is a model and a first feature; deeper, it is one more feature the lineage
    does not have yet. `tried` keeps two siblings from ever getting the same candidate, including one
    that was already tried and pruned — scoring the same feature set twice is not refining it.

    The score is drawn here, from the seeded RNG, and passed to the builder to write down: a run is
    then reproducible from its seed, and whether a candidate survives is decided in the same place
    as everything else the agent decides. It clears the bar with probability p_correct.
    """
    if not parent_state:
        candidates = [root for root in ROOTS if root not in tried]
        if not candidates:
            return None
        target = rng.choice(candidates)
        model, first = target.split(":", 1)
        features = [first]
    else:
        model, features = _lineage(parent_state)
        candidates = [feature for feature in FEATURES if feature not in features and feature not in tried]
        if not candidates:
            return None
        target = rng.choice(candidates)
        features = [*features, target]

    score = rng.random()
    threshold = 1 - p_correct
    return Action(
        target=target,
        # Nothing is ever built wrong here: whether a candidate survives is down to its score alone
        correct=True,
        builder=BUILDER,
        params=(
            ("features", ",".join(sorted(features))),
            ("model", model),
            ("score", f"{score:.6f}"),
            ("threshold", f"{threshold:.6f}"),
        ),
    )


# A candidate survives when its score clears the bar. The feature set is checked too, so a builder
# that failed cannot pass on the strength of the metrics row it inherited from its parent.
SCORE_CHECK = "SELECT score >= {threshold} AND features = '{features}' AS ok FROM ds_metrics"

WORKLOAD = Workload(
    name="data_science",
    # The fixture seeds the catalogue of candidate features; everything else each branch builds itself
    fixture=Fixture(name="ds_fixture", tables=("ds_candidates",)),
    targets=TARGETS,
    dependencies=dict.fromkeys(TARGETS, frozenset()),
    # One check, whatever the target: every attempt is judged on its own score
    checks={target: {"score": SCORE_CHECK} for target in TARGETS},
    choose_action=choose_action,
    rank_by=("ds_metrics", "score"),
)
