import typer

from src.branch.cli import benchmark
from src.data.cli import app as data_app
from src.macrobench.cli import macrobenchmark

app = typer.Typer(help="OlapBranchBench")

# Single benchmark command across Bauplan, Databricks and Snowflake (backend is the first arg)
app.command("bench")(benchmark)

# End-to-end workload benchmark, same backend-as-first-arg shape as "bench"
app.command("macrobench")(macrobenchmark)

# App to generate TPC-H tables with a given scaling factor
app.add_typer(data_app, name="data")


if __name__ == "__main__":
    app()
