import typer

from src.branch.cli import Backend
from src.macrobench.bauplan import FIXTURE_TABLES, connect, create_root_branch

# The namespace the fixture is built in, and that the workload's own models will be written to
NAMESPACE = "tpch_1"


def run_data_engineering(backend: Backend, base_branch: str) -> None:
    """Data engineering workload: branch, rewrite a model in the DAG, compare against gold, merge."""
    if backend is not Backend.bauplan:
        raise NotImplementedError(f"the data engineering workload is not implemented for {backend} yet")

    client = connect()
    root_branch = create_root_branch(client, base_branch, NAMESPACE)
    typer.echo(f"root branch {root_branch} ready with {len(FIXTURE_TABLES)} fixture tables")

    try:
        raise NotImplementedError("the timed steps on top of the root branch are not implemented yet")
    finally:
        # Nothing branches off the root yet, so do not leave it behind
        client.delete_branch(root_branch)
        typer.echo(f"deleted {root_branch}")
