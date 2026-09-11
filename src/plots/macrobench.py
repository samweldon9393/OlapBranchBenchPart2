"""Plots comparing what a macrobenchmark run cost, and where that cost went.

Two questions, two charts. How long did a workload take end to end on each backend, and how was
that time divided between branching and the work around it — which is the comparison the whole
benchmark exists to make, since the backends differ by two orders of magnitude on one half of it
and much less on the other.

Colours are the validated categorical palette, assigned in a fixed order so a backend or an
operation keeps its hue however many appear in a given file. Every value is also printed as a
table, so nothing is reachable only by matching colours.
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

# The order a step runs in, which is also the order segments stack. Fixed, so an operation keeps
# its colour whether or not a given run happens to contain it.
OPERATIONS = ("create_branch", "run", "evaluate", "merge_branch", "delete_branch")

OPERATION_LABELS = {
    "create_branch": "create branch",
    "run": "run (build)",
    "evaluate": "evaluate (check)",
    "merge_branch": "merge branch",
    "delete_branch": "delete branch",
}

# Rows whose operation ends this way carry the whole timed region rather than one operation
TOTAL_SUFFIX = "_workload"


@dataclass(frozen=True)
class Theme:
    """Chart surface and ink, plus the categorical slots, for one mode.

    Both palettes are the reference instance's categorical slots 1-5 and pass the six checks for
    their own surface. Dark is its own steps rather than a flipped copy of light.
    """

    surface: str
    primary_ink: str
    secondary_ink: str
    muted_ink: str
    grid: str
    axis: str
    series: tuple[str, ...]


LIGHT = Theme(
    surface="#fcfcfb",
    primary_ink="#0b0b0b",
    secondary_ink="#52514e",
    muted_ink="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"),
)

DARK = Theme(
    surface="#1a1a19",
    primary_ink="#ffffff",
    secondary_ink="#c3c2b7",
    muted_ink="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"),
)


def load(results_path: str | Path) -> pl.DataFrame:
    """Read a results parquet, keeping only the macrobenchmark rows."""
    frame = pl.read_parquet(results_path)
    missing = {"backend", "workload", "operation", "duration_s"} - set(frame.columns)
    if missing:
        raise RuntimeError(f"{results_path} is not a macrobench results file; it has no {', '.join(sorted(missing))}")
    return frame


def wall_clock(frame: pl.DataFrame) -> pl.DataFrame:
    """End-to-end seconds per workload and backend, averaged over the runs in the file."""
    return (
        frame.filter(pl.col("operation").str.ends_with(TOTAL_SUFFIX))
        .group_by("workload", "backend")
        .agg(
            pl.col("duration_s").mean().alias("seconds"),
            pl.col("exp_id").n_unique().alias("runs"),
        )
        .sort("workload", "backend")
    )


def by_operation(frame: pl.DataFrame) -> pl.DataFrame:
    """Seconds spent in each operation per workload and backend, averaged over runs.

    Summed within a run first and then averaged across runs, so a file holding several runs reports
    what one run costs rather than what all of them cost together.
    """
    per_run = (
        frame.filter(~pl.col("operation").str.ends_with(TOTAL_SUFFIX))
        .group_by("workload", "backend", "exp_id", "operation")
        .agg(pl.col("duration_s").sum().alias("seconds"))
    )
    return (
        per_run.group_by("workload", "backend", "operation")
        .agg(pl.col("seconds").mean().alias("seconds"))
        .sort("workload", "backend")
    )


def _rows(frame: pl.DataFrame) -> list[tuple[str, str]]:
    """The (workload, backend) pairs in the file, in a stable order."""
    return [(w, b) for w, b in frame.select("workload", "backend").unique().sort("workload", "backend").rows()]


def _style(axes: "object", theme: Theme) -> None:
    """Recessive chrome: hairline grid on the value axis only, no box, muted tick text."""
    axes.set_facecolor(theme.surface)
    axes.xaxis.grid(visible=True, color=theme.grid, linewidth=0.8, zorder=0)
    axes.yaxis.grid(visible=False)
    axes.set_axisbelow(True)
    for side, visible in (("left", True), ("bottom", False), ("top", False), ("right", False)):
        axes.spines[side].set_visible(visible)
        if visible:
            axes.spines[side].set_color(theme.axis)
            axes.spines[side].set_linewidth(0.8)
    axes.tick_params(colors=theme.muted_ink, length=0, labelsize=9)


def _label(text: str) -> str:
    return text.replace("_", " ")


def _ink_on(fill: str, theme: Theme) -> str:
    """Readable ink for a label sitting inside a fill.

    A label inside a coloured mark is the one place text does not wear a text token, so it has to
    be picked against the fill rather than assumed: white disappears on the yellow slot.
    """
    red, green, blue = (int(fill[i : i + 2], 16) / 255 for i in (1, 3, 5))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return theme.surface if luminance < 0.55 else "#0b0b0b"


def plot_wall_clock(totals: pl.DataFrame, out_path: Path, theme: Theme) -> Path:
    """Horizontal grouped bars: one group per workload, one bar per backend.

    Every bar is labelled with its value, so the comparison never depends on reading a bar against
    a gridline or on telling two fills apart.
    """
    import matplotlib.pyplot as plt

    workloads = sorted(totals["workload"].unique().to_list())
    backends = sorted(totals["backend"].unique().to_list())
    colours = {backend: theme.series[i] for i, backend in enumerate(backends)}

    # A thin bar with air around it, and a 2px-equivalent gap between adjacent bars
    bar = 0.18
    gap = 0.03
    figure, axes = plt.subplots(figsize=(9, 1.5 + 0.5 * len(workloads) * len(backends)))
    figure.patch.set_facecolor(theme.surface)

    ticks, tick_labels = [], []
    for w, workload in enumerate(workloads):
        span = (bar + gap) * (len(backends) - 1)
        for b, backend in enumerate(backends):
            row = totals.filter((pl.col("workload") == workload) & (pl.col("backend") == backend))
            if row.is_empty():
                continue
            seconds = row["seconds"][0]
            y = w - span / 2 + b * (bar + gap)
            axes.barh(y, seconds, height=bar, color=colours[backend], zorder=2,
                      label=backend if w == 0 else None)
            axes.text(seconds + totals["seconds"].max() * 0.015, y, f"{seconds:,.0f}s",
                      va="center", ha="left", fontsize=9, color=theme.secondary_ink)
        ticks.append(w)
        tick_labels.append(_label(workload))

    axes.set_yticks(ticks, tick_labels, fontsize=10, color=theme.secondary_ink)
    axes.invert_yaxis()
    axes.set_xlabel("seconds, end to end", fontsize=9, color=theme.muted_ink, labelpad=8)
    axes.set_xlim(0, totals["seconds"].max() * 1.14)
    _style(axes, theme)

    runs = totals["runs"].max()
    subtitle = f"mean of {runs} runs per backend" if runs > 1 else "single run per backend"
    axes.set_title("How long a workload takes end to end", loc="left", pad=22,
                   fontsize=13, color=theme.primary_ink)
    axes.text(0, 1.035, subtitle, transform=axes.transAxes, fontsize=9, color=theme.muted_ink)
    # Below the plot, where it cannot sit on top of the longest bar
    axes.legend(frameon=False, fontsize=9, labelcolor=theme.secondary_ink, loc="upper center",
                bbox_to_anchor=(0.5, -0.22 if len(workloads) > 1 else -0.35), ncols=len(backends))

    figure.tight_layout()
    figure.savefig(out_path, dpi=200, facecolor=theme.surface)
    plt.close(figure)
    return out_path


def plot_by_operation(breakdown: pl.DataFrame, out_path: Path, theme: Theme) -> Path:
    """Stacked horizontal bars: one bar per workload and backend, one segment per operation.

    Absolute seconds rather than shares, so the bar lengths stay comparable across backends while
    the segments still answer "where did the time go". A 2px surface gap separates the segments,
    and a segment is only labelled inline when the text fits inside it; the rest are carried by the
    legend and the printed table.
    """
    import matplotlib.pyplot as plt

    pairs = _rows(breakdown)
    present = [op for op in OPERATIONS if op in set(breakdown["operation"].to_list())]
    colours = {op: theme.series[OPERATIONS.index(op)] for op in present}

    totals = {(w, b): breakdown.filter((pl.col("workload") == w) & (pl.col("backend") == b))["seconds"].sum()
              for w, b in pairs}
    longest = max(totals.values())

    figure, axes = plt.subplots(figsize=(10, 1.6 + 0.85 * len(pairs)))
    figure.patch.set_facecolor(theme.surface)

    # A gap drawn in the surface colour, sized as a fraction of the axis, separates the segments
    gap = longest * 0.004
    for index, (workload, backend) in enumerate(pairs):
        left = 0.0
        for operation in present:
            row = breakdown.filter(
                (pl.col("workload") == workload)
                & (pl.col("backend") == backend)
                & (pl.col("operation") == operation)
            )
            if row.is_empty():
                continue
            seconds = row["seconds"][0]
            axes.barh(index, seconds - gap, left=left, height=0.4, color=colours[operation], zorder=2,
                      label=OPERATION_LABELS[operation] if index == 0 else None)
            # Only label inside the segment when the number comfortably fits
            if seconds / longest > 0.09:
                axes.text(left + (seconds - gap) / 2, index, f"{seconds:,.0f}s", va="center", ha="center",
                          fontsize=8.5, color=_ink_on(colours[operation], theme), zorder=3)
            left += seconds
        axes.text(left + longest * 0.012, index, f"{totals[(workload, backend)]:,.0f}s of work",
                  va="center", ha="left", fontsize=9, color=theme.secondary_ink)

    axes.set_yticks(range(len(pairs)), [f"{_label(w)}\n{b}" for w, b in pairs],
                    fontsize=10, color=theme.secondary_ink)
    axes.invert_yaxis()
    axes.set_xlabel("seconds of work, summed across workers", fontsize=9, color=theme.muted_ink, labelpad=8)
    axes.set_xlim(0, longest * 1.2)
    _style(axes, theme)

    axes.set_title("Where a run spends its time", loc="left", pad=34, fontsize=13, color=theme.primary_ink)
    axes.text(0, 1.055, "branching against the work around it — summed across workers, so a run with several "
              "exceeds its wall clock", transform=axes.transAxes, fontsize=9, color=theme.muted_ink)
    axes.legend(frameon=False, fontsize=9, labelcolor=theme.secondary_ink, loc="upper center",
                bbox_to_anchor=(0.5, -0.16), ncols=len(present))

    figure.tight_layout()
    figure.savefig(out_path, dpi=200, facecolor=theme.surface)
    plt.close(figure)
    return out_path


def table(totals: pl.DataFrame, breakdown: pl.DataFrame) -> str:
    """The same numbers as text, so no value is reachable only by reading a colour."""
    present = [op for op in OPERATIONS if op in set(breakdown["operation"].to_list())]
    header = f"{'workload':<18} {'backend':<11} {'total':>9}  " + "  ".join(f"{OPERATION_LABELS[o]:>16}" for o in present)
    lines = [header, "-" * len(header)]
    for workload, backend in _rows(breakdown):
        total = totals.filter((pl.col("workload") == workload) & (pl.col("backend") == backend))
        cells = []
        for operation in present:
            row = breakdown.filter(
                (pl.col("workload") == workload)
                & (pl.col("backend") == backend)
                & (pl.col("operation") == operation)
            )
            cells.append(f"{row['seconds'][0]:>15,.1f}s" if not row.is_empty() else f"{'-':>16}")
        spent = f"{total['seconds'][0]:>8,.1f}s" if not total.is_empty() else f"{'-':>9}"
        lines.append(f"{_label(workload):<18} {backend:<11} {spent}  " + "  ".join(cells))
    return "\n".join(lines)
