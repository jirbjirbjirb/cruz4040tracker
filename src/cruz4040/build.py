"""Build site/index.html from the SQLite cache. No network access."""

import argparse
import datetime as dt
import html
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version

from cruz4040 import db, model

SITE_DIR = Path("site")
REPO_URL = "https://github.com/jirbjirbjirb/cruz4040tracker"
# Heatmap slider stops: every Nth date, plus the peak and the final date.
FRAME_EVERY = 5


@dataclass(frozen=True)
class Absence:
    first_missed: str
    last_missed: str
    team_games: int
    # Date he returned (or the last missed date if he never did). The step line holds
    # each value until the next date, so the shading runs to here.
    shade_to: str


@dataclass(frozen=True)
class Story:
    season: int
    final: db.DateState
    peak_i: int
    zero_i: int | None
    absence: Absence | None


def fmt_date(iso: str, month: str = "%B") -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:{month}} {d.day}"


def longest_absence(states: list[db.DateState]) -> Absence | None:
    """Longest run of consecutive team games Cruz did not play, opening day included."""
    runs = []  # (first index, last index, team games completed before the run)
    start = None
    prev_gp, prev_done = 0, 0
    for i, s in enumerate(states):
        if s.games_played == prev_gp:
            if start is None:
                start = (i, prev_done)
        elif start is not None:
            runs.append((start[0], i - 1, start[1]))
            start = None
        prev_gp, prev_done = s.games_played, s.team_completed
    if start is not None:
        runs.append((start[0], len(states) - 1, start[1]))
    if not runs:
        return None

    first, last, before = max(runs, key=lambda r: states[r[1]].team_completed - r[2])
    shade_to = states[last + 1] if last + 1 < len(states) else states[last]
    return Absence(
        states[first].game_date,
        states[last].game_date,
        states[last].team_completed - before,
        shade_to.game_date,
    )


def first_permanent_zero(probs: list[float]) -> int | None:
    """Index of the date from which the probability stays at 0 through season's end."""
    i = len(probs)
    while i > 0 and probs[i - 1] == 0:
        i -= 1
    return i if i < len(probs) else None


def probability_figure(states: list[db.DateState], probs: list[float], story: Story) -> go.Figure:
    dates = [s.game_date for s in states]
    custom = [[s.hr, s.sb, s.games_played, s.team_remaining] for s in states]
    fig = go.Figure(
        go.Scatter(
            x=dates,
            y=probs,
            mode="lines",
            meta="series-1",
            line={"width": 2, "shape": "hv"},
            customdata=custom,
            hovertemplate=(
                "<b>%{x|%b %-d}</b><br>P(40/40): %{y:.1%}<br>"
                "%{customdata[0]} HR · %{customdata[1]} SB<br>"
                "%{customdata[2]} games played · %{customdata[3]} team games left"
                "<extra></extra>"
            ),
        )
    )
    peak = states[story.peak_i]
    annotations = [
        {
            "x": peak.game_date,
            "y": probs[story.peak_i],
            "text": f"Peak {probs[story.peak_i]:.0%}<br>{fmt_date(peak.game_date)}",
            "ax": 20,
            "ay": -10,
            "xanchor": "left",
        }
    ]
    if story.zero_i is not None:
        z = states[story.zero_i]
        annotations.append(
            {
                "x": z.game_date,
                "y": 0,
                "text": f"0% from {fmt_date(z.game_date)}",
                "ax": 30,
                "ay": -36,
                "xanchor": "left",
            }
        )
    fig.update_layout(annotations=annotations)
    add_absence(fig, story.absence)
    fig.update_xaxes(range=[dates[0], dates[-1]])
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    return fig


def totals_figure(states: list[db.DateState]) -> go.Figure:
    dates = [s.game_date for s in states]
    pace = [model.TARGET * s.team_completed / db.SEASON_GAMES for s in states]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=pace,
            name="40 pace",
            meta="reference",
            mode="lines",
            line={"width": 1.5, "dash": "dot"},
            hovertemplate="40 pace: %{y:.1f}<extra></extra>",
        )
    )
    for stat, label, slot in (("hr", "HR", "series-1"), ("sb", "SB", "series-2")):
        ys = [getattr(s, stat) for s in states]
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=ys,
                name=label,
                meta=slot,
                mode="lines",
                line={"width": 2, "shape": "hv"},
                hovertemplate=f"{label}: %{{y}}<extra></extra>",
            )
        )
        fig.add_annotation(
            x=dates[-1],
            y=ys[-1],
            text=f"{ys[-1]} {label}",
            showarrow=False,
            xanchor="left",
            xshift=6,
        )
    fig.update_layout(
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0},
    )
    fig.update_xaxes(range=[dates[0], dates[-1]])
    fig.update_yaxes(rangemode="tozero")
    return fig


