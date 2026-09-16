"""One subcommand per workload, so each carries the shape and concurrency it is actually run at.

The options are the same set everywhere; only the defaults differ, and they differ enough to matter
— data engineering walks a single chain one step at a time, while WAP fans a star out of the root
across many workers. Spelling them out per subcommand keeps `--help` showing the values a run will
really use instead of a generic set nobody wants.
"""

from pathlib import Path
from typing import Annotated

import typer

from src.common.backend import Backend
from src.macrobench.backends.protocol import BACKENDS
from src.macrobench.driver import run_workload
from src.macrobench.experiment import MacrobenchConfig, Workload
from src.macrobench.workloads.data_engineering import WORKLOAD as DATA_ENGINEERING
from src.macrobench.workloads.data_science import WORKLOAD as DATA_SCIENCE
from src.macrobench.workloads.fixing import CULPRIT, LAST_BATCH, Kind
from src.macrobench.workloads.fixing import workload as fixing_workload
from src.macrobench.workloads.wap import TABLES as WAP_TABLES
from src.macrobench.workloads.wap import WORKLOAD as WAP

app = typer.Typer(help="End-to-end workload benchmarks")

RESULTS_PATH = Path("results/macrobench.parquet")

# WAP hands each table out once, so the table count is its fanout, its step budget and the most
# workers that can be busy at a time
WAP_STEPS = len(WAP_TABLES)

# Every node of the complete data science tree: 8 off the root, 3 off each of those, then the 2
# features a depth-2 lineage has left. The tree ends when candidates run out, well before this.
DS_STEPS = 8 + 8 * 3 + 8 * 3 * 2

# Every good commit after the bad one is another month of TPC-H, and the months run out
FIX_MAX_COMMITS = LAST_BATCH - CULPRIT

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


def _config(
    backend: Backend,
    namespace: str | None,
    seed: int,
    cache: bool,
    p_correct: float,
    root_fanout: int,
    inner_fanout: int,
    max_depth: int,
    max_steps: int,
    n_workers: int,
    merge_on_commit: bool,
) -> MacrobenchConfig:
    """The knobs every subcommand takes, in the shape the driver wants them.

    The subcommands spell the options out themselves, since their defaults are the point; what they
    do with them afterwards is the same everywhere.
    """
    return MacrobenchConfig(
        seed=seed,
        namespace=namespace or BACKENDS[backend].DEFAULT_NAMESPACE,
        cache=cache,
        p_correct=p_correct,
        root_fanout=root_fanout,
        inner_fanout=inner_fanout,
        max_depth=max_depth,
        max_steps=max_steps,
        n_workers=n_workers,
        merge_on_commit=merge_on_commit,
    )


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
    config = _config(
        backend, namespace, seed, cache, p_correct, root_fanout, inner_fanout, max_depth, max_steps,
        n_workers, merge_on_commit,
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
    config = _config(
        backend, namespace, seed, cache, p_correct, root_fanout, inner_fanout, max_depth, max_steps,
        n_workers, merge_on_commit,
    )
    _run(WAP, backend, base_branch, config, results_path)


@app.command("data-science")
def data_science(
    backend: BackendArg,
    base_branch: BaseBranchArg,
    seed: Seed = 0,
    namespace: Namespace = None,
    cache: Cache = False,
    p_correct: PCorrect = 0.5,
    root_fanout: RootFanout = 8,
    inner_fanout: InnerFanout = 3,
    max_depth: MaxDepth = 3,
    max_steps: MaxSteps = DS_STEPS,
    n_workers: NWorkers = 8,
    merge_on_commit: MergeOnCommit = False,
    results_path: ResultsPath = RESULTS_PATH,
) -> None:
    """Search for features that predict late deliveries, keeping the promising candidates.

    A bushy tree a few levels deep: 8 candidates off the root, each promising one refined by adding a
    feature at a time. Every branch writes its own tables, and the highest scorer is published at the
    end after reading every survivor's score at once.
    """
    if backend is Backend.databricks:
        raise typer.BadParameter(
            "a Databricks SQL warehouse can only run Python one row at a time, which put a single "
            "feature table at 481s against 7s on Snowflake; this workload is not run there",
            param_hint="BACKEND",
        )
    config = _config(
        backend, namespace, seed, cache, p_correct, root_fanout, inner_fanout, max_depth, max_steps,
        n_workers, merge_on_commit,
    )
    _run(DATA_SCIENCE, backend, base_branch, config, results_path)


@app.command("fixing")
def fixing(
    backend: BackendArg,
    base_branch: BaseBranchArg,
    kind: Annotated[Kind, typer.Option(help="How the bad commit loads its batch wrong")] = Kind.duplicate,
    commits: Annotated[int, typer.Option(help="Good commits made on top of the bad one")] = 12,
    seed: Seed = 0,
    namespace: Namespace = None,
    cache: Cache = False,
    p_correct: PCorrect = 1.0,
    root_fanout: RootFanout = 16,
    inner_fanout: InnerFanout = 12,
    max_depth: MaxDepth = 2,
    max_steps: MaxSteps = 100,
    n_workers: NWorkers = 8,
    merge_on_commit: MergeOnCommit = False,
    results_path: ResultsPath = RESULTS_PATH,
) -> None:
    """Find the commit that overstated a revenue mart, then try repairs and publish the best.

    Two wide, flat bursts: probes of the root's past commits, newest first, until one holds; then a
    dozen repairs off that last good state, the least disturbing of those that hold published over
    the root. Nothing is random, so the seed and p_correct change nothing; they are taken so that
    every workload accepts the same options.
    """
    if not 1 <= commits <= FIX_MAX_COMMITS:
        raise typer.BadParameter(f"between 1 and {FIX_MAX_COMMITS}, the months TPC-H has left", param_hint="--commits")
    config = _config(
        backend, namespace, seed, cache, p_correct, root_fanout, inner_fanout, max_depth, max_steps,
        n_workers, merge_on_commit,
    )
    _run(fixing_workload(kind, commits), backend, base_branch, config, results_path)
