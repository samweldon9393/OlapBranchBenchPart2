import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime


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
