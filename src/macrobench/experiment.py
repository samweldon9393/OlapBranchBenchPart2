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
    """

    seed: int = 0
    max_steps: int = 20
    p_correct: float = 0.7
    namespace: str = "tpch_1"


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
