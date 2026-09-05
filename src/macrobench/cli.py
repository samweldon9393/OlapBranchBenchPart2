from pathlib import Path
from typing import Annotated

import typer

from src.branch.cli import Backend
from src.macrobench.experiment import MacrobenchConfig
from src.macrobench.workloads import run_data_engineering


def macrobenchmark(
    backend: Annotated[Backend, typer.Argument(help="Backend to benchmark")],
    base_branch: Annotated[str, typer.Argument(help="Ref / database / catalog.schema to branch from")],
    seed: Annotated[int, typer.Option(help="Seed for the agent's choices, for reproducible runs")] = 0,
    max_steps: Annotated[int, typer.Option(help="Attempts before the agent gives up")] = 20,
    p_correct: Annotated[float, typer.Option(help="Chance an attempt is a correct rewrite")] = 0.7,
    namespace: Annotated[str, typer.Option(help="Namespace holding the workload's tables")] = "tpch_1",
    results_path: Annotated[Path, typer.Option(help="Cumulative results parquet")] = Path("results/macrobench.parquet"),
) -> None:
    """Run an end-to-end workload benchmark on the chosen backend"""
    config = MacrobenchConfig(seed=seed, max_steps=max_steps, p_correct=p_correct, namespace=namespace)
    run_data_engineering(backend, base_branch, config, results_path)
    typer.echo(f"results appended to {results_path}")
