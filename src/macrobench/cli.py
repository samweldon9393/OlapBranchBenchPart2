from typing import Annotated

import typer

from src.branch.cli import Backend
from src.macrobench.workloads import run_data_engineering


def macrobenchmark(
    backend: Annotated[Backend, typer.Argument(help="Backend to benchmark")],
    base_branch: Annotated[str, typer.Argument(help="Ref / database / catalog.schema to branch from")],
) -> None:
    """Run an end-to-end workload benchmark on the chosen backend"""
    run_data_engineering(backend, base_branch)
