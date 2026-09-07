from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from src.branch.cli import Backend
from src.macrobench.data_engineering import WORKLOAD as DATA_ENGINEERING
from src.macrobench.experiment import MacrobenchConfig
from src.macrobench.spec import Workload
from src.macrobench.wap import WORKLOAD as WAP
from src.macrobench.workloads import run_workload


class WorkloadName(StrEnum):
    data_engineering = "data-engineering"
    wap = "wap"


WORKLOADS: dict[WorkloadName, Workload] = {
    WorkloadName.data_engineering: DATA_ENGINEERING,
    WorkloadName.wap: WAP,
}


def macrobenchmark(
    backend: Annotated[Backend, typer.Argument(help="Backend to benchmark")],
    workload: Annotated[WorkloadName, typer.Argument(help="Workload to run")],
    base_branch: Annotated[str, typer.Argument(help="Ref / database / catalog.schema to branch from")],
    seed: Annotated[int, typer.Option(help="Seed for the agent's choices, for reproducible runs")] = 0,
    namespace: Annotated[str, typer.Option(help="Namespace holding the workload's tables")] = "tpch_1",
    cache: Annotated[
        bool, typer.Option(help="Let the backend serve repeated work from cache instead of rebuilding")
    ] = False,
    p_correct: Annotated[float, typer.Option(help="Chance an attempt is a correct rewrite")] = 0.7,
    root_fanout: Annotated[int, typer.Option(help="Branches taken off the root")] = 1,
    inner_fanout: Annotated[int, typer.Option(help="Branches taken off each non-root branch")] = 1,
    max_depth: Annotated[int, typer.Option(help="Deepest branch the tree may reach")] = 50,
    max_steps: Annotated[int, typer.Option(help="Attempts before the agent gives up")] = 20,
    n_workers: Annotated[int, typer.Option(help="Worker threads attempting steps at once")] = 1,
    merge_on_commit: Annotated[
        bool, typer.Option(help="Merge each accepted branch into its parent instead of keeping it")
    ] = False,
    results_path: Annotated[Path, typer.Option(help="Cumulative results parquet")] = Path("results/macrobench.parquet"),
) -> None:
    """Run an end-to-end workload benchmark on the chosen backend"""
    config = MacrobenchConfig(
        seed=seed,
        namespace=namespace,
        cache=cache,
        p_correct=p_correct,
        root_fanout=root_fanout,
        inner_fanout=inner_fanout,
        max_depth=max_depth,
        max_steps=max_steps,
        n_workers=n_workers,
        merge_on_commit=merge_on_commit,
    )
    run_workload(WORKLOADS[workload], backend, base_branch, config, results_path)
    typer.echo(f"results appended to {results_path}")
