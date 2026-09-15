"""The fixing workload: a revenue mart is overstated, and the agent finds the commit that did it.

The root carries a history. The fixture loads two years of lineitem batches cleanly; then one commit
loads the next month's batch wrong, and a run of good commits follows it, a month each. Which way the
bad one is wrong is the run's kind — a batch loaded twice, discounts dropped on part of it, or lines
for orders that were never booked — and all three overstate revenue by supplier nation.

Phase 1 finds it. Each probe branches off one of the root's past commits, newest first, recomputes
revenue and line counts from source over what that commit had loaded, and checks the mart against
them. Every probe back to the culprit fails and is discarded; the first to hold is the last good
state, and is kept.

Phase 2 fixes it from that last good state. Each candidate replays the culprit and every commit after
it the way they were made, applying one repair strategy over one scope as it goes, and records how
many rows outside the culprit it rewrote. Those that restore the invariants survive, and the least
disturbing is published over the root.

Nothing here is random: which commit to probe and which repair to try next follow a fixed order, so
a run takes the same steps at any worker count.
"""

import random
from datetime import date, timedelta
from enum import StrEnum

from src.macrobench.experiment import Action, Fixture, Workload


class Kind(StrEnum):
    """How the bad commit loads its batch wrong."""

    duplicate = "duplicate"  # the whole batch loaded twice
    discount = "discount"  # discounts dropped on the batch's first days
    unbooked = "unbooked"  # extra lines for orders that were never booked


# A batch is one month of lineitems by ship date, numbered from January 1992. The fixture loads the
# first two years, the bad commit loads the month after, and the good commits follow a month each.
FIRST_YEAR = 1992
BASE_BATCHES = 24
CULPRIT = BASE_BATCHES
# The last month TPC-H ships anything in, December 1998, which bounds how many commits can follow
LAST_BATCH = 83

# How far into the culprit's month the dropped discounts run
DISCOUNT_DAYS = 10

# Every repair is one strategy over one scope: the culprit's batch alone, its quarter, or every batch
# replayed. The targeted strategy for the run's kind and re-deriving from source restore the
# invariants at any scope; the other two leave the defect in place. The wider the scope, the more
# rows that were never wrong get rewritten along with it.
STRATEGIES = ("dedupe", "rederive", "filter", "restore")
SCOPES = ("batch", "quarter", "all")
REPAIRS = tuple(f"{strategy}@{scope}" for strategy in STRATEGIES for scope in SCOPES)


