"""Rate blending and Monte Carlo simulation of Cruz's final HR/SB totals."""

from dataclasses import dataclass

import numpy as np

from cruz4040.db import Baseline, DateState

TARGET = 40
SIMS = 10_000
SEED = 4040
# Prior strength in games: at g = K games played, 2026 and 2025 rates get equal weight.
K = 50
# MLB single-game records. Beyond these, a target is treated as unreachable for simulation purposes
MAX_HR_PER_GAME = 4
MAX_SB_PER_GAME = 6


@dataclass(frozen=True)
class SimResult:
    prob: float
    final_hr: np.ndarray
    final_sb: np.ndarray


def weight_current(games_played: int, k: float = K) -> float:
    """Weight on the current-season rate: g / (g + k)."""
    return games_played / (games_played + k)


def blend_rate(total: int, games_played: int, prior_rate: float, k: float = K) -> float:
    """Per-game rate blending the current season (total / games_played) with prior_rate."""
    if games_played == 0:
        return prior_rate
    w = weight_current(games_played, k)
    return w * (total / games_played) + (1 - w) * prior_rate


def availability(state: DateState) -> float:
    """P(Cruz plays a given remaining game) = his games played / completed team games."""
    if state.team_completed == 0:
        return 0.0
    return state.games_played / state.team_completed


def simulate(
    state: DateState,
    baseline: Baseline,
    rng: np.random.Generator,
    sims: int = SIMS,
    k: float = K,
) -> SimResult:
    """Simulate the rest of the season from `state`.

    Each remaining team game: Cruz plays with probability `availability`; if he plays,
    HR ~ Poisson(lam_hr) and SB ~ Poisson(lam_sb). A sum of n independent Poisson(lam)
    draws is Poisson(n * lam), so each sim draws games played ~ Binomial(remaining, p)
    and then one Poisson per stat.
    
    """
    n = state.team_remaining
    need_hr = max(TARGET - state.hr, 0)
    need_sb = max(TARGET - state.sb, 0)

    if need_hr > n * MAX_HR_PER_GAME or need_sb > n * MAX_SB_PER_GAME:
        hr = np.full(sims, state.hr)
        sb = np.full(sims, state.sb)
        return SimResult(0.0, hr, sb)

    lam_hr = blend_rate(state.hr, state.games_played, baseline.hr / baseline.games, k)
    lam_sb = blend_rate(state.sb, state.games_played, baseline.sb / baseline.games, k)

    played = rng.binomial(n, availability(state), size=sims)
    final_hr = state.hr + rng.poisson(lam_hr * played)
    final_sb = state.sb + rng.poisson(lam_sb * played)

    prob = float(np.mean((final_hr >= TARGET) & (final_sb >= TARGET)))
    return SimResult(prob, final_hr, final_sb)


def run_season(
    states: list[DateState],
    baseline: Baseline,
    seed: int = SEED,
    sims: int = SIMS,
    k: float = K,
) -> list[SimResult]:
    """Simulate from every date. One seeded generator, consumed in date order, so reruns match."""
    rng = np.random.default_rng(seed)
    return [simulate(s, baseline, rng, sims, k) for s in states]
