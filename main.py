import typer

from src.branch.cli import benchmark
from src.data.cli import app as data_app
from src.macrobench.cli import app as macrobench_app

app = typer.Typer(help="OlapBranchBench")

# Single benchmark command across Bauplan, Databricks and Snowflake (backend is the first arg)
app.command("bench")(benchmark)

# End-to-end workload benchmarks, one subcommand per workload so each carries its own defaults
app.add_typer(macrobench_app, name="macrobench")

# App to generate TPC-H tables with a given scaling factor
app.add_typer(data_app, name="data")


if __name__ == "__main__":
    app()
