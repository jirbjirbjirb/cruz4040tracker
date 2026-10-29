import pytest

from cruz4040.model import K, blend_rate, weight_current

PRIOR = 20 / 135
CURRENT = 0.3


def test_no_games_uses_prior_rate():
    assert weight_current(0) == 0
    assert blend_rate(0, 0, PRIOR) == PRIOR


def test_equal_weight_at_k_games():
    assert weight_current(K) == pytest.approx(0.5)
    assert blend_rate(int(CURRENT * K), K, PRIOR) == pytest.approx((CURRENT + PRIOR) / 2)


def test_rate_approaches_current_season_as_games_accumulate():
    gaps = [
        abs(blend_rate(round(CURRENT * g), g, PRIOR) - CURRENT) for g in (10, 100, 1_000, 100_000)
    ]
    assert gaps == sorted(gaps, reverse=True)
    assert gaps[-1] == pytest.approx(0, abs=1e-3)


def test_blend_uses_games_played_not_team_games():
    # 10 HR in 50 games played is a 0.2 rate however many team games have passed.
    assert blend_rate(10, 50, prior_rate=0.2) == pytest.approx(0.2)
