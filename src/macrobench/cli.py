from pathlib import Path
from typing import Annotated

import typer

from src.branch.cli import Backend
from src.macrobench.data_engineering import WORKLOAD as DATA_ENGINEERING
from src.macrobench.experiment import MacrobenchConfig
from src.macrobench.workloads import run_workload


def macrobenchmark(
    backend: Annotated[Backend, typer.Argument(help="Backend to benchmark")],
    base_branch: Annotated[str, typer.Argument(help="Ref / database / catalog.schema to branch from")],
    seed: Annotated[int, typer.Option(help="Seed for the agent's choices, for reproducible runs")] = 0,
    max_steps: Annotated[int, typer.Option(help="Attempts before the agent gives up")] = 20,
    p_correct: Annotated[float, typer.Option(help="Chance an attempt is a correct rewrite")] = 0.7,
    namespace: Annotated[str, typer.Option(help="Namespace holding the workload's tables")] = "tpch_1",
    cache: Annotated[
        bool, typer.Option(help="Let the backend serve repeated work from cache instead of rebuilding")
    ] = False,
    results_path: Annotated[Path, typer.Option(help="Cumulative results parquet")] = Path("results/macrobench.parquet"),
) -> None:
    """Run an end-to-end workload benchmark on the chosen backend"""
    config = MacrobenchConfig(
        seed=seed, max_steps=max_steps, p_correct=p_correct, namespace=namespace, cache=cache
    )
    # Data engineering is the only workload so far; the other three plug in here as they land
    run_workload(DATA_ENGINEERING, backend, base_branch, config, results_path)
    typer.echo(f"results appended to {results_path}")
