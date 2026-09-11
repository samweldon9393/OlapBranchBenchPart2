"""One subcommand per workload, so each carries the shape and concurrency it is actually run at.

The options are the same set everywhere; only the defaults differ, and they differ enough to matter
— data engineering walks a single chain one step at a time, while WAP fans a star out of the root
across many workers. Spelling them out per subcommand keeps `--help` showing the values a run will
really use instead of a generic set nobody wants.
"""

from pathlib import Path
from typing import Annotated

import typer

from src.branch.cli import Backend
from src.macrobench.backends.protocol import resolve
from src.macrobench.driver import run_workload
from src.macrobench.experiment import MacrobenchConfig, Workload
from src.macrobench.workloads.data_engineering import WORKLOAD as DATA_ENGINEERING
from src.macrobench.workloads.wap import TABLES as WAP_TABLES
from src.macrobench.workloads.wap import WORKLOAD as WAP

app = typer.Typer(help="End-to-end workload benchmarks")

RESULTS_PATH = Path("results/macrobench.parquet")

# WAP hands each table out once, so the table count is its fanout, its step budget and the most
# workers that can be busy at a time
WAP_STEPS = len(WAP_TABLES)

BackendArg = Annotated[Backend, typer.Argument(help="Backend to benchmark")]
BaseBranchArg = Annotated[str, typer.Argument(help="Ref / database / catalog.schema to branch from")]
Seed = Annotated[int, typer.Option(help="Seed for the agent's choices, for reproducible runs")]
Namespace = Annotated[
    str | None,
    typer.Option(help="Namespace holding the workload's tables; defaults to the backend's own"),
]
Cache = Annotated[bool, typer.Option(help="Let the backend serve repeated work from cache instead of rebuilding")]
PCorrect = Annotated[float, typer.Option(help="Chance an attempt is a correct rewrite")]
RootFanout = Annotated[int, typer.Option(help="Branches taken off the root")]
InnerFanout = Annotated[int, typer.Option(help="Branches taken off each non-root branch")]
MaxDepth = Annotated[int, typer.Option(help="Deepest branch the tree may reach")]
MaxSteps = Annotated[int, typer.Option(help="Attempts before the agent gives up")]
NWorkers = Annotated[int, typer.Option(help="Worker threads attempting steps at once")]
MergeOnCommit = Annotated[
    bool, typer.Option(help="Merge each accepted branch into its parent instead of keeping it")
]
ResultsPath = Annotated[Path, typer.Option(help="Cumulative results parquet")]


def _run(
    workload: Workload, backend: Backend, base_branch: str, config: MacrobenchConfig, results_path: Path
) -> None:
    run_workload(workload, backend, base_branch, config, results_path)
    typer.echo(f"results appended to {results_path}")


@app.command("data-engineering")
def data_engineering(
    backend: BackendArg,
    base_branch: BaseBranchArg,
    seed: Seed = 0,
    namespace: Namespace = None,
    cache: Cache = False,
    p_correct: PCorrect = 0.7,
    root_fanout: RootFanout = 1,
    inner_fanout: InnerFanout = 1,
    max_depth: MaxDepth = 50,
    max_steps: MaxSteps = 20,
    n_workers: NWorkers = 1,
    merge_on_commit: MergeOnCommit = False,
    results_path: ResultsPath = RESULTS_PATH,
) -> None:
    """Rewrite models until the pipeline matches gold, each attempt on its own branch.

    A chain by default: one branch off the root, one off each branch after it, so accepted steps
    stack into a single deep line and the run publishes once at the end.
    """
    config = MacrobenchConfig(
        seed=seed,
        namespace=namespace or resolve(backend).DEFAULT_NAMESPACE,
        cache=cache,
        p_correct=p_correct,
        root_fanout=root_fanout,
        inner_fanout=inner_fanout,
        max_depth=max_depth,
        max_steps=max_steps,
        n_workers=n_workers,
        merge_on_commit=merge_on_commit,
    )
    _run(DATA_ENGINEERING, backend, base_branch, config, results_path)


@app.command("wap")
def wap(
    backend: BackendArg,
    base_branch: BaseBranchArg,
    seed: Seed = 0,
    namespace: Namespace = None,
    cache: Cache = False,
    p_correct: PCorrect = 0.7,
    root_fanout: RootFanout = WAP_STEPS,
    inner_fanout: InnerFanout = 0,
    max_depth: MaxDepth = 1,
    max_steps: MaxSteps = WAP_STEPS,
    n_workers: NWorkers = WAP_STEPS,
    merge_on_commit: MergeOnCommit = True,
    results_path: ResultsPath = RESULTS_PATH,
) -> None:
    """Ingest each TPC-H table on its own branch, audit what landed, and publish it.

    A star: every table branches straight off the root and merges back into it. There are eight
    tables and each is handed out once, so eight is both the default and the most workers that can
    be busy at a time.
    """
    if n_workers > WAP_STEPS:
        raise typer.BadParameter(f"at most {WAP_STEPS} workers, one per table", param_hint="--n-workers")
    config = MacrobenchConfig(
        seed=seed,
        namespace=namespace or resolve(backend).DEFAULT_NAMESPACE,
        cache=cache,
        p_correct=p_correct,
        root_fanout=root_fanout,
        inner_fanout=inner_fanout,
        max_depth=max_depth,
        max_steps=max_steps,
        n_workers=n_workers,
        merge_on_commit=merge_on_commit,
    )
    _run(WAP, backend, base_branch, config, results_path)
