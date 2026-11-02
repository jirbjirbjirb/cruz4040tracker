"""Build site/index.html from the SQLite cache. No network access."""

import argparse
import datetime as dt
import html
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version

from cruz4040 import db, model

SITE_DIR = Path("site")
REPO_URL = "https://github.com/jirbjirbjirb/cruz4040tracker"
# Heatmap slider stops: every Nth date, plus the peak and the final date.
FRAME_EVERY = 5


def fmt_date(iso: str, month: str = "%B") -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:{month}} {d.day}"


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


def heatmap_figure(
    states: list[db.DateState], results: list[model.SimResult], peak_i: int
) -> go.Figure:
    picks = sorted(set(range(0, len(states), FRAME_EVERY)) | {peak_i, len(states) - 1})
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
    start = picks.index(peak_i)
    fig = go.Figure(
        data=[heat(peak_i)],
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
        title={"text": frame_title(states, results, peak_i), "x": 0, "font": {"size": 13}},
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


def method_paragraph(baseline: db.Baseline) -> str:
    return (
        f"After each game, the model simulates the rest of the season "
        f"{model.SIMS:,} times. Cruz's chance of appearing in a given simulated game is based "
        f"on his availability prior to the simulation. When the simulation decides that he does "
        f"play in a given game, home runs and steals accrued during that game are determined by "
        f"Poisson draws whose per-game HR and SB rates blend his {baseline.season + 1} rate "
        f"with his {baseline.season} rate. The {baseline.season + 1} weight is "
        f"g / (g + {model.K}), where g represents games played. As the {baseline.season + 1} "
        f"season goes on, the {baseline.season} season's influence on projected HR and SB "
        f"rates is reduced."
    )


def render(states, baseline, results, season: int) -> str:
    probs = [r.prob for r in results]
    peak_i = int(np.argmax(probs))
    figs = {
        "totals": totals_figure(states),
        "heat": heatmap_figure(states, results, peak_i),
    }
    payload = json.dumps({k: json.loads(f.to_json()) for k, f in figs.items()}, sort_keys=True)
    here = Path(__file__).parent
    template = (here / "template.html").read_text(encoding="utf-8")
    replacements = {
        "{{STYLES}}": (here / "styles.css").read_text(encoding="utf-8").rstrip(),
        "{{PLOTLY_VERSION}}": get_plotlyjs_version(),
        "{{SEASON}}": str(season),
        "{{PEAK_PROB}}": f"{probs[peak_i]:.0%}",
        "{{PEAK_DATE}}": fmt_date(states[peak_i].game_date),
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
