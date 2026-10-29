import socket

import pytest

from cruz4040 import build, db
from cruz4040.ingest import store_game_log, store_schedule

SEASON = 2026


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / "cruz.sqlite"
    conn = db.connect(path)
    games = [
        {"game_id": i, "game_date": f"2026-04-{i:02d}", "game_type": "R", "status": "Final"}
        for i in range(1, 21)
    ]
    store_schedule(conn, SEASON, games)
    # Plays the first 8 and last 6 games: a 6-game absence in the middle.
    played = [g for g in games if g["game_id"] <= 8 or g["game_id"] > 14]
    store_game_log(
        conn,
        SEASON,
        [
            {
                "game": {"gamePk": g["game_id"]},
                "date": g["game_date"],
                "gameType": "R",
                "stat": {"homeRuns": g["game_id"] % 3 == 0, "stolenBases": g["game_id"] % 2},
            }
            for g in played
        ],
    )
    conn.execute("INSERT INTO baseline VALUES (2025, 20, 38, 135)")
    conn.commit()
    conn.close()
    return path


def test_build_is_offline_and_deterministic(no_network, cache, tmp_path):
    first = build.build(cache, tmp_path / "a", SEASON).read_text()
    second = build.build(cache, tmp_path / "b", SEASON).read_text()

    assert first == second
    assert "{{" not in first
    for chart_id in ('id="prob"', 'id="totals"', 'id="heat"'):
        assert chart_id in first


def test_story_reports_absence():
    states = [
        db.DateState(f"2026-04-{d:02d}", 0, 0, gp, d, db.SEASON_GAMES - d)
        for d, gp in zip(range(1, 8), [1, 2, 2, 2, 3, 3, 4], strict=True)
    ]
    a = build.longest_absence(states)
    assert (a.first_missed, a.last_missed, a.team_games) == ("2026-04-03", "2026-04-04", 2)


def test_first_permanent_zero():
    assert build.first_permanent_zero([0.1, 0.0, 0.2, 0.0, 0.0]) == 3
    assert build.first_permanent_zero([0.1, 0.2]) is None
    assert build.first_permanent_zero([0.0, 0.0]) == 0
