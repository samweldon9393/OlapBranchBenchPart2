"""The data science workload: an agent searches for features that predict late deliveries.

The label is whether a line item arrived after its committed date. The agent tries a batch of
candidate feature sets, scores each, keeps the promising ones, and refines those further by adding a
feature at a time — so the tree is bushy and a few levels deep rather than a single chain.

Every attempt builds its own feature table and its own metrics table on its own branch, so nothing
is shared between siblings: this is the workload that makes storage grow, and that has to clean up
after itself. The winner is decided at the end by reading every surviving branch's metrics at once.

Each attempt runs the whole pipeline: build the candidate's features, fit a model to them, and score
it on rows it never saw. The model is real and deterministic — least squares, or a single best
split — so a candidate's score comes from the data and is the same on every backend and every run,
and which candidates survive is the data's call rather than a draw. On TPC-H that means the lineages
that carry ship_delay: the other columns are generated independently of whether a line arrives late.
"""

import random

from src.macrobench.experiment import Action, Fixture, Workload

# The candidate features, all derivable from lineitem joined to orders
FEATURES = ("ship_delay", "quantity", "discount", "priority")

# The two kinds of model the agent compares — a single best split, and least squares. Chosen once,
# off the root, and kept down a lineage.
MODELS = ("tree", "regression")

# Off the root, a candidate is a model and a first feature: 2 x 4 = 8 branches. Below that, each
# refinement adds one more feature, so a target there is just the feature it adds.
ROOTS = tuple(f"{model}:{feature}" for model in MODELS for feature in FEATURES)

# Every attempt runs the same pipeline — features, a fitted model, its score — and only its
# parameters differ, so all of them run one builder rather than a project or script per target
BUILDER = "ds_pipeline"

# How much of the label's variance a candidate has to explain, on held-out rows, to be refined further.
# Calibrated on SF1: every feature set with ship_delay scores about 0.50 (tree) or 0.55 (regression),
# and every one without it about zero, so the bar sits well clear of both.
THRESHOLD = 0.1


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

    Which candidate comes next is drawn from the seeded RNG; whether it survives is the data's to
    say, so p_correct is unused.
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

    return Action(
        target=target,
        builder=BUILDER,
        params=(
            ("features", ",".join(sorted(features))),
            ("model", model),
            ("threshold", str(THRESHOLD)),
        ),
    )


# A candidate survives when its score clears the bar. The feature set is checked too, so a pipeline
# that failed cannot pass on the strength of the metrics row it inherited from its parent.
SCORE_CHECK = "SELECT score >= {threshold} AND features = '{features}' AS ok FROM ds_metrics"

WORKLOAD = Workload(
    name="data_science",
    # The fixture seeds the catalogue of candidate features; everything else each branch builds itself
    fixture=Fixture(builds=(Action(target="ds_fixture"),), tables=("ds_candidates",)),
    # Every attempt is judged the same way, on its own score, whatever it built
    invariants={"score": SCORE_CHECK},
    choose_action=choose_action,
    rank_by=("ds_metrics", "score"),
)
