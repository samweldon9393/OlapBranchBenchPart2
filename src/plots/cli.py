from pathlib import Path
from typing import Annotated

import typer

from src.plots.macrobench import (
    DARK,
    LIGHT,
    by_operation,
    load,
    plot_by_operation,
    plot_wall_clock,
    table,
    wall_clock,
)

app = typer.Typer(help="Plots of benchmark results")


@app.command()
def macrobench(
    results_path: Annotated[Path, typer.Argument(help="Results parquet written by a macrobench run")],
    out_dir: Annotated[Path | None, typer.Option(help="Where to write the plots (default alongside)")] = None,
    dark: Annotated[bool, typer.Option(help="Draw on the dark surface instead of the light one")] = False,
) -> None:
    """Compare end-to-end time and where it went, across the backends in a results file."""
    frame = load(results_path)
    totals = wall_clock(frame)
    breakdown = by_operation(frame)
    if totals.is_empty():
        raise typer.BadParameter(f"{results_path} holds no completed runs to plot")

    target = out_dir or Path(results_path).parent
    target.mkdir(parents=True, exist_ok=True)
    theme = DARK if dark else LIGHT

    written = [
        plot_wall_clock(totals, target / "wall_clock.png", theme),
        plot_by_operation(breakdown, target / "by_operation.png", theme),
    ]

    typer.echo(table(totals, breakdown))
    typer.echo("")
    for path in written:
        typer.echo(f"wrote {path}")
