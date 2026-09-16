from pathlib import Path
from typing import Annotated

import typer

from src.plots.macrobench import (
    DARK,
    LIGHT,
    by_operation,
    load,
    only,
    plot_by_operation,
    plot_wall_clock,
    table,
    wall_clock,
    workloads,
)

app = typer.Typer(help="Plots of benchmark results")


@app.command()
def macrobench(
    results_path: Annotated[Path, typer.Argument(help="Results parquet written by a macrobench run")],
    workload: Annotated[
        str | None, typer.Argument(help="Draw where the time went for this workload alone")
    ] = None,
    out_dir: Annotated[Path | None, typer.Option(help="Where to write the plots (default alongside)")] = None,
    dark: Annotated[bool, typer.Option(help="Draw on the dark surface instead of the light one")] = False,
) -> None:
    """Compare end-to-end time and where it went, across the backends in a results file.

    Given a workload, it draws that one's breakdown by itself, so a comparison can be read without
    the longest workload in the file setting the scale for all of them.
    """
    frame = load(results_path)
    if workload is not None:
        chosen = only(frame, workload)
        if chosen.is_empty():
            available = ", ".join(workloads(frame)) or "nothing"
            raise typer.BadParameter(
                f"{results_path} holds no rows for {workload}; it holds {available}", param_hint="WORKLOAD"
            )
        frame = chosen

    totals = wall_clock(frame)
    breakdown = by_operation(frame)
    if totals.is_empty():
        raise typer.BadParameter(f"{results_path} holds no completed runs to plot")

    target = out_dir or Path(results_path).parent
    target.mkdir(parents=True, exist_ok=True)
    theme = DARK if dark else LIGHT

    if workload is None:
        written = [
            plot_wall_clock(totals, target / "wall_clock.png", theme),
            plot_by_operation(breakdown, target / "by_operation.png", theme),
        ]
    else:
        # One workload has nothing to compare end to end against, so only the breakdown is drawn, and
        # it is named for the workload rather than overwriting the one covering the whole file
        written = [plot_by_operation(breakdown, target / f"by_operation_{workload.replace('-', '_')}.png", theme)]

    typer.echo(table(totals, breakdown))
    typer.echo("")
    for path in written:
        typer.echo(f"wrote {path}")