def add_absence(fig: go.Figure, absence: Absence | None) -> None:
    if absence is None:
        return
    fig.add_vrect(
        x0=absence.first_missed,
        x1=absence.shade_to,
        name="absence",
        layer="below",
        line_width=0,
        annotation_text=f"Out<br>{absence.team_games} games",
        annotation_position="top right",
    )


def heatmap_figure(
    states: list[db.DateState], results: list[model.SimResult], story: Story
) -> go.Figure:
    picks = sorted(set(range(0, len(states), FRAME_EVERY)) | {story.peak_i, len(states) - 1})
    hr_lo = min(int(results[i].final_hr.min()) for i in picks)
    hr_hi = max(int(results[i].final_hr.max()) for i in picks)
    sb_lo = min(int(results[i].final_sb.min()) for i in picks)
    sb_hi = max(int(results[i].final_sb.max()) for i in picks)
    hr_bins = list(range(hr_lo, hr_hi + 1))
    sb_bins = list(range(sb_lo, sb_hi + 1))

    def grid(r: model.SimResult) -> list[list[float | None]]:
        counts = np.zeros((len(sb_bins), len(hr_bins)))
        np.add.at(counts, (r.final_sb - sb_lo, r.final_hr - hr_lo), 1)
        share = counts / len(r.final_hr)
        return [[round(float(v), 5) if v else None for v in row] for row in share]

    def heat(i: int) -> go.Heatmap:
        return go.Heatmap(
            x=hr_bins,
            y=sb_bins,
            z=grid(results[i]),
            zmin=0,
            meta="sequential",
            colorbar={"title": {"text": "Share"}, "tickformat": ".1%", "thickness": 10},
            hovertemplate="%{x} HR · %{y} SB<br>%{z:.2%} of sims<extra></extra>",
        )

    names = [states[i].game_date for i in picks]
    start = picks.index(story.peak_i)
    fig = go.Figure(
        data=[heat(story.peak_i)],
        frames=[
            go.Frame(
                data=[heat(i)], name=n, layout={"title": {"text": frame_title(states, results, i)}}
            )
            for i, n in zip(picks, names, strict=True)
        ],
    )
    fig.add_shape(
        type="rect",
        x0=model.TARGET - 0.5,
        y0=model.TARGET - 0.5,
        x1=max(hr_hi, model.TARGET) + 0.5,
        y1=max(sb_hi, model.TARGET) + 0.5,
        name="region",
        line={"width": 2},
    )
    fig.add_annotation(
        x=model.TARGET - 0.5,
        y=max(sb_hi, model.TARGET) + 0.5,
        text="40/40",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        xshift=4,
        yshift=-2,
    )
    fig.update_layout(
        title={"text": frame_title(states, results, story.peak_i), "x": 0, "font": {"size": 13}},
        sliders=[
            {
                "active": start,
                "currentvalue": {"visible": False},
                "pad": {"t": 36},
                "steps": [
                    {
                        "label": fmt_date(n, "%b"),
                        "method": "animate",
                        "args": [
                            [n],
                            {
                                "mode": "immediate",
                                "frame": {"duration": 0, "redraw": True},
                                "transition": {"duration": 0},
                            },
                        ],
                    }
                    for n in names
                ],
            }
        ],
    )
    fig.update_xaxes(title_text="Final HR", dtick=5)
    fig.update_yaxes(title_text="Final SB", dtick=5)
    return fig


def frame_title(states: list[db.DateState], results: list[model.SimResult], i: int) -> str:
    s = states[i]
    return (
        f"{fmt_date(s.game_date)}: {s.hr} HR, {s.sb} SB, {s.team_remaining} games left"
        f" · P(40/40) {results[i].prob:.1%}"
    )


