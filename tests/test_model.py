import numpy as np
import pytest

from cruz4040.db import SEASON_GAMES, Baseline, DateState
from cruz4040.model import SEED, run_season, simulate

BASELINE = Baseline(2025, hr=20, sb=38, games=135)


def state(hr, sb, games_played, team_completed):
    return DateState(
        "2026-08-01", hr, sb, games_played, team_completed, SEASON_GAMES - team_completed
    )


def sim(s, sims=2_000):
    return simulate(s, BASELINE, np.random.default_rng(SEED), sims=sims)


def test_already_40_40_is_certain():
    assert sim(state(40, 41, 120, 130)).prob == 1.0


def test_unreachable_with_games_left_is_zero():
    # 30 HR short with 2 games left exceeds the single-game HR record.
    r = sim(state(10, 40, 155, 160))
    assert r.prob == 0.0
    assert (r.final_hr == 10).all()


@pytest.mark.parametrize("hr, sb, expected", [(40, 40, 1.0), (39, 45, 0.0), (20, 30, 0.0)])
def test_no_games_left_matches_actual_totals(hr, sb, expected):
    r = sim(state(hr, sb, 150, SEASON_GAMES))
    assert r.prob == expected
    assert (r.final_hr == hr).all() and (r.final_sb == sb).all()


def test_never_plays_means_totals_stay_put():
    r = sim(state(30, 30, 0, 10))
    assert (r.final_hr == 30).all() and (r.final_sb == 30).all()


def test_plausible_state_is_between_zero_and_one():
    r = sim(state(20, 20, 60, 70))
    assert 0 < r.prob < 1
    assert r.final_hr.min() >= 20 and r.final_sb.min() >= 20


def test_same_seed_same_output():
    states = [state(10, 10, 40, 45), state(12, 11, 44, 50)]
    a = run_season(states, BASELINE, sims=1_000)
    b = run_season(states, BASELINE, sims=1_000)
    for x, y in zip(a, b, strict=True):
        assert x.prob == y.prob
        assert np.array_equal(x.final_hr, y.final_hr)
        assert np.array_equal(x.final_sb, y.final_sb)


def test_changing_one_date_leaves_other_dates_unchanged():
    states = [state(10, 10, 40, 45), state(12, 11, 44, 50), state(13, 12, 48, 55)]
    edited = [states[0], state(5, 40, 44, 155), states[2]]  # middle date now hits the cutoff
    a = run_season(states, BASELINE, sims=1_000)
    b = run_season(edited, BASELINE, sims=1_000)
    assert a[0].prob == b[0].prob
    assert a[2].prob == b[2].prob


def test_empty_baseline_is_rejected():
    with pytest.raises(ValueError):
        run_season([state(10, 10, 40, 45)], Baseline(2025, 0, 0, 0))
