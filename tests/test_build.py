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


def states_from(games_played):
    return [
        db.DateState(f"2026-04-{d:02d}", 0, 0, gp, d, db.SEASON_GAMES - d)
        for d, gp in enumerate(games_played, start=1)
    ]


def test_longest_absence_and_shading_end():
    a = build.longest_absence(states_from([1, 2, 2, 2, 3, 3, 4]))
    assert (a.first_missed, a.last_missed, a.team_games) == ("2026-04-03", "2026-04-04", 2)
    assert a.shade_to == "2026-04-05"


def test_absence_from_opening_day():
    a = build.longest_absence(states_from([0, 0, 0, 1, 2]))
    assert (a.first_missed, a.last_missed, a.team_games) == ("2026-04-01", "2026-04-03", 3)


def test_absence_through_season_end():
    a = build.longest_absence(states_from([1, 2, 2, 2]))
    assert (a.team_games, a.shade_to) == (2, "2026-04-04")


def test_no_absence():
    assert build.longest_absence(states_from([1, 2, 3])) is None


def story_for(final, absence_first, peak_i=1):
    states = [
        db.DateState("2026-04-01", 1, 1, 1, 1, 161),
        db.DateState("2026-05-01", 9, 9, 30, 30, 132),
        final,
    ]
    absence = build.Absence(absence_first, absence_first, 3, absence_first)
    story = build.Story(2026, final, peak_i, None, absence)
    return build.story_paragraph(states, [0.1, 0.3, 0.0], story)


def test_story_orders_absence_relative_to_peak():
    final = db.DateState("2026-09-27", 20, 30, 97, 162, 0)
    assert "He then missed" in story_for(final, "2026-06-01")
    assert "He missed" in story_for(final, "2026-04-10")


def test_story_wording_for_reached_and_in_progress():
    reached = story_for(db.DateState("2026-09-27", 41, 42, 150, 162, 0), "2026-06-01")
    assert "a 40/40 season" in reached and "short of" not in reached
    live = story_for(db.DateState("2026-07-01", 20, 20, 80, 85, 77), "2026-06-01")
    assert live.startswith("Through 85 Pirates games in 2026")


def test_missing_cache_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        build.build(path, tmp_path / "out", SEASON)
    assert not path.exists()


def test_first_permanent_zero():
    assert build.first_permanent_zero([0.1, 0.0, 0.2, 0.0, 0.0]) == 3
    assert build.first_permanent_zero([0.1, 0.2]) is None
    assert build.first_permanent_zero([0.0, 0.0]) == 0
