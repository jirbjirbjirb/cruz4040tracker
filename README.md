# cruz4040tracker

How Oneil Cruz's chance of a 40 HR / 40 SB season changed across 2026, re-estimated after every Pirates game.

**Live page:** https://jirbjirbjirb.github.io/cruz4040tracker

Cruz finished 2026 with 20 HR and 30 SB in 97 games. His 40/40 chance peaked at 26% on April 23 and reached 0% for good on July 2, during a 61-game absence.

## How it works

```
MLB Stats API ──ingest──▶ data/cruz.sqlite ──build──▶ site/index.html ──Actions──▶ GitHub Pages
                          (committed)         SQL → model → Plotly
```

1. **Ingest** (`uv run ingest`) fetches the Pirates schedule, Cruz's game log, and his prior-season line into SQLite. Re-runs skip games already stored as official.
2. **Build** (`uv run build`) reads only the SQLite cache, never the network. SQL produces one row per date with a completed team game; the model simulates from each date; Plotly renders three views into one self-contained HTML file.
3. **CI** lints, tests, builds, and deploys `site/` to GitHub Pages on every push to `main`.

### Counting games

Only regular-season games with an official status (`Final`, `Game Over`, `Completed Early`) count. Spring training, exhibitions, postponed and suspended entries are excluded. A postponed game and its makeup share a `gamePk`, so each game is counted once on the date it finished. Each half of a doubleheader counts as one game.

## Model

After each date, the rest of the season is simulated 10,000 times.

- **Availability.** Cruz plays each remaining game with probability *games played ÷ team games completed*.
- **Production.** When he plays, HR and SB per game are Poisson. Each rate blends 2026-to-date with 2025:

  λ = w · rate₂₀₂₆ + (1 − w) · rate₂₀₂₅, w = g / (g + k), **k = 50**

  where g is his 2026 games played. At 50 games the seasons count equally; by 150 games 2026 carries 75% of the weight. k = 50 keeps a hot or cold first two weeks from dominating while letting a real change in his game show up by midseason. Rates are per game Cruz played, not per team game.
- **Sampling.** Games played ~ Binomial(remaining, availability), then HR ~ Poisson(λ_HR × games played) and SB likewise. This is the same distribution as drawing every remaining game separately, with far fewer random numbers.
- **Output.** The share of simulations that end at ≥ 40 HR and ≥ 40 SB, plus the full distribution of final totals for the heatmap.
- **Determinism.** Seed 4040; each date gets its own generator spawned from it, so rebuilds are byte-identical and one date's inputs never shift another's draws.
- **Hard zero.** If the remaining games can't cover the gap even at MLB single-game records (4 HR, 6 SB), the probability is 0 without sampling.

### Limits

- Missed games so far predict missed games later. An injury reads as low availability after he returns and as near-normal availability at its start.
- HR and SB are independent, and per-game rates are constant for the rest of the season: no streaks, platoon splits, park effects, or opponents.
- One prior season (2025) anchors the blend; no aging curve or league-wide regression.
- Early-season availability is volatile: one missed opening game starts it at 0.

## Process

The project started from a terminal script that printed Cruz's HR/SB totals and a naive 162-game pace. That script had two counting bugs: it counted postponed and suspended games, and it divided by team games instead of games Cruz played. Both are fixed here, and the script itself is not part of this repo.

**Plan.** Scope, out-of-scope items, and success criteria were written down first as a handoff document, then broken into five sprints, each tracked in a [sprint plan](https://claude.ai/artifact/5fZVE3exroVCcVJw5a59rr).

**Loop per sprint.** Every sprint ran the same way:

1. Work on its own branch.
2. Lint and test locally, then review the diff before each commit.
3. Open a PR and run an automated code review (Claude Code `/code-review`, medium effort).
4. Triage each finding: fix it, or decline it with a reason. The disposition is posted as a PR comment.
5. Merge, then start the next sprint from the updated `main`.

| Sprint | Scope | PR | Review |
|---|---|---|---|
| 0 | Repo, `uv` project, dependencies | (direct to `main`) | — |
| 1 | Stats API ingest, SQLite schema, game-count tests | [#1](https://github.com/jirbjirbjirb/cruz4040tracker/pull/1) | 10 findings · 6 fixed |
| 2 | Rate blending, Monte Carlo, model tests | [#2](https://github.com/jirbjirbjirb/cruz4040tracker/pull/2) | 9 findings · 3 fixed |
| 3 | Plotly views, page, offline deterministic build | [#3](https://github.com/jirbjirbjirb/cruz4040tracker/pull/3) | 10 findings · 7 fixed |
| 4 | CI, GitHub Pages, README | [#4](https://github.com/jirbjirbjirb/cruz4040tracker/pull/4) | 9 findings · 6 fixed |

**Decisions along the way.**

- **Probe before parsing.** Live API responses showed that a postponed game and its makeup share a `gamePk`, so the schedule key became `(gamePk, date)` rather than `gamePk` alone.
- **Review caught a real bug in its own fix.** Sprint 1's review flagged that cached game-log rows were never refreshed. The first fix marked a game settled as soon as its schedule turned Final, which a new test showed would still freeze a mid-game line. The final fix records whether each row was written while the game was already official.
- **A review suggestion declined on purpose.** Sprint 2's review proposed shrinking availability toward 2025, as the rates are. On the 2026 data it cut the peak from 26% to 10%. Availability stayed as specified (games played ÷ team games), with the early-season volatility listed under Limits.
- **Reproducibility.** Every date gets its own random stream from one seed, so a correction to one date can't change another, and two builds are byte-identical (checked in tests).
- **CI as a check, not a formality.** The first PR run failed at setup: `astral-sh/setup-uv` publishes no floating `v10` tag. The action is now pinned to an exact release.
- **Least privilege in CI.** Sprint 4's review noted that the build job held push access on pull requests. The scheduled ingest now runs as its own job, the only one with write access; the build job checks out without credentials.

## Run locally

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv.

```sh
uv sync                      # install runtime + dev dependencies
uv run build                 # data/cruz.sqlite → site/index.html (offline)
open site/index.html

uv run pytest                # tests, no network
uv run ruff check            # lint
uv run ingest --season 2026  # refresh the cache from the MLB Stats API (not needed for 2026)
```

## Layout

| Path | Purpose |
|---|---|
| `src/cruz4040/ingest.py` | Stats API → SQLite; incremental; `--season` |
| `src/cruz4040/db.py` | Schema and per-date season queries |
| `src/cruz4040/model.py` | Rate blending and Monte Carlo |
| `src/cruz4040/build.py` | Cache → model → Plotly → `site/index.html` |
| `src/cruz4040/template.html`, `styles.css` | Page markup and styles, inlined at build |
| `tests/` | Game counting, blending, model edge cases, offline build |
| `data/cruz.sqlite` | Final 2026 cache, committed so CI never calls the API |
| `.github/workflows/deploy.yml` | Lint → test → build → Pages; daily ingest disabled until next season |

## Next season

The daily ingest is written but commented out in `.github/workflows/deploy.yml`. To track a live season:

1. Wait until opening day: the build needs at least one completed game in the new season.
2. Set the repo variable `SEASON` (Settings → Variables → Actions). Every build, not only scheduled ones, then uses that season.
3. Uncomment the `schedule:` block.

Each scheduled run ingests and pushes the refreshed cache to `main`, then builds and deploys. Branch protection on `main` must allow that push from `github-actions[bot]`.

Data: MLB Stats API via [MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI).