def _start(batch: int) -> date:
    """The first day of a batch's month."""
    return date(FIRST_YEAR + batch // 12, batch % 12 + 1, 1)


def _commit(batch: int, kind: Kind, bad: bool) -> Action:
    """One commit on the root, appending a month's batch; the bad one loads it the run's wrong way."""
    start = _start(batch)
    return Action(
        target=f"commit_{batch}",
        correct=True,
        builder="fix_commit",
        params=(
            ("batch", str(batch)),
            ("start", start.isoformat()),
            ("end", _start(batch + 1).isoformat()),
            ("cut", (start + timedelta(days=DISCOUNT_DAYS)).isoformat()),
            ("kind", str(kind)),
            ("bad", "1" if bad else "0"),
        ),
    )


def choose_action(
    workload: Workload,
    rng: random.Random,
    parent_state: frozenset[str],
    tried: frozenset[str],
    step: int,
    p_correct: float,
) -> Action | None:
    """Probe the root's history newest first, then try each repair off the commit that held.

    Off the root, the next step probes the newest commit not yet probed. commits[0] is the fixture
    itself, from before the bad commit, so the walk always ends by finding the last good state. A
    probe that holds is kept, and its state names the commit it held at; off that probe, the next step
    is the next repair in a fixed order. A repair branches from the probe's commit rather than from
    the probe, which holds the same data but would make every repair a clone of a clone.

    Nothing is drawn from the RNG and p_correct is unused: whether a probe or a repair holds is down
    to the data.
    """
    history = workload.fixture.commits
    culprit = dict(history[0].params)

    if not parent_state:
        for commit in range(len(history), -1, -1):
            if f"probe_{commit}" not in tried:
                return Action(
                    target=f"probe_{commit}",
                    correct=True,
                    builder="fix_probe",
                    at_commit=commit,
                    params=(("commit", str(commit)), ("kind", culprit["kind"])),
                )
        return None

    (probe,) = parent_state
    good = int(probe.removeprefix("probe_"))
    # The commit right after the last good state is the culprit, and every one after it is replayed
    culprit = dict(history[good].params)
    first, last = int(culprit["batch"]), int(dict(history[-1].params)["batch"])
    for target in REPAIRS:
        if target in tried:
            continue
        strategy, scope = target.split("@")
        high = {"batch": first, "quarter": min(first - first % 3 + 2, last), "all": last}[scope]
        return Action(
            target=target,
            correct=True,
            builder="fix_repair",
            at_commit=good,
            params=(
                ("commit", str(good)),
                ("strategy", strategy),
                ("scope", scope),
                ("culprit", str(first)),
                ("scope_lo", str(first)),
                ("scope_hi", str(high)),
                ("scope_end", _start(high + 1).isoformat()),
                ("start", culprit["start"]),
                ("end", _start(last + 1).isoformat()),
                ("cut", culprit["cut"]),
                ("kind", culprit["kind"]),
            ),
        )
    return None


# The mart against revenue recomputed from source over the same months. Every kind overstates it.
# Bauplan keeps money as floating point, so equality is to within a unit of currency rather than
# exact; each kind of defect moves a nation's total by far more than that.
_REVENUE = """
    WITH mart AS (SELECT nation_key, SUM(revenue) AS revenue FROM revenue_mart GROUP BY nation_key),
         gaps AS (
             SELECT abs(coalesce(m.revenue, 0) - coalesce(r.revenue, 0)) AS gap
             FROM mart m FULL OUTER JOIN revenue_recheck r ON m.nation_key = r.nation_key
         )
    SELECT coalesce(max(gap), 0) < 1 AS ok FROM gaps
"""

# Lines per order against source over the same months, which catches a batch loaded twice and lines
# for orders that do not exist, though not a wrong discount
_LINE_COUNTS = """
    WITH actual AS (SELECT l_orderkey AS order_key, count(*) AS line_count FROM li_clean GROUP BY l_orderkey),
         mismatched AS (
             SELECT 1 AS mismatch
             FROM actual a FULL OUTER JOIN lines_recheck e ON a.order_key = e.order_key
             WHERE a.line_count IS NULL OR e.line_count IS NULL OR a.line_count <> e.line_count
         )
    SELECT count(*) = 0 AS ok FROM mismatched
"""

# Every line points at an order, a part, and a supplier that exist
_REF_INTEGRITY = """
    SELECT (SELECT count(*) FROM li_clean l LEFT JOIN orders o ON l.l_orderkey = o.o_orderkey
            WHERE o.o_orderkey IS NULL) = 0
       AND (SELECT count(*) FROM li_clean l LEFT JOIN part p ON l.l_partkey = p.p_partkey
            WHERE p.p_partkey IS NULL) = 0
       AND (SELECT count(*) FROM li_clean l LEFT JOIN supplier s ON l.l_suppkey = s.s_suppkey
            WHERE s.s_suppkey IS NULL) = 0 AS ok
"""

CHECKS = {"revenue": _REVENUE, "line_counts": _LINE_COUNTS, "ref_integrity": _REF_INTEGRITY}


def workload(kind: Kind, commits: int) -> Workload:
    """The fixing workload for one kind of bad commit, with `commits` good ones made on top of it.

    Built per run rather than once, since how many commits there are to probe is the run's to choose.
    """
    history = (_commit(CULPRIT, kind, bad=True),) + tuple(
        _commit(CULPRIT + i, kind, bad=False) for i in range(1, commits + 1)
    )
    targets = tuple(f"probe_{commit}" for commit in range(commits + 2)) + REPAIRS
    return Workload(
        name="fixing",
        fixture=Fixture(name="fix_fixture", tables=("li_raw", "li_clean", "revenue_mart"), commits=history),
        targets=targets,
        dependencies=dict.fromkeys(targets, frozenset()),
        # The same invariants judge every step: a probe holds when they do, and a repair has to
        # restore them
        checks=dict.fromkeys(targets, CHECKS),
        choose_action=choose_action,
        rank_by=("fix_metrics", "score"),
        overwrite_on_publish=True,
    )
