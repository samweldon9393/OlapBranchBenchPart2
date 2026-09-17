"""Building a step with dbt, which is what the dbt backends share.

These backends exist to answer a question the SQL ones cannot: what the agent loop costs a team whose
transformations live in dbt rather than in statements they run themselves. Branching, checking and
publishing are unchanged — each dbt backend borrows those from its plain sibling — so the only thing
that differs is how a build happens, and the difference in the numbers is the tool's.

A build is `dbt run --select tag:<build>`: the models carrying that tag, in dbt's own dependency
order, into the branch the step is building on. That mirrors Bauplan, which is handed a project and
resolves the DAG itself, where the plain SQL backends are handed an ordered list of statements.

dbt runs as a subprocess rather than through dbtRunner, which serializes concurrent invocations
inside one process: with eight workers claiming steps at once that would measure a queue rather than
a warehouse.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.macrobench.experiment import Action

PROJECT = Path(__file__).parents[1] / "workloads" / "dbt"
PROFILES = PROJECT / "profiles"

# A fixture builds the tables the rest of a workload adds to, so it starts them over rather than
# appending to whatever a previous run left. Every other build takes the tables as it finds them.
FULL_REFRESH = frozenset({"fix_fixture"})


@dataclass(frozen=True)
class DbtTarget:
    """What one platform needs from dbt. Everything else about running a build is shared."""

    # The output in profiles.yml
    name: str
    # Where a branch lives, as the two vars the project's generate_{database,schema}_name macros read
    branch_vars: Callable[[str, str], dict[str, str]]


# dbt writes its manifest, its run results and its logs under the paths it is given, so every worker
# needs its own: eight invocations sharing one directory would read each other's results.
_worker = threading.local()


def _paths() -> tuple[Path, Path]:
    """This worker's dbt target and log directories."""
    paths = getattr(_worker, "paths", None)
    if paths is None:
        root = Path(tempfile.gettempdir()) / f"macrobench_dbt_{os.getpid()}_{threading.get_ident()}"
        paths = (root / "target", root / "logs")
        _worker.paths = paths
    return paths


def _invocation(
    target: DbtTarget, target_path: Path, log_path: Path, action: Action, variables: Mapping[str, str]
) -> list[str]:
    """The dbt command for one build."""
    command = [
        str(Path(sys.executable).parent / "dbt"),
        "run",
        "--project-dir",
        str(PROJECT),
        "--profiles-dir",
        str(PROFILES),
        "--target",
        target.name,
        "--target-path",
        str(target_path),
        "--log-path",
        str(log_path),
        # One thread, because the benchmark's concurrency is its own: a step is one build, and the
        # workers are what run several at a time
        "--threads",
        "1",
        # Every step passes different vars, which invalidates dbt's partial parse anyway; saying so
        # keeps the cost of a build honest rather than making the first one look unlucky
        "--no-partial-parse",
        "--select",
        f"tag:{action.build}",
        "--vars",
        json.dumps(dict(variables)),
    ]
    if action.build in FULL_REFRESH:
        command.append("--full-refresh")
    return command


def _built(results_path: Path, completed: subprocess.CompletedProcess) -> bool:
    """Whether every model dbt was asked for built.

    An invocation that never reached execution — a profile it could not read, a warehouse it could
    not reach — writes no results at all. That is a broken run rather than a wrong attempt, so it
    raises here instead of being reported as a step the checks should prune.
    """
    if not results_path.exists():
        output = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"dbt did not run (exit {completed.returncode}): {output[-2000:]}")
    results = json.loads(results_path.read_text())
    return all(result["status"] == "success" for result in results["results"])


def _environment() -> dict[str, str]:
    """What dbt inherits: this process's environment, which already holds the credentials.

    With one repair — the Snowflake connector expands a `~` in the key path and dbt does not, so a
    profile that reads the same variable would go looking for a directory called `~`.
    """
    environment = dict(os.environ)
    key_file = environment.get("SF_PRIVATE_KEY_FILE")
    if key_file:
        environment["SF_PRIVATE_KEY_FILE"] = str(Path(key_file).expanduser())
    return environment


def run(
    target: DbtTarget, branch: str, namespace: str, action: Action, cache: bool = False
) -> bool:
    """Build the action on the branch by running the models its build is tagged with."""
    target_path, log_path = _paths()
    results_path = target_path / "run_results.json"
    # Last invocation's results would otherwise stand in for an invocation that never started
    results_path.unlink(missing_ok=True)

    variables = {
        **target.branch_vars(branch, namespace),
        "variant": action.variant,
        "cache": cache,
        **dict(action.params),
    }
    completed = subprocess.run(  # noqa: S603 - the command is built here, not taken from input
        _invocation(target, target_path, log_path, action, variables),
        capture_output=True,
        text=True,
        check=False,
        env=_environment(),
    )
    return _built(results_path, completed)
