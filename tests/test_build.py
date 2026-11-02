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
    for chart_id in ('id="totals"', 'id="heat"'):
        assert chart_id in first