def story_paragraph(states: list[db.DateState], probs: list[float], story: Story) -> str:
    f = story.final
    peak = states[story.peak_i]
    if f.team_remaining > 0:
        opening = (
            f"Through {f.team_completed} Pirates games in {story.season}, Cruz has {f.hr} "
            f"home runs and {f.sb} stolen bases in {f.games_played} games played."
        )
    elif f.hr >= model.TARGET and f.sb >= model.TARGET:
        opening = (
            f"Cruz finished {story.season} with {f.hr} home runs and {f.sb} stolen bases "
            f"in {f.games_played} games: a 40/40 season."
        )
    else:
        opening = (
            f"Cruz finished {story.season} with {f.hr} home runs and {f.sb} stolen bases in "
            f"{f.games_played} of {f.team_completed} team games, "
            f"{max(model.TARGET - f.hr, 0)} homers and {max(model.TARGET - f.sb, 0)} steals"
            " short of 40/40."
        )
    parts = [
        opening,
        f"His chances peaked at {probs[story.peak_i]:.0%} on {fmt_date(peak.game_date)}, "
        f"{peak.team_completed} games in, with {peak.hr} HR and {peak.sb} SB.",
    ]
    a = story.absence
    if a is not None:
        parts.append(
            ("He then missed" if a.first_missed > peak.game_date else "He missed")
            + f" {a.team_games} straight team games, "
            f"from {fmt_date(a.first_missed)} through {fmt_date(a.last_missed)}."
        )
    if story.zero_i is not None:
        z = states[story.zero_i]
        during = a is not None and a.first_missed <= z.game_date <= a.last_missed
        parts.append(
            f"The model's estimate hit 0% on {fmt_date(z.game_date)}"
            + (", during that absence," if during else ",")
            + f" with {z.team_remaining} games left, and never came back."
        )
    return " ".join(parts)


def method_paragraph(baseline: db.Baseline) -> str:
    return (
        f"After every completed Pirates game, the model simulates the rest of the season "
        f"{model.SIMS:,} times. Cruz plays each remaining game with probability equal to his "
        f"share of team games played so far. When he plays, home runs and steals are Poisson "
        f"draws whose per-game rates blend his {baseline.season + 1} rate with his "
        f"{baseline.season} rate ({baseline.hr} HR and {baseline.sb} SB in {baseline.games} "
        f"games). The {baseline.season + 1} weight is g / (g + {model.K}), where g is his games "
        f"played, so the two seasons count equally at {model.K} games. The chart shows the share "
        f"of simulations that end with at least 40 HR and 40 SB. A fixed seed "
        f"({model.SEED}) makes every rebuild identical. The model assumes games missed so far "
        f"predict games missed later and ignores streaks, matchups and injuries."
    )


def render(states, baseline, results, season: int) -> str:
    probs = [r.prob for r in results]
    story = Story(
        season=season,
        final=states[-1],
        peak_i=int(np.argmax(probs)),
        zero_i=first_permanent_zero(probs),
        absence=longest_absence(states),
    )
    figs = {
        "prob": probability_figure(states, probs, story),
        "totals": totals_figure(states),
        "heat": heatmap_figure(states, results, story),
    }
    payload = json.dumps({k: json.loads(f.to_json()) for k, f in figs.items()}, sort_keys=True)
    here = Path(__file__).parent
    template = (here / "template.html").read_text(encoding="utf-8")
    replacements = {
        "{{STYLES}}": (here / "styles.css").read_text(encoding="utf-8").rstrip(),
        "{{PLOTLY_VERSION}}": get_plotlyjs_version(),
        "{{SEASON}}": str(season),
        "{{FINAL_PROB}}": f"{probs[-1]:.0%}",
        "{{PEAK_PROB}}": f"{probs[story.peak_i]:.0%}",
        "{{PEAK_DATE}}": fmt_date(states[story.peak_i].game_date),
        "{{FINAL_LINE}}": f"{states[-1].hr} HR · {states[-1].sb} SB",
        "{{STORY}}": html.escape(story_paragraph(states, probs, story)),
        "{{METHOD}}": html.escape(method_paragraph(baseline)),
        "{{REPO_URL}}": REPO_URL,
        "{{FIGURES}}": payload.replace("</", "<\\/"),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def build(db_path: Path | str, out_dir: Path, season: int) -> Path:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"no cache at {db_path}; run ingest")
    conn = db.connect(db_path)
    try:
        states = db.season_progress(conn, season)
        baseline = db.get_baseline(conn, season - 1)
    finally:
        conn.close()
    if not states or baseline is None:
        raise RuntimeError(f"cache has no {season} games or no {season - 1} baseline; run ingest")

    results = model.run_season(states, baseline)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(render(states, baseline, results, season), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", type=Path, default=SITE_DIR)
    args = parser.parse_args()
    print(f"wrote {build(args.db, args.out, args.season)}")
